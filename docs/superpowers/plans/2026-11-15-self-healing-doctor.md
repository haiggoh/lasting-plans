# One Mirrored Archive + Self-Healing Doctor (lasting-plans 2.0.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (native execution: the executor does every task, then one final whole-branch review). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The backup looks exactly like the original (one archive mirroring `~/.claude/plans`, playbooks inside `_playbooks/`), and Lasting Plans never puts routine maintenance on the user's plate: a background auto-repair resolves every foreseeable failure, and the SessionStart banner speaks only when a problem survived repeated automatic repair, or for a true emergency.

**Architecture:** `Library` gets ONE archive root whose paths equal source-relative paths. `plan`/`playbook` stays as sidecar metadata (search/filter label), never a location. A self-running migration (`migrate.py`) merges the v1 playbook archive into the plan archive with full history, relocates every document to its source path, and retires the old archive (kept, never deleted). A new `repair.py` turns doctor checks + scan pending/errors into keyed issues, applies a safe, idempotent fixer per kind (the migration is one such kind), and keeps a persistence ledger that decides when the banner may speak. Watcher and SessionStart hook both call `repair.run()`.

**Tech Stack:** Python 3 stdlib, Git CLI (≥2.30), pytest (`pytest -n auto` for full runs), launchd.

**Spec:** User decisions, this session (2026-11-15):
1. "not putting tasks on the user's plate unless it's an emergency … routine pending tasks … done via a script in the background without any user action."
2. Banner only "if stuck and the doctor script has already been run automatically and the issue still isn't resolved"; the script should "resolve any kind of error of this type … safe enough to be run without explicit user permission at any time."
3. Fix the case-only-rename bug in the same release; folder spelling: "whichever works best with git" → follow the SOURCE spelling everywhere (`~/.claude/plans`'s own Git repo indexes `_playbooks/`).
4. Layout: "One mirrored archive" — `~/Claude-plans` mirrors `~/.claude/plans`, playbooks in `_playbooks/`, type kept only as a label, `~/Claude-playbooks` history merged in, old folder + GitHub repo left untouched and marked retired, never deleted.
5. "One combined release" → 2.0.0.

## Global Constraints

- Every fixer and the migration are **non-destructive** (nothing removed that Git history or a backup cannot restore; anything overwritten first copied to `<state_dir>/repair-backups/<UTC-stamp>/`) and **idempotent** (re-running after a crash at any step converges).
- All repair and migration run under `engine.scan_lock()`; `engine.Busy` ⇒ skip this pass silently, no attempt counted.
- Visible, not hidden: every fix/migration step is logged (watcher log + `<state_dir>/repairs.jsonl`) and shown in `lasting-plans doctor` and `status`. Native opt-out: setting `auto_repair` (default `true`).
- Config: new `archive_root` (default `~/Claude-plans`), `remote` (single URL or null), `auto_repair: bool = True`, `alert_after_hours: int = 24` (min 1), `alert_min_attempts: int = 3` (min 1), `layout: int` (absent/1 = v1, 2 = migrated), `retired_archives: list[str]`. Legacy `plans_root` → `archive_root`, `playbooks_root` → `retired_archives`, `remotes.plan` → `remote` (read-compatible; written only by the migration).
- Never create an archive folder that holds no documents; prune folders emptied by a move.
- Alert copy (exact): `⚠ %d problem(s) auto-repair could not fix (since %s) — details: \`lasting-plans doctor\``, date `YYYY-MM-DD`.
- Hook always exits 0. Every script/subcommand supports `--help` and runs nothing with it.
- Version 2.0.0 on EVERY surface: `VERSION`, `.claude-plugin/plugin.json`, `lib/lasting_plans/__init__.py` (currently drifted at 1.2.2), `CHANGELOG.md`.
- Tests use the synthetic-HOME `home` fixture; case tests `pytest.skip` when the tmp FS is case-sensitive.

## Authority & preflight (executor = this session)

| Action | Without asking? |
|---|---|
| Edit/commit on `feat/self-healing-doctor` in `~/.wt/lp-self-heal` | yes |
| rtc-ship: merge to `main`, tag `v2.0.0`, release, `claude plugin update lasting-plans` | yes (user chose a combined release) |
| Migrate the live `~/Claude-plans` / `~/Claude-playbooks` | yes, only after Task 9 Step 1 backup receipt |
| Fast-forward push to `haiggoh/Claude-plans`; one `RETIRED.md` commit pushed to `haiggoh/Claude-playbooks` | yes (the existing auto-push behaviour) |
| Force-push, move a published tag, delete any archive folder/repo, archive the GitHub repo | no |

Phase 0 (before Task 1): worktree `git status --porcelain` empty; `git ls-remote --tags origin v2.0.0` empty; `pytest -n auto tests` green on the branch base — record the pass count.

## Review Focus

1. **The old 1.3.0 watcher scanning during/after migration** — it reads `playbooks_root` and would rebuild the split. The migration must first restage + restart the watcher on 2.0.0 code (`scheduler.install`), then migrate under `scan_lock`. Test in Task 3 (`test_migration_restages_watcher_first`, scheduler mocked: install called before any git write).
2. **Case-only rename while content also changed** — one move + one update, never a "(2)" copy. Test in Task 1.
3. **Two v1 docs claiming the same source path, or v1 archive paths that collide across the two repos** — the migration keeps both (second gets `_free_relpath`), logs it, never overwrites. Test in Task 3.
4. **An issue that disappears then returns** — the ledger resets `first_seen`, so a recurrence does not alert instantly. Test in Task 5.
5. **Corrupt `repair-state.json` or a crash halfway through migration** — ledger backed up and reset; migration re-run converges to the same tree. Tests in Tasks 3 and 5.

---

### Task 1: Case-safe Git commits

**Files:** Modify `lib/lasting_plans/gitrepo.py` (`commit_paths`, new `index_case`, new `move_path`); Test: `tests/test_case_rename.py` (create).

**Interfaces — Produces:**
- `gitrepo.index_case(root: str, paths: list[str]) -> list[str]`: each path rewritten to the spelling in Git's index, else the on-disk spelling (per-component `os.listdir` casefold match), else unchanged.
- `gitrepo.move_path(root: str, old: str, new: str) -> None`: `git mv`, going via `<new>.lp-case-tmp` when `old.casefold() == new.casefold()`; creates parent dirs; then removes now-empty parent dirs of `old` up to root.

- [ ] Step 1: failing tests: `test_commit_paths_accepts_wrong_case` (tracked `_PLAYBOOKS/A.md` modified; `commit_paths(root, ["_playbooks/A.md"], "m")` → SHA, status clean); `test_move_path_case_only` (`_PLAYBOOKS/A.md` → `_playbooks/A.md`: `git ls-files` = `_playbooks/A.md`, `os.listdir(root)` contains `_playbooks`, not `_PLAYBOOKS`).
- [ ] Step 2: `pytest tests/test_case_rename.py -v` → FAIL.
- [ ] Step 3: implement; `commit_paths` maps `paths` through `index_case` before `add`/`commit --only`.
- [ ] Step 4: same command → PASS.
- [ ] Step 5: commit by path: `fix(git): case-safe commits and moves`.

### Task 2: One archive whose paths mirror the source

**Files:** Modify `lib/lasting_plans/config.py`, `engine.py`, `library.py`, `remote.py`, `watch.py`, `cli.py`, `classify.py` (callers only); Tests: update `tests/test_engine.py` for one root; extend `tests/test_case_rename.py`.

**Interfaces — Produces:**
- `Library.root: str` (replaces `Library.roots`); `Document.root == Library.root` always; `doc.type` stays (from sidecar).
- `config.load()` returns `archive_root`, `remote`, `layout`, `retired_archives`, resolving legacy keys as in Global Constraints.
- Import/update/move set `archive_relpath = source_relpath` (current source spelling). The only exceptions are the existing ones: the name is taken by another live doc (`_free_relpath`, casefold-compared), and source-edit conflict copies.
- `_scan_source`: a doc whose `source_relpath` is absent but casefold-equals a present `rel` is a **case-only rename** → `_handle_case_rename(lib, doc, rel, res)`: update `source_relpath`/`source_history`, `gitrepo.move_path` the archive file to `rel`, commit, event `("moved", id, rel, "case-only rename: old -> new")`, then continue the normal hash comparison for that doc.
- Moves (`_handle_move`) relocate the archive file to the new source path via `gitrepo.move_path` (prunes emptied folders).
- `reclassify(lib, doc, new_type)` becomes a sidecar-only type change (no file move), `type_reason="reclassified by user"`, returns `sha`.
- `_sync_folder_tags`: one root; record keys deduped casefold, keeping the source spelling; still never creates a folder.
- `remote.py`: one remote (`cfg["remote"]`); `status --verify` / `push` drop the `plan|playbook` kind argument but accept and ignore it with a deprecation note on stderr.
- CLI: `--type plan|playbook` filters keep working (label filter); `settings` shows new keys; `remote set URL` (legacy `remote set plan URL` accepted).

- [ ] Step 1: failing tests: `test_playbook_archived_at_source_path` (`_playbooks/P.md` with playbook text → `archive_root/_playbooks/P.md`, sidecar `type == "playbook"`); `test_case_only_folder_rename_is_a_clean_move` (import `_PLAYBOOKS/P.md`, rename source dir to `_playbooks`, scan → no pending/errors, archive status clean, `git ls-files` = `_playbooks/P.md` only, no `* (2).md`); `test_case_rename_with_content_change` (move + update events, no "(2)"); `test_move_prunes_empty_folder`; `test_reclassify_is_label_only` (file path unchanged, type changed, one commit); `test_folder_tags_never_create_folders`; `test_legacy_config_keys_resolve`.
- [ ] Step 2: run them → FAIL.
- [ ] Step 3: implement; adapt existing `test_engine.py` cases that assert two roots to the one-root model (assertions on location become assertions on `type`).
- [ ] Step 4: `pytest -n auto tests` → PASS.
- [ ] Step 5: commit by path: `feat!: one archive mirroring the source layout; type is a label`.

### Task 3: Self-running migration from the v1 two-archive layout

**Files:** Create `lib/lasting_plans/migrate.py`; Test: `tests/test_migrate.py` (create; fixture helper `make_v1_layout(home, ...)` builds two v1 repos by hand with git, incl. sidecars, `folders.json` in both, a staged-but-uncommitted wedge like the live one, and a `_PLAYBOOKS/X (2).md`).

**Interfaces — Produces:** `migrate.needed(cfg) -> bool` (`layout != 2` and a v1 playbook root exists with a `.git`); `migrate.run(lib, dry_run: bool = False) -> list[str]` (step log lines). Steps, each idempotent:
1. `scheduler.install(LIB)` when supported+enabled, so no 1.x watcher runs again (Review Focus 1).
2. Back up: `git bundle create <state_dir>/repair-backups/<stamp>/{plans,playbooks}.bundle --all`, plus a copy of each repo's `.lasting-plans/`; `git bundle verify` must pass or abort.
3. In each v1 repo, commit any dirty `.lasting-plans/**` and document paths (`commit_paths`, case-safe) — `"pre-migration: commit pending state"`.
4. In the plan archive: `git fetch <playbooks_root> HEAD` + `git merge --allow-unrelated-histories --no-edit -m "migrate: merge playbook archive (history kept)"`; on conflict, only `.lasting-plans/folders.json` is expected → union of both tag maps (casefold-deduped), commit; any OTHER conflicting path → keep the plan-side file, write the playbook-side one to `_free_relpath`, record it (Review Focus 3).
5. For every sidecar whose source still exists: `gitrepo.move_path` archive file → `source_relpath` (drops "(2)" suffixes and stale case), update sidecar; one commit `"migrate: archive paths now mirror the source"`. Docs whose source is gone keep their archive path.
6. Write `RETIRED.md` in the old playbook archive ("merged into <archive_root> at <sha> on <date>; kept read-only — Lasting Plans no longer writes here") and commit; if it had a remote, push that one commit (plain push, never force).
7. Config: `archive_root` = old `plans_root`, `retired_archives += [playbooks_root]`, `remote` = old `remotes.plan`, `layout = 2`; keep the legacy keys' values under `legacy` for audit.
`dry_run=True` prints the plan of steps 3–7 and writes nothing (archive status + config byte-identical).

- [ ] Step 1: failing tests: `test_migration_merges_history` (every v1 playbook doc's `git log --follow` in the new root reaches its v1 first commit); `test_migration_mirrors_source` (`archive_root/_playbooks/` lists exactly the source's 10-style fixture files; no `(2)`, no `_PLAYBOOKS`); `test_migration_restages_watcher_first`; `test_migration_collision_keeps_both`; `test_migration_rerun_converges` (crash injected after step 4 via monkeypatch → second `run` ends in the same tree as a clean run); `test_migration_dry_run_writes_nothing`; `test_retired_note_written_old_repo_untouched_otherwise` (old repo: only `RETIRED.md` added, no file removed).
- [ ] Step 2: run → FAIL. Step 3: implement. Step 4: `pytest tests/test_migrate.py -v` → PASS.
- [ ] Step 5: commit by path: `feat(migrate): v1 two archives → one mirrored archive, history kept`.

### Task 4: Fixers for every foreseeable failure class

**Files:** Create `lib/lasting_plans/repair.py` (fixers); Test: `tests/test_repair.py` (create).

**Interfaces — Produces:** `Issue = dict(key, kind, path, detail, severity: "routine"|"emergency")`; `collect_issues(lib, res: ScanResult | None) -> list[Issue]` (key = `f"{kind}:{path}"`; `res=None` ⇒ `engine.last_run()`); `FIXERS: dict[str, Callable[[Library, Issue, str], tuple[bool, str]]]` (third arg = backup dir).

| kind | detected from | fixer (test `test_fix_<kind>`) |
|---|---|---|
| `migration_pending` | `migrate.needed(cfg)` | `migrate.run(lib)` |
| `uncommitted` | pending `uncommitted:` | `commit_paths` doc + sidecar |
| `no_identity` | doctor identity ✗ | repo-LOCAL `user.name`/`user.email` from `git config --global`, else `Lasting Plans` / `lasting-plans@localhost` |
| `archive_missing` | doctor "every archive document present" ✗ / pending "removed by hand" | `HEAD:<path>` exists → `git checkout HEAD -- <path>`; else an unclaimed file with `sha256 == archive_sha256` → repoint sidecar, commit; else unfixed |
| `sidecar_corrupt` | `lib.corrupt` | back up, `git checkout HEAD -- <sidecar>`; unfixed if HEAD lacks it |
| `type_mismatch` | `engine.type_mismatches` | label-only `reclassify`, then `type_reason = "auto-reclassified by repair"` (a user's own reclassify stays sticky) |
| `empty_folder` | archive dir with no docs and no tracked files | `os.rmdir` (only if truly empty) |
| `watcher_down` | supported, enabled, not running | `scheduler.install(LIB)` |
| `transient` | pending "will retry", remote `pending remote` | none (`(False, "waits for next pass")`) |
| `emergency` | git missing; archive root not a repo after `ensure_repo` | none, `severity="emergency"` |

- [ ] Step 1: failing tests per row (build broken state in fixture → fixer → `fixed is True` and the matching doctor check passes; `transient`/`emergency` → `fixed is False`). Step 2: run → FAIL. Step 3: implement. Step 4: `pytest tests/test_repair.py -v` → PASS. Step 5: commit by path: `feat(repair): safe fixers for every known failure class`.

### Task 5: Repair loop, ledger, alert policy, settings

**Files:** Modify `repair.py`, `config.py`; Test: `tests/test_repair.py`.

**Interfaces — Produces:**
- `repair.run(lib, res=None, dry_run=False) -> dict(fixed: list, remaining: list, skipped: bool)`: under `scan_lock` (Busy ⇒ `skipped=True`, ledger untouched); fixer order `migration_pending, sidecar_corrupt, no_identity, archive_missing, uncommitted, type_mismatch, empty_folder, watcher_down`; anything fixed ⇒ one more scan (lock-free inner scan) and re-collect.
- Ledger `<state_dir>/repair-state.json`: `{key: {kind, path, detail, severity, first_seen_utc, attempts, last_attempt_utc}}`; resolved keys removed and journaled to `repairs.jsonl` as `{"utc", "key", "event": "fixed"|"resolved", "note"}`.
- `repair.alerts(now: float | None = None) -> list[dict]`: `severity == "emergency"` OR (`attempts >= alert_min_attempts` AND age ≥ `alert_after_hours`).
- `repair.recent_fixes(days: int = 7) -> list[dict]`.

- [ ] Step 1: failing tests: `test_run_fixes_and_journals`; `test_alert_needs_age_and_attempts` (5 attempts / 1 h ⇒ none; 3 attempts / 25 h ⇒ one); `test_emergency_alerts_immediately`; `test_resolved_issue_resets_first_seen`; `test_busy_lock_skips_without_counting`; `test_transient_never_alerts_early`; `test_corrupt_ledger_is_backed_up_and_reset`; `test_dry_run_changes_nothing`; `test_settings_parse` (`auto_repair off` → False; `alert_after_hours 0` → ConfigError).
- [ ] Step 2: run → FAIL. Step 3: implement. Step 4: PASS. Step 5: commit by path: `feat(repair): ledger, alert policy, auto_repair setting`.

### Task 6: Wire into watcher, hook, CLI; docs

**Files:** `lib/lasting_plans/watch.py`, `hooks/session-start.py`, `lib/lasting_plans/cli.py`, `README.md`, `skills/lasting-plans/SKILL.md`, `CHANGELOG.md`; Test: `tests/test_repair.py`.

- `watch._run_scan`: after the scan, if `auto_repair` → `repair.run(lib, res)`; log `repair: fixed <key> — <note>` per fix and the remaining count.
- `session-start.py`: replace lines 57–58. With `auto_repair` → `repair.run(lib, res)`, note only `repair.alerts()` in the exact alert copy; the watcher-install failure and the generic `except` are recorded as ledger issues (`watcher_down`, `hook_exception`) instead of printed. With `auto_repair` false → the old `⚠ N item(s) pending — run \`lasting-plans doctor\`` line verbatim (user opted out). The first-run "set up" note names one archive.
- CLI: `repair [--dry-run] [--json]` (exit 0 nothing remaining, 5 otherwise); `migrate [--dry-run]` (same as the fixer, for visibility); `doctor` appends an "auto-repair" section (last run, remaining with first-seen/attempts, fixes in the last 7 days); `status` adds `  ✓ auto-repaired N issue(s) in the last 7 days` when N>0.
- Docs: README layout section rewritten (one mirrored archive, type = label, migration + retired folder explained, auto-repair + opt-out); SKILL.md Health row ("automatic — `lasting-plans repair` runs it now; the banner speaks only when it could not fix something"); CHANGELOG `## 2.0.0` entry flagging the layout change as BREAKING.

- [ ] Step 1: failing tests: `test_hook_silent_when_repair_fixes` (subprocess-run the hook in the fixture with a planted `uncommitted` wedge → stdout has no `pending` and no `⚠`); `test_hook_alerts_when_stuck` (planted ledger entry 25 h / 3 attempts → stdout contains `auto-repair could not fix`); `test_hook_migrates_v1_silently` (v1 fixture → one hook run → `layout == 2`, no `⚠`); `test_hook_help_runs_nothing`; `test_cli_repair_dry_run_exit_code`.
- [ ] Step 2: run → FAIL. Step 3: implement. Step 4: `pytest -n auto tests` → all PASS, count ≥ Phase-0 count + new tests; hand-run `hooks/session-start.py --help`, `bin/lasting-plans repair --help`, `bin/lasting-plans migrate --help` → usage only.
- [ ] Step 5: commit by path.

### Task 7: Version 2.0.0 everywhere + consistency test

**Files:** `VERSION`, `.claude-plugin/plugin.json` (also update its `description` to "one local, Git-versioned archive (~/Claude-plans)"), `lib/lasting_plans/__init__.py`, `CHANGELOG.md`; Test: `tests/test_version_consistency.py` (create: the three agree and CHANGELOG has `## 2.0.0`).

- [ ] Write test → run (FAIL on the 1.2.2 drift) → bump → PASS → commit `chore: 2.0.0 (aligns drifted __version__)`.

### Task 8: Ship

- [ ] One fresh whole-branch reviewer (most capable model) on `git diff origin/main...`; address findings.
- [ ] run-to-completion `ship` (rtc-ship + `rtc-ship.json`): gates, merge to `main`, tag `v2.0.0`, release, `claude plugin update lasting-plans`. Receipts: `git ls-remote --tags origin v2.0.0` prints a SHA; installed version reads 2.0.0.

### Task 9: Live migration + dogfood (live state — backup first)

- [ ] Step 1 — backup receipt, independent of the migration's own: `git bundle create` for `~/Claude-plans` and `~/Claude-playbooks` (`--all`) into `~/Claude-plans-premigration-2026-11-15/`, plus `cp -R` of both `.lasting-plans/` dirs (the live sidecars are uncommitted); `git bundle verify` OK for both.
- [ ] Step 2: INSTALLED `lasting-plans migrate --dry-run` → lists the 10 wedged playbook docs, the merge, the relocations; `git status` of both repos unchanged afterwards.
- [ ] Step 3: INSTALLED `lasting-plans repair` → exit 0.
- [ ] Step 4 — known-bad discriminants: `~/Claude-plans/_playbooks/` holds every file in `~/.claude/plans/_playbooks/` (`diff -rq` on documents shows no missing files); `git -C ~/Claude-plans ls-files | grep -c "_PLAYBOOKS/\| (2)\.md"` = 0 unless a listed collision; both repos `git status --porcelain` empty; `~/Claude-playbooks/RETIRED.md` exists, and no file was removed there (`git diff --stat <pre-sha> HEAD` shows only the addition); `git ls-remote` shows the Claude-plans remote at the local HEAD.
- [ ] Step 5: `lasting-plans doctor` → every check ✓, with the auto-repair section listing what it did.
- [ ] Step 6 — dogfood the banner: run the INSTALLED `hooks/session-start.py` twice → the second run prints nothing.
