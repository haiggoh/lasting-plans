"""Thin, path-scoped Git wrapper. Never stages anything but the paths it is given."""
import os
import subprocess


class GitError(Exception):
    pass


def git(root, *args, check=True, input=None):
    cmd = ["git", "-c", "core.quotepath=false", "-C", root] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, input=input, timeout=120)
    except FileNotFoundError:
        raise GitError("git is not installed") from None
    if check and r.returncode != 0:
        raise GitError("git %s failed: %s" % (" ".join(args[:2]), (r.stderr or r.stdout).strip()[:400]))
    return r


def toplevel(path):
    """The repo containing `path` (walking up), or None."""
    p = path
    while not os.path.isdir(p):
        p = os.path.dirname(p)
    r = git(p, "rev-parse", "--show-toplevel", check=False)
    return os.path.realpath(r.stdout.strip()) if r.returncode == 0 else None


def ensure_repo(root, role):
    """Create or adopt the archive repo at `root`. Returns a short human status.

    - missing or empty dir with no enclosing repo -> git init
    - existing repo whose top level IS root         -> adopt
    - anything else (non-empty non-repo, nested in another repo) -> refuse
    """
    real = os.path.realpath(root) if os.path.exists(root) else root
    if os.path.isdir(root) and toplevel(root) == os.path.realpath(root):
        return "adopted"
    parent_repo = toplevel(os.path.dirname(real) or "/")
    if parent_repo:
        raise GitError("%s would be nested inside the Git repo %s; choose another root" % (root, parent_repo))
    if os.path.isdir(root) and os.listdir(root):
        raise GitError("%s exists, is not empty and is not a Git repo; refusing to initialise it" % root)
    os.makedirs(root, exist_ok=True)
    git(root, "init", "-q")
    return "initialised"


def has_identity(root):
    name = git(root, "config", "user.name", check=False).stdout.strip() or os.environ.get("GIT_AUTHOR_NAME")
    mail = git(root, "config", "user.email", check=False).stdout.strip() or os.environ.get("GIT_AUTHOR_EMAIL")
    return bool(name and mail)


def index_case(root, paths):
    """Rewrite each path to the spelling Git's index uses for it, else the
    on-disk spelling (per-component casefold match), else unchanged.

    Git pathspecs match the index case-sensitively even on a case-insensitive
    volume, so a wrong-case path silently stages nothing — map every path the
    caller got from a scan or a user through this first.
    """
    try:
        idx = [e for e in git(root, "ls-files", "-z").stdout.split("\0") if e]
    except GitError:
        idx = []
    out = []
    for path in paths:
        if not path:
            out.append(path)
            continue
        fold = [e for e in idx if e.casefold() == path.casefold()]
        if fold:
            out.append(fold[0])
            continue
        fixed, cur = [], root
        for comp in path.split("/"):
            try:
                entries = os.listdir(cur)
            except OSError:
                entries = []
            m = [e for e in entries if e.casefold() == comp.casefold()]
            chosen = m[0] if m else comp
            fixed.append(chosen)
            cur = os.path.join(cur, chosen)
        out.append("/".join(fixed))
    return out


def move_path(root, old, new):
    """`git mv` old -> new, via `<new>.lp-case-tmp` when only the case differs
    (a plain mv refuses the destination on a case-insensitive volume). Creates
    parent directories, re-cases a parent folder that is physically the same
    directory, and prunes the now-empty parent directories of `old` up to root.

    `git mv` refuses paths that are staged but never committed ("not under version
    control"), so those go via os.rename + add instead."""
    new_abs = os.path.join(root, new)
    os.makedirs(os.path.dirname(new_abs) or root, exist_ok=True)
    head = git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).stdout.strip()
    in_head = bool(head) and bool(git(root, "ls-tree", head, "--", old, check=False).stdout.strip())
    if not in_head:
        # staged-new or untracked: `git mv` refuses ("not under version control")
        os.rename(os.path.join(root, old), new_abs)
        git(root, "add", "-A", "--", old, new, check=False)
    elif old.casefold() == new.casefold():
        tmp = new + ".lp-case-tmp"
        if os.path.exists(os.path.join(root, tmp)):
            git(root, "rm", "-q", "-f", "--", tmp, check=False)   # stale temp from a crashed run (tracked)
            if os.path.exists(os.path.join(root, tmp)):
                os.remove(os.path.join(root, tmp))               # untracked leftover
        git(root, "mv", "--", old, tmp)
        git(root, "mv", "--", tmp, new)
    else:
        git(root, "mv", "--", old, new)
    old_parent, new_parent = os.path.dirname(old), os.path.dirname(new)
    if (old_parent and old_parent != new_parent
            and old_parent.casefold() == new_parent.casefold()):
        src_dir, dst_dir = os.path.join(root, old_parent), os.path.join(root, new_parent)
        if os.path.isdir(src_dir) and os.path.isdir(dst_dir) and os.path.samefile(src_dir, dst_dir):
            os.rename(src_dir, dst_dir)
    d = os.path.dirname(os.path.join(root, old))
    stop = os.path.realpath(root)
    while d and os.path.isdir(d) and os.path.realpath(d) != stop and not os.listdir(d):
        os.rmdir(d)
        d = os.path.dirname(d)


def commit_paths(root, paths, message):
    """Stage exactly `paths` (additions, edits or removals) and commit only them. Returns the SHA.

    Paths that are staged-deleted and gone from disk (neither in the index nor on the
    volume) are NOT passed to `git add` — that pathspec fatals — but stay in the commit
    pathspec, where `commit --only` reads the worktree and records the deletion."""
    paths = index_case(root, list(paths))
    addable = [p for p in paths
               if git(root, "ls-files", "--", p, check=False).stdout.strip()
               or os.path.exists(os.path.join(root, p))]
    if addable:
        git(root, "add", "-A", "--", *addable)
    staged = git(root, "diff", "--cached", "--name-only", "-z", "--", *paths).stdout
    if not staged.strip("\0"):
        return None
    git(root, "commit", "-q", "-m", message, "--only", "--", *paths)
    sha = git(root, "rev-parse", "HEAD").stdout.strip()
    left = git(root, "status", "--porcelain", "-z", "--", *paths).stdout
    if left.strip("\0"):
        raise GitError("paths still dirty after commit %s: %r" % (sha[:8], left[:200]))
    return sha


def commit_staged_paths(root, paths, message):
    """Commit exactly the staged changes for `paths` (which may include a rename
    pair staged by `git mv`), leaving every other staged change staged.

    `commit --only -- <paths>` cannot record a case-only staged rename on a
    case-insensitive volume (the old path still resolves in the working tree,
    so its staged deletion is skipped), so this uses a plain index commit after
    temporarily unstaging the rest — and restores those via a cached patch, so
    the user's other staged work is never committed nor lost from the index.
    Returns the SHA."""
    # no index_case mapping here: it would collapse a rename pair (old casefolds to new)
    # and unstage the old path's deletion — callers pass current-spelling paths
    paths = list(paths)
    staged = [p for p in git(root, "diff", "--cached", "--name-only", "-z").stdout.split("\0") if p]
    keep = set(paths)
    non_keep = [p for p in staged if p not in keep]
    patch = None
    if non_keep:
        patch = git(root, "diff", "--cached", "--binary", "--", *non_keep).stdout
        git(root, "reset", "-q", "--", *non_keep)
    try:
        git(root, "commit", "-q", "-m", message)
    except GitError:
        if patch:
            git(root, "apply", "--cached", "--binary", input=patch, check=False)
        raise
    sha = git(root, "rev-parse", "HEAD").stdout.strip()
    if patch:
        git(root, "apply", "--cached", "--binary", input=patch, check=False)
    left = git(root, "status", "--porcelain", "-z", "--", *paths).stdout
    # only STAGED leftovers mean the commit missed them; an unstaged ' D' deletion of a
    # moved-away old path is committed by the next pass's catch-up
    bad = [e for e in left.split("\0") if e and e[0] not in " ?"]
    if bad:
        raise GitError("paths still staged-dirty after commit %s: %r" % (sha[:8], bad[:3]))
    return sha


def status_z(root):
    """[(code, path)] from porcelain -z, untracked files listed individually."""
    out = git(root, "status", "--porcelain", "-z", "--untracked-files=all").stdout
    items, parts, i = [], out.split("\0"), 0
    while i < len(parts):
        e = parts[i]
        if not e:
            i += 1
            continue
        code, path = e[:2], e[3:]
        if code[0] in "RC":
            i += 1  # the rename source follows as its own field
        items.append((code, path))
        i += 1
    return items


def head(root):
    r = git(root, "rev-parse", "--verify", "-q", "HEAD", check=False)
    return r.stdout.strip() or None
