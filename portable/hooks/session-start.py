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
        first = not os.path.isdir(os.path.join(lib.root, ".git"))
        auto = cfg.get("auto_repair", True)
        if auto:
            # a v1 layout must be migrated BEFORE any one-root scan runs, or the
            # playbook sources would be re-imported as duplicates
            from lasting_plans import migrate, repair
            if migrate.needed(cfg):
                repair.run(lib)
                lib = engine.Library(cfgmod.load())
        res = engine.scan(lib)
        if first:
            notes.append("set up: plans are now kept in %s (local Git, never deleted by Claude Code's cleanup)"
                         % cfg["archive_root"])
        if res.events and first:
            notes.append("imported %d document(s)" % len(res.events))
        if cfg["scheduler_enabled"] and scheduler.supported():
            stamp = os.path.join(scheduler.install_dir(), "VERSION")
            staged = open(stamp).read().strip() if os.path.exists(stamp) else None
            st = scheduler.state()
            if not st.get("installed") or staged != __version__:
                ok, msg = scheduler.install(LIB)  # stage_code writes the VERSION stamp
                if ok:
                    notes.append(("watcher %s — opt out: lasting-plans scheduler uninstall" % ("installed" if not staged else "updated to " + __version__)))
                else:
                    from lasting_plans import repair
                    repair.note_issue("watcher_down", "watcher", "install failed: %s" % msg)
        if auto:
            from lasting_plans import repair
            out = repair.run(lib, res)
            del out  # fixes are journaled; `doctor` shows them
            alerts = repair.alerts()
            if alerts:
                oldest = min(a.get("first_seen_utc") or "" for a in alerts)[:10]
                notes.append("⚠ %d problem(s) auto-repair could not fix (since %s) — details: `lasting-plans doctor`"
                             % (len(alerts), oldest))
        elif res.pending or res.errors:
            notes.append("⚠ %d item(s) pending — run `lasting-plans doctor`" % (len(res.pending) + len(res.errors)))
    except engine.Busy:
        return 0
    except Exception as e:
        try:
            from lasting_plans import repair
            repair.note_issue("hook_exception", "hook", str(e))
        except Exception:
            pass
        return 0
    if notes:
        msg = "%s: %s" % (PREFIX, "; ".join(notes))
        print(json.dumps({"systemMessage": msg,
                          "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
