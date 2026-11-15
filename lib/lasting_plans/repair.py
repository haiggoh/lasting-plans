"""Background auto-repair (2.0.0): turn doctor/scan findings into keyed issues and
apply one safe, idempotent fixer per kind. Every fixer is non-destructive (anything
overwritten is first copied to the backup dir) and converges when re-run.

`collect_issues(lib, res)` — res is a ScanResult or None (then engine.last_run()).
`FIXERS[kind](lib, issue, backup_dir) -> (fixed: bool, note: str)`.
"""
import os
import shutil

from . import config as cfgmod
from . import engine, gitrepo, migrate, remote, scheduler, tools


def _last_commit_with(root, rel):
    """The newest commit in which `rel` still exists (rev-list alone lands on the
    deletion commit, where checkout would fail)."""
    for sha in gitrepo.git(root, "rev-list", "HEAD", "--", rel, check=False).stdout.split():
        if gitrepo.git(root, "ls-tree", sha, "--", rel, check=False).stdout.strip():
            return sha
    return None


def _trash_dir():
    return os.environ.get("LASTING_PLANS_TRASH_DIR") or os.path.join(cfgmod.home(), ".Trash")


def _in_trash(sha):
    """True if a file with this sha256 sits in the Trash (the user deleted it in Finder).
    A PermissionError (launchd's TCC context cannot read ~/.Trash) propagates to the
    caller, which defers instead of guessing."""
    def _raise(e):
        raise e
    t = _trash_dir()
    for r, _dirs, files in os.walk(t, onerror=_raise):
        for f in files:
            p = os.path.join(r, f)
            try:
                if os.path.getsize(p) <= engine.MAX_BYTES and engine.sha256_file(p) == sha:
                    return True
            except OSError:
                continue
    return False


def collect_issues(lib, res=None):
    issues = []

    def add(kind, path, detail, severity="routine"):
        issues.append({"key": "%s:%s" % (kind, path), "kind": kind, "path": path,
                       "detail": detail, "severity": severity})

    cfg = lib.cfg
    if migrate.needed(cfg):
        add("migration_pending", cfg.get("archive_root") or "", "v1 two-archive layout still present")
    if res is None:
        res = engine.last_run() or {}
    if isinstance(res, engine.ScanResult):
        pending_items = [{"path": p, "reason": r} for p, r in res.pending]
        error_items = [{"path": p, "reason": r} for p, r in res.errors]
    else:
        pending_items = res.get("pending_items") or []
        error_items = res.get("error_items") or []
    for item in pending_items + error_items:
        p, reason = item.get("path", ""), item.get("reason", "")
        if reason.startswith("uncommitted:"):
            add("uncommitted", p, reason)
        elif "removed by hand" in reason:
            add("archive_missing", p, reason)
        else:
            add("transient", p, reason)
    for _k, v in remote.summary(lib).items():
        if str(v.get("state", "")).startswith("pending"):
            add("transient", "remote", v["state"])
    for c in engine.doctor(lib):
        if c["ok"]:
            continue
        name = c["check"]
        if name == "archive has Git identity":
            add("no_identity", lib.root, c.get("detail") or "")
        elif name == "every archive document present":
            for m in (c.get("detail") or "").split(","):
                m = m.strip()
                if m:
                    add("archive_missing", m, "missing from the archive")
        elif name == "stored types match the classifier":
            add("type_mismatch", lib.root, (c.get("detail") or "")[:200])
        elif name == "archive is a Git repo":
            add("emergency", lib.root, "archive root is not a Git repo", "emergency")
    if tools.on_path("git") is None:
        add("emergency", "git", "git is not installed", "emergency")
    for p, err in lib.corrupt:
        add("sidecar_corrupt", os.path.relpath(p, lib.root), err)
    # empty folders in the archive (no docs, nothing tracked under them)
    if os.path.isdir(os.path.join(lib.root, ".git")):
        tracked = {p for p in gitrepo.git(lib.root, "ls-files", "-z").stdout.split("\0") if p}
        for d, dirs, _files in os.walk(lib.root):
            dirs[:] = [x for x in dirs if x != ".git" and not x.startswith(".")]
            for x in dirs:
                fp = os.path.join(d, x)
                rel = os.path.relpath(fp, lib.root)
                if rel.startswith(engine.META_DIR):
                    continue
                try:
                    has_files = any(os.path.isfile(os.path.join(fp, f)) for f in os.listdir(fp))
                except OSError:
                    continue
                has_tracked = any(t.startswith(rel + "/") for t in tracked)
                if not has_files and not has_tracked:
                    add("empty_folder", rel, "empty folder in the archive")
    if cfg.get("scheduler_enabled", True) and scheduler.supported():
        st = scheduler.state()
        if not st.get("running"):
            add("watcher_down", "watcher", "supported and enabled but not running")
    return issues


# ------------------------------------------------------------------ fixers

def _fix_migration_pending(lib, issue, backup):
    log = migrate.run(lib)
    return True, "; ".join(log[-3:])


def _fix_uncommitted(lib, issue, backup):
    paths = [issue["path"]]
    doc = next((d for d in lib.docs if d.sc["archive_relpath"] == issue["path"]), None)
    if doc:
        paths.append(engine.sidecar_rel(doc.id))
    sha = gitrepo.commit_paths(lib.root, paths, "repair: commit pending %s" % issue["path"])
    return (sha is not None), ("committed %s" % sha[:10]) if sha else "nothing to commit"


def _fix_no_identity(lib, issue, backup):
    root = lib.root
    name = gitrepo.git(root, "config", "--global", "user.name", check=False).stdout.strip()
    mail = gitrepo.git(root, "config", "--global", "user.email", check=False).stdout.strip()
    name = name or "Lasting Plans"
    mail = mail or "lasting-plans@localhost"
    gitrepo.git(root, "config", "user.name", name)
    gitrepo.git(root, "config", "user.email", mail)
    return True, "repo-local identity %s <%s>" % (name, mail)


def _fix_archive_missing(lib, issue, backup):
    root = lib.root
    rel = issue["path"]
    doc = next((d for d in lib.docs if d.sc["archive_relpath"] == rel), None)
    if doc is None:
        return False, "no sidecar points at %s" % rel
    target = os.path.join(root, rel)
    sha = doc.sc.get("archive_sha256")
    if not os.path.exists(target) and sha:
        # it may have been MOVED, not deleted: an unclaimed file with the same content
        meta_prefix = engine.META_DIR + "/"
        claimed = {d.sc["archive_relpath"] for d in lib.docs}
        for r, _dirs, files in os.walk(root):
            if os.path.join(root, engine.META_DIR) == r or r.startswith(os.path.join(root, engine.META_DIR)):
                continue
            for f in files:
                p = os.path.join(r, f)
                prel = os.path.relpath(p, root)
                if prel.startswith(meta_prefix) or prel in claimed:
                    continue
                try:
                    if engine.sha256_file(p) == sha:
                        doc.sc["archive_relpath"] = prel
                        engine.write_sidecar(root, doc.sc)
                        gitrepo.commit_paths(root, [engine.sidecar_rel(doc.id)],
                                             "repair: %s was moved, not deleted — sidecar repointed" % rel)
                        return True, "repointed to %s" % prel
                except OSError:
                    pass
    policy = lib.cfg.get("archive_deletions", "restore-unless-trashed")
    trashed = False
    if policy == "restore-unless-trashed":
        try:
            trashed = bool(sha) and _in_trash(sha)
        except PermissionError:
            return False, "deferred: Trash unreadable here"   # the hook (Trash readable) decides next pass
    if policy == "honor" or (policy == "restore-unless-trashed" and trashed):
        doc.sc["deleted_utc"] = engine.now_utc()
        doc.sc["deleted_by"] = "user"
        engine.write_sidecar(root, doc.sc)
        in_index = bool(gitrepo.git(root, "ls-files", "--", rel, check=False).stdout.strip())
        paths = [engine.sidecar_rel(doc.id)] + ([rel] if in_index else [])
        gitrepo.commit_paths(root, paths, "repair: %s deleted by the user (honoured)" % rel)
        return True, "marked deleted (policy %s)" % policy
    if not gitrepo.has_identity(root):
        return False, "no Git identity; not restoring"
    rev = _last_commit_with(root, rel)
    if not rev:
        return False, "no committed version of %s to restore" % rel
    gitrepo.git(root, "checkout", rev, "--", rel)
    doc.sc["archive_sha256"] = engine.sha256_file(target)
    engine.write_sidecar(root, doc.sc)
    gitrepo.commit_paths(root, [rel, engine.sidecar_rel(doc.id)], "repair: restored %s from Git" % rel)
    return True, "restored from Git (%s)" % rev[:10]


def _fix_sidecar_corrupt(lib, issue, backup):
    root = lib.root
    rel = issue["path"]
    p = os.path.join(root, rel)
    try:
        shutil.copy2(p, os.path.join(backup, os.path.basename(rel)))
    except OSError:
        pass
    rev = _last_commit_with(root, rel)
    if not rev:
        return False, "no committed version of the sidecar"
    gitrepo.git(root, "checkout", rev, "--", rel)
    gitrepo.commit_paths(root, [rel], "repair: restored sidecar %s from Git" % rel)
    return True, "restored from Git (%s)" % rev[:10]


def _fix_type_mismatch(lib, issue, backup):
    mm = engine.type_mismatches(lib)
    if not mm:
        return False, "no mismatch anymore"
    d, new_type, _reason = mm[0]
    if not gitrepo.has_identity(d.root):
        return False, "no Git identity"
    sc = d.sc
    sc["type"] = new_type
    sc["type_reason"] = "auto-reclassified by repair"
    sc.setdefault("type_history", []).append(
        {"from": d.type, "to": new_type, "at_utc": engine.now_utc(), "by": "repair"})
    engine.write_sidecar(d.root, sc)
    sha = gitrepo.commit_paths(d.root, [engine.sidecar_rel(sc["id"])],
                               "repair: auto-reclassified %s -> %s" % (sc["archive_relpath"], new_type))
    d.type = new_type
    return sha is not None, "auto-reclassified to %s" % new_type


def _fix_empty_folder(lib, issue, backup):
    p = os.path.join(lib.root, issue["path"])
    try:
        os.rmdir(p)
        return True, "removed empty folder %s" % issue["path"]
    except OSError:
        return False, "not empty"


def _fix_watcher_down(lib, issue, backup):
    ok, msg = scheduler.install(migrate.LIB)
    return ok, msg


def _fix_transient(lib, issue, backup):
    return False, "waits for next pass"


def _fix_emergency(lib, issue, backup):
    return False, "emergency: %s" % issue["detail"]


FIXERS = {
    "migration_pending": _fix_migration_pending,
    "uncommitted": _fix_uncommitted,
    "no_identity": _fix_no_identity,
    "archive_missing": _fix_archive_missing,
    "sidecar_corrupt": _fix_sidecar_corrupt,
    "type_mismatch": _fix_type_mismatch,
    "empty_folder": _fix_empty_folder,
    "watcher_down": _fix_watcher_down,
    "transient": _fix_transient,
    "emergency": _fix_emergency,
}
