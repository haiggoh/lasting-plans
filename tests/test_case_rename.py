"""Case-safe Git commits and moves (2.0.0 Task 1).

The live bug this file pins: a folder renamed case-only (`_PLAYBOOKS` <-> `_playbooks`)
left Git commits failing with "pathspec … did not match" and the engine writing
`X (2).md` copies instead of clean renames.
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from lasting_plans import gitrepo  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("LASTING_PLANS_CONFIG_DIR", str(h / ".config" / "lasting-plans"))
    monkeypatch.setenv("LASTING_PLANS_STATE_DIR", str(h / ".state"))
    for k, v in {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "f@example.invalid",
                 "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "f@example.invalid",
                 "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(k, v)
    return h


def fs_is_case_sensitive(root):
    probe = os.path.join(root, "lp-case-probe")
    with open(probe, "w") as f:
        f.write("x")
    insensitive = os.path.exists(os.path.join(root, "LP-CASE-PROBE"))
    os.remove(probe)
    return not insensitive


def _git(root, *a):
    r = subprocess.run(["git", "-C", str(root)] + list(a), capture_output=True, text=True)
    assert r.returncode == 0, "git %s failed: %s" % (" ".join(a), r.stderr)
    return r.stdout


@pytest.fixture
def repo(tmp_path, home):
    root = tmp_path / "repo"
    root.mkdir()
    if fs_is_case_sensitive(str(root)):
        pytest.skip("tmp filesystem is case-sensitive; the case-rename behaviour targets case-insensitive volumes")
    _git(root, "init", "-q")
    return root


def test_commit_paths_accepts_wrong_case(repo):
    """A wrong-case path (as the scan produced on the live volume) still commits."""
    d = repo / "_PLAYBOOKS"
    d.mkdir()
    (d / "A.md").write_text("one\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")

    (d / "A.md").write_text("two\n", encoding="utf-8")
    sha = gitrepo.commit_paths(str(repo), ["_playbooks/A.md"], "edit given in wrong case")
    assert sha
    assert _git(repo, "ls-files").splitlines() == ["_PLAYBOOKS/A.md"]
    assert _git(repo, "status", "--porcelain").strip() == ""


def test_move_path_case_only(repo):
    """A case-only move is one clean rename in index and on disk — never a copy."""
    d = repo / "_playbooks"
    d.mkdir()
    (d / "A.md").write_text("content\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")

    gitrepo.move_path(str(repo), "_playbooks/A.md", "_PLAYBOOKS/A.md")

    assert _git(repo, "ls-files").splitlines() == ["_PLAYBOOKS/A.md"]
    entries = os.listdir(repo)
    assert "_PLAYBOOKS" in entries and "_playbooks" not in entries
    assert (repo / "_PLAYBOOKS" / "A.md").read_text(encoding="utf-8") == "content\n"
    # git mv stages the rename pair; committing it is the caller's step
    # (the engine commits with `commit --only -- <old> <new>`, Task 2)
    assert _git(repo, "status", "--porcelain").strip() == "R  _playbooks/A.md -> _PLAYBOOKS/A.md"
