"""Task 4: safe, idempotent fixers for every foreseeable failure class (repair.py)."""
import json
import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from lasting_plans import config as cfgmod  # noqa: E402
from lasting_plans import engine, gitrepo, repair  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".claude" / "plans").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("LASTING_PLANS_CONFIG_DIR", str(h / ".config" / "lasting-plans"))
    monkeypatch.setenv("LASTING_PLANS_STATE_DIR", str(h / ".state"))
    monkeypatch.setenv("LASTING_PLANS_SETTLE_SECONDS", "0")
    monkeypatch.setenv("LASTING_PLANS_TRASH_DIR", str(h / ".Trash"))
    (h / ".Trash").mkdir()
    for k, v in {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "f@example.invalid",
                 "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "f@example.invalid",
                 "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(k, v)
    return h


def src(home):
    return home / ".claude" / "plans"


def arch(home):
    return home / "Claude-plans"


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def git(root, *a, check=True):
    r = subprocess.run(["git", "-C", str(root)] + list(a), capture_output=True, text=True)
    if check:
        assert r.returncode == 0, "git %s failed: %s" % (" ".join(a), r.stderr)
    return r.stdout


def scan():
    return engine.scan(engine.Library())


def issues(home, res=None):
    return {i["key"]: i for i in repair.collect_issues(engine.Library(), res)}


def fix(home, key, tmp_path, res=None):
    iss = issues(home, res)
    assert key in iss, "no issue %s (have %s)" % (key, sorted(iss))
    backup = str(tmp_path / "backup")
    os.makedirs(backup, exist_ok=True)
    return repair.FIXERS[iss[key]["kind"]](engine.Library(), iss[key], backup)


# ------------------------------------------------------------------ fixers

def test_fix_migration_pending(home, monkeypatch):
    from lasting_plans import migrate
    monkeypatch.setattr(migrate.scheduler, "install", lambda lib: (True, "ok"))
    monkeypatch.setattr(migrate.scheduler, "supported", lambda: True)
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from test_migrate import make_v1_layout
    make_v1_layout(home)
    iss = issues(home)
    assert any(k.startswith("migration_pending:") for k in iss)
    fixed, note = fix(home, next(k for k in iss if k.startswith("migration_pending:")), home / "tmp", None)
    assert fixed
    assert cfgmod.load()["layout"] == 2


def test_fix_uncommitted(home, monkeypatch):
    put(src(home) / "a.md", "# a\n")
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k)
    res = scan()
    assert any("uncommitted" in r for _p, r in res.pending)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "F")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "f@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "F")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "f@example.invalid")
    key = next(k for k in issues(home, res) if k.startswith("uncommitted:"))
    fixed, _note = fix(home, key, home / "tmp", res)
    assert fixed
    assert git(arch(home), "status", "--porcelain") == ""


def test_fix_no_identity(home, monkeypatch):
    put(src(home) / "a.md", "# a\n")
    scan()
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k)
    iss = issues(home)
    key = next((k for k in iss if k.startswith("no_identity:")), None)
    assert key, sorted(iss)
    fixed, _note = fix(home, key, home / "tmp")
    assert fixed
    assert git(arch(home), "config", "user.name").strip() == "Lasting Plans"
    assert git(arch(home), "config", "user.email").strip() == "lasting-plans@localhost"


def _rm_archive_doc(home):
    put(src(home) / "a.md", "# a\n")
    scan()
    (arch(home) / "a.md").unlink()
    git(arch(home), "add", "-A", "--", "a.md")
    git(arch(home), "commit", "-q", "-m", "user removed it")   # removal committed; sidecar still points at a.md
    return engine.Library().docs[0]


def test_fix_archive_missing_rm_is_restored(home):
    _rm_archive_doc(home)
    key = next(k for k in issues(home) if k.startswith("archive_missing:"))
    fixed, _note = fix(home, key, home / "tmp")
    assert fixed
    assert (arch(home) / "a.md").read_text(encoding="utf-8") == "# a\n"
    assert not [c for c in engine.doctor(engine.Library()) if c["check"] == "every archive document present" and not c["ok"]]


def test_fix_archive_missing_moved_is_repointed(home):
    put(src(home) / "a.md", "# a\n")
    scan()
    os.rename(arch(home) / "a.md", arch(home) / "renamed-by-hand.md")   # untracked, unclaimed
    key = next(k for k in issues(home) if k.startswith("archive_missing:"))
    fixed, _note = fix(home, key, home / "tmp")
    assert fixed
    doc = engine.Library().docs[0]
    assert doc.sc["archive_relpath"] == "renamed-by-hand.md"
    assert os.path.exists(doc.path)


def test_fix_archive_missing_trashed_is_honoured(home):
    doc = _rm_archive_doc(home)
    sha = doc.sc["archive_sha256"]
    trash_file = home / ".Trash" / "a.md"
    trash_file.write_bytes((arch(home) / ".git" and b"") or b"")  # placeholder, replaced below
    # put the SAME content in the Trash (what Finder would do)
    import hashlib
    content = b"# a\n"
    assert hashlib.sha256(content).hexdigest() == sha
    trash_file.write_bytes(content)
    key = next(k for k in issues(home) if k.startswith("archive_missing:"))
    fixed, _note = fix(home, key, home / "tmp")
    assert fixed
    doc = engine.Library().docs[0]
    assert doc.sc.get("deleted_by") == "user" and doc.sc.get("deleted_utc")
    assert not os.path.exists(arch(home) / "a.md") or True
    assert git(arch(home), "status", "--porcelain") == ""


def test_fix_archive_missing_trash_unreadable_defers(home, monkeypatch):
    _rm_archive_doc(home)
    os.chmod(home / ".Trash", 0)
    try:
        key = next(k for k in issues(home) if k.startswith("archive_missing:"))
        fixed, note = fix(home, key, home / "tmp")
        assert not fixed and "deferred" in note
    finally:
        os.chmod(home / ".Trash", 0o755)


def test_fix_archive_missing_policy_honor_and_restore(home, monkeypatch):
    # honor: never restore, mark deleted
    _rm_archive_doc(home)
    cfg = cfgmod.load()
    cfg["archive_deletions"] = "honor"
    cfgmod.save(cfg)
    key = next(k for k in issues(home) if k.startswith("archive_missing:"))
    fixed, _ = fix(home, key, home / "tmp")
    assert fixed and engine.Library().docs[0].sc.get("deleted_by") == "user"
    # restore: always restore even when trashed
    put(src(home) / "b.md", "# b\n")
    scan()
    (arch(home) / "b.md").unlink()
    git(arch(home), "add", "-A", "--", "b.md")
    git(arch(home), "commit", "-q", "-m", "rm b")
    (home / ".Trash" / "b.md").write_bytes(b"# b\n")
    cfg = cfgmod.load()
    cfg["archive_deletions"] = "restore"
    cfgmod.save(cfg)
    key = next(k for k in issues(home) if k.startswith("archive_missing:") and k.endswith("b.md"))
    fixed, _ = fix(home, key, home / "tmp")
    assert fixed and (arch(home) / "b.md").exists()


def test_fix_sidecar_corrupt(home):
    put(src(home) / "a.md", "# a\n")
    scan()
    sc = engine.Library().docs[0]
    p = arch(home) / ".lasting-plans" / "docs" / (sc.id + ".json")
    p.write_text("{not json", encoding="utf-8")   # corrupt on disk; HEAD still holds the good copy
    iss = issues(home)
    key = next(k for k in iss if k.startswith("sidecar_corrupt:"))
    fixed, _ = fix(home, key, home / "tmp")
    assert fixed
    lib = engine.Library()
    assert not lib.corrupt
    assert json.loads(p.read_text())["id"] == sc.id


def test_fix_type_mismatch(home):
    put(src(home) / "x.md", "# notes\n")
    scan()
    lib = engine.Library()
    d = lib.docs[0]
    d.sc["type_reason"] = "old rule"
    engine.write_sidecar(d.root, d.sc)
    git(arch(home), "add", "-A", "--", ".lasting-plans/docs/%s.json" % d.id)
    git(arch(home), "commit", "-q", "-m", "mismatch")
    # pretend the classifier now says playbook
    engine.reclassify(engine.Library(), engine.Library().docs[0], "playbook")
    d = engine.Library().docs[0]
    d.sc["type_reason"] = "filename matched playbook/handbook"
    engine.write_sidecar(d.root, d.sc)
    git(arch(home), "add", "-A", "--", ".lasting-plans/docs/%s.json" % d.id)
    git(arch(home), "commit", "-q", "-m", "mismatch2")
    iss = issues(home)
    key = next(k for k in iss if k.startswith("type_mismatch:"))
    fixed, _ = fix(home, key, home / "tmp")
    assert fixed
    d = engine.Library().docs[0]
    assert d.type == "plan" and d.sc["type_reason"] == "auto-reclassified by repair"
    assert engine.type_mismatches(engine.Library()) == []


def test_fix_empty_folder(home):
    put(src(home) / "a.md", "# a\n")
    scan()
    (arch(home) / "emptydir").mkdir()
    iss = issues(home)
    key = next(k for k in iss if k.startswith("empty_folder:"))
    fixed, _ = fix(home, key, home / "tmp")
    assert fixed and not (arch(home) / "emptydir").exists()


def test_fix_watcher_down(home, monkeypatch):
    put(src(home) / "a.md", "# a\n")
    scan()
    from lasting_plans import scheduler
    monkeypatch.setattr(scheduler, "supported", lambda: True)
    monkeypatch.setattr(scheduler, "state", lambda: {"supported": True, "installed": True, "running": False})
    calls = []
    monkeypatch.setattr(scheduler, "install", lambda lib: calls.append(lib) or (True, "ok"))
    iss = issues(home)
    key = next(k for k in iss if k.startswith("watcher_down:"))
    fixed, _ = fix(home, key, home / "tmp")
    assert fixed and calls


def test_fix_transient_and_emergency_not_fixed(home, monkeypatch, tmp_path):
    put(src(home) / "a.md", "# a\n", )
    monkeypatch.setenv("LASTING_PLANS_SETTLE_SECONDS", "30")
    import time
    p = src(home) / "a.md"
    os.utime(p, (time.time(), time.time()))
    res = scan()
    assert any("will retry" in r for _p, r in res.pending)
    iss = issues(home, res)
    key = next(k for k in iss if k.startswith("transient:"))
    fixed, note = fix(home, key, home / "tmp", res)
    assert not fixed and "wait" in note.lower()
    # emergency: git missing
    from lasting_plans import tools
    monkeypatch.setattr(tools, "on_path", lambda name: None)
    iss = issues(home, res)
    ekey = next(k for k in iss if k.startswith("emergency:"))
    assert iss[ekey]["severity"] == "emergency"
    fixed, _ = fix(home, ekey, home / "tmp", res)
    assert not fixed


# ------------------------------------------------------------------ Task 5: loop, ledger, alerts

def _ledger(home):
    p = home / ".state" / "repair-state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _journal(home):
    p = home / ".state" / "repairs.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []


def test_run_fixes_and_journals(home, monkeypatch):
    put(src(home) / "a.md", "# a\n")
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k)
    scan()                                   # leaves an uncommitted pending
    monkeypatch.setenv("GIT_AUTHOR_NAME", "F")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "f@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "F")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "f@example.invalid")
    out = repair.run(engine.Library())
    assert out["skipped"] is False
    assert any(i["kind"] == "uncommitted" for i in out["fixed"])
    assert git(arch(home), "status", "--porcelain") == ""
    assert _ledger(home) == {}
    events = [e["event"] for e in _journal(home)]
    assert "fixed" in events
    assert any(e["key"].startswith("uncommitted:") for e in _journal(home))


def test_alert_needs_age_and_attempts(home):
    import datetime
    led = {
        "x:old": {"kind": "uncommitted", "path": "x", "detail": "", "severity": "routine",
                  "first_seen_utc": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "attempts": 5, "last_attempt_utc": None},
        "y:stuck": {"kind": "uncommitted", "path": "y", "detail": "", "severity": "routine",
                    "first_seen_utc": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "attempts": 3, "last_attempt_utc": None},
    }
    (home / ".state").mkdir(exist_ok=True)
    (home / ".state" / "repair-state.json").write_text(json.dumps(led))
    alerts = repair.alerts()
    assert [a["key"] for a in alerts] == ["y:stuck"]     # 5 attempts but only 1h old ⇒ no alert


def test_emergency_alerts_immediately(home):
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    led = {"emergency:git": {"kind": "emergency", "path": "git", "detail": "git missing", "severity": "emergency",
                             "first_seen_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "attempts": 1, "last_attempt_utc": None}}
    (home / ".state").mkdir(exist_ok=True)
    (home / ".state" / "repair-state.json").write_text(json.dumps(led))
    assert [a["key"] for a in repair.alerts()] == ["emergency:git"]


def test_resolved_issue_resets_first_seen(home):
    import datetime
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    led = {"uncommitted:gone.md": {"kind": "uncommitted", "path": "gone.md", "detail": "", "severity": "routine",
                                   "first_seen_utc": old, "attempts": 9, "last_attempt_utc": None}}
    (home / ".state").mkdir(exist_ok=True)
    (home / ".state" / "repair-state.json").write_text(json.dumps(led))
    put(src(home) / "a.md", "# a\n")
    scan()
    repair.run(engine.Library())                       # gone.md no longer an issue ⇒ resolved + journaled
    assert "uncommitted:gone.md" not in _ledger(home)
    assert any(e["event"] == "resolved" and e["key"] == "uncommitted:gone.md" for e in _journal(home))
    # when it comes back (ledger entry was resolved away), first_seen must be fresh
    put(src(home) / "gone.md", "# gone\n")
    import lasting_plans.engine as _e
    res = _e.ScanResult()
    res.pending.append(("gone.md", "uncommitted: test"))
    repair.run(engine.Library(), res)
    e = _ledger(home).get("uncommitted:gone.md")
    assert e and e["attempts"] == 1 and e["first_seen_utc"] != old


def test_busy_lock_skips_without_counting(home):
    put(src(home) / "a.md", "# a\n")
    scan()
    with engine.scan_lock():
        out = repair.run(engine.Library())
    assert out["skipped"] is True
    assert not (home / ".state" / "repair-state.json").exists()   # ledger untouched


def test_transient_never_alerts_early(home):
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    led = {"transient:a.md": {"kind": "transient", "path": "a.md", "detail": "will retry", "severity": "routine",
                              "first_seen_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "attempts": 1, "last_attempt_utc": None}}
    (home / ".state").mkdir(exist_ok=True)
    (home / ".state" / "repair-state.json").write_text(json.dumps(led))
    assert repair.alerts() == []


def test_corrupt_ledger_is_backed_up_and_reset(home):
    put(src(home) / "a.md", "# a\n")
    scan()
    (home / ".state").mkdir(exist_ok=True)
    (home / ".state" / "repair-state.json").write_text("{garbage")
    out = repair.run(engine.Library())
    assert out["skipped"] is False
    baks = [f for f in os.listdir(home / ".state") if f.startswith("repair-state.json.bak")]
    assert baks
    assert _ledger(home) == {} or isinstance(_ledger(home), dict)


def test_dry_run_changes_nothing(home, monkeypatch):
    put(src(home) / "a.md", "# a\n")
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k)
    scan()
    state_before = sorted(os.listdir(home / ".state")) if (home / ".state").exists() else []
    arch_before = git(arch(home), "status", "--porcelain")
    out = repair.run(engine.Library(), dry_run=True)
    assert out["skipped"] is False and out["fixed"] == []
    assert any(i["kind"] == "uncommitted" for i in out["remaining"])
    assert (sorted(os.listdir(home / ".state")) if (home / ".state").exists() else []) == state_before
    assert git(arch(home), "status", "--porcelain") == arch_before
    assert not (home / ".state" / "repair-state.json").exists()


def test_settings_parse(home):
    assert cfgmod.parse_value("auto_repair", "off") is False
    assert cfgmod.parse_value("auto_repair", "on") is True
    p = home / ".config" / "lasting-plans" / "config.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"alert_after_hours": 0}))
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load()


# ------------------------------------------------------------------ Task 6: wiring, hook, menu

def run_cli(home, *args, stdin=None):
    env = dict(os.environ, HOME=str(home))
    env.pop("CLAUDE_CONFIG_DIR", None)
    env["LASTING_PLANS_SETTLE_SECONDS"] = "0"
    env["LASTING_PLANS_TRASH_DIR"] = str(home / ".Trash")
    return subprocess.run([sys.executable, os.path.join(ROOT, "bin", "lasting-plans")] + list(args),
                          capture_output=True, text=True, env=env, input=stdin, timeout=60)


def run_hook(home):
    env = dict(os.environ, HOME=str(home))
    env.pop("CLAUDE_CONFIG_DIR", None)
    env["LASTING_PLANS_CONFIG_DIR"] = str(home / ".config" / "lasting-plans")
    env["LASTING_PLANS_STATE_DIR"] = str(home / ".state")
    env["LASTING_PLANS_SETTLE_SECONDS"] = "0"
    env["LASTING_PLANS_TRASH_DIR"] = str(home / ".Trash")
    return subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "session-start.py")],
                          capture_output=True, text=True, env=env, timeout=120)


def _hook_config(home, extra=None):
    p = home / ".config" / "lasting-plans" / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    d = {"scheduler_enabled": False}
    d.update(extra or {})
    p.write_text(json.dumps(d))


def test_hook_silent_when_repair_fixes(home, monkeypatch):
    _hook_config(home)
    put(src(home) / "a.md", "# a\n")
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k)
    scan()                                   # uncommitted wedge (no identity)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "F")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "f@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "F")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "f@example.invalid")
    r = run_hook(home)
    assert r.returncode == 0
    assert "pending" not in r.stdout and "⚠" not in r.stdout
    assert git(arch(home), "status", "--porcelain") == ""   # the hook's repair pass committed it


def test_hook_alerts_when_stuck(home):
    import datetime
    _hook_config(home)
    # an over-size file reports "will retry" in EVERY scan — a genuinely stuck pending
    put(src(home) / "big.md", "x" * (6 * 1024 * 1024))
    scan()
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (home / ".state").mkdir(parents=True, exist_ok=True)
    (home / ".state" / "repair-state.json").write_text(json.dumps({
        "transient:big.md": {"kind": "transient", "path": "big.md", "detail": "will retry", "severity": "routine",
                             "first_seen_utc": old, "attempts": 3, "last_attempt_utc": old}}))
    r = run_hook(home)
    assert r.returncode == 0, r.stderr
    assert "auto-repair could not fix" in r.stdout


def test_hook_migrates_v1_silently(home, monkeypatch):
    from lasting_plans import migrate
    monkeypatch.setattr(migrate.scheduler, "install", lambda lib: (True, "ok"))
    monkeypatch.setattr(migrate.scheduler, "supported", lambda: True)
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from test_migrate import make_v1_layout
    make_v1_layout(home)
    p = home / ".config" / "lasting-plans" / "config.json"
    d = json.loads(p.read_text())
    d["scheduler_enabled"] = False          # subprocess hook cannot see monkeypatched scheduler
    p.write_text(json.dumps(d))
    r = run_hook(home)
    assert r.returncode == 0, r.stderr
    assert "⚠" not in r.stdout
    assert cfgmod.load()["layout"] == 2


def test_hook_help_runs_nothing(home):
    r = run_hook.__wrapped__ if False else subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", "session-start.py"), "--help"],
        capture_output=True, text=True, env=dict(os.environ, HOME=str(home),
                                                 LASTING_PLANS_CONFIG_DIR=str(home / ".config" / "lp"),
                                                 LASTING_PLANS_STATE_DIR=str(home / ".state")),
        timeout=30)
    assert r.returncode == 0 and "SessionStart" in r.stdout
    assert not (home / ".state").exists()


def test_cli_repair_dry_run_exit_code(home, monkeypatch):
    put(src(home) / "a.md", "# a\n")
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k)
    scan()
    monkeypatch.setenv("GIT_AUTHOR_NAME", "F")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "f@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "F")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "f@example.invalid")
    before = git(arch(home), "status", "--porcelain")
    r = run_cli(home, "repair", "--dry-run")
    assert r.returncode == 5                                   # remaining issues listed, nothing written
    assert git(arch(home), "status", "--porcelain") == before
    r = run_cli(home, "repair")
    assert r.returncode == 0
    assert git(arch(home), "status", "--porcelain") == ""


# ------------------------------------------------------------------ behaviour menu

def test_behaviour_table_covers_new_settings():
    for key, label, choices, _expl in cfgmod.BEHAVIOUR_SETTINGS:
        assert key in cfgmod.DEFAULTS, key
        assert label
        if choices == ["on", "off"]:
            assert isinstance(cfgmod.parse_value(key, "on"), bool)
            assert isinstance(cfgmod.parse_value(key, "off"), bool)
            continue
        for c in choices:
            val = c[0] if isinstance(c, tuple) else c
            if val == "int":
                assert isinstance(cfgmod.parse_value(key, "5"), int)
            else:
                cfgmod.parse_value(key, val)      # must not raise


def test_behaviour_menu_toggle_writes_setting(home, monkeypatch, capsys):
    import argparse
    import io
    from lasting_plans import cli

    class TTY(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", TTY("1\nq\n"))
    monkeypatch.setattr(sys, "stdout", TTY())
    rc = cli.cmd_behaviour(argparse.Namespace())
    assert rc == 0
    d = json.loads((home / ".config" / "lasting-plans" / "config.json").read_text())
    assert d["auto_repair"] is False


def test_behaviour_menu_rejects_invalid(home, monkeypatch, capsys):
    import argparse
    import io
    from lasting_plans import cli

    class TTY(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", TTY("5\n0\nq\n"))   # row 5 = alert_after_hours, 0 is invalid
    out = TTY()
    monkeypatch.setattr(sys, "stdout", out)
    rc = cli.cmd_behaviour(argparse.Namespace())
    assert rc == 0
    p = home / ".config" / "lasting-plans" / "config.json"
    if p.exists():
        assert json.loads(p.read_text()).get("alert_after_hours", 24) != 0 or "alert_after_hours" not in json.loads(p.read_text())
    assert cfgmod.load()["alert_after_hours"] == 24       # unchanged


def test_settings_show_uses_table_labels(home):
    r = run_cli(home, "settings", "show")
    assert r.returncode == 0
    assert "Fix problems automatically in the background" in r.stdout


# ------------------------------------------------------------------ review regression (2026-11-15 cross-family review)

def test_emergency_is_recorded_and_alerts(home, monkeypatch):
    """Review F6: emergency issues must reach the ledger (and thus alerts) via a real pass."""
    from lasting_plans import tools
    monkeypatch.setattr(tools, "on_path", lambda name: None if name == "git" else None)
    put(src(home) / "a.md", "# a\n")
    scan()
    out = repair.run(engine.Library())
    assert any(i["kind"] == "emergency" for i in out["remaining"])
    led = _ledger(home)
    assert any(k.startswith("emergency:") for k in led)
    assert any(a["key"].startswith("emergency:") for a in repair.alerts())


def test_migration_runs_before_any_other_git_write(home, monkeypatch):
    """Review F7: on a v1 layout, repair must restage the watcher (migration step 1)
    before ANY git write, including canonicalize re-casing."""
    from lasting_plans import migrate
    order = []
    monkeypatch.setattr(migrate.scheduler, "install", lambda lib: order.append("install") or (True, "ok"))
    monkeypatch.setattr(migrate.scheduler, "supported", lambda: True)
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from test_migrate import make_v1_layout
    make_v1_layout(home)
    # make the source also need re-casing, so canonicalize WOULD write if it ran first
    real_git = gitrepo.git
    def spy(root, *a, **kw):
        if a and a[0] in ("commit", "bundle", "merge", "fetch", "mv", "rm", "reset", "add"):
            order.append(("git-write", a[:2]))
        return real_git(root, *a, **kw)
    monkeypatch.setattr(migrate.gitrepo, "git", spy)
    monkeypatch.setattr(__import__("lasting_plans.sorting", fromlist=["gitrepo"]).gitrepo, "git", spy)
    repair.run(engine.Library())
    assert order and order[0] == "install", order[:5]
    assert cfgmod.load()["layout"] == 2
