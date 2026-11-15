"""Task 5b: completion signals + sorting (moves only, never deletes)."""
import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from lasting_plans import engine, sorting  # noqa: E402

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


# ------------------------------------------------------------------ status parsing

def test_status_of_parses_canonical_line():
    assert sorting.status_of("# Plan\n\n**Status:** approved\n") == "approved"
    assert sorting.status_of("# Plan\n\n**Status:** Completed\n") == "completed"
    assert sorting.status_of("# Plan\nno status here\n") is None
    # only the first 40 lines count
    far = "# P\n" + "\n".join("line %d" % i for i in range(50)) + "\n**Status:** completed\n"
    assert sorting.status_of(far) is None


# ------------------------------------------------------------------ completion

def test_explicit_complete_moves_now_and_sets_status(home):
    p = put(src(home) / "Plan A.md", "# Plan A\n\n**Status:** in-progress\n\nbody\n")
    scan()
    lib = engine.Library()
    new_rel = sorting.complete(lib, "Plan A.md")
    assert new_rel == "_ARCHIVED/Plan A.md"
    assert (src(home) / "_ARCHIVED" / "Plan A.md").exists()
    assert not (src(home) / "Plan A.md").exists()
    text = (src(home) / "_ARCHIVED" / "Plan A.md").read_text(encoding="utf-8")
    assert "**Status:** completed" in text
    # source repo (if any) committed the move as a rename
    # and the backup follows on the next scan
    scan()
    assert (arch(home) / "_ARCHIVED" / "Plan A.md").exists()


def test_all_ticked_waits_quiet_days(home):
    body = "# Plan\n\n- [x] step one\n- [x] step two\n"
    put(src(home) / "done.md", body, mtime=time.time() - 2 * 86400)
    scan()
    assert sorting.sort_pass(engine.Library(), time.time()) == []          # 2 days < 3 quiet
    assert (src(home) / "done.md").exists()
    os.utime(src(home) / "done.md", (time.time() - 4 * 86400, time.time() - 4 * 86400))
    ev = sorting.sort_pass(engine.Library(), time.time())
    assert ev and (src(home) / "_ARCHIVED" / "done.md").exists()


def test_open_checkbox_never_moves(home):
    put(src(home) / "wip.md", "# Plan\n\n- [x] done\n- [ ] todo\n", mtime=time.time() - 10 * 86400)
    scan()
    assert sorting.sort_pass(engine.Library(), time.time()) == []
    assert (src(home) / "wip.md").exists()


def test_status_approved_never_moves(home):
    put(src(home) / "a.md", "# Plan\n\n**Status:** approved\n", mtime=time.time() - 10 * 86400)
    scan()
    assert sorting.sort_pass(engine.Library(), time.time()) == []


# ------------------------------------------------------------------ sorting

def test_historical_playbook_archived(home):
    put(src(home) / "_PLAYBOOKS" / "old.md", "# HISTORICAL — old runbook\n\nbody\n",
        mtime=time.time() - 10 * 86400)
    scan()
    ev = sorting.sort_pass(engine.Library(), time.time())
    assert (src(home) / "_ARCHIVED" / "old.md").exists()
    assert not (src(home) / "_PLAYBOOKS" / "old.md").exists()


def test_top_level_playbook_sorted_into_PLAYBOOKS_subdir(home):
    put(src(home) / "Release Playbook.md", "# Release Playbook\n\nbody\n")
    scan()
    ev = sorting.sort_pass(engine.Library(), time.time())
    assert ev
    assert (src(home) / "_PLAYBOOKS" / "Release Playbook.md").exists()
    assert not (src(home) / "Release Playbook.md").exists()


def test_recent_file_never_moved(home):
    put(src(home) / "hot.md", "# Plan\n\n- [x] all done\n", mtime=time.time() - 300)
    scan()
    assert sorting.sort_pass(engine.Library(), time.time()) == []
    assert (src(home) / "hot.md").exists()


def test_user_move_back_is_sticky(home):
    put(src(home) / "Guide.md", "# Guide\n\nbody\n")   # H1 "Guide"? classify via filename... use playbook name
    # use a playbook-classified name so sorting moves it
    os.rename(src(home) / "Guide.md", src(home) / "Handbook-x.md")
    put(src(home) / "Handbook-x.md", "# Handbook\n\nbody\n")
    scan()
    ev = sorting.sort_pass(engine.Library(), time.time())
    assert ev
    assert (src(home) / "_PLAYBOOKS" / "Handbook-x.md").exists()
    # the user moves it back out
    (src(home) / "_PLAYBOOKS").mkdir(exist_ok=True)
    os.rename(src(home) / "_PLAYBOOKS" / "Handbook-x.md", src(home) / "Handbook-x.md")
    scan()
    ev2 = sorting.sort_pass(engine.Library(), time.time())
    assert ev2 == []                                   # sticky override: never re-moved
    assert (src(home) / "Handbook-x.md").exists()
    lib = engine.Library()
    d = next(d for d in lib.docs if d.sc.get("source_relpath") == "Handbook-x.md")
    assert d.sc.get("sort_override") is True


def test_backup_mirrors_sort_move(home):
    put(src(home) / "Plan B.md", "# Plan B\n\n- [x] only step\n", mtime=time.time() - 5 * 86400)
    scan()
    before = git(arch(home), "log", "--format=%H", "--follow", "--", "Plan B.md").split()
    sorting.sort_pass(engine.Library(), time.time())
    scan()
    assert (arch(home) / "_ARCHIVED" / "Plan B.md").exists()
    after = git(arch(home), "log", "--format=%H", "--follow", "--", "_ARCHIVED/Plan B.md").split()
    assert set(before) <= set(after)                   # history follows the move


def test_source_git_repo_never_staged(home):
    put(src(home) / "Plan C.md", "# Plan C\n\n- [x] step\n", mtime=time.time() - 5 * 86400)
    git(src(home), "init", "-q")
    git(src(home), "add", "-A", "--", ".")
    git(src(home), "commit", "-q", "-m", "src initial")
    # plant an unrelated staged change in the source repo
    put(src(home) / "unrelated.md", "# unrelated\n")
    git(src(home), "add", "--", "unrelated.md")
    scan()
    sorting.sort_pass(engine.Library(), time.time())
    assert (src(home) / "_ARCHIVED" / "Plan C.md").exists()
    # the sort move was committed as a rename and nothing else was swept in
    last = git(src(home), "log", "-1", "--name-status", "--format=")
    assert "R" in last and "Plan C.md" in last and "_ARCHIVED/Plan C.md" in last
    assert "unrelated.md" not in last
    assert "unrelated.md" in git(src(home), "diff", "--cached", "--name-only")   # still staged, untouched


def test_name_collision_in_archived(home):
    put(src(home) / "_ARCHIVED" / "Plan D.md", "# old archived\n")
    put(src(home) / "Plan D.md", "# Plan D\n\n- [x] step\n", mtime=time.time() - 5 * 86400)
    scan()
    new_rel = sorting.complete(engine.Library(), "Plan D.md")
    assert new_rel == "_ARCHIVED/Plan D (2).md"
    assert (src(home) / "_ARCHIVED" / "Plan D (2).md").exists()
    assert (src(home) / "_ARCHIVED" / "Plan D.md").exists()


# ------------------------------------------------------------------ canonicalize

def test_canonicalize_recases_folder_and_git_entries(home):
    put(src(home) / "_playbooks" / "A.md", "# A\n")
    put(src(home) / "_playbooks" / "B.md", "# B\n")
    git(src(home), "init", "-q")
    git(src(home), "add", "-A", "--", ".")
    git(src(home), "commit", "-q", "-m", "src initial")
    put(src(home) / "unrelated.md", "# u\n")
    git(src(home), "add", "--", "unrelated.md")        # planted unrelated staged change
    ev = sorting.canonicalize_folders(engine.Library())
    assert ev
    assert "_PLAYBOOKS" in os.listdir(src(home)) and "_playbooks" not in os.listdir(src(home))
    tracked = git(src(home), "ls-files").splitlines()
    assert "_PLAYBOOKS/A.md" in tracked and "_PLAYBOOKS/B.md" in tracked
    assert not [t for t in tracked if t.startswith("_playbooks/")]
    last = git(src(home), "log", "-1", "--name-status", "--format=%s").splitlines()
    assert all(line.startswith("R") for line in last[1:] if line)   # one commit, renames only
    assert "unrelated.md" in git(src(home), "diff", "--cached", "--name-only")  # still staged


def test_canonicalize_noop_when_spelled_right(home):
    put(src(home) / "_PLAYBOOKS" / "A.md", "# A\n")
    git(src(home), "init", "-q")
    git(src(home), "add", "-A", "--", ".")
    git(src(home), "commit", "-q", "-m", "init")
    before = git(src(home), "rev-parse", "HEAD")
    assert sorting.canonicalize_folders(engine.Library()) == []
    assert git(src(home), "rev-parse", "HEAD") == before


def test_sort_move_is_committed_as_rename(home):
    put(src(home) / "PLAYBOOK-y.md", "# Playbook\n\nbody\n")
    git(src(home), "init", "-q")
    git(src(home), "add", "-A", "--", ".")
    git(src(home), "commit", "-q", "-m", "init")
    scan()
    sorting.sort_pass(engine.Library(), time.time())
    assert (src(home) / "_PLAYBOOKS" / "PLAYBOOK-y.md").exists()
    last = git(src(home), "log", "-1", "--name-status", "--format=")
    assert "R" in last and "_PLAYBOOKS/PLAYBOOK-y.md" in last
