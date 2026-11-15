"""Case-safe Git commits and moves (2.0.0 Task 1).

The live bug this file pins: a folder renamed case-only (`_PLAYBOOKS` <-> `_playbooks`)
left Git commits failing with "pathspec … did not match" and the engine writing
`X (2).md` copies instead of clean renames.
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from lasting_plans import engine, gitrepo, metadata  # noqa: E402
from lasting_plans import config as cfgmod  # noqa: E402


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


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def scan():
    return engine.scan(engine.Library())


def kinds(res):
    return sorted(e[0] for e in res.events)


def git(root, *a):
    r = subprocess.run(["git", "-C", str(root)] + list(a), capture_output=True, text=True)
    assert r.returncode == 0, "git %s failed: %s" % (" ".join(a), r.stderr)
    return r.stdout


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


# ------------------------------------------------------------------ 2.0.0 Task 2: one archive

def test_playbook_archived_at_source_path(home):
    """A playbook mirrors to its source path in the ONE archive; type is a label."""
    put(src(home) / "_PLAYBOOKS" / "P.md", "# Team Handbook\n")
    res = scan()
    assert kinds(res) == ["imported"]
    assert (home / "Claude-plans" / "_PLAYBOOKS" / "P.md").read_text(encoding="utf-8") == "# Team Handbook\n"
    doc = engine.Library().docs[0]
    assert doc.type == "playbook"
    assert doc.sc["archive_relpath"] == "_PLAYBOOKS/P.md"
    assert doc.sc["source_relpath"] == "_PLAYBOOKS/P.md"
    assert doc.root == engine.Library().root


def test_case_only_folder_rename_is_a_clean_move(home):
    """Renaming the source folder case-only is one clean rename in the archive — never a copy."""
    put(src(home) / "_playbooks" / "P.md", "# Handbook\n")
    scan()
    os.rename(src(home) / "_playbooks", src(home) / "_PLAYBOOKS")
    res = scan()
    assert res.pending == [] and res.errors == []
    assert kinds(res) == ["moved"]
    arch = home / "Claude-plans"
    tracked = [f for f in git(arch, "ls-files").splitlines() if not f.startswith(".lasting-plans")]
    assert tracked == ["_PLAYBOOKS/P.md"]
    assert git(arch, "status", "--porcelain") == ""
    assert not [f for f in os.listdir(arch / "_PLAYBOOKS") if "(2)" in f]
    entries = os.listdir(arch)
    assert "_PLAYBOOKS" in entries and "_playbooks" not in entries  # stored case, not just existence


def test_case_rename_with_content_change(home):
    """A case-only rename that also changes content: move + update, no '(2)' copy."""
    put(src(home) / "_playbooks" / "P.md", "# Handbook\nv1\n")
    scan()
    os.rename(src(home) / "_playbooks", src(home) / "_PLAYBOOKS")
    put(src(home) / "_PLAYBOOKS" / "P.md", "# Handbook\nv2\n")
    res = scan()
    assert res.pending == [] and res.errors == []
    assert kinds(res) == ["moved", "updated"]
    arch = home / "Claude-plans"
    assert (arch / "_PLAYBOOKS" / "P.md").read_text(encoding="utf-8").endswith("v2\n")
    assert not [f for f in os.listdir(arch / "_PLAYBOOKS") if "(2)" in f]
    assert git(arch, "status", "--porcelain") == ""


def test_move_prunes_empty_folder(home):
    """A source move prunes the emptied archive folder."""
    p = put(src(home) / "old" / "a.md", "# a\n")
    scan()
    assert (home / "Claude-plans" / "old" / "a.md").exists()
    (src(home) / "new").mkdir()
    os.rename(p, src(home) / "new" / "a.md")
    os.rmdir(src(home) / "old")
    res = scan()
    assert kinds(res) == ["moved"]
    arch = home / "Claude-plans"
    assert (arch / "new" / "a.md").exists()
    assert not (arch / "old").exists()
    assert git(arch, "status", "--porcelain") == ""


def test_reclassify_is_label_only(home):
    """reclassify changes the sidecar label only — the file never moves, one commit."""
    put(src(home) / "x.md", "# Plan and playbook preservation\n")
    scan()
    lib = engine.Library()
    d = lib.resolve("x.md")[0]
    assert d.type == "plan"
    sha = engine.reclassify(lib, d, "playbook")
    assert sha
    arch = home / "Claude-plans"
    assert (arch / "x.md").exists()
    lib = engine.Library()
    d = lib.docs[0]
    assert d.type == "playbook" and d.sc["archive_relpath"] == "x.md"
    assert d.sc["type_reason"] == "reclassified by user"
    subjects = [s for s in git(arch, "log", "--format=%s").splitlines() if s.startswith("reclassify")]
    assert len(subjects) == 1
    assert git(arch, "status", "--porcelain") == ""
    assert scan().events == []
    assert engine.type_mismatches(engine.Library()) == []  # a user reclassification is final


@pytest.mark.skipif(not metadata.IS_MAC, reason="Finder tags are macOS only")
def test_folder_tags_never_create_folders(home):
    """A tag on a source folder with no archived documents never creates an archive folder."""
    put(src(home) / "drafts" / "keep.md", "# a\n")
    (src(home) / "empty-tagged").mkdir()
    assert metadata.write_tags(str(src(home) / "drafts"), ["Rot\n6"])
    assert metadata.write_tags(str(src(home) / "empty-tagged"), ["Blau\n4"])
    scan()
    arch = home / "Claude-plans"
    assert not (arch / "empty-tagged").exists()
    assert "empty-tagged" not in engine.load_folder_tags(str(arch))
    assert "Rot\n6" in metadata.read_tags(str(arch / "drafts"))


def test_legacy_config_keys_resolve(home):
    """v1 config keys resolve to the 2.0.0 names at load time (read-compatible)."""
    p = home / ".config" / "lasting-plans" / "config.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "plans_root": "~/Custom-plans",
        "playbooks_root": "~/Custom-playbooks",
        "remotes": {"plan": "https://github.com/x/y.git"},
    }), encoding="utf-8")
    cfg = cfgmod.load()
    assert cfg["archive_root"] == "~/Custom-plans"
    assert cfg["retired_archives"] == ["~/Custom-playbooks"]
    assert cfg["remote"] == "https://github.com/x/y.git"
    assert cfg["layout"] == 1
    assert cfgmod.archive_root(cfg).endswith("Custom-plans")


def test_commit_paths_skips_add_for_staged_deleted_paths(repo):
    """2.0.1 hotfix (live wedge): a path that is staged-deleted and gone from disk must
    not fatal the `git add -A` — it is skipped for adding but still committed (the
    deletion) via the --only pathspec."""
    d = repo / "_PLAYBOOKS"
    d.mkdir()
    (d / "A.md").write_text("one\n", encoding="utf-8")
    (d / "B.md").write_text("two\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    (d / "A.md").unlink()
    _git(repo, "add", "-A", "--", "_PLAYBOOKS/A.md")          # staged deletion (out of index now)
    (d / "B.md").write_text("two changed\n", encoding="utf-8")
    sha = gitrepo.commit_paths(str(repo), ["_PLAYBOOKS/A.md", "_PLAYBOOKS/B.md"], "wedge commit")
    assert sha
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert _git(repo, "ls-files").splitlines() == ["_PLAYBOOKS/B.md"]
    assert "wedge commit" in _git(repo, "log", "-1", "--format=%s")


def test_move_path_staged_but_never_committed(repo):
    """2.0.2: a staged-added file (in index, not in HEAD) must move via os.rename+add,
    not `git mv` (which refuses 'not under version control')."""
    d = repo / "old"
    d.mkdir()
    (d / "A.md").write_text("one\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    (d / "B.md").write_text("untracked wedge copy\n", encoding="utf-8")   # untracked: the live case
    gitrepo.move_path(str(repo), "old/B.md", "OLD/B.md")   # case-only: the live failure
    assert (repo / "OLD" / "B.md").read_text(encoding="utf-8") == "untracked wedge copy\n"
    assert "OLD" in os.listdir(repo) and "old" not in os.listdir(repo)


def test_move_path_untracked_plain_rename(repo):
    """2.0.3: untracked old path on a NON-case-only move must also avoid git mv."""
    d = repo / "old"
    d.mkdir()
    (d / "A.md").write_text("one\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    (d / "B.md").write_text("untracked\n", encoding="utf-8")   # untracked
    gitrepo.move_path(str(repo), "old/B.md", "new/B.md")
    assert (repo / "new" / "B.md").exists()
    assert not (repo / "old" / "B.md").exists()
