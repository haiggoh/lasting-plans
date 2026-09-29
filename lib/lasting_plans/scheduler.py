"""macOS LaunchAgent for the watcher. Installs, reports effective state, removes only its own job.

The plist points at a STABLE launcher copied to ~/.local/share/lasting-plans/, never at the
versioned plugin cache, so a plugin update does not strand the job on a deleted path.
"""
import os
import plistlib
import shutil
import subprocess
import sys

from . import config as cfgmod

LABEL = "com.haiggoh.lasting-plans"


def plist_path():
    return os.path.join(cfgmod.home(), "Library", "LaunchAgents", LABEL + ".plist")


def install_dir():
    return os.environ.get("LASTING_PLANS_INSTALL_DIR") or os.path.join(cfgmod.home(), ".local", "share", "lasting-plans")


def log_path():
    return os.path.join(cfgmod.state_dir(), "watch.log")


def _uid_domain():
    return "gui/%d" % os.getuid()


def _launchctl(*args):
    try:
        return subprocess.run(["launchctl"] + list(args), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def supported():
    return sys.platform == "darwin" and shutil.which("launchctl") is not None


def stage_code(src_lib):
    """Copy the package to a stable location; return the launcher path."""
    dest = install_dir()
    pkg_dest = os.path.join(dest, "lib", "lasting_plans")
    tmp = pkg_dest + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(os.path.join(src_lib, "lasting_plans"), tmp, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.rmtree(pkg_dest, ignore_errors=True)
    os.replace(tmp, pkg_dest)
    launcher = os.path.join(dest, "lasting-plans-watch")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write('#!/bin/sh\n# Stable launcher for the Lasting Plans LaunchAgent (regenerated on install).\n'
                'LP_LIB="%s"\nexport PYTHONPATH="$LP_LIB${PYTHONPATH:+:$PYTHONPATH}"\n'
                'exec "%s" -m lasting_plans.cli watch "$@"\n' % (os.path.join(dest, "lib"), sys.executable))
    os.chmod(launcher, 0o755)
    return launcher


def install(src_lib):
    if not supported():
        return False, "launchd is only available on macOS; run `lasting-plans watch` yourself"
    launcher = stage_code(src_lib)
    os.makedirs(cfgmod.state_dir(), exist_ok=True)
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"}
    for k in ("CLAUDE_CONFIG_DIR", "LASTING_PLANS_CONFIG_DIR", "LASTING_PLANS_STATE_DIR"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    pl = {
        "Label": LABEL,
        "ProgramArguments": [launcher],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": log_path(),
        "StandardErrorPath": log_path(),
        "EnvironmentVariables": env,
    }
    os.makedirs(os.path.dirname(plist_path()), exist_ok=True)
    data = plistlib.dumps(pl)
    _launchctl("bootout", "%s/%s" % (_uid_domain(), LABEL))
    with open(plist_path(), "wb") as f:
        f.write(data)
    r = _launchctl("bootstrap", _uid_domain(), plist_path())
    if r.returncode != 0:
        return False, "launchctl bootstrap failed: %s" % (r.stderr or r.stdout).strip()
    return True, "installed %s" % plist_path()


def uninstall():
    if not os.path.exists(plist_path()):
        return True, "no Lasting Plans LaunchAgent installed"
    _launchctl("bootout", "%s/%s" % (_uid_domain(), LABEL))
    os.unlink(plist_path())
    return True, "removed %s (archives untouched)" % plist_path()


def state():
    """Effective state from launchd itself, not from the config file."""
    if not supported():
        return {"supported": False, "installed": False, "running": False, "detail": "not macOS"}
    installed = os.path.exists(plist_path())
    r = _launchctl("print", "%s/%s" % (_uid_domain(), LABEL))
    loaded = r.returncode == 0
    pid, last_exit = None, None
    for line in r.stdout.splitlines():
        s = line.strip()
        if s.startswith("pid = "):
            pid = s.split("=", 1)[1].strip()
        elif s.startswith("last exit code = "):
            last_exit = s.split("=", 1)[1].strip()
    return {"supported": True, "installed": installed, "loaded": loaded, "running": bool(pid),
            "pid": pid, "last_exit": last_exit, "plist": plist_path(), "log": log_path()}
