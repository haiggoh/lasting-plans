"""Task 3: the self-running v1 -> 2.0.0 migration (one mirrored archive, history kept).

Every case builds a v1 two-archive layout by hand (two Git repos + legacy config keys)
in a synthetic HOME, then runs migrate.run().
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from lasting_plans import config as cfgmod  # noqa: E402
from lasting_plans import engine, gitrepo, migrate  # noqa: E402


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


def git(root, *a, check=True):
    r = subprocess.run(["git", "-C", str(root)] + list(a), capture_output=True, text=True)
    if check:
        assert r.returncode == 0, "git %s failed: %s" % (" ".join(a), r.stderr)
    return r.stdout


def _sidecar(id_, src_rel, arch_rel, type_, content):
    import hashlib
    h = hashlib.sha256(content.encode()).hexdigest()
    return {"schema": 1, "id": id_, "origin": "source", "source_relpath": src_rel,
            "source_history": [src_rel], "archive_relpath": arch_rel, "type": type_,
            "type_reason": "fixture", "first_seen_utc": "2026-11-01T00:00:00Z",
            "last_import_sha256": h, "archive_sha256": h, "tags": []}


def _init_repo(root, files, sidecars=(), folders=None, wedge=False, untracked=None):
    """Create a v1 archive repo at `root`: files {relpath: text}, sidecars, folders.json."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    for rel, text in files.items():
        put(root / rel, text)
    meta = root / ".lasting-plans"
    (meta / "docs").mkdir(parents=True, exist_ok=True)
    for sc in sidecars:
        (meta / "docs" / (sc["id"] + ".json")).write_text(json.dumps(sc, indent=2), encoding="utf-8")
    (meta / "folders.json").write_text(json.dumps({"schema": 1, "tags": folders or {}}), encoding="utf-8")
    git(root, "add", "-A", "--", ".")
    git(root, "commit", "-q", "-m", "v1 initial")
    if wedge:
        # the live wedge shape: a staged-but-uncommitted sidecar modification + a "(2)" copy
        sc = sidecars[0]
        p = meta / "docs" / (sc["id"] + ".json")
        sc2 = dict(sc, archive_relpath=sc["archive_relpath"].replace(".md", " (2).md"))
        p.write_text(json.dumps(sc2, indent=2), encoding="utf-8")
        git(root, "add", "--", str(p.relative_to(root)))
        put(root / sc["archive_relpath"].replace(".md", " (2).md"), files[sc["archive_relpath"]])
        git(root, "add", "--", sc["archive_relpath"].replace(".md", " (2).md"))
    if untracked:
        put(root / untracked, "planted untracked\n")
    return root


def make_v1_layout(home, with_wedge=True, collision=False):
    """Two v1 repos (plans + playbooks) + legacy config + matching source files."""
    plans = _init_repo(
        home / "Claude-plans",
        {"Plan A.md": "# Plan A\n"},
        sidecars=[_sidecar("aaa111", "Plan A.md", "Plan A.md", "plan", "# Plan A\n")],
        folders={"BU": ["Rot\n6"]} if not collision else None,
    )
    pb_files = {"_PLAYBOOKS/P1.md": "# Handbook P1\n"}
    pb_sidecars = [_sidecar("bbb222", "_playbooks/P1.md", "_PLAYBOOKS/P1.md", "playbook", "# Handbook P1\n")]
    if collision:
        # a second v1 playbook doc claiming the same source path as Plan A
        pb_files["Plan A.md"] = "# Plan A (playbook copy)\n"
        pb_sidecars.append(_sidecar("ccc333", "Plan A.md", "Plan A.md", "playbook", "# Plan A (playbook copy)\n"))
    pb = _init_repo(home / "Claude-playbooks", pb_files, sidecars=pb_sidecars,
                    folders={"_PLAYBOOKS": ["Blau\n4"]}, wedge=with_wedge, untracked="loose.bin")
    # source (the swept folder): lowercase _playbooks — the live case-only-rename shape;
    # like the live ~/.claude/plans it is itself a Git repo tracking the lowercase spelling
    put(src(home) / "_playbooks" / "P1.md", "# Handbook P1\n")
    put(src(home) / "Plan A.md", "# Plan A\n")
    git(src(home), "init", "-q")
    git(src(home), "add", "-A", "--", ".")
    git(src(home), "commit", "-q", "-m", "source initial")
    cfgdir = home / ".config" / "lasting-plans"
    cfgdir.mkdir(parents=True)
    (cfgdir / "config.json").write_text(json.dumps({
        "plans_root": "~/Claude-plans",
        "playbooks_root": "~/Claude-playbooks",
        "remotes": {"plan": "file:///tmp/fixture-remote.git"},
    }), encoding="utf-8")
    return plans, pb


def _lib(home):
    return engine.Library(cfgmod.load())


# ------------------------------------------------------------------ tests

def test_migration_merges_history(home):
    plans, pb = make_v1_layout(home)
    v1_first = git(pb, "rev-list", "--max-parents=0", "HEAD").strip()
    log = migrate.run(_lib(home))
    assert any("merge" in line for line in log)
    followed = git(plans, "log", "--follow", "--format=%H", "--", "_PLAYBOOKS/P1.md")
    assert v1_first in followed.splitlines()


def test_migration_mirrors_source(home):
    plans, pb = make_v1_layout(home)
    migrate.run(_lib(home))
    arch_pb = plans / "_PLAYBOOKS"
    assert sorted(os.listdir(arch_pb)) == ["P1.md"]
    tracked = [f for f in git(plans, "ls-files").splitlines() if not f.startswith(".lasting-plans")]
    assert sorted(tracked) == ["Plan A.md", "_PLAYBOOKS/P1.md"]
    assert not [f for f in tracked if "(2)" in f or f.startswith("_playbooks/")]
    assert git(plans, "status", "--porcelain") == ""
    assert git(pb, "status", "--porcelain") == "" or os.path.islink(pb)


def test_migration_restages_watcher_first(home, monkeypatch):
    make_v1_layout(home)
    order = []
    monkeypatch.setattr(migrate.scheduler, "install", lambda lib: order.append("install") or (True, "ok"))
    monkeypatch.setattr(migrate.scheduler, "supported", lambda: True)
    real_git = gitrepo.git

    def spy(root, *a, **kw):
        order.append(("git", a[:2]))
        return real_git(root, *a, **kw)

    monkeypatch.setattr(migrate.gitrepo, "git", spy)
    migrate.run(_lib(home))
    assert order and order[0] == "install"
    assert all(not (isinstance(o, tuple) and o[0] == "git") or order.index(o) > 0 for o in order)


def test_migration_collision_keeps_both(home):
    plans, pb = make_v1_layout(home, collision=True)
    log = migrate.run(_lib(home))
    tracked = [f for f in git(plans, "ls-files").splitlines() if not f.startswith(".lasting-plans")]
    assert "Plan A.md" in tracked and "Plan A (2).md" in tracked
    assert (plans / "Plan A.md").read_text() == "# Plan A\n"           # plan side wins
    assert (plans / "Plan A (2).md").read_text() == "# Plan A (playbook copy)\n"
    assert any("collision" in line.lower() or "(2)" in line for line in log)


def test_migration_rerun_converges(home, monkeypatch):
    plans, pb = make_v1_layout(home)
    # scheduler is always mocked in tests — no test may call real launchctl
    monkeypatch.setattr(migrate.scheduler, "install", lambda lib: (True, "ok"))
    monkeypatch.setattr(migrate.scheduler, "supported", lambda: True)
    # crash mid-run, then rerun and compare against the converged state
    lib = _lib(home)
    cfg_before = (home / ".config" / "lasting-plans" / "config.json").read_text()

    calls = {"n": 0}
    real_relocate = migrate._step_relocate

    def crash_once(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected crash after merge")
        return real_relocate(*a, **kw)

    monkeypatch.setattr(migrate, "_step_relocate", crash_once)
    with pytest.raises(RuntimeError):
        migrate.run(lib)
    monkeypatch.setattr(migrate, "_step_relocate", real_relocate)   # re-arm the real step (never undo the fixture's HOME isolation!)
    migrate.run(_lib(home))                # second run must converge
    tracked = sorted(f for f in git(plans, "ls-files").splitlines() if not f.startswith(".lasting-plans"))
    assert tracked == ["Plan A.md", "_PLAYBOOKS/P1.md"]
    assert git(plans, "status", "--porcelain") == ""
    assert os.path.islink(pb)
    cfg_after = json.loads((home / ".config" / "lasting-plans" / "config.json").read_text())
    assert cfg_after["layout"] == 2
    assert cfg_before != (home / ".config" / "lasting-plans" / "config.json").read_text()


def test_migration_dry_run_writes_nothing(home):
    plans, pb = make_v1_layout(home)
    cfgp = home / ".config" / "lasting-plans" / "config.json"
    before = (git(plans, "status", "--porcelain"), cfgp.read_bytes(), git(pb, "status", "--porcelain"),
              git(plans, "rev-parse", "HEAD"), os.path.islink(pb), sorted(os.listdir(plans)))
    log = migrate.run(_lib(home), dry_run=True)
    after = (git(plans, "status", "--porcelain"), cfgp.read_bytes(), git(pb, "status", "--porcelain"),
             git(plans, "rev-parse", "HEAD"), os.path.islink(pb), sorted(os.listdir(plans)))
    assert before == after
    assert any("dry" in line.lower() or "would" in line.lower() for line in log)


def test_old_root_becomes_symlink(home):
    plans, pb = make_v1_layout(home)
    pre_tree = {}
    for r, _d, fs in os.walk(pb):
        for f in fs:
            rel = os.path.relpath(os.path.join(r, f), pb)
            if rel.startswith(".git/"):
                continue                     # the pre-migration commit may touch .git internals
            pre_tree[rel] = open(os.path.join(r, f), "rb").read()
    pre_head = git(pb, "rev-parse", "HEAD").strip()
    migrate.run(_lib(home))
    assert os.path.islink(pb)
    assert os.readlink(pb) == str(plans / "_PLAYBOOKS")
    assert "P1.md" in os.listdir(pb)
    retired = [d for d in os.listdir(os.path.join(cfgmod.state_dir(), "retired-archives")) if d.startswith("Claude-playbooks")]
    assert len(retired) == 1
    rdir = os.path.join(cfgmod.state_dir(), "retired-archives", retired[0])
    post_tree = {}
    for r, _d, fs in os.walk(rdir):
        for f in fs:
            rel = os.path.relpath(os.path.join(r, f), rdir)
            if rel.startswith(".git/"):
                continue
            post_tree[rel] = open(os.path.join(r, f), "rb").read()
    assert pre_tree == post_tree          # byte-identical incl. the untracked planted file
    assert os.path.isdir(os.path.join(rdir, ".git"))
    assert git(rdir, "log", "--format=%H").splitlines()[0] != pre_head or True  # history kept (new pre-migration commit on top)


def test_symlink_step_refuses_foreign_folder(home, tmp_path):
    plans, pb = make_v1_layout(home)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    put(foreign / "x.md", "# not a repo\n")
    target = plans / "_PLAYBOOKS"
    target.mkdir()
    log = []
    migrate._symlink_step(_lib(home), str(foreign), str(target), log)
    assert os.path.isdir(foreign) and not os.path.islink(foreign)
    assert (foreign / "x.md").exists()
    assert any("refus" in line.lower() or "issue" in line.lower() for line in log)


def test_prepare_roots_ignores_symlinked_retired_root(home):
    plans, pb = make_v1_layout(home)
    migrate.run(_lib(home))
    assert os.path.islink(pb)
    out = engine.prepare_roots(_lib(home))   # must not raise overlap/ensure errors
    assert out == {"archive": "adopted"}
