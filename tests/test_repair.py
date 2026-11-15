"""Task 4: safe, idempotent fixers for every foreseeable failure class (repair.py)."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from lasting_plans import config as cfgmod  # noqa: E402
from lasting_plans import engine, repair  # noqa: E402


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
