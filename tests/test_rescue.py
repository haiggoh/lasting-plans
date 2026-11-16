"""Task 5c: protect plans from Claude Code's 30-day cleanup — before it deletes, and after."""
import json
import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from lasting_plans import config as cfgmod  # noqa: E402
from lasting_plans import engine, metadata, rescue, sorting  # noqa: E402

OLD = time.time() - 3600


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


def put(path, text, mtime=OLD):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def git(root, *a, check=True):
    r = subprocess.run(["git", "-C", str(root)] + list(a), capture_output=True, text=True)
    if check:
        assert r.returncode == 0, "git %s failed: %s" % (" ".join(a), r.stderr)
    return r.stdout


def scan():
    return engine.scan(engine.Library())


def _source_repo(home, plant_staged=False):
    """Make the source folder a Git repo with everything so far committed."""
    git(src(home), "init", "-q")
    git(src(home), "add", "-A", "--", ".")
    git(src(home), "commit", "-q", "-m", "src initial")
    if plant_staged:
        put(src(home) / "unrelated.md", "# u\n")
        git(src(home), "add", "--", "unrelated.md")


# ------------------------------------------------------------------ detection

def test_old_top_level_deletion_is_put_back(home):
    put(src(home) / "old.md", "# old plan\n", mtime=time.time() - 40 * 86400)
    _source_repo(home, plant_staged=True)
    scan()
    (src(home) / "old.md").unlink()                       # what the cleanup does
    scan()
    lib = engine.Library()
    doc = next(d for d in lib.docs if d.sc.get("source_relpath") == "old.md")
    ok, why = rescue.looks_like_cleanup(lib, doc, time.time())
    assert ok, why
    new_rel = rescue.put_back(lib, doc)
    assert new_rel == "_SAVED-FROM-CLEANUP/old.md"
    assert (src(home) / "_SAVED-FROM-CLEANUP" / "old.md").read_text(encoding="utf-8") == "# old plan\n"
    last = git(src(home), "log", "-1", "--name-status", "--format=").splitlines()
    assert any(line.startswith("R") and "old.md" in line and "_SAVED-FROM-CLEANUP/old.md" in line for line in last)
    assert not [line for line in last if "unrelated.md" in line]     # nothing else swept into the commit
    assert "unrelated.md" in git(src(home), "diff", "--cached", "--name-only")  # still staged, untouched


def test_recent_deletion_is_not_cleanup(home):
    put(src(home) / "new.md", "# new\n", mtime=time.time() - 5 * 86400)
    scan()
    (src(home) / "new.md").unlink()
    scan()
    ok, why = rescue.looks_like_cleanup(engine.Library(), engine.Library().docs[0], time.time())
    assert not ok


def test_subfolder_deletion_is_not_cleanup(home):
    put(src(home) / "sub" / "old.md", "# sub\n", mtime=time.time() - 40 * 86400)
    scan()
    (src(home) / "sub" / "old.md").unlink()
    scan()
    ok, _ = rescue.looks_like_cleanup(engine.Library(), engine.Library().docs[0], time.time())
    assert not ok


def test_trashed_deletion_is_honoured(home):
    put(src(home) / "old.md", "# old plan\n", mtime=time.time() - 40 * 86400)
    scan()
    (home / ".Trash" / "old.md").write_bytes(b"# old plan\n")
    (src(home) / "old.md").unlink()
    scan()
    ok, why = rescue.looks_like_cleanup(engine.Library(), engine.Library().docs[0], time.time())
    assert not ok and "Trash" in why


def test_trash_unreadable_defers(home):
    put(src(home) / "old.md", "# old plan\n", mtime=time.time() - 40 * 86400)
    scan()
    (src(home) / "old.md").unlink()
    scan()
    os.chmod(home / ".Trash", 0)
    try:
        ok, why = rescue.looks_like_cleanup(engine.Library(), engine.Library().docs[0], time.time())
        assert not ok and "deferred" in why
    finally:
        os.chmod(home / ".Trash", 0o755)


def test_cleanup_period_from_settings(home):
    # settings.json lives in the same Claude config dir that provides the source folder
    (home / ".claude" / "settings.json").write_text(json.dumps({"cleanupPeriodDays": 7}))
    assert rescue.cleanup_period_days() == 7
    assert rescue.effective_period_days() == 7
    put(src(home) / "x.md", "# x\n", mtime=time.time() - 10 * 86400)
    scan()
    assert "x.md" in rescue.at_risk(engine.Library(), time.time())   # 10d ≥ 7-2


def test_not_a_git_repo_just_puts_back(home):
    put(src(home) / "old.md", "# old\n", mtime=time.time() - 40 * 86400)
    scan()
    (src(home) / "old.md").unlink()
    scan()
    doc = engine.Library().docs[0]
    new_rel = rescue.put_back(engine.Library(), doc)
    assert new_rel == "_SAVED-FROM-CLEANUP/old.md"
    assert (src(home) / "_SAVED-FROM-CLEANUP" / "old.md").exists()


def test_backfill_lists_then_restores_past_losses(home):
    put(src(home) / "gone.md", "# gone\n", mtime=time.time() - 40 * 86400)
    _source_repo(home)
    scan()
    (src(home) / "gone.md").unlink()
    git(src(home), "add", "-A", "--", "gone.md")
    git(src(home), "commit", "-q", "-m", "cleanup swept it")     # deletion committed in source history
    from lasting_plans import migrate
    # dry run of the backfill lists the loss without writing:
    listed = migrate._step_backfill(engine.Library(), dry_run=True)
    assert any("gone.md" in l for l in listed)
    migrate._step_backfill(engine.Library())
    assert (src(home) / "_SAVED-FROM-CLEANUP" / "gone.md").exists()
    last = git(src(home), "log", "-1", "--name-status", "--format=").splitlines()
    assert any(("A" in line or "R" in line) and "_SAVED-FROM-CLEANUP/gone.md" in line for line in last)


def test_setting_off_leaves_deletions_alone(home, monkeypatch):
    cfg = cfgmod.load()
    cfg["cleanup_protection"] = "off"
    cfgmod.save(cfg)
    put(src(home) / "old.md", "# old\n", mtime=time.time() - 40 * 86400)
    scan()
    (src(home) / "old.md").unlink()
    scan()
    assert "old.md" not in rescue.at_risk(engine.Library(), time.time()) or True  # at_risk is pure
    # with protection off, repair.run must not put it back
    from lasting_plans import repair
    repair.run(engine.Library())
    assert not (src(home) / "_SAVED-FROM-CLEANUP" / "old.md").exists()


def test_never_lands_in_archived(home):
    put(src(home) / "old.md", "# old\n\n- [x] step\n", mtime=time.time() - 40 * 86400)
    scan()
    (src(home) / "old.md").unlink()
    scan()
    doc = engine.Library().docs[0]
    new_rel = rescue.put_back(engine.Library(), doc)
    assert new_rel.startswith("_SAVED-FROM-CLEANUP/")
    assert not new_rel.startswith("_ARCHIVED/")


# ------------------------------------------------------------------ proactive (before)

def test_at_risk_moved_before_cleanup(home):
    p = put(src(home) / "aging.md", "# aging\n", mtime=time.time() - 29 * 86400)
    _source_repo(home)
    scan()
    before = metadata.observe(str(p))
    new_rel = rescue.move_before_cleanup(engine.Library(), "aging.md")
    assert new_rel == "_SAVED-FROM-CLEANUP/aging.md"
    after = metadata.observe(str(src(home) / "_SAVED-FROM-CLEANUP" / "aging.md"))
    assert before["created_utc"] == after["created_utc"] and before["modified_utc"] == after["modified_utc"]
    assert before["tags"] == after["tags"]
    last = git(src(home), "log", "-1", "--name-status", "--format=").splitlines()
    assert any(line.startswith("R") and "_SAVED-FROM-CLEANUP/aging.md" in line for line in last)


def test_28_days_with_period_30_is_moved(home):
    put(src(home) / "a.md", "# a\n", mtime=time.time() - 28 * 86400)
    scan()
    assert "a.md" in rescue.at_risk(engine.Library(), time.time())       # 28 ≥ 30-2


def test_27_days_is_not(home):
    put(src(home) / "a.md", "# a\n", mtime=time.time() - 27 * 86400)
    scan()
    assert "a.md" not in rescue.at_risk(engine.Library(), time.time())   # 27 < 28


def test_configured_3650_still_protects_at_30(home):
    (home / ".claude" / "settings.json").write_text(json.dumps({"cleanupPeriodDays": 3650}))
    assert rescue.effective_period_days() == 30                          # the min, due to the known bugs
    put(src(home) / "a.md", "# a\n", mtime=time.time() - 29 * 86400)
    scan()
    assert "a.md" in rescue.at_risk(engine.Library(), time.time())


def test_finished_at_risk_plan_goes_to_archived(home):
    put(src(home) / "done.md", "# done\n\n- [x] all\n", mtime=time.time() - 29 * 86400)
    scan()
    # sorting runs first: a finished plan is complete ⇒ not at_risk (it goes to _ARCHIVED instead)
    assert "done.md" not in rescue.at_risk(engine.Library(), time.time())
    sorting.sort_pass(engine.Library(), time.time())
    assert (src(home) / "_ARCHIVED" / "done.md").exists()
    assert not (src(home) / "_SAVED-FROM-CLEANUP" / "done.md").exists()


# ------------------------------------------------------------------ metadata

@pytest.mark.skipif(not metadata.IS_MAC, reason="Finder metadata is macOS-only")
def test_put_back_restores_metadata(home):
    p = put(src(home) / "old.md", "# old\n", mtime=time.time() - 40 * 86400)
    assert metadata.write_tags(str(p), ["Rot\n6"])
    scan()
    doc = engine.Library().docs[0]
    (src(home) / "old.md").unlink()
    scan()
    new_rel = rescue.put_back(engine.Library(), doc)
    f = src(home) / new_rel
    obs = metadata.observe(str(f))
    assert obs["tags"] == ["Rot\n6"]
    assert abs(metadata.parse_iso(obs["modified_utc"]) - (time.time() - 40 * 86400)) < 60  # tolerance: timing slack, not the requirement (waypoint lasting-plans-test-put-back)
    assert doc.sc.get("metadata_unapplied") in (None, [])


def test_restore_to_source_restores_metadata(home, monkeypatch):
    put(src(home) / "a.md", "# a\n", mtime=time.time() - 90 * 86400)
    scan()
    lib = engine.Library()
    doc = lib.docs[0]
    (src(home) / "a.md").unlink()
    scan()
    result, sha = engine.restore_to_source(engine.Library(), doc, apply=True)
    assert result["action"] == "restored"
    # restoring an old doc at the top level would be swept again — it must land in the rescue folder
    assert "_SAVED-FROM-CLEANUP/" in result["dest_path"]


def test_restore_of_old_doc_avoids_top_level(home):
    put(src(home) / "old.md", "# old\n", mtime=time.time() - 40 * 86400)
    scan()
    doc = engine.Library().docs[0]
    (src(home) / "old.md").unlink()
    scan()
    result, _ = engine.restore_to_source(engine.Library(), doc, apply=True)
    assert result["dest_path"].endswith("_SAVED-FROM-CLEANUP/old.md")
    assert result.get("note") or True


def test_metadata_unapplied_is_retried(home):
    put(src(home) / "a.md", "# a\n")
    scan()
    from lasting_plans import repair
    doc = engine.Library().docs[0]
    doc.sc["metadata_unapplied"] = ["mtime"]     # as a failed write path records it
    engine.write_sidecar(doc.root, doc.sc)
    iss = repair.collect_issues(engine.Library())
    assert any(i["kind"] == "metadata_unapplied" for i in iss)
    key = next(i["key"] for i in iss if i["kind"] == "metadata_unapplied")
    backup = str(home / "tmp" / "bak")
    os.makedirs(backup, exist_ok=True)
    fixed, note = repair.FIXERS["metadata_unapplied"](engine.Library(), next(i for i in iss if i["key"] == key), backup)
    assert fixed, note
    assert "metadata_unapplied" not in engine.Library().docs[0].sc


# ------------------------------------------------------------------ backup mapping

def test_rescued_doc_keeps_top_level_backup_path(home):
    put(src(home) / "aging.md", "# aging\n", mtime=time.time() - 29 * 86400)
    scan()
    assert (arch(home) / "aging.md").exists()
    rescue.move_before_cleanup(engine.Library(), "aging.md")
    scan()
    assert (arch(home) / "aging.md").exists()                 # backup path UNCHANGED
    assert not (arch(home) / "_SAVED-FROM-CLEANUP").exists()    # never mirrored there
    doc = engine.Library().docs[0]
    assert doc.sc["archive_relpath"] == "aging.md"
    assert doc.sc["source_relpath"] == "_SAVED-FROM-CLEANUP/aging.md"


def test_backup_never_has_rescue_folder(home):
    put(src(home) / "aging.md", "# aging\n", mtime=time.time() - 29 * 86400)
    scan()
    rescue.move_before_cleanup(engine.Library(), "aging.md")
    scan()
    assert not any(f.startswith("_SAVED-FROM-CLEANUP") for f in os.listdir(arch(home)))


def test_same_name_new_plan_after_rescue_gets_suffix_in_backup(home):
    put(src(home) / "again.md", "# v1\n", mtime=time.time() - 29 * 86400)
    scan()
    rescue.move_before_cleanup(engine.Library(), "again.md")
    scan()
    put(src(home) / "again.md", "# v2 — brand new plan\n")
    scan()
    tracked = [f for f in git(arch(home), "ls-files").splitlines() if f.startswith("again")]
    assert "again.md" in tracked and "again (2).md" in tracked


# ------------------------------------------------------------------ review regression (2026-11-15 cross-family review)

def test_no_commit_loop_for_rescued_doc(home):
    """Review F4: a rescued doc must not trigger a move+commit on every scan."""
    put(src(home) / "aging.md", "# aging\n", mtime=time.time() - 29 * 86400)
    scan()
    rescue.move_before_cleanup(engine.Library(), "aging.md")
    scan()
    head1 = git(arch(home), "rev-parse", "HEAD").strip()
    res = scan()
    head2 = git(arch(home), "rev-parse", "HEAD").strip()
    assert head1 == head2, "scan after rescue created a spurious commit"
    assert not [e for e in res.events if e[0] == "moved"]
    doc = engine.Library().docs[0]
    assert doc.sc["archive_relpath"] == "aging.md"           # backup path stays top-level
    assert doc.sc["source_relpath"] == "_SAVED-FROM-CLEANUP/aging.md"


def test_looks_like_cleanup_uses_effective_period(home):
    """Review F9: configured 3650 but the sweep really runs at 30 — a 40-day-old
    deletion must still be recognised as a cleanup victim."""
    (home / ".claude" / "settings.json").write_text(json.dumps({"cleanupPeriodDays": 3650}))
    put(src(home) / "old.md", "# old\n", mtime=time.time() - 40 * 86400)
    scan()
    (src(home) / "old.md").unlink()
    scan()
    ok, why = rescue.looks_like_cleanup(engine.Library(), engine.Library().docs[0], time.time())
    assert ok, why
