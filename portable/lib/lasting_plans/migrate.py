"""Self-running migration: v1 two-archive layout -> 2.0.0 one mirrored archive.

Runs under engine.scan_lock() (the caller — repair.run / the SessionStart hook —
holds it). Every step is idempotent, so a crash halfway converges on re-run.
Nothing is ever deleted: the old playbook archive folder is MOVED under the state
dir (whole folder, incl. untracked files and .git) and replaced by a symlink.

Steps:
  0. re-case canonical folder spellings in the source repo (sorting.canonicalize_folders)
  1. restage the launchd watcher on the 2.0.0 code, so no 1.x watcher runs again
  2. git bundle backups of both v1 repos + copies of their .lasting-plans/ (verify must pass)
  3. commit any dirty pending state in each v1 repo (case-safe commit_paths)
  4. merge the playbook archive's history into the plan archive (--allow-unrelated-histories)
  5. relocate every sidecar's archive file to its (current-spelling) source path, one commit
  6. move the old playbook root under <state>/retired-archives/ and symlink it to
     <archive_root>/<playbooks_subdir>
  7. write the 2.0.0 config (archive_root / retired_archives / remote / layout=2),
     keeping the legacy values under "legacy" for audit
"""
import datetime
import json
import os
import shutil

from . import config as cfgmod
from . import engine, gitrepo, scheduler, sorting

LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../lib (for scheduler.install)


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _v1_playbook_root(cfg):
    for r in cfg.get("retired_archives") or []:
        p = cfgmod.expand(r)
        if os.path.isdir(os.path.join(p, ".git")):
            return p
    return None


def needed(cfg):
    """True when a v1 playbook archive still exists and the layout migration has not run."""
    return cfg.get("layout") != 2 and _v1_playbook_root(cfg) is not None


def run(lib, dry_run=False):
    """Run the migration. Caller must hold engine.scan_lock(). Returns step log lines."""
    cfg = lib.cfg
    plans_root = lib.root
    pb_root = _v1_playbook_root(cfg)
    if cfg.get("layout") == 2:
        return ["nothing to migrate: layout already 2"]
    if pb_root is None:
        return ["nothing to migrate: no v1 playbook repo found"]
    state = cfgmod.state_dir()
    stamp = _stamp()
    if dry_run:
        return [
            "dry-run: step 0 re-case canonical folders in the source",
            "dry-run: step 1 would restage the watcher (scheduler.install)",
            "dry-run: step 2 would write bundles+meta copies into %s" % os.path.join(state, "repair-backups", stamp),
            "dry-run: step 3 would commit pending state in %s and %s" % (plans_root, pb_root),
            "dry-run: step 4 would merge %s history into %s" % (pb_root, plans_root),
            "dry-run: step 5 would relocate sidecar archive files to their source paths",
            "dry-run: step 6 would move %s to %s and symlink it to %s" % (
                pb_root, os.path.join(state, "retired-archives"), os.path.join(plans_root, cfg.get("playbooks_subdir") or "_PLAYBOOKS")),
            "dry-run: step 7 would write layout=2 config",
        ]
    log = []
    log += _step_watcher(cfg)          # first: no 1.x watcher may run against a half-migrated archive
    log += _step_recase(lib, cfg)
    log += _step_backup(plans_root, pb_root, state, stamp)
    log += _step_commit_dirty(plans_root, pb_root)
    log += _step_merge(plans_root, pb_root)
    log += _step_relocate(lib, plans_root)
    _step_symlink(lib, plans_root, pb_root, state, stamp, log)   # appends to log in place
    log += _step_config(lib, cfg, plans_root, pb_root)
    log += _step_backfill(lib)
    return log


def _step_backfill(lib, dry_run=False):
    """Step 8 (idempotent): every archived source doc whose top-level source is gone and
    looks like a cleanup victim ⇒ put_back. dry_run lists them without writing."""
    import time as _t
    from . import rescue
    log = []
    now = _t.time()
    for d in lib.docs:
        if d.sc.get("origin") != "source":
            continue
        s = d.sc.get("source_relpath")
        if not s or "/" in s or os.path.exists(os.path.join(lib.source, s)):
            continue
        ok, why = rescue.looks_like_cleanup(lib, d, now)
        if not ok:
            continue
        if dry_run:
            log.append("would put back %s (%s)" % (s, why))
            continue
        new_rel = rescue.put_back(lib, d)
        log.append("put back %s -> %s" % (s, new_rel))
    return log


def _step_recase(lib, cfg):
    events = sorting.canonicalize_folders(lib)
    return ["recased %s (%s)" % (rel, detail) for _k, rel, detail in events]


def _step_watcher(cfg):
    if not cfg.get("scheduler_enabled", True) or not scheduler.supported():
        return ["watcher: skipped (disabled or unsupported)"]
    ok, msg = scheduler.install(LIB)
    return ["watcher restaged on 2.0.0 code: %s" % msg]


def _step_backup(plans_root, pb_root, state, stamp):
    bdir = os.path.join(state, "repair-backups", stamp)
    os.makedirs(bdir, exist_ok=True)
    log = []
    for name, root in (("plans", plans_root), ("playbooks", pb_root)):
        bundle = os.path.join(bdir, name + ".bundle")
        gitrepo.git(root, "bundle", "create", bundle, "--all")
        gitrepo.git(root, "bundle", "verify", bundle)   # raises (aborts) if the bundle is bad
        meta = os.path.join(root, engine.META_DIR)
        if os.path.isdir(meta):
            shutil.copytree(meta, os.path.join(bdir, name + "-meta"), dirs_exist_ok=True)
        log.append("backed up %s -> %s (bundle verified)" % (root, bundle))
    return log


def _step_commit_dirty(plans_root, pb_root):
    log = []
    for name, root in (("plans", plans_root), ("playbooks", pb_root)):
        # only documents and .lasting-plans state — never arbitrary untracked files
        dirty = [p for _c, p in gitrepo.status_z(root)
                 if p.startswith(engine.META_DIR + "/") or engine.is_doc_name(os.path.basename(p))]
        if dirty:
            gitrepo.commit_paths(root, dirty, "pre-migration: commit pending state")
            log.append("%s: committed %d pending path(s)" % (name, len(dirty)))
    return log


def _step_merge(plans_root, pb_root):
    gitrepo.git(plans_root, "fetch", "-q", pb_root, "HEAD")
    msg = "migrate: merge playbook archive (history kept)"
    r = gitrepo.git(plans_root, "merge", "--allow-unrelated-histories", "--no-commit", "--no-edit",
                    "-m", msg, "FETCH_HEAD", check=False)
    log = []
    already = gitrepo.git(plans_root, "merge-base", "--is-ancestor", "FETCH_HEAD", "HEAD", check=False).returncode == 0
    if r.returncode == 0 and already:
        return ["playbook history already merged"]
    if r.returncode != 0:
        unmerged = [p for p in gitrepo.git(plans_root, "diff", "--name-only", "--diff-filter=U", "-z").stdout.split("\0") if p]
        taken = {d.sc["archive_relpath"] for d in engine.Library(cfgmod.load()).docs}
        for p in unmerged:
            if p == engine.FOLDERS_REL:
                ours = json.loads(_stage(plans_root, p, 2) or b"{}")
                theirs = json.loads(_stage(plans_root, p, 3) or b"{}")
                o_tags, t_tags = ours.get("tags") or {}, theirs.get("tags") or {}
                merged = {}
                for k, v in list(o_tags.items()) + list(t_tags.items()):
                    if not any(k.casefold() == x.casefold() for x in merged):
                        merged[k] = v
                with open(os.path.join(plans_root, p), "w", encoding="utf-8") as f:
                    json.dump({"schema": 1, "tags": merged}, f, indent=2, sort_keys=True, ensure_ascii=False)
                gitrepo.git(plans_root, "add", "--", p)
                log.append("merged folders.json (union, casefold-deduped)")
            else:
                # keep the plan-side file; the playbook-side one goes to a free path
                theirs = _stage(plans_root, p, 3)
                ours = _stage(plans_root, p, 2)
                if ours is not None:
                    with open(os.path.join(plans_root, p), "wb") as f:
                        f.write(ours)
                gitrepo.git(plans_root, "add", "--", p)
                if theirs is not None:
                    free = engine._free_relpath(plans_root, p, taken)
                    taken.add(free)
                    with open(os.path.join(plans_root, free), "wb") as f:
                        f.write(theirs)
                    gitrepo.git(plans_root, "add", "--", free)
                    # keep the sidecar pointing at the copy we actually kept
                    scdir = os.path.join(plans_root, engine.META_DIR, "docs")
                    if os.path.isdir(scdir):
                        for name in os.listdir(scdir):
                            sp = os.path.join(scdir, name)
                            try:
                                with open(sp, encoding="utf-8") as f:
                                    sc = json.load(f)
                            except (OSError, ValueError):
                                continue
                            if isinstance(sc, dict) and sc.get("archive_relpath") == p:
                                sc["archive_relpath"] = free
                                with open(sp, "w", encoding="utf-8") as f:
                                    json.dump(sc, f, indent=2, sort_keys=True, ensure_ascii=False)
                                gitrepo.git(plans_root, "add", "--", os.path.relpath(sp, plans_root))
                    log.append("collision on %s: playbook-side copy kept as %s (sidecar updated)" % (p, free))
    gitrepo.git(plans_root, "commit", "-q", "-m", msg)
    log.append("merged %s history into %s" % (pb_root, plans_root))
    return log


def _stage(root, path, n):
    r = gitrepo.git(root, "show", ":%d:%s" % (n, path), check=False)
    return r.stdout.encode("utf-8", "surrogateescape") if r.returncode == 0 else None


def _step_relocate(lib, plans_root):
    """Move every sidecar's archive file to its source path (current spelling)."""
    lib.reload()
    present = {rel for rel, _ in engine.walk_docs(lib.source)}
    by_fold = {}
    for rel in present:
        by_fold.setdefault(rel.casefold(), rel)
    taken = {d.sc["archive_relpath"] for d in lib.docs}
    pairs, sidecars = [], []
    for d in lib.docs:
        s = d.sc.get("source_relpath")
        if not s:
            continue
        actual = by_fold.get(s.casefold(), s)     # current on-disk spelling (post re-case)
        if actual not in present:
            continue                               # source gone: keep the archive path
        old = d.sc["archive_relpath"]
        if old == actual and os.path.exists(d.path):
            continue
        taken.discard(old)
        actual = engine.archive_rel_for(lib.cfg, actual)   # strip a rescue-subdir prefix: the backup never mirrors it
        actual_abs = os.path.join(plans_root, actual)
        if (os.path.exists(d.path) and os.path.exists(actual_abs)
                and not os.path.samefile(d.path, actual_abs)
                and engine.sha256_file(actual_abs) == engine.sha256_file(d.path)):
            # same content already sits at the source path (a wedge "(2)" duplicate
            # that the merge brought in): drop the copy, never overwrite. samefile()
            # guards the case-only situation where old and actual are ONE physical file
            # on a case-insensitive volume — `git rm` would delete the document itself
            new = actual
            gitrepo.git(plans_root, "rm", "-q", "--", old)
        else:
            new = engine._free_relpath(plans_root, actual, taken, ignore=old)
            if os.path.exists(d.path):
                gitrepo.move_path(plans_root, old, new)
        d.sc["archive_relpath"] = new
        d.sc["source_relpath"] = actual
        if actual not in d.sc.get("source_history", []):
            d.sc.setdefault("source_history", []).append(actual)
        engine.write_sidecar(plans_root, d.sc)
        pairs.append((old, new))
        sidecars.append(engine.sidecar_rel(d.id))
        taken.add(new)
    if not pairs:
        return ["no relocations needed"]
    paths = [x for pair in pairs for x in pair] + sidecars
    add_paths = [p for p in [x[1] for x in pairs] + sidecars if os.path.exists(os.path.join(plans_root, p))]
    if add_paths:
        gitrepo.git(plans_root, "add", "-A", "--", *add_paths)
    gitrepo.commit_staged_paths(plans_root, paths, "migrate: archive paths now mirror the source")
    return ["relocated %d document(s) to their source paths" % len(pairs)]


def _symlink_step(lib, pb_root, target, log):
    """Replace the old playbook root with a symlink to the archive's playbook folder.
    Idempotent; refuses to touch a symlink pointing elsewhere or a foreign real folder."""
    if os.path.islink(pb_root):
        if os.path.realpath(pb_root) == os.path.realpath(target):
            log.append("symlink already correct: %s -> %s" % (pb_root, target))
            return
        log.append("REFUSED: %s is a symlink to %s, not %s — recorded as an issue, touched nothing"
                   % (pb_root, os.readlink(pb_root), target))
        return
    if os.path.isdir(pb_root) and not os.path.isdir(os.path.join(pb_root, ".git")):
        log.append("REFUSED: %s is a real folder that is not the v1 repo — recorded as an issue, touched nothing" % pb_root)
        return
    if not os.path.isdir(target):
        log.append("symlink skipped: target %s does not exist (no playbook folder mirrored)" % target)
        return
    state = cfgmod.state_dir()
    retired = os.path.join(state, "retired-archives", "%s-%s" % (os.path.basename(pb_root.rstrip("/")), _stamp()))
    os.makedirs(os.path.dirname(retired), exist_ok=True)
    os.rename(pb_root, retired)                 # the WHOLE folder moves; nothing is lost
    os.symlink(target, pb_root)
    log.append("moved %s -> %s and symlinked it to %s" % (pb_root, retired, target))


def _step_symlink(lib, plans_root, pb_root, state, stamp, log):
    # target = the source's playbook folder name as mirrored (resolved by casefold)
    want = lib.cfg.get("playbooks_subdir") or "_PLAYBOOKS"
    target_name = None
    if os.path.isdir(lib.source):
        for entry in os.listdir(lib.source):
            if entry.casefold() == want.casefold() and os.path.isdir(os.path.join(lib.source, entry)):
                target_name = entry
    target = os.path.join(plans_root, target_name or want)
    _symlink_step(lib, pb_root, target, log)
    return log


def _step_config(lib, cfg, plans_root, pb_root):
    new = dict(cfg)
    legacy = {}
    for k in ("plans_root", "playbooks_root", "remotes"):
        if k in cfg and k not in ("remotes",):
            legacy[k] = cfg[k]
    if isinstance(cfg.get("remotes"), dict) and cfg["remotes"].get("plan"):
        legacy["remotes.plan"] = cfg["remotes"]["plan"]
    new["archive_root"] = cfg.get("archive_root") or cfg.get("plans_root") or "~/Claude-plans"
    ret = list(new.get("retired_archives") or [])
    if pb_root not in ret:
        ret.append(pb_root)
    new["retired_archives"] = ret
    new["remote"] = cfg.get("remote") or (cfg.get("remotes") or {}).get("plan")
    new["layout"] = 2
    new["legacy"] = legacy
    cfgmod.save(new)
    lib.cfg = new
    return ["config written: layout=2, archive_root=%s, retired_archives+=%s, remote=%s"
            % (new["archive_root"], pb_root, "set" if new["remote"] else "none")]
