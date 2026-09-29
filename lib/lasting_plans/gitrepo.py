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


def commit_paths(root, paths, message):
    """Stage exactly `paths` (additions, edits or removals) and commit only them. Returns the SHA."""
    git(root, "add", "-A", "--", *paths)
    staged = git(root, "diff", "--cached", "--name-only", "-z", "--", *paths).stdout
    if not staged.strip("\0"):
        return None
    git(root, "commit", "-q", "-m", message, "--only", "--", *paths)
    sha = git(root, "rev-parse", "HEAD").stdout.strip()
    left = git(root, "status", "--porcelain", "-z", "--", *paths).stdout
    if left.strip("\0"):
        raise GitError("paths still dirty after commit %s: %r" % (sha[:8], left[:200]))
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
