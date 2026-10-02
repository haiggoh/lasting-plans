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
    env = dict(os.environ, HOME=str(home))
    env.pop("CLAUDE_CONFIG_DIR", None)  # ensure test source dir is used
    env["LASTING_PLANS_SETTLE_SECONDS"] = "0"  # instant settle for tests
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


# ------------------------------------------------------------------ 0.2.0 remote

def bare(tmp_path, name):
    p = tmp_path / name
    subprocess.run(["git", "init", "-q", "--bare", str(p)], check=True)
    return "file://" + str(p)


def test_remote_push_verifies_tip_and_tracks_pending(home, tmp_path):
    from lasting_plans import remote
    put(src(home) / "a.md", "# a\n")
    scan()
    lib = engine.Library()
    u = bare(tmp_path, "plans.git")
    remote.configure(lib, "plan", u)
    assert remote.summary(lib)["plan"]["state"] == "pending remote"   # configured is not pushed
    ok, detail = remote.push(lib, "plan")
    assert ok and "verified" in detail
    head = gitrepo_head(home / "Claude-plans")
    assert remote.remote_tip(str(home / "Claude-plans"), remote.branch(str(home / "Claude-plans"))) == head
    assert remote.summary(lib, verify=True)["plan"]["state"] == "in sync"
    assert remote.summary(lib)["playbook"]["state"] == "off"
    put(src(home) / "b.md", "# b\n")
    scan()
    s = remote.summary(engine.Library())["plan"]
    assert s["state"] == "pending remote" and s["unpushed_commits"] == 1


def gitrepo_head(root):
    return git(root, "rev-parse", "HEAD").strip()


def test_auto_push_after_sync_and_manual_mode_does_not(home, tmp_path):
    from lasting_plans import remote
    put(src(home) / "a.md", "# a\n")
    scan()
    remote.configure(engine.Library(), "plan", bare(tmp_path, "p.git"))
    run_cli(home, "settings", "set", "remote_push", "manual")
    r = run_cli(home, "sync")
    assert "remote" not in r.stdout
    assert remote.summary(engine.Library())["plan"]["state"] == "pending remote"
    run_cli(home, "settings", "set", "remote_push", "auto")
    put(src(home) / "b.md", "# b\n")
    r = run_cli(home, "sync")
    assert r.returncode == 0 and "remote plan: remote verified" in r.stdout
    assert remote.summary(engine.Library(), verify=True)["plan"]["state"] == "in sync"
    r = run_cli(home, "sync")                  # nothing new: no push attempted at all
    assert "remote" not in r.stdout


def test_rejected_push_is_pending_never_forced(home, tmp_path):
    from lasting_plans import remote
    put(src(home) / "a.md", "# a\n")
    scan()
    lib = engine.Library()
    u = bare(tmp_path, "p.git")
    remote.configure(lib, "plan", u)
    assert remote.push(lib, "plan")[0]
    # someone else moves the remote on
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", u, str(other)], check=True)
    (other / "x.md").write_text("foreign")
    subprocess.run(["git", "-C", str(other), "add", "x.md"], check=True)
    subprocess.run(["git", "-C", str(other), "commit", "-qm", "foreign"], check=True)
    subprocess.run(["git", "-C", str(other), "push", "-q"], check=True)
    foreign = git(other, "rev-parse", "HEAD").strip()
    put(src(home) / "b.md", "# b\n")
    scan()
    ok, detail = remote.push(engine.Library(), "plan")
    assert not ok
    assert remote.remote_tip(str(home / "Claude-plans"), remote.branch(str(home / "Claude-plans"))) == foreign
    assert remote.summary(engine.Library())["plan"]["state"] == "pending remote (last push failed)"
    r = run_cli(home, "status")
    assert r.returncode == 5 and "remote push pending" in r.stdout


def test_offline_push_is_pending(home, tmp_path):
    from lasting_plans import remote
    put(src(home) / "a.md", "# a\n")
    scan()
    lib = engine.Library()
    remote.configure(lib, "plan", bare(tmp_path, "gone.git"))
    import shutil as _sh
    _sh.rmtree(tmp_path / "gone.git")
    ok, _ = remote.push(lib, "plan")
    assert not ok and remote.summary(engine.Library())["plan"]["state"].startswith("pending")
    assert remote.summary(engine.Library(), verify=True)["plan"]["state"].startswith("unknown")


def test_public_remote_refused_and_unverified_needs_confirm(home, monkeypatch):
    from lasting_plans import gitrepo, remote
    scan()
    lib = engine.Library()
    monkeypatch.setattr(remote, "privacy", lambda u: ("public", "GitHub reports PUBLIC"))
    with pytest.raises(gitrepo.GitError, match="private"):
        remote.configure(lib, "plan", "https://github.com/x/y.git")
    monkeypatch.setattr(remote, "privacy", lambda u: ("unverified", "not a GitHub URL"))
    with pytest.raises(gitrepo.GitError, match="confirm-private"):
        remote.configure(lib, "plan", "https://git.example/y.git")
    assert not engine.Library().cfg.get("remotes")
    assert run_cli(home, "settings", "set", "remotes", "{}").returncode == 2


def test_clone_on_fresh_home_restores_docs_and_dates(home, tmp_path, monkeypatch):
    from lasting_plans import remote
    put(src(home) / "sub" / "a.md", "# a\n\nDate: 2026-08-19\n")
    scan()
    lib = engine.Library()
    u = bare(tmp_path, "p.git")
    remote.configure(lib, "plan", u)
    assert remote.push(lib, "plan")[0]
    want = engine.Library().docs[0].sc["modified_utc"]
    fresh = tmp_path / "fresh"
    (fresh / ".claude" / "plans").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fresh))
    monkeypatch.setenv("LASTING_PLANS_CONFIG_DIR", str(fresh / ".config"))
    monkeypatch.setenv("LASTING_PLANS_STATE_DIR", str(fresh / ".state"))
    n, unapplied = remote.clone(engine.Library(), "plan", u)
    assert n == 1
    f = fresh / "Claude-plans" / "sub" / "a.md"
    assert f.read_text().startswith("# a")
    assert metadata.utc_iso(os.stat(f).st_mtime) == want              # the clone's checkout time was replaced
    lib = engine.Library()
    assert remote.summary(lib)["plan"]["state"] == "in sync"
    assert scan(). events == [] or all(e[0] != "imported" for e in scan().events)


# ------------------------------------------------------------------ 0.2.0 folder tags

@pytest.mark.skipif(not metadata.IS_MAC, reason="Finder tags are macOS only")
def test_folder_tags_mirror_to_archive_additively(home):
    put(src(home) / "drafts" / "a.md", "# a\n")
    assert metadata.write_tags(str(src(home) / "drafts"), ["Rot\n6"])
    res = scan()
    arch = home / "Claude-plans" / "drafts"
    assert "Rot\n6" in metadata.read_tags(str(arch))
    assert any(e[0] == "metadata" and e[2] == "drafts/" for e in res.events)
    assert "drafts" in json.loads((home / "Claude-plans" / ".lasting-plans" / "folders.json").read_text())["tags"]
    assert "folder tags" in git(home / "Claude-plans", "log", "-1", "--format=%s")
    assert scan().events == []                                   # idempotent
    metadata.write_tags(str(arch), ["Rot\n6", "Blau\n4"])          # user tags the archive folder too
    assert metadata.remove_raw_xattr(str(src(home) / "drafts"), metadata.TAGS_ATTR)
    scan()
    assert set(metadata.read_tags(str(arch))) >= {"Rot\n6", "Blau\n4"}   # never removed
    # a tag set only on the archive folder is not recorded, but survives; after a wipe the record restores
    assert metadata.remove_raw_xattr(str(arch), metadata.TAGS_ATTR)
    assert engine.apply_folder_tags(str(home / "Claude-plans")) == []
    assert "Rot\n6" in metadata.read_tags(str(arch))


def test_push_that_exits_zero_but_tip_differs_is_not_backed_up(home, tmp_path, monkeypatch):
    from lasting_plans import remote
    put(src(home) / "a.md", "# a\n")
    scan()
    lib = engine.Library()
    remote.configure(lib, "plan", bare(tmp_path, "p.git"))
    monkeypatch.setattr(remote, "remote_tip", lambda root, br, timeout=30: "0" * 40)
    ok, detail = remote.push(lib, "plan")
    assert not ok and "remote reports" in detail
    assert remote.summary(engine.Library())["plan"]["state"] != "in sync"


@pytest.mark.skipif(not metadata.IS_MAC, reason="Finder tags are macOS only")
def test_folder_tag_record_is_a_union_across_source_changes(home):
    put(src(home) / "drafts" / "a.md", "# a\n")
    metadata.write_tags(str(src(home) / "drafts"), ["Rot\n6"])
    scan()
    assert metadata.remove_raw_xattr(str(src(home) / "drafts"), metadata.TAGS_ATTR)
    metadata.write_tags(str(src(home) / "drafts"), ["Grün\n2"])
    scan()
    rec = engine.load_folder_tags(str(home / "Claude-plans"))["drafts"]
    assert rec == ["Rot\n6", "Grün\n2"]


# ------------------------------------------------------------------ tool resolution guard

def test_no_module_runs_a_system_tool_by_bare_name():
    """Every external program goes through tools.py. A bare "xattr"/"SetFile"/"launchctl"
    in a subprocess argv or shutil.which() elsewhere resolves via PATH, where pipx's xattr
    (or any shim) silently replaces the system one."""
    import ast
    import glob
    from lasting_plans import tools
    names = set(tools.SYSTEM)
    bad = []
    files = glob.glob(os.path.join(ROOT, "lib", "lasting_plans", "*.py")) + glob.glob(os.path.join(ROOT, "hooks", "*.py")) + [BIN]
    for f in files:
        if f.endswith("tools.py"):
            continue
        tree = ast.parse(open(f, encoding="utf-8").read(), f)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = ast.unparse(node.func)
                if fn in ("shutil.which", "which") and node.args and isinstance(node.args[0], ast.Constant):
                    bad.append("%s:%d which(%r) — use tools.system/on_path" % (os.path.basename(f), node.lineno, node.args[0].value))
                if fn.startswith("subprocess.") and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    first = node.args[0].elts[0] if node.args[0].elts else None
                    if isinstance(first, ast.Constant) and (first.value in names or os.path.basename(str(first.value)) in names):
                        bad.append("%s:%d runs %r directly — use tools.system()" % (os.path.basename(f), node.lineno, first.value))
    assert not bad, "\n".join(bad)


def test_tools_system_paths_are_absolute_and_path_is_ignored(tmp_path, monkeypatch):
    from lasting_plans import tools
    fake = tmp_path / "xattr"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    assert all(os.path.isabs(p) for p in tools.SYSTEM.values())
    if tools.IS_MAC and os.path.exists("/usr/bin/xattr"):
        assert tools.system("xattr") == "/usr/bin/xattr"
        assert ("xattr", str(fake), "/usr/bin/xattr") in tools.shadows()
    with pytest.raises(ValueError):
        tools.on_path("xattr")


# ------------------------------------------------------------------ 0.3.0 library

def _three_revisions(home):
    p = src(home) / "doc.md"
    put(p, "# Doc\n\nfirst draft mentions ZEPHYR\n", mtime=OLD - 300)
    scan()
    put(p, "# Doc\n\nsecond draft\n", mtime=OLD - 200)
    scan()
    put(p, "# Doc\n\nthird draft\n", mtime=OLD - 100)
    scan()
    return engine.Library().resolve("doc.md")[0]


def test_revision_selectors_and_old_text(home):
    from lasting_plans import library
    d = _three_revisions(home)
    revs = library.revisions(d)
    assert [r["n"] for r in revs] == [3, 2, 1]
    assert "ZEPHYR" in library.text_at(d, library.resolve_rev(d, "1"))
    assert library.resolve_rev(d, "first") == library.resolve_rev(d, "1")
    assert library.resolve_rev(d, "latest") == revs[0]["sha"] == library.resolve_rev(d, "3")
    assert library.resolve_rev(d, "-1") == revs[1]["sha"]
    assert library.resolve_rev(d, revs[2]["sha"][:8]) == revs[2]["sha"]
    for bad in ("9", "-3", "-4", "nope", "@1999-01-01"):
        # match our message: a bare IndexError is also a LookupError and would pass
        with pytest.raises(LookupError, match="revision|too far"):
            library.resolve_rev(d, bad)
    r = run_cli(home, "show", "doc.md", "--rev", "1")
    assert r.returncode == 0 and "ZEPHYR" in r.stdout
    assert run_cli(home, "show", "doc.md", "--rev", "9").returncode == 3
    r = run_cli(home, "diff", "doc.md", "1", "3")
    assert r.returncode == 0 and "-first draft mentions ZEPHYR" in r.stdout and "+third draft" in r.stdout
    assert run_cli(home, "diff", "doc.md", "1", "9").returncode == 3


def test_historical_search_finds_text_only_in_old_revision(home):
    d = _three_revisions(home)
    r = run_cli(home, "search", "zephyr")                      # current text: no match
    assert r.returncode == 3
    r = run_cli(home, "search", "zephyr", "--history")         # case-insensitive, all revisions
    assert r.returncode == 0 and "ONLY in older revisions" in r.stdout and d.id in r.stdout
    assert run_cli(home, "search", "never-written-anywhere", "--history").returncode == 3


def test_activity_counts_content_commits_not_scans_or_metadata(home):
    from lasting_plans import library
    d = _three_revisions(home)
    for _ in range(3):
        scan()                                                   # scans alone change nothing
    engine.set_metadata(d, add_tags=["Blau\n4"]) if metadata.IS_MAC else None
    library.set_labels(engine.Library().resolve("doc.md")[0], add=["infra"])
    (src(home) / "sub").mkdir()                                  # a move is not an update either
    os.rename(src(home) / "doc.md", src(home) / "sub" / "doc.md")
    scan()
    d = engine.Library().resolve("sub/doc.md")[0]
    assert len(engine.history(d)) > 3                              # there ARE non-content commits
    a = library.activity(d)
    assert a["content_revisions"] == 3 and a["updates"] == 2
    assert a["first_seen"] and a["last_content_edit"]
    assert a["created"] != a["last_content_edit"]


def test_move_is_not_a_content_revision(home):
    from lasting_plans import library
    put(src(home) / "a.md", "# a\n")
    scan()
    (src(home) / "sub").mkdir()
    os.rename(src(home) / "a.md", src(home) / "sub" / "a.md")
    scan()
    d = engine.Library().resolve("sub/a.md")[0]
    assert len(library.revisions(d)) == 1
    assert "# a" in library.text_at(d, library.resolve_rev(d, "1"))


def test_group_by_creation_date_with_unknown_bucket_last(home):
    from lasting_plans import library
    put(src(home) / "a.md", "# a\n")
    put(src(home) / "b.md", "# b\n")
    scan()
    lib = engine.Library()
    a, b = lib.resolve("a.md")[0], lib.resolve("b.md")[0]
    a.sc["created_utc"] = "2026-07-15T10:00:00Z"
    b.sc["created_utc"] = None
    b.sc["created_source"] = "unknown"
    for d in (a, b):
        engine.write_sidecar(d.root, d.sc)
    groups = library.grouped(engine.Library().docs, "month")
    assert [k for k, _ in groups][-1] == "unknown"
    assert "2026-07" in [k for k, _ in groups]
    # a commit date is never used as a creation date
    assert library.group_key(engine.Library().resolve("b.md")[0], "month") == "unknown"
    r = run_cli(home, "list", "--group-by", "month")
    assert r.returncode == 0 and r.stdout.rstrip().splitlines()[-2].startswith("unknown")


def test_labels_are_explicit_validated_and_filterable(home):
    put(src(home) / "a.md", "# a\n")
    put(src(home) / "b.md", "# b\n")
    scan()
    assert run_cli(home, "label", "a.md", "--add", "infra", "--add", "cost").returncode == 0
    assert run_cli(home, "label", "a.md", "--add", "bad\nlabel").returncode == 2
    assert run_cli(home, "label", "a.md", "--add", "").returncode == 2
    r = run_cli(home, "list", "--label", "infra")
    assert "a.md" in r.stdout and "b.md" not in r.stdout
    assert "infra" in run_cli(home, "label").stdout
    run_cli(home, "label", "a.md", "--remove", "infra")
    assert "a.md" not in run_cli(home, "list", "--label", "infra").stdout
    assert "labels:" in git(home / "Claude-plans", "log", "-1", "--format=%s")


def test_huge_multibyte_document_is_bounded_by_default(home):
    body = "# Größe — 日本語\n" + ("Zeile mit Umlauten äöü und 漢字\n" * 5000)
    put(src(home) / "big.md", body)
    scan()
    r = run_cli(home, "show", "big.md")
    assert r.returncode == 0 and len(r.stdout.splitlines()) < 80 and "more line(s)" in r.stdout
    r = run_cli(home, "search", "漢字", "--limit", "1")
    assert r.returncode == 0 and len(r.stdout) < 2000
    r = run_cli(home, "show", "big.md", "--full", "--json")
    assert json.loads(r.stdout)["content"] == body


def test_import_preview_shows_dest_and_conflict(home):
    """import --dry-run shows destination and detects divergence."""
    put(src(home) / "Plan A.md", "# Plan A\n")
    scan()
    lib = engine.Library()
    d = lib.resolve("Plan A.md")[0]

    # Dry run - no divergence yet
    can, details = engine.restore_preview(lib, d)
    assert can is True
    assert details["dest_path"] == str(src(home) / "Plan A.md")
    assert details["source_exists"] is True
    assert details["conflict"] is False

    # Modify source OUTSIDE of lasting-plans to create divergence
    # (simulating user edit or external change without scan)
    plan_path = src(home) / "Plan A.md"
    plan_path.write_text("# Plan A MODIFIED\n", encoding="utf-8")
    # Don't run scan - we want to test divergence detection against last_import_sha256

    lib = engine.Library()
    d = lib.resolve("Plan A.md")[0]

    can, details = engine.restore_preview(lib, d)
    assert can is False
    assert details["conflict"] is True
    assert details["has_diverged"] is True


def test_import_playbook_requires_force(home):
    """Playbooks require --force-playbook to import."""
    put(src(home) / "PLAYBOOK-x.md", "# PB\n")
    scan()
    lib = engine.Library()
    d = lib.resolve("PLAYBOOK-x.md")[0]
    assert d.type == "playbook"

    # Without force_playbook, should fail
    can, details = engine.restore_preview(lib, d)
    assert can is False
    assert "playbook import requires explicit" in details["error"]

    # With force_playbook, should succeed
    can, details = engine.restore_preview(lib, d, force_type="playbook")
    assert can is True


def test_import_creates_source_copy(home):
    """import with apply=True copies archive to source and updates sidecar."""
    put(src(home) / "Plan B.md", "# Plan B\n")
    scan()
    lib = engine.Library()
    d = lib.resolve("Plan B.md")[0]
    doc_id = d.id

    # Delete source to simulate sweep
    os.remove(src(home) / "Plan B.md")
    scan()
    lib = engine.Library()
    d = lib.resolve(doc_id)[0]

    # Import with apply
    result, sha = engine.import_to_source(lib, doc_id)
    assert "error" not in result
    assert result["action"] == "restored"
    assert os.path.exists(src(home) / "Plan B.md")
    with open(src(home) / "Plan B.md") as f:
        assert f.read() == "# Plan B\n"
    # sha may be None if no Git identity, but operation should succeed
    # The important thing is the file was restored


def test_import_cli_dry_run(home):
    """CLI import --dry-run shows preview."""
    put(src(home) / "Plan C.md", "# Plan C\n")
    scan()
    lib = engine.Library()
    d = lib.resolve("Plan C.md")[0]
    doc_id = d.id

    r = run_cli(home, "import", doc_id, "--dry-run")
    assert r.returncode == 0
    assert "import preview" in r.stdout
    assert "dest:" in r.stdout


def test_import_cli_playbook_requires_flag(home):
    """CLI import playbook without --force-playbook fails."""
    put(src(home) / "PLAYBOOK-y.md", "# PB\n")
    scan()
    lib = engine.Library()
    d = lib.resolve("PLAYBOOK-y.md")[0]
    doc_id = d.id

    r = run_cli(home, "import", doc_id, "--dry-run")
    assert r.returncode == 2
    assert "playbook import requires explicit" in r.stderr

    r = run_cli(home, "import", doc_id, "--dry-run", "--force-playbook")
    assert r.returncode == 0
    assert "import preview" in r.stdout


# Phase 9 tests

def test_migrate_detects_existing_git_repo(home):
    """migrate detects existing Git repo in source."""
    put(src(home) / "Plan A.md", "# Plan A\n")
    scan()
    # Initialize git in source
    subprocess.run(["git", "init"], cwd=src(home), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=src(home), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=src(home), capture_output=True)
    subprocess.run(["git", "add", "."], cwd=src(home), capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=src(home), capture_output=True)

    lib = engine.Library()
    audit, imported = engine.migrate_existing_git_repo(lib)
    assert audit["source_is_git_repo"] is True
    assert audit["has_remote"] is False
    assert len(audit["existing_files"]) >= 1
    # All files already in archive, so skipped
    assert len(audit["skipped"]) >= 1


def test_migrate_imports_missing_files(home):
    """migrate --apply imports files not yet in archive."""
    put(src(home) / "Plan A.md", "# Plan A\n")
    scan()
    # Initialize git in source
    subprocess.run(["git", "init"], cwd=src(home), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=src(home), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=src(home), capture_output=True)
    subprocess.run(["git", "add", "."], cwd=src(home), capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=src(home), capture_output=True)

    # Delete from archive but keep in source
    import os
    os.remove(src(home) / "Plan A.md")
    scan()
    lib = engine.Library()

    # Now add a NEW file to source (not in archive)
    put(src(home) / "New Plan.md", "# New Plan\n")

    lib = engine.Library()
    audit, imported = engine.migrate_existing_git_repo(lib, keep_existing=False)
    assert imported == 1
    assert len(audit["imported"]) == 1
    assert audit["imported"][0]["path"] == "New Plan.md"


def test_disaster_drill_runs(home):
    """disaster-drill runs and returns results."""
    put(src(home) / "Plan A.md", "# Plan A\n")
    scan()
    lib = engine.Library()
    results = engine.disaster_recovery_drill(lib)
    assert "git_checkout_test" in results
    assert "metadata_restore_test" in results
    assert "tags_preserved_test" in results
    assert "errors" in results
    # Should pass basic tests
    assert results["git_checkout_test"] is True
    assert results["metadata_restore_test"] is True


def test_privacy_audit_detects_patterns(home):
    """privacy-audit detects potential secrets."""
    put(src(home) / "Plan A.md", "# Plan A\n")
    put(src(home) / "Secret.md", "API_KEY = sk-1234567890abcdef1234\n")
    scan()
    lib = engine.Library()
    suspicious = engine.privacy_secrets_audit(lib)
    # Should find at least the secret file
    assert len(suspicious) >= 1
    paths = [s["path"] for s in suspicious]
    assert any("Secret.md" in p for p in paths)


def test_migrate_cli_dry_run(home):
    """CLI migrate dry-run shows preview."""
    put(src(home) / "Plan A.md", "# Plan A\n")
    scan()
    # Initialize git
    subprocess.run(["git", "init"], cwd=src(home), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=src(home), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=src(home), capture_output=True)
    subprocess.run(["git", "add", "."], cwd=src(home), capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=src(home), capture_output=True)

    r = run_cli(home, "migrate")
    assert r.returncode == 0
    assert "migration preview" in r.stdout
    assert "existing Git repo: yes" in r.stdout


def test_disaster_drill_cli(home):
    """CLI disaster-drill runs."""
    put(src(home) / "Plan A.md", "# Plan A\n")
    scan()
    r = run_cli(home, "disaster-drill")
    assert r.returncode == 0
    assert "disaster recovery drill" in r.stdout
    assert "PASS" in r.stdout


def test_privacy_audit_cli(home):
    """CLI privacy-audit runs."""
    put(src(home) / "Plan A.md", "# Plan A\n")
    put(src(home) / "Secret.md", "token = abc123\n")
    scan()
    # Need to scan again to pick up new file
    scan()
    r = run_cli(home, "privacy-audit")
    assert r.returncode == 5  # suspicious found
    assert "privacy/secrets audit" in r.stdout
    assert "suspicious" in r.stdout.lower() or "file(s)" in r.stdout


def test_duplicates_cli(home):
    """CLI duplicates command finds exact and near duplicates."""
    # Create exact duplicate content (FULL content must match for SHA256)
    # Use a longer unique content to ensure min_length is met
    dup_content = "# Duplicate Test\n\n" + "This is the exact same content for testing.\n" * 5
    put(src(home) / "Plan A.md", dup_content)
    put(src(home) / "Plan B.md", dup_content)
    # Create near-duplicate
    put(src(home) / "Plan C.md", "# Duplicate Test\n\nThis is very similar content for testing with small differences.\n" * 5)
    scan()

    # Test exact-only
    r = run_cli(home, "duplicates", "--exact-only")
    assert r.returncode == 0
    assert "EXACT duplicates" in r.stdout
    assert "1 groups" in r.stdout or "group" in r.stdout

    # Test near-duplicate (lower threshold)
    r = run_cli(home, "duplicates", "--threshold", "0.5")
    assert r.returncode == 0
    # Should find exact + near duplicates
    assert "EXACT duplicates" in r.stdout
    assert "NEAR duplicates" in r.stdout


def test_search_save_run_list_rm(home):
    """CLI search save/run/list/rm commands work."""
    put(src(home) / "Plan A.md", "# Plan A\n")
    put(src(home) / "Plan B.md", "# Plan B with cost tracker\n")
    scan()

    # Save search
    r = run_cli(home, "search", "cost tracker", "--save-as", "mysearch")
    assert r.returncode == 0
    assert "saved search 'mysearch'" in r.stdout

    # List searches
    r = run_cli(home, "search-list")
    assert r.returncode == 0
    assert "mysearch" in r.stdout

    # Run saved search
    r = run_cli(home, "search-run", "mysearch")
    assert r.returncode == 0
    assert "cost tracker" in r.stdout

    # Delete saved search
    r = run_cli(home, "search-rm", "mysearch")
    assert r.returncode == 0
    assert "deleted saved search 'mysearch'" in r.stdout

    # Verify deleted
    r = run_cli(home, "search-list")
    assert "mysearch" not in r.stdout
