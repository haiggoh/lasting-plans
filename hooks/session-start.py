#!/usr/bin/env python3
"""SessionStart hook — the plugin's install/upgrade step.

Plugins have no install hook, so the first session after install does the setup:
create the archives, import, and install the launchd watcher (unless the user opted out
with `lasting-plans settings set scheduler_enabled false`). Later sessions only
re-stage the watcher when the plugin version changed, and run one quick catch-up scan.
Silent when nothing needs saying. Always exits 0: a hook must never block a session.

--help prints this text and does nothing else.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")
sys.path.insert(0, LIB)


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        print("usage: session-start.py [--help]", file=sys.stderr)
        return 2
    try:
        from lasting_plans import PREFIX, __version__
        from lasting_plans import config as cfgmod
        from lasting_plans import engine, scheduler
    except Exception:
        return 0
    notes = []
    try:
        cfg = cfgmod.load()
        lib = engine.Library(cfg)
        if not os.path.isdir(lib.source):
            return 0
        first = not all(os.path.isdir(os.path.join(r, ".git")) for r in lib.roots.values())
        res = engine.scan(lib)
        if first:
            notes.append("set up: plans are now kept in %s and %s (local Git, never deleted by Claude Code's cleanup)"
                         % (cfg["plans_root"], cfg["playbooks_root"]))
        if res.events and first:
            notes.append("imported %d document(s)" % len(res.events))
        if cfg["scheduler_enabled"] and scheduler.supported():
            stamp = os.path.join(scheduler.install_dir(), "VERSION")
            staged = open(stamp).read().strip() if os.path.exists(stamp) else None
            st = scheduler.state()
            if not st.get("installed") or staged != __version__:
                ok, msg = scheduler.install(LIB)
                if ok:
                    with open(stamp, "w") as f:
                        f.write(__version__ + "\n")
                    notes.append(("watcher %s — opt out: lasting-plans scheduler uninstall" % ("installed" if not staged else "updated to " + __version__)))
                else:
                    notes.append("⚠ watcher NOT installed: %s" % msg)
        if res.pending or res.errors:
            notes.append("⚠ %d item(s) pending — run `lasting-plans doctor`" % (len(res.pending) + len(res.errors)))
    except engine.Busy:
        return 0
    except Exception as e:
        notes.append("⚠ %s" % e)
    if notes:
        msg = "%s: %s" % (PREFIX, "; ".join(notes))
        print(json.dumps({"systemMessage": msg,
                          "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
