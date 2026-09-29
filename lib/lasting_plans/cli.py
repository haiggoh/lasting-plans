"""`lasting-plans` — CLI and flat TTY menu over the one engine.

Exit codes: 0 ok · 1 error · 2 usage · 3 not found · 4 ambiguous · 5 pending/unhealthy.
"""
import argparse
import json
import os
import shlex
import sys

from . import PREFIX, __version__
from . import config as cfgmod
from . import engine, gitrepo, metadata, scheduler

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENV_HELP = """environment:
  CLAUDE_CONFIG_DIR           Claude Code config dir (source = <it>/plans unless plansDirectory is set)
  LASTING_PLANS_CONFIG_DIR    settings location   (default ~/.config/lasting-plans)
  LASTING_PLANS_STATE_DIR     lock, last-run, log (default ~/.local/state/lasting-plans)
  LASTING_PLANS_SETTLE_SECONDS  a file must be unchanged this long before import (default 2)

exit codes: 0 ok, 1 error, 2 usage, 3 not found, 4 ambiguous id, 5 pending/unhealthy"""


def out(args, human, data):
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(human)


def _one(lib, ref):
    m = lib.resolve(ref)
    if not m:
        print("%s: no document matches %r" % (PREFIX, ref), file=sys.stderr)
        sys.exit(3)
    if len(m) > 1:
        print("%s: %r is ambiguous (%d matches):" % (PREFIX, ref, len(m)), file=sys.stderr)
        for d in m[:10]:
            print("  %s  %s" % (d.id, d.sc["archive_relpath"]), file=sys.stderr)
        sys.exit(4)
    return m[0]


# ------------------------------------------------------------------ commands

def cmd_status(args):
    lib = engine.Library()
    st = engine.status(lib)
    st["scheduler"] = scheduler.state()
    lr = st["last_run"] or {}
    sch = st["scheduler"]
    watch = ("running (pid %s)" % sch["pid"]) if sch.get("running") else ("installed, not running" if sch.get("installed") else "not installed")
    lines = [
        "%s %s" % (PREFIX, __version__),
        "  source (swept by Claude Code): %s — %d document(s)" % (st["source"], st["source_files"]),
        "  plans archive:     %s — %d" % (st["roots"]["plan"], st["counts"].get("plan", 0)),
        "  playbooks archive: %s — %d" % (st["roots"]["playbook"], st["counts"].get("playbook", 0)),
        "  kept after the source copy was swept: %d" % st["kept_after_source_gone"],
        "  watcher: %s" % watch,
        "  last scan: %s" % (lr.get("finished_utc") or "never"),
        "  remote backup: off (local Git only — not an off-machine copy)",
    ]
    bad = False
    if st["unprotected"]:
        bad = True
        lines.append("  ⚠ NOT protected yet: %d source document(s) — run `lasting-plans sync`" % len(st["unprotected"]))
        lines += ["      %s" % p for p in st["unprotected"][:5]]
    if lr.get("pending"):
        bad = True
        lines.append("  ⚠ pending from last scan: %d (see `lasting-plans doctor`)" % lr["pending"])
    if st["corrupt_sidecars"]:
        bad = True
        lines.append("  ⚠ corrupt sidecar(s): %d" % len(st["corrupt_sidecars"]))
    if not bad:
        lines.append("  ✓ every source document has a lasting copy")
    out(args, "\n".join(lines), st)
    return 5 if bad else 0


def cmd_sync(args):
    lib = engine.Library()
    try:
        res = engine.scan(lib)
    except engine.Busy:
        print("%s: another scan is running; try again in a moment" % PREFIX, file=sys.stderr)
        return 5
    except gitrepo.GitError as e:
        print("%s: %s" % (PREFIX, e), file=sys.stderr)
        return 1
    lines = ["%s sync: %d change(s)" % (PREFIX, len(res.events))]
    counts = {}
    for e in res.events:
        counts[e[0]] = counts.get(e[0], 0) + 1
    if counts:
        lines.append("  " + ", ".join("%s %d" % kv for kv in sorted(counts.items())))
    for e in res.events[: (None if args.verbose else 15)]:
        lines.append("  %-12s %s%s" % (e[0], e[2], ("  (" + e[3] + ")") if e[3] else ""))
    if not args.verbose and len(res.events) > 15:
        lines.append("  … %d more (use -v)" % (len(res.events) - 15))
    for p, r in res.pending:
        lines.append("  ⏳ %s — %s" % (p, r))
    for p, r in res.errors:
        lines.append("  ✗ %s — %s" % (p, r))
    out(args, "\n".join(lines), res.as_json())
    return 5 if (res.pending or res.errors) else 0


def _doc_line(d, src):
    j = d.as_json(src)
    flag = "" if j.get("source_present", True) else "  [source swept]"
    created = (j.get("created_utc") or "unknown")[:10]
    return "%s  %-8s %s  %s%s" % (d.id, d.type, created, d.sc["archive_relpath"], flag)


def cmd_list(args):
    lib = engine.Library()
    docs = sorted(lib.docs, key=lambda d: d.sc["archive_relpath"].lower())
    if args.type:
        docs = [d for d in docs if d.type == args.type]
    total = len(docs)
    page = docs[args.offset: args.offset + args.limit] if args.limit else docs[args.offset:]
    human = "\n".join([_doc_line(d, lib.source) for d in page] +
                      (["… showing %d-%d of %d (--offset/--limit)" % (args.offset + 1, args.offset + len(page), total)]
                       if len(page) < total else []))
    out(args, human or "%s: no documents yet — run `lasting-plans sync`" % PREFIX,
        {"total": total, "offset": args.offset, "items": [d.as_json(lib.source) for d in page]})
    return 0


def cmd_show(args):
    lib = engine.Library()
    d = _one(lib, args.ref)
    j = d.as_json(lib.source)
    text = ""
    if os.path.exists(d.path):
        with open(d.path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    meta = "\n".join("  %-18s %s" % (k, j[k]) for k in (
        "id", "type", "type_reason", "archive_path", "source_relpath", "source_present", "created_utc",
        "created_source", "modified_utc", "first_seen_utc", "tags") if k in j)
    if args.full:
        body = text
    else:
        lines = text.splitlines()
        body = "\n".join(lines[: args.lines]) + ("\n… %d more line(s) (--full)" % (len(lines) - args.lines) if len(lines) > args.lines else "")
    j["content"] = text if args.full else None
    out(args, "%s\n%s\n\n%s" % (PREFIX, meta, body), j)
    return 0


def cmd_search(args):
    lib = engine.Library()
    hits = engine.search(lib, args.query, regex=args.regex, limit=args.limit)
    if not hits:
        out(args, "%s: no match for %r in %d document(s)" % (PREFIX, args.query, len(lib.docs)), {"hits": []})
        return 3
    lines = []
    for h in hits:
        lines.append("%s  %s  (%d match%s%s)" % (h["id"], h["path"], h["matches"], "" if h["matches"] == 1 else "es",
                                                ", name" if h["name_match"] else ""))
        lines += ["    … %s …" % s for s in h["snippets"]]
    out(args, "\n".join(lines), {"hits": hits})
    return 0


def cmd_history(args):
    lib = engine.Library()
    d = _one(lib, args.ref)
    h = engine.history(d)
    out(args, "\n".join("%s  %s  %-8s %s" % (x["sha"][:10], x["date"][:19], x["kind"], x["subject"]) for x in h) or "no history",
        {"id": d.id, "history": h})
    return 0


def cmd_diff(args):
    lib = engine.Library()
    d = _one(lib, args.ref)
    text = engine.diff(d, args.rev_a, args.rev_b)
    out(args, text or "%s: no differences" % PREFIX, {"id": d.id, "diff": text})
    return 0


def cmd_meta(args):
    lib = engine.Library()
    d = _one(lib, args.ref)
    if args.apply:
        failed = engine.apply_metadata(d)
        sha = None
    else:
        if not (args.created or args.modified or args.tag):
            print("usage: lasting-plans meta REF [--created DATE] [--modified DATE] [--tag T] | --apply", file=sys.stderr)
            return 2
        failed, sha = engine.set_metadata(d, args.created, args.modified, args.tag)
    msg = "%s: metadata %s for %s" % (PREFIX, "applied" if args.apply else "recorded", d.sc["archive_relpath"])
    if failed:
        msg += "\n  could not apply to the file: %s (kept in the sidecar)" % ", ".join(failed)
    out(args, msg, {"id": d.id, "unapplied": failed, "commit": sha})
    return 5 if failed else 0


def cmd_reclassify(args):
    lib = engine.Library()
    if not args.ref:
        mm = engine.type_mismatches(lib)
        human = "\n".join(["%s: %d document(s) the classifier would file differently" % (PREFIX, len(mm))] +
                          ["  %s  %s -> %s  %s  (%s)" % (d.id, d.type, k, d.sc["archive_relpath"], r) for d, k, r in mm])
        out(args, human, {"mismatches": [{"id": d.id, "type": d.type, "suggested": k, "reason": r,
                                          "path": d.sc["archive_relpath"]} for d, k, r in mm]})
        return 0
    d = _one(lib, args.ref)
    if not args.type:
        print("usage: lasting-plans reclassify REF {plan,playbook}", file=sys.stderr)
        return 2
    try:
        rel, a, b = engine.reclassify(lib, d, args.type)
    except ValueError as e:
        print("%s: %s" % (PREFIX, e), file=sys.stderr)
        return 2
    except engine.Busy:
        print("%s: a scan is running; try again in a moment" % PREFIX, file=sys.stderr)
        return 5
    out(args, "%s: %s is now a %s\n  %s\n  commits: %s (added), %s (removed from the %s archive)" % (
        PREFIX, d.id, args.type, os.path.join(lib.roots[args.type], rel), (a or "")[:10], (b or "")[:10], d.type),
        {"id": d.id, "type": args.type, "path": rel, "commit_added": a, "commit_removed": b})
    return 0


def cmd_recover_dates(args):
    from . import recover
    lib = engine.Library()
    try:
        start = metadata.parse_iso(args.since)
        end = metadata.parse_iso(args.until) if args.until else start + 86400
    except ValueError as e:
        print("%s: bad date: %s" % (PREFIX, e), file=sys.stderr)
        return 2
    mtimes = recover.load_mtimes(args.mtimes) if args.mtimes else {}
    changes = recover.plan(lib, start, end, mtimes)
    lines = ["%s recover-dates: %d document(s) with a recorded creation date in [%s, %s) or none%s" % (
        PREFIX, len(changes), metadata.utc_iso(start), metadata.utc_iso(end), "" if args.apply else " — DRY RUN, nothing written")]
    for ch in changes[: None if args.verbose else 20]:
        sc = ch["doc"].sc
        lines.append("  %s  %s" % (ch["doc"].id, sc["archive_relpath"]))
        if ch["created"]:
            lines.append("      created  %s -> %s  (%s)" % ((sc.get("created_utc") or "unknown")[:16], metadata.utc_iso(ch["created"][0])[:16], ch["created"][1]))
        if ch["modified"]:
            lines.append("      modified %s -> %s  (%s)" % ((sc.get("modified_utc") or "unknown")[:16], metadata.utc_iso(ch["modified"][0])[:16], ch["modified"][1]))
    if not args.verbose and len(changes) > 20:
        lines.append("  … %d more (-v)" % (len(changes) - 20))
    data = {"changes": [{"id": c["doc"].id, "path": c["doc"].sc["archive_relpath"],
                         "created": c["created"] and {"utc": metadata.utc_iso(c["created"][0]), "evidence": c["created"][1]},
                         "modified": c["modified"] and {"utc": metadata.utc_iso(c["modified"][0]), "evidence": c["modified"][1]}}
                        for c in changes]}
    if args.apply and changes:
        if not args.reason:
            print("%s: --apply needs --reason \"what lost the dates\" (it is recorded in every sidecar)" % PREFIX, file=sys.stderr)
            return 2
        shas, failed = recover.apply(changes, args.reason)
        lines.append("  recorded; commits: %s" % ", ".join("%s %s" % (os.path.basename(r), (s or "none")[:10]) for r, s in shas.items()))
        for rel, bad in failed:
            lines.append("  ⚠ %s: could not apply %s to the file (kept in the sidecar)" % (rel, ", ".join(bad)))
        data.update(commits=shas, unapplied=failed)
    out(args, "\n".join(lines), data)
    return 0


def cmd_doctor(args):
    lib = engine.Library()
    checks = engine.doctor(lib)
    sch = scheduler.state()
    checks.append({"check": "watcher running (launchd)", "ok": bool(sch.get("running")),
                   "detail": "" if sch.get("supported") else "unsupported here — run `lasting-plans watch`"})
    lr = engine.last_run() or {}
    for p in lr.get("pending_items", []) + lr.get("error_items", []):
        checks.append({"check": "last scan: %s" % p["path"], "ok": False, "detail": p["reason"]})
    human = "\n".join(["%s doctor" % PREFIX] + ["  %s %s%s" % ("✓" if c["ok"] else "✗", c["check"], ("  — " + c["detail"]) if c["detail"] and not c["ok"] else "") for c in checks])
    out(args, human, {"checks": checks})
    return 0 if all(c["ok"] for c in checks) else 5


def cmd_settings(args):
    cfg = cfgmod.load()
    if args.action == "show":
        out(args, "%s settings (%s)\n" % (PREFIX, cfgmod.config_path()) +
            "\n".join("  %-20s %s" % (k, json.dumps(v)) for k, v in sorted(cfg.items())), cfg)
        return 0
    if args.action == "set":
        if not args.key or args.value is None:
            print("usage: lasting-plans settings set KEY VALUE", file=sys.stderr)
            return 2
        cfg[args.key] = cfgmod.parse_value(args.key, args.value)
    elif args.action == "reset":
        if not args.key or args.key not in cfgmod.DEFAULTS:
            print("usage: lasting-plans settings reset KEY", file=sys.stderr)
            return 2
        cfg[args.key] = cfgmod.DEFAULTS[args.key]
    cfgmod.save(cfg)
    cfgmod.load()  # validate what we wrote
    print("%s: %s = %s" % (PREFIX, args.key, json.dumps(cfg[args.key])))
    if args.key in ("scheduler_enabled", "interval_seconds", "source_dir", "plans_root", "playbooks_root") and scheduler.state().get("installed"):
        ok, msg = (scheduler.install(LIB_DIR) if cfg["scheduler_enabled"] else scheduler.uninstall())
        print("  watcher: %s" % msg)
    return 0


def cmd_scheduler(args):
    if args.action == "status":
        st = scheduler.state()
        out(args, "%s watcher: %s" % (PREFIX, json.dumps(st, indent=2)), st)
        return 0 if st.get("running") else 5
    if args.action == "install":
        ok, msg = scheduler.install(LIB_DIR)
    else:
        ok, msg = scheduler.uninstall()
    print("%s: %s" % (PREFIX, msg))
    if ok and args.action == "install":
        st = scheduler.state()
        print("  effective state: loaded=%s running=%s" % (st.get("loaded"), st.get("running")))
    return 0 if ok else 1


def cmd_watch(args):
    from . import watch
    watch.run(once=args.once, max_seconds=args.max_seconds)
    return 0


def cmd_setup(args):
    """Idempotent first run: create the archives, import, install the watcher (opt-out)."""
    print("%s setup — local only, no network, no account." % PREFIX)
    lib = engine.Library()
    for t, how in engine.prepare_roots(lib).items():
        print("  %s archive %s: %s" % (t, lib.roots[t], how))
    rc = cmd_sync(argparse.Namespace(json=False, verbose=False))
    cfg = cfgmod.load()
    if args.no_scheduler or not cfg["scheduler_enabled"]:
        print("  watcher: not installed (%s)" % ("--no-scheduler" if args.no_scheduler else "scheduler_enabled=false"))
    else:
        ok, msg = scheduler.install(LIB_DIR)
        print("  watcher: %s" % msg)
        print("  opt out any time: lasting-plans scheduler uninstall")
    return rc


# ------------------------------------------------------------------ menu

MENU = [
    ("status", "Status dashboard", []),
    ("sync", "Sync now (import new/changed plans)", []),
    ("list", "List documents", []),
    ("search", "Search full text", ["query"]),
    ("show", "Show a document", ["ref"]),
    ("history", "History of a document", ["ref"]),
    ("diff", "Diff latest change of a document", ["ref"]),
    ("doctor", "Doctor (health checks)", []),
    ("settings show", "Show settings", []),
    ("scheduler status", "Watcher status", []),
]


def menu(parser):
    cmd_status(argparse.Namespace(json=False))
    while True:
        print()
        for i, (_, label, _) in enumerate(MENU, 1):
            print("  %2d) %s" % (i, label))
        print("   q) quit")
        try:
            c = input("%s > " % PREFIX).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if c.lower() in ("q", "quit", ""):
            return 0
        if not c.isdigit() or not 1 <= int(c) <= len(MENU):
            print("pick 1-%d or q" % len(MENU))
            continue
        verb, _, params = MENU[int(c) - 1]
        argv = verb.split()
        try:
            for p in params:
                argv.append(input("  %s: " % p).strip())
        except (EOFError, KeyboardInterrupt):
            print()
            continue
        print("  $ lasting-plans %s" % " ".join(shlex.quote(a) for a in argv))
        try:
            dispatch(parser, argv)
        except SystemExit:
            pass


# ------------------------------------------------------------------ parser

def build_parser():
    p = argparse.ArgumentParser(
        prog="lasting-plans",
        description="🗂️ Lasting Plans — keep Claude Code plans and playbooks in visible, Git-versioned archives "
                    "(~/Claude-plans, ~/Claude-playbooks) that the 30-day plans sweep cannot touch. "
                    "Bare `lasting-plans` on a terminal opens a menu; otherwise prints status.",
        epilog=ENV_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version="lasting-plans " + __version__)
    sub = p.add_subparsers(dest="cmd")

    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_, description=help_)
        s.add_argument("--json", action="store_true", help="machine-readable output")
        s.set_defaults(fn=fn)
        return s

    add("status", cmd_status, "dashboard: what is protected, what is not, watcher state")
    s = add("sync", cmd_sync, "scan the source and archives once and commit changes")
    s.add_argument("-v", "--verbose", action="store_true")
    s = add("list", cmd_list, "list archived documents")
    s.add_argument("--type", choices=["plan", "playbook"])
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--offset", type=int, default=0)
    s = add("show", cmd_show, "show one document's metadata and text")
    s.add_argument("ref", help="id, id prefix, or path fragment")
    s.add_argument("--full", action="store_true", help="whole text (default: first --lines)")
    s.add_argument("--lines", type=int, default=40)
    s = add("search", cmd_search, "search the FULL text of every archived document")
    s.add_argument("query")
    s.add_argument("--regex", action="store_true")
    s.add_argument("--limit", type=int, default=50)
    s = add("history", cmd_history, "commits touching a document (content vs metadata)")
    s.add_argument("ref")
    s = add("diff", cmd_diff, "diff a document: latest content change, or REV_A [REV_B]")
    s.add_argument("ref")
    s.add_argument("rev_a", nargs="?")
    s.add_argument("rev_b", nargs="?")
    s = add("meta", cmd_meta, "record dates/tags in the sidecar and apply them to the archive file")
    s.add_argument("ref")
    s.add_argument("--created", help="ISO date/time (local if no zone)")
    s.add_argument("--modified")
    s.add_argument("--tag", action="append", help="Finder tag to ADD (repeatable; never removes)")
    s.add_argument("--apply", action="store_true", help="re-apply recorded metadata (e.g. after a clone)")
    s = add("reclassify", cmd_reclassify, "move a document between the plan and playbook archives "
            "(no REF: list documents the classifier would now file differently)")
    s.add_argument("ref", nargs="?")
    s.add_argument("type", nargs="?", choices=["plan", "playbook"])
    s = add("recover-dates", cmd_recover_dates,
            "after a DOCUMENTED loss of file dates, recover them from backup mtimes and the dates "
            "written in each document (dry run unless --apply)")
    s.add_argument("--since", required=True, help="start of the loss window: documents whose recorded creation date is in it (or unknown)")
    s.add_argument("--until", help="end of the window (default: --since + 1 day)")
    s.add_argument("--mtimes", help="recovery TSV: verdict, path, current_mtime, backup_mtime (only 'exact' rows used)")
    s.add_argument("--apply", action="store_true", help="write the dates (default: show what would change)")
    s.add_argument("--reason", help="what lost the dates; recorded in each sidecar (required with --apply)")
    s.add_argument("-v", "--verbose", action="store_true")
    add("doctor", cmd_doctor, "health checks, including last scan's pending items")
    s = add("settings", cmd_settings, "show / set / reset settings")
    s.add_argument("action", choices=["show", "set", "reset"])
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")
    s = add("scheduler", cmd_scheduler, "install / uninstall / status of the launchd watcher")
    s.add_argument("action", choices=["install", "uninstall", "status"])
    s = add("watch", cmd_watch, "run the watch-folder loop in the foreground (what launchd runs)")
    s.add_argument("--once", action="store_true")
    s.add_argument("--max-seconds", type=float, help=argparse.SUPPRESS)
    s = add("setup", cmd_setup, "first run: create archives, import, install the watcher")
    s.add_argument("--no-scheduler", action="store_true")
    return p


def dispatch(parser, argv):
    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        if sys.stdin.isatty() and sys.stdout.isatty():
            return menu(parser)
        return cmd_status(argparse.Namespace(json=False))
    try:
        return args.fn(args)
    except cfgmod.ConfigError as e:
        print("%s: %s" % (PREFIX, e), file=sys.stderr)
        return 2
    except gitrepo.GitError as e:
        print("%s: %s" % (PREFIX, e), file=sys.stderr)
        return 1


def main(argv=None):
    parser = build_parser()
    rc = dispatch(parser, sys.argv[1:] if argv is None else argv)
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
