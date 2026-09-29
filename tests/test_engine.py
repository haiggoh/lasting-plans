"""Fixture-only tests: every case runs in a synthetic temp HOME with a synthetic Git identity."""
import json
import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from lasting_plans import classify, engine, metadata  # noqa: E402
from lasting_plans import config as cfgmod  # noqa: E402

BIN = os.path.join(ROOT, "bin", "lasting-plans")
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


def put(path, text, mtime=OLD):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def scan():
    return engine.scan(engine.Library())


def git(root, *a):
    return subprocess.run(["git", "-C", str(root)] + list(a), capture_output=True, text=True).stdout


def kinds(res):
    return sorted(e[0] for e in res.events)


# ------------------------------------------------------------------ classification

@pytest.mark.parametrize("name,h1,want", [
    ("PLAYBOOK-full-auto.md", "", "playbook"),
    ("notes.md", "Team Handbook", "playbook"),
    ("x.md", "Manual: Writing AI-Targeted Execution Plans (v4)", "playbook"),
    ("deploy-manual.md", "", "playbook"),
    ("a.md", "Operator Manual for the stack", "playbook"),
    ("manual-installation-plan.md", "", "plan"),          # adjective: stays a plan
    ("x.md", "Manual testing of the login flow", "plan"),  # adjective in H1
    ("x.md", "Plan — refactor", "plan"),
    # the leading/trailing noun decides; a mid-sentence mention does not (0.1.1)
    ("Execution plan — X_ plan and playbook preservation.md", "Execution plan — X", "plan"),
    ("DECISION-LEDGER-playbook-decomposition.md", "", "plan"),
    ("x.md", "Making a Repo Portable — Playbook", "playbook"),
    ("Playbook_AI-Targeted_Execution_Plan_v4.md", "", "playbook"),
    ("x.md", "Release Playbook (v2)", "playbook"),
    ("Workflow — Feature Branches and Checkpoints.md", "", "playbook"),
    ("x.md", "Workflow: shipping a plugin", "playbook"),
    ("x.md", "Plugin Release Workflow", "playbook"),
    ("workflow-fix-plan.md", "", "plan"),                  # adjective, like manual-installation
    ("x.md", "Fix the CI workflow cache", "plan"),
    ("_PLAYBOOKS/notes.md", "", "playbook"),               # a playbook folder decides
    ("drafts/notes.md", "", "plan"),
])
def test_classify(name, h1, want):
    text = ("# %s\n\nbody mentions playbook many times\n" % h1) if h1 else "no heading, playbook in body\n"
    assert classify.classify(name, text)[0] == want


def test_classify_ignores_body_and_skips_frontmatter():
    assert classify.classify("a.md", "---\ntitle: x\n---\n# Handbook\n")[0] == "playbook"
    assert classify.classify("a.md", "# Plan\n\nThis is a playbook.\n")[0] == "plan"
    assert classify.classify("a.md", "# Plan\n", {"a.md": "playbook"}) == ("playbook", "user override")


# ------------------------------------------------------------------ import & invariants

def test_import_routes_and_commits(home):
    put(src(home) / "Plan A.md", "# Plan A\n")
    put(src(home) / "PLAYBOOK-x.md", "# PB\n")
    put(src(home) / "BU" / "old.md", "# old\n")
    res = scan()
    assert kinds(res) == ["imported"] * 3 and not res.pending
    assert (home / "Claude-plans" / "Plan A.md").read_text() == "# Plan A\n"
    assert (home / "Claude-plans" / "BU" / "old.md").exists()
    assert (home / "Claude-playbooks" / "PLAYBOOK-x.md").exists()
    assert git(home / "Claude-plans", "status", "--porcelain") == ""
    assert "import: Plan A.md" in git(home / "Claude-plans", "log", "--format=%s")


def test_idempotent(home):
    put(src(home) / "a.md", "# a\n")
    scan()
    before = git(home / "Claude-plans", "rev-parse", "HEAD")
    res = scan()
    assert res.events == [] and git(home / "Claude-plans", "rev-parse", "HEAD") == before


def test_source_swept_never_deletes_archive(home):
    p = put(src(home) / "a.md", "# a\n")
    scan()
    p.unlink()
    res = scan()
    assert res.events == []
    assert (home / "Claude-plans" / "a.md").read_text() == "# a\n"
    assert git(home / "Claude-plans", "status", "--porcelain") == ""
    st = engine.status(engine.Library())
    assert st["kept_after_source_gone"] == 1 and not st["unprotected"]


def test_update_commits_new_revision(home):
    p = put(src(home) / "a.md", "# a\nv1\n")
    scan()
    put(p, "# a\nv2\n")
    res = scan()
    assert kinds(res) == ["updated"]
    assert (home / "Claude-plans" / "a.md").read_text().endswith("v2\n")
    doc = engine.Library().resolve("a.md")[0]
    assert [h["kind"] for h in engine.history(doc)][:2] == ["content", "content"]
    assert "-v1" in engine.diff(doc) and "+v2" in engine.diff(doc)


def test_hand_edited_archive_is_not_overwritten(home):
    p = put(src(home) / "a.md", "# a\nv1\n")
    scan()
    arch = home / "Claude-plans" / "a.md"
    put(arch, "# a\nMY EDIT\n")
    scan()                                    # commits the archive edit
    put(p, "# a\nsource v2\n")
    res = scan()
    assert "conflict" in kinds(res)
    assert arch.read_text() == "# a\nMY EDIT\n"
    copies = [f for f in os.listdir(home / "Claude-plans") if "source edit" in f]
    assert len(copies) == 1
    assert (home / "Claude-plans" / copies[0]).read_text() == "# a\nsource v2\n"
    assert scan().events == []                # no conflict loop


def test_same_name_independent_doc_kept_both(home):
    put(src(home) / "a.md", "# first\n")
    scan()
    (src(home) / "a.md").unlink()
    put(home / "Claude-plans" / "a.md", "# first\n")  # unchanged archive
    put(src(home) / "a.md", "# totally different\n")
    res = scan()
    # same source path returns with new content: treated as an update of the same doc
    assert kinds(res) == ["updated"]
    assert len(git(home / "Claude-plans", "log", "--format=%H", "--", "a.md").split()) == 2


def test_collision_with_foreign_file_in_archive(home):
    scan()                                     # creates the archive repo
    put(home / "Claude-plans" / "x.md", "# dropped by hand\n")
    assert kinds(scan()) == ["adopted"]
    put(src(home) / "x.md", "# from claude\n")
    res = scan()
    assert (home / "Claude-plans" / "x.md").read_text() == "# dropped by hand\n"
    assert (home / "Claude-plans" / "x (2).md").read_text() == "# from claude\n"
    assert any("name taken" in e[3] for e in res.events)


def test_move_between_subdirectories_follows(home):
    p = put(src(home) / "a.md", "# a\n")
    scan()
    (src(home) / "BU").mkdir()
    os.rename(p, src(home) / "BU" / "a.md")
    res = scan()
    assert kinds(res) == ["moved"]
    assert (home / "Claude-plans" / "BU" / "a.md").exists()
    assert not (home / "Claude-plans" / "a.md").exists()
    assert len(engine.Library().docs) == 1
    assert git(home / "Claude-plans", "status", "--porcelain") == ""


def test_symlinks_and_escapes_ignored(home, tmp_path):
    outside = put(tmp_path / "secret.md", "# secret\n")
    os.symlink(outside, src(home) / "link.md")
    os.symlink(tmp_path, src(home) / "linkdir")
    put(src(home) / ".hidden.md", "# h\n")
    res = scan()
    assert res.events == []
    assert not (home / "Claude-plans" / "link.md").exists()


def test_half_written_file_is_retried(home, monkeypatch):
    monkeypatch.setenv("LASTING_PLANS_SETTLE_SECONDS", "30")
    put(src(home) / "a.md", "# a\n", mtime=time.time())
    res = scan()
    assert res.events == [] and res.pending
    monkeypatch.setenv("LASTING_PLANS_SETTLE_SECONDS", "0")
    assert kinds(scan()) == ["imported"]


def test_git_identity_missing_keeps_copy_and_catches_up(home, monkeypatch):
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k)
    put(src(home) / "a.md", "# a\n")
    res = scan()
    assert res.pending and "no Git" in res.pending[0][1]
    assert (home / "Claude-plans" / "a.md").exists()
    monkeypatch.setenv("GIT_AUTHOR_NAME", "F")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "f@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "F")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "f@example.invalid")
    res = scan()
    assert kinds(res) == ["committed"]
    assert git(home / "Claude-plans", "status", "--porcelain") == ""


def test_unrelated_dirty_files_stay_unstaged(home):
    put(src(home) / "a.md", "# a\n")
    scan()
    junk = home / "Claude-plans" / "notes.bin"
    junk.write_bytes(b"\0private")
    put(src(home) / "b.md", "# b\n")
    scan()
    assert "notes.bin" not in git(home / "Claude-plans", "log", "--name-only", "--format=")
    assert "?? notes.bin" in git(home / "Claude-plans", "status", "--porcelain")


def test_refuses_archive_nested_in_other_repo(home):
    subprocess.run(["git", "init", "-q", str(home)], check=True)
    put(src(home) / "a.md", "# a\n")
    with pytest.raises(engine.gitrepo.GitError, match="nested"):
        scan()


def test_refuses_nonempty_non_repo_root(home):
    put(home / "Claude-plans" / "stuff.txt", "x")
    with pytest.raises(engine.gitrepo.GitError, match="not empty"):
        scan()


# ------------------------------------------------------------------ metadata

@pytest.mark.skipif(sys.platform != "darwin", reason="Finder metadata is macOS-only")
def test_metadata_captured_and_applied(home):
    p = put(src(home) / "a.md", "# a\n", mtime=time.time() - 86400 * 90)
    assert metadata.write_tags(str(p), ["Rot"])
    scan()
    arch = home / "Claude-plans" / "a.md"
    doc = engine.Library().resolve("a.md")[0]
    assert "Rot" in doc.sc["tags"] and metadata.read_tags(str(arch)) == ["Rot"]
    assert abs(os.stat(arch).st_mtime - os.stat(p).st_mtime) < 1
    assert doc.sc["created_source"] == "filesystem birthtime"


@pytest.mark.skipif(sys.platform != "darwin", reason="Finder metadata is macOS-only")
def test_tags_are_additive_and_existing_user_tags_survive(home):
    p = put(src(home) / "a.md", "# a\n")
    scan()
    arch = str(home / "Claude-plans" / "a.md")
    metadata.write_tags(arch, ["Mine"])
    metadata.write_tags(str(p), ["Gelb"])
    res = scan()
    assert "metadata" in kinds(res)
    assert set(metadata.read_tags(arch)) == {"Mine", "Gelb"}


@pytest.mark.skipif(sys.platform != "darwin", reason="Finder metadata is macOS-only")
def test_meta_command_sets_dates_and_records_provenance(home):
    put(src(home) / "a.md", "# a\n")
    scan()
    doc = engine.Library().resolve("a.md")[0]
    failed, sha = engine.set_metadata(doc, created="2026-07-01T10:00:00", modified="2026-08-02T11:00:00")
    arch = home / "Claude-plans" / "a.md"
    assert sha and "created" not in failed
    assert time.strftime("%Y-%m-%d", time.localtime(os.stat(arch).st_mtime)) == "2026-08-02"
    assert time.strftime("%Y-%m-%d", time.localtime(os.stat(arch).st_birthtime)) == "2026-07-01"
    doc = engine.Library().resolve("a.md")[0]
    assert doc.sc["created_source"] == "user"
    scan()  # a later scan must not overwrite the user-supplied creation date
    assert engine.Library().resolve("a.md")[0].sc["created_source"] == "user"


# ------------------------------------------------------------------ search / CLI

def test_search_finds_text_beyond_any_preview(home):
    body = "# a\n" + ("filler line\n" * 500) + "needle-deep-in-body\n"
    put(src(home) / "a.md", body)
    scan()
    hits = engine.search(engine.Library(), "needle-deep")
    assert len(hits) == 1 and hits[0]["matches"] == 1


def run_cli(home, *args, stdin=None):
    env = dict(os.environ)
    return subprocess.run([sys.executable, BIN] + list(args), capture_output=True, text=True, env=env,
                          input=stdin, timeout=60)


def test_cli_help_runs_nothing(home):
    r = run_cli(home, "--help")
    assert r.returncode == 0 and "LASTING_PLANS_CONFIG_DIR" in r.stdout
    assert not (home / "Claude-plans").exists()
    r = run_cli(home, "--bogus")
    assert r.returncode == 2 and not (home / "Claude-plans").exists()


def test_cli_end_to_end_and_exit_codes(home):
    put(src(home) / "Alpha plan.md", "# Alpha\nsecret-word\n")
    put(src(home) / "Beta plan.md", "# Beta\n")
    assert run_cli(home, "setup", "--no-scheduler").returncode == 0
    lst = json.loads(run_cli(home, "list", "--json").stdout)
    assert lst["total"] == 2
    assert run_cli(home, "show", "nomatch-xyz").returncode == 3
    assert run_cli(home, "show", "plan").returncode == 4       # ambiguous
    r = run_cli(home, "show", "Alpha", "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["type"] == "plan"
    assert run_cli(home, "search", "secret-word").returncode == 0
    assert run_cli(home, "search", "absent-word").returncode == 3
    assert run_cli(home, "history", "Alpha").returncode == 0


def test_cli_pipe_never_prompts(home):
    r = run_cli(home, stdin="1\n")
    assert r.returncode in (0, 5) and "Lasting Plans" in r.stdout and ">" not in r.stdout.splitlines()[-1]


def test_malformed_config_is_reported(home):
    p = home / ".config" / "lasting-plans" / "config.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not json")
    r = run_cli(home, "status")
    assert r.returncode == 2 and "malformed" in r.stderr


def test_settings_roundtrip_keeps_unknown_keys(home):
    p = home / ".config" / "lasting-plans" / "config.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"future_key": 1}))
    assert run_cli(home, "settings", "set", "interval_seconds", "600").returncode == 0
    d = json.loads(p.read_text())
    assert d["interval_seconds"] == 600 and d["future_key"] == 1
    assert run_cli(home, "settings", "set", "interval_seconds", "5").returncode == 2


def test_claude_config_dir_and_plans_directory_honoured(home, monkeypatch, tmp_path):
    alt = tmp_path / "altcfg"
    (alt / "plans").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(alt))
    assert cfgmod.source_dir(cfgmod.load()) == str(alt / "plans")
    (alt / "settings.json").write_text(json.dumps({"plansDirectory": str(tmp_path / "pd")}))
    assert cfgmod.source_dir(cfgmod.load()) == str(tmp_path / "pd")


# ------------------------------------------------------------------ watcher

@pytest.mark.skipif(not hasattr(__import__("select"), "kqueue"), reason="kqueue only")
def test_watcher_fires_on_enter_leave_and_move(home):
    from lasting_plans import watch
    (src(home) / "sub").mkdir()
    w = watch.KqueueWatcher([str(src(home))])
    try:
        assert not w.wait(0.2)
        put(src(home) / "new.md", "x")
        assert w.wait(2)
        os.rename(src(home) / "new.md", src(home) / "sub" / "new.md")
        assert w.wait(2)
        w.rearm()
        (src(home) / "sub" / "new.md").unlink()
        assert w.wait(2)
    finally:
        w.close()


def test_watch_max_seconds_is_a_deadline(home):
    # idle wait used to be interval-bound (900s) and never checked max_seconds
    t0 = time.monotonic()
    r = run_cli(home, "watch", "--max-seconds", "2")
    assert r.returncode == 0
    assert time.monotonic() - t0 < 10


def test_watch_once_imports(home):
    put(src(home) / "a.md", "# a\n")
    r = run_cli(home, "watch", "--once")
    assert r.returncode == 0 and "imported" in r.stdout
    assert (home / "Claude-plans" / "a.md").exists()


# ------------------------------------------------------------------ 0.1.1

def test_1984_birthtime_sentinel_is_unknown(monkeypatch, tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    real = os.stat

    class St:
        def __init__(self, s):
            self._s = s
            self.st_birthtime = 443779200.0  # 1984-01-24 09:00 CET: the no-date placeholder

        def __getattr__(self, k):
            return getattr(self._s, k)

    monkeypatch.setattr(metadata.os, "stat", lambda p, *a, **k: St(real(p, *a, **k)))
    obs = metadata.observe(str(f))
    assert obs["created_utc"] is None and obs["created_source"].startswith("unknown")
    assert metadata.is_no_birthtime_sentinel(443779200.0)
    assert not metadata.is_no_birthtime_sentinel(1759000000.0)


def test_reclassify_moves_between_archives_and_doctor_reports(home):
    put(src(home) / "x.md", "# Plan and playbook preservation\n")
    scan()
    lib = engine.Library()
    d = lib.resolve("x.md")[0]
    assert d.type == "plan"
    rel, a, b = engine.reclassify(lib, d, "playbook")
    assert a and b
    assert (home / "Claude-playbooks" / "x.md").exists() and not (home / "Claude-plans" / "x.md").exists()
    assert "reclassify" in git(home / "Claude-plans", "log", "-1", "--format=%s")
    lib = engine.Library()
    assert [x.type for x in lib.docs] == ["playbook"]
    assert not engine.type_mismatches(lib)  # a user reclassification is final
    assert scan().events == []              # the next scan neither re-imports nor moves it back


def test_type_mismatch_is_reported_not_moved(home):
    put(src(home) / "x.md", "# notes\n")
    scan()
    lib = engine.Library()
    d = lib.docs[0]
    d.sc["type_reason"] = "old rule"
    engine.write_sidecar(d.root, d.sc)
    # pretend an older classifier filed it as a playbook
    engine.reclassify(lib, d, "playbook")
    lib = engine.Library()
    d = lib.docs[0]
    d.sc["type_reason"] = "filename matched playbook/handbook"
    engine.write_sidecar(d.root, d.sc)
    mm = engine.type_mismatches(engine.Library())
    assert [(x.type, k) for x, k, _ in mm] == [("playbook", "plan")]
    scan()
    assert engine.Library().docs[0].type == "playbook"


def test_recover_dates_from_text_and_mtimes(home, tmp_path):
    from lasting_plans import recover
    put(src(home) / "a.md", "# A\n\n**Date:** 2026-08-19\n")
    put(src(home) / "b 2026-07-02.md", "# B\n")
    put(src(home) / "c.md", "# C\n")                              # no date anywhere
    put(src(home) / "d.md", "# D\n\nCreated: 2099-01-01\n")       # impossible: in the future
    scan()
    lib = engine.Library()
    tsv = tmp_path / "m.tsv"
    tsv.write_text("verdict\tpath\tcurrent_mtime\tbackup_mtime\tarchive\n"
                   "exact\tc.md\tx\t2026-08-01 10:00\tcm\n"
                   "edited-after\ta.md\tx\t2026-01-01 10:00\tcm\n")
    now = time.time()
    ch = {c["doc"].sc["archive_relpath"]: c for c in recover.plan(lib, now - 7200, now + 60, recover.load_mtimes(str(tsv)))}
    assert "labelled" in ch["a.md"]["created"][1] and metadata.utc_iso(ch["a.md"]["created"][0]).startswith("2026-08-1")
    assert ch["a.md"]["modified"] is None                             # only 'exact' rows count
    assert "file name" in ch["b 2026-07-02.md"]["created"][1]
    assert ch["c.md"]["created"][1].startswith("upper bound") and ch["c.md"]["modified"]
    assert "d.md" not in ch                                           # never moves a date LATER
    shas, failed = recover.apply(list(ch.values()), "fixture loss")
    assert all(shas.values())
    sc = engine.Library().resolve("a.md")[0].sc
    assert sc["created_source"].startswith("recovered") and sc["date_recovery"][0]["reason"] == "fixture loss"
    # a later source EDIT re-reads the filesystem; it must not overwrite a recovered date
    put(src(home) / "a.md", "# A\n\n**Date:** 2026-08-19\n\nedited\n")
    assert "updated" in kinds(scan())
    assert engine.Library().resolve("a.md")[0].sc["created_utc"] == sc["created_utc"]
    assert recover.plan(engine.Library(), now - 7200, now + 60) == [] or all(
        c["doc"].sc["archive_relpath"] == "d.md" for c in recover.plan(engine.Library(), now - 7200, now + 60))


def test_recover_dates_cli_is_dry_run_by_default(home):
    put(src(home) / "a.md", "# A\n\nDate: 2026-08-19\n")
    scan()
    before = git(home / "Claude-plans", "rev-parse", "HEAD")
    r = run_cli(home, "recover-dates", "--since", "2000-01-01", "--until", "2100-01-01")
    assert r.returncode == 0 and "DRY RUN" in r.stdout and "labelled" in r.stdout
    assert git(home / "Claude-plans", "rev-parse", "HEAD") == before
    r = run_cli(home, "recover-dates", "--since", "2000-01-01", "--until", "2100-01-01", "--apply")
    assert r.returncode == 2                                          # --reason is required


def test_recover_replaces_recorded_1984_placeholder_with_upper_bound(home):
    from lasting_plans import recover
    put(src(home) / "a.md", "# no dates here\n")
    scan()
    lib = engine.Library()
    d = lib.docs[0]
    d.sc["created_utc"], d.sc["created_source"] = "1984-01-24T08:00:00Z", "filesystem birthtime"  # as 0.1.0 recorded it
    engine.write_sidecar(d.root, d.sc)
    ch = recover.plan(engine.Library(), metadata.parse_iso("1984-01-23"), metadata.parse_iso("1984-01-26"))
    assert len(ch) == 1 and ch[0]["created"][1].startswith("upper bound: last modification")
    assert ch[0]["created"][0] == metadata.parse_iso(d.sc["modified_utc"])


def test_stage_code_writes_version_stamp(home, monkeypatch):
    from lasting_plans import __version__, scheduler
    monkeypatch.setattr(scheduler, "install_dir", lambda: str(home / "stage"))
    scheduler.stage_code(os.path.join(ROOT, "lib"))
    assert (home / "stage" / "VERSION").read_text().strip() == __version__
