"""Source-repo moves (2.0.0): the ONE helper every move in ~/.claude/plans goes
through, plus canonical folder re-casing. Moves only — never deletes anything.

`source_move` commits in the source repo with `--only` on exactly the moved pair,
so the user's other staged/unstaged work is never included. Case-only moves go
through `gitrepo.move_path` (the only reliable index rename on a case-insensitive
volume) and are committed with `gitrepo.commit_staged_paths`.
"""
import os
import time

from . import gitrepo

HOT_SECONDS = 600  # never move a file modified less than 10 minutes ago (live plan-mode use)


def source_move(lib, old_rel, new_rel, message):
    """Move `old_rel` -> `new_rel` in the source folder (and its Git repo, if the
    source is one). Returns the commit sha, or None when only staged (no Git
    identity) or skipped (hot file / missing)."""
    src = lib.source
    old_abs = os.path.join(src, old_rel)
    if not os.path.exists(old_abs):
        return None
    if time.time() - os.stat(old_abs).st_mtime < HOT_SECONDS:
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
