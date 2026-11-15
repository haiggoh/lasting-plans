"""Source-repo moves + completion signals (2.0.0): the ONE helper every move in
~/.claude/plans goes through, canonical folder re-casing, and sorting of completed
plans / playbooks into their folders. Moves only — never deletes anything.

`source_move` commits in the source repo with `--only` on exactly the moved pair,
so the user's other staged/unstaged work is never included. Case-only moves go
through `gitrepo.move_path` (the only reliable index rename on a case-insensitive
volume) and are committed with `gitrepo.commit_staged_paths`.

Canonical completion signal (first 40 lines of a doc): a line `**Status:** <value>`
with values draft | approved | in-progress | completed (completed/done/shipped,
case-insensitive = complete), plus a blockquote line `> **Lasting Plans:**` naming
the closing command — plans written with plan-airtight carry both.
"""
import os
import re
import time

from . import classify as classify_mod
from . import engine
from . import gitrepo

HOT_SECONDS = 600  # never move a file modified less than 10 minutes ago (live plan-mode use)

_STATUS_RX = re.compile(r"^\s*\*\*Status:\*\*\s*(\S+)\s*$", re.I)
COMPLETE_WORDS = {"completed", "done", "shipped"}
_CHECKBOX_RX = re.compile(r"^\s*-\s*\[( |x|X)\]", re.M)
_HISTORICAL_RX = re.compile(r"\bHISTORICAL\b")


def status_of(text):
    """The canonical `**Status:**` value from the first 40 lines, lower-cased, or None."""
    for line in text.splitlines()[:40]:
        m = _STATUS_RX.match(line)
        if m:
            return m.group(1).lower()
    return None


def is_complete(lib, doc, text, now):
    """(True, reason) when the document is complete: (a) the Status line says
    completed/done/shipped, (b) it has ≥1 checkbox and all are ticked, or
    (c) it is a playbook whose heading/first lines say HISTORICAL. For all of
    those (not for an explicit `complete` call) the source must also be untouched
    for >= complete_quiet_days."""
    cfg = lib.cfg
    quiet_s = cfg.get("complete_quiet_days", 3) * 86400
    src_rel = doc.sc.get("source_relpath") if doc else None
    mtime = None
    if src_rel:
        p = os.path.join(lib.source, src_rel)
        if os.path.exists(p):
            mtime = os.stat(p).st_mtime
    quiet_ok = mtime is not None and (now - mtime) >= quiet_s
    st = status_of(text)
    if st in COMPLETE_WORDS:
        if quiet_ok:
            return True, "status line '%s' (quiet %dd)" % (st, cfg.get("complete_quiet_days", 3))
        return False, "status '%s' but source touched recently" % st
    boxes = _CHECKBOX_RX.findall(text)
    if boxes and all(b.lower() == "x" for b in boxes):
        if quiet_ok:
            return True, "all %d checkboxes ticked (quiet %dd)" % (len(boxes), cfg.get("complete_quiet_days", 3))
        return False, "all ticked but source touched recently"
    kind = doc.type if doc else classify_mod.classify(src_rel or "", text, cfg.get("classify_overrides"))[0]
    head = "\n".join(text.splitlines()[:5])
    if kind == "playbook" and _HISTORICAL_RX.search(head):
        if quiet_ok:
            return True, "HISTORICAL playbook (quiet %dd)" % cfg.get("complete_quiet_days", 3)
        return False, "HISTORICAL but source touched recently"
    return False, ""


def complete(lib, ref):
    """Explicit completion: set the Status line to `completed` (inserting one under
    the H1 if absent), move the source to <archive_subdir>/ immediately (no quiet
    wait), return the new source relpath."""
    docs = lib.resolve(ref)
    if len(docs) != 1:
        raise LookupError("%r matches %d documents" % (ref, len(docs)))
    doc = docs[0]
    src_rel = doc.sc.get("source_relpath") or doc.sc["archive_relpath"]
    p = os.path.join(lib.source, src_rel)
    text = open(p, encoding="utf-8").read()
    lines = text.splitlines()
    new_lines, done = [], False
    for i, line in enumerate(lines):
        if not done and _STATUS_RX.match(line):
            new_lines.append("**Status:** completed")
            done = True
        else:
            new_lines.append(line)
        if not done and i == 0 and line.startswith("#"):
            new_lines.append("")
            new_lines.append("**Status:** completed")
            done = True
    if not done:
        new_lines = ["**Status:** completed", ""] + new_lines
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")
    arch_sub = lib.cfg.get("archive_subdir") or "_ARCHIVED"
    base = os.path.basename(src_rel)
    taken = {rel for rel, _ in engine.walk_docs(lib.source)}
    new_rel = engine._free_relpath(lib.source, arch_sub + "/" + base, taken)
    source_move(lib, src_rel, new_rel, "Lasting Plans: completed %s -> %s" % (base, new_rel), force=True)
    sc = doc.sc
    sc["source_relpath"] = new_rel
    sc.setdefault("source_history", []).append(new_rel)
    sc["completed_utc"] = engine.now_utc()
    sc.setdefault("sort_moves", []).append({"from": src_rel, "to": new_rel, "utc": engine.now_utc(), "by": "complete"})
    engine.write_sidecar(lib.root, sc)
    return new_rel


def sort_pass(lib, now):
    """One sorting pass over the source: completed docs -> <archive_subdir>/,
    top-level playbook-classified docs -> <playbooks_subdir>/. Moves only, via
    source_move (committed as renames in the source repo). Sticky override:
    sort_override sidecar flag is never re-moved."""
    if not lib.cfg.get("auto_sort", True):
        return []
    arch_sub = lib.cfg.get("archive_subdir") or "_ARCHIVED"
    pb_sub = lib.cfg.get("playbooks_subdir") or "_PLAYBOOKS"
    by_src = lib.by_source()
    events = []
    for rel, abspath in engine.walk_docs(lib.source):
        if rel.startswith(arch_sub + "/"):
            continue                      # already archived
        already_in_pb = rel.startswith(pb_sub + "/")
        doc = by_src.get(rel)
        if doc and doc.sc.get("sort_override"):
            continue
        if doc:
            sm = doc.sc.get("sort_moves") or []
            if sm and doc.sc.get("source_relpath") != sm[-1]["to"]:
                # someone moved it out of where sorting put it: sticky override
                doc.sc["sort_override"] = True
                engine.write_sidecar(lib.root, doc.sc)
                if gitrepo.has_identity(lib.root):
                    gitrepo.commit_paths(lib.root, [engine.sidecar_rel(doc.id)],
                                         "sorting: %s moved back by hand — override recorded" % rel)
                continue
        data = engine.stable_read(abspath)
        if data is None:
            continue
        text = data.decode("utf-8", "replace")
        base = os.path.basename(rel)
        target = None
        reason = ""
        if doc is not None or True:
            ok, reason = is_complete(lib, doc, text, now)
            if ok:
                target = arch_sub
        if target is None and "/" not in rel and not already_in_pb:
            kind = doc.type if doc else classify_mod.classify(rel, text, lib.cfg.get("classify_overrides"))[0]
            if kind == "playbook":
                target = pb_sub
                reason = "playbook"
        if target is None:
            continue
        if time.time() - os.stat(abspath).st_mtime < HOT_SECONDS:
            continue   # hot file (live plan-mode use)
        taken = {r for r, _ in engine.walk_docs(lib.source)}
        new_rel = engine._free_relpath(lib.source, target + "/" + base, taken)
        source_move(lib, rel, new_rel, "Lasting Plans: sorted %s into %s/" % (base, target))
        if doc is not None:
            doc.sc["source_relpath"] = new_rel
            doc.sc.setdefault("source_history", []).append(new_rel)
            doc.sc.setdefault("sort_moves", []).append(
                {"from": rel, "to": new_rel, "utc": engine.now_utc(), "by": "sort (%s)" % reason})
            engine.write_sidecar(lib.root, doc.sc)
        events.append(("sorted", rel, new_rel + "  (" + reason + ")"))
    return events


def source_move(lib, old_rel, new_rel, message, force=False):
    """Move `old_rel` -> `new_rel` in the source folder (and its Git repo, if the
    source is one). Returns the commit sha, or None when only staged (no Git
    identity) or skipped (hot file / missing). `force=True` (explicit `complete`)
    skips the hot-file guard."""
    src = lib.source
    old_abs = os.path.join(src, old_rel)
    if not os.path.exists(old_abs):
        return None
    if not force and time.time() - os.stat(old_abs).st_mtime < HOT_SECONDS:
        return None
    new_abs = os.path.join(src, new_rel)
    os.makedirs(os.path.dirname(new_abs) or src, exist_ok=True)
    case_only = old_rel.casefold() == new_rel.casefold()
    if case_only:
        gitrepo.move_path(src, old_rel, new_rel)      # stages the rename pair
    else:
        os.rename(old_abs, new_abs)
    top = gitrepo.toplevel(src)
    if not top or os.path.realpath(top) != os.path.realpath(src):
        return None                                    # not its own repo: plain FS move
    if not gitrepo.has_identity(src):
        gitrepo.git(src, "add", "-A", "--", old_rel, new_rel)   # staged only, retried later
        return None
    try:
        if case_only:
            gitrepo.git(src, "add", "-A", "--", new_rel)
            return gitrepo.commit_staged_paths(src, [old_rel, new_rel], message)
        return gitrepo.commit_paths(src, [old_rel, new_rel], message)
    except gitrepo.GitError:
        gitrepo.git(src, "add", "-A", "--", old_rel, new_rel, check=False)
        return None


def canonicalize_folders(lib):
    """Re-case top-level source folders that match a canonical subdir name casefold
    but not byte-equal (e.g. `_playbooks` -> `_PLAYBOOKS`): every tracked file under
    the folder is moved in ONE commit, then the folder itself via a temp-name rename.
    Returns event tuples (kind, rel, detail)."""
    cfg = lib.cfg
    wants = [cfg.get("archive_subdir") or "_ARCHIVED",
             cfg.get("playbooks_subdir") or "_PLAYBOOKS",
             cfg.get("cleanup_rescue_subdir") or "_SAVED-FROM-CLEANUP"]
    src = lib.source
    events = []
    if not os.path.isdir(src):
        return events
    for want in wants:
        for entry in sorted(os.listdir(src)):
            if entry == want or entry.casefold() != want.casefold():
                continue
            if not os.path.isdir(os.path.join(src, entry)):
                continue
            old_dir = entry
            prefix = old_dir + "/"
            is_repo = gitrepo.toplevel(src) == os.path.realpath(src)
            tracked = ([p for p in gitrepo.git(src, "ls-files", "-z").stdout.split("\0") if p.startswith(prefix)]
                       if is_repo else [])
            if is_repo and not tracked:
                # folder exists on disk but holds no tracked files: re-case the dir only
                pass
            # re-case the folder itself first (temp name), then every tracked file
            tmp = os.path.join(src, want + ".lp-case-tmp")
            os.rename(os.path.join(src, old_dir), tmp)
            os.rename(tmp, os.path.join(src, want))
            pairs = []
            for p in tracked:
                np = want + "/" + p[len(prefix):]
                gitrepo.move_path(src, p, np)
                pairs.append((p, np))
            msg = "Lasting Plans: folder name %s/ -> %s/ (canonical spelling)" % (old_dir, want)
            if is_repo and pairs and gitrepo.has_identity(src):
                gitrepo.git(src, "add", "-A", "--", *[np for _o, np in pairs])
                gitrepo.commit_staged_paths(src, [x for pair in pairs for x in pair], msg)
            events.append(("recased", old_dir + "/", "%s/ -> %s/" % (old_dir, want)))
    return events
