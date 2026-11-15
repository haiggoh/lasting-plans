"""Optional off-machine copy of THE archive: one PRIVATE Git remote (2.0.0: single archive).

Local preservation never depends on this. States are kept apart on purpose:
  copied    the file is in the archive            (engine)
  committed it is in local Git history            (engine)
  pushed    the remote's tip was READ BACK equal to the local commit (here)
A push that was attempted, rejected, or made while offline is `pending remote`, never
`backed up`. Nothing here force-pushes, and nothing configures a remote implicitly.

The Git remote is named `lasting-plans`, so a remote the user added themselves is left alone.
Legacy `plan`/`playbook` kind arguments are accepted and ignored (one archive now).
"""
import datetime
import json
import os
import re
import subprocess

from . import config as cfgmod
from . import gitrepo, tools

REMOTE = "lasting-plans"
_GH = re.compile(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?$")
# never block on a credential prompt: a scheduled job has no one to answer it
_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes", "GCM_INTERACTIVE": "never"}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(root, *args, check=True, timeout=60):
    env = dict(os.environ, **_ENV)
    cmd = ["git", "-C", root] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise gitrepo.GitError("git %s timed out after %ds (offline?)" % (args[0], timeout)) from None
    except FileNotFoundError:
        raise gitrepo.GitError("git is not installed") from None
    if check and r.returncode != 0:
        raise gitrepo.GitError(_redact((r.stderr or r.stdout).strip())[:400] or "git %s failed" % args[0])
    return r


def _redact(s):
    return re.sub(r"(https?://)[^/@\s]+@", r"\1***@", s)


# ---------------------------------------------------------------- state

def _state_path():
    return os.path.join(cfgmod.state_dir(), "remote.json")


def load_state():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(st):
    cfgmod.atomic_write(_state_path(), json.dumps(st, indent=2, sort_keys=True) + "\n")


def _record(kind, **kw):
    st = load_state()
    st.setdefault(kind, {}).update(kw)
    _save_state(st)


# ---------------------------------------------------------------- config

def url(cfg, kind=None):
    """The single remote URL. `kind` is a legacy v1 argument, ignored."""
    return cfg.get("remote") or (cfg.get("remotes") or {}).get(kind or "plan")


def branch(root):
    r = _git(root, "symbolic-ref", "--short", "HEAD", check=False)
    return r.stdout.strip() or "master"


def privacy(u):
    """('private'|'public'|'unverified', detail) for a remote URL, without pushing anything."""
    if u.startswith("file://") or u.startswith("/"):
        return "private", "local path"
    m = _GH.match(u)
    if not m:
        return "unverified", "not a GitHub URL; privacy cannot be checked"
    gh = tools.on_path("gh")
    if not gh:
        return "unverified", "gh CLI not found; cannot check GitHub visibility"
    r = subprocess.run([gh, "api", "repos/%s/%s" % m.groups(), "--jq", ".private"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return "unverified", "GitHub repo %s/%s not readable: %s" % (m.group(1), m.group(2), r.stderr.strip()[:200])
    return ("private", "GitHub reports private") if r.stdout.strip() == "true" else ("public", "GitHub reports PUBLIC")


KIND = "archive"  # the single state bucket (legacy per-archive keys folded in by load_state)


def configure(lib, kind, u, confirm_private=False):
    """Point the archive at a remote after a privacy check. Pushes nothing. `kind` is legacy, ignored."""
    verdict, detail = privacy(u)
    if verdict == "public":
        raise gitrepo.GitError("refusing %s: %s. Plan archives go only to private remotes." % (u, detail))
    if verdict == "unverified" and not confirm_private:
        raise gitrepo.GitError("%s — re-run with --confirm-private if you know it is private" % detail)
    root = lib.root
    have = _git(root, "remote", check=False).stdout.split()
    _git(root, "remote", "set-url" if REMOTE in have else "add", REMOTE, u)
    cfg = dict(lib.cfg)
    cfg["remote"] = u
    cfgmod.save(cfg)
    lib.cfg = cfg
    _record(KIND, url=_redact(u), privacy=verdict, privacy_detail=detail, privacy_checked_utc=_now())
    return verdict, detail


def disable(lib, kind=None):
    root = lib.root
    if REMOTE in _git(root, "remote", check=False).stdout.split():
        _git(root, "remote", "remove", REMOTE)
    cfg = dict(lib.cfg)
    cfg["remote"] = None
    cfgmod.save(cfg)
    lib.cfg = cfg
    st = load_state()
    st.pop(KIND, None)
    st.pop(kind, None)
    _save_state(st)


# ---------------------------------------------------------------- push / verify

def remote_tip(root, br, timeout=30):
    """The remote's current commit for the branch, READ from the remote (network)."""
    r = _git(root, "ls-remote", REMOTE, "refs/heads/" + br, timeout=timeout)
    line = r.stdout.strip().split("\n")[0]
    return line.split()[0] if line else None


def push(lib, kind=None):
    """Push, then read the tip back. Returns (ok, detail). Never forces. `kind` is legacy, ignored."""
    root = lib.root
    if not url(lib.cfg):
        return False, "no remote configured"
    head = gitrepo.head(root)
    if not head:
        return True, "nothing committed yet"
    br = branch(root)
    try:
        _git(root, "push", "--quiet", REMOTE, "HEAD:refs/heads/" + br, timeout=120)
        tip = remote_tip(root, br)
    except gitrepo.GitError as e:
        _record(KIND, last_error=str(e), last_error_utc=_now(),
                pending_since=load_state().get(KIND, {}).get("pending_since") or _now())
        return False, str(e)
    if tip != head:
        msg = "pushed, but the remote reports %s, not %s" % ((tip or "nothing")[:10], head[:10])
        _record(KIND, last_error=msg, last_error_utc=_now())
        return False, msg
    st = load_state().get(KIND, {})
    _record(KIND, last_pushed_sha=head, pushed_utc=_now(), last_error=None, pending_since=None)
    return True, "remote verified at %s" % head[:10] + ("" if st.get("last_pushed_sha") != head else " (already there)")


def auto_push(lib):
    """After a scan: push the archive if its HEAD differs from the last VERIFIED push.
    Local check only, so an up-to-date archive costs no network. [(kind, ok, detail)]"""
    if lib.cfg.get("remote_push") != "auto":
        return []
    if not url(lib.cfg):
        return []
    head = gitrepo.head(lib.root)
    st = load_state().get(KIND, {})
    if head and head != st.get("last_pushed_sha"):
        ok, detail = push(lib)
        return [(KIND, ok, detail)]
    return []


def summary(lib, verify=False):
    """Remote state of THE archive. Without verify, reports only what was last READ BACK."""
    st = load_state()
    out = {}
    u = url(lib.cfg)
    if not u:
        out[KIND] = {"state": "off"}
        return out
    s = dict(st.get(KIND, {}))
    head = gitrepo.head(lib.root)
    s.update(url=_redact(u), mode=lib.cfg.get("remote_push", "manual"), local_head=head)
    if verify:
        try:
            s["remote_tip"] = remote_tip(lib.root, branch(lib.root))
            s["verified_utc"] = _now()
        except gitrepo.GitError as e:
            s["verify_error"] = str(e)
    tip = s.get("remote_tip") if verify else s.get("last_pushed_sha")
    if verify and s.get("verify_error"):
        s["state"] = "unknown (remote unreachable)"
    elif head is None:
        s["state"] = "nothing to push"
    elif tip == head:
        s["state"] = "in sync"
    elif s.get("last_error"):
        s["state"] = "pending remote (last push failed)"
    else:
        s["state"] = "pending remote"
    if head and tip and tip != head:
        n = _git(lib.root, "rev-list", "--count", "%s..HEAD" % tip, check=False).stdout.strip()
        if n.isdigit():
            s["unpushed_commits"] = int(n)
    out[KIND] = s
    return out


# ---------------------------------------------------------------- GitHub helper + recovery

def create_github(owner, name):
    """Create a PRIVATE GitHub repo if it does not exist; refuse an existing public one."""
    gh = tools.on_path("gh")
    if not gh:
        raise gitrepo.GitError("gh CLI not found")
    full = "%s/%s" % (owner, name)
    r = subprocess.run([gh, "api", "repos/" + full, "--jq", ".private"], capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        if r.stdout.strip() != "true":
            raise gitrepo.GitError("%s already exists and is PUBLIC; not using it" % full)
        return "https://github.com/%s.git" % full, "exists (private)"
    r = subprocess.run([gh, "repo", "create", full, "--private",
                        "--description", "Lasting Plans archive (private). Managed by lasting-plans."],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise gitrepo.GitError("gh repo create %s failed: %s" % (full, r.stderr.strip()[:300]))
    return "https://github.com/%s.git" % full, "created (private)"


def clone(lib, kind, u, confirm_private=False):
    """Recover the archive on a fresh machine: clone into an empty/missing root, remember
    the remote, and re-apply every recorded date and tag to the files. `kind` is legacy, ignored."""
    from . import engine
    root = lib.root
    if os.path.isdir(root) and os.listdir(root):
        raise gitrepo.GitError("%s is not empty; clone refuses to touch it" % root)
    verdict, detail = privacy(u)
    if verdict == "public":
        raise gitrepo.GitError("refusing %s: %s" % (u, detail))
    if verdict == "unverified" and not confirm_private:
        raise gitrepo.GitError("%s — re-run with --confirm-private if you know it is private" % detail)
    os.makedirs(os.path.dirname(root) or ".", exist_ok=True)
    env = dict(os.environ, **_ENV)
    r = subprocess.run(["git", "clone", "--quiet", "--origin", REMOTE, u, root], capture_output=True, text=True, env=env, timeout=600)
    if r.returncode != 0:
        raise gitrepo.GitError("clone failed: %s" % _redact(r.stderr.strip())[:300])
    cfg = dict(lib.cfg)
    cfg["remote"] = u
    cfgmod.save(cfg)
    lib.cfg = cfg
    lib.reload()
    unapplied = {}
    for d in lib.docs:
        bad = engine.apply_metadata(d)
        if bad:
            unapplied[d.sc["archive_relpath"]] = bad
    for rel in engine.apply_folder_tags(root):
        unapplied[rel + "/"] = ["tags"]
    head = gitrepo.head(root)
    _record(KIND, url=_redact(u), privacy=verdict, last_pushed_sha=head, pushed_utc=_now(), last_error=None)
    return len(lib.docs), unapplied
