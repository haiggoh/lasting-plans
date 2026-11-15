# Self-Healing Doctor + Quiet Banner (lasting-plans 1.4.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (native execution: the executor does every task, then one final whole-branch review). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lasting Plans never puts routine maintenance on the user's plate: a background auto-repair resolves every foreseeable failure class, and the SessionStart banner speaks only when a problem has survived repeated automatic repair (or is a true emergency).

**Architecture:** A new `repair.py` turns doctor checks + last-scan pending/errors into keyed *issues*, applies a safe, idempotent fixer per issue kind, re-scans, and keeps a persistence ledger (`repair-state.json`) plus an append-only journal (`repairs.jsonl`). The launchd watcher and the SessionStart hook both call `repair.run()`; the hook prints only `repair.alerts()`. The root-cause bug (case-only source renames wedging Git commits on case-insensitive APFS) is fixed in `engine.py`/`gitrepo.py`, and a fixer un-wedges archives already damaged by it.

**Tech Stack:** Python 3 stdlib, Git CLI, pytest (`pytest -n auto` for full runs), launchd.

**Spec:** User request 2026-11-15 (this session): "not putting tasks on the user's plate unless it's an emergency … routine pending tasks … done via a script in the background without any user action"; answers: banner only "if stuck and the doctor script has already been run automatically and the issue still isn't resolved"; the script should "resolve any kind of error of this type … safe enough to be run without explicit user permission at any time"; fix the case-rename bug in the same release.

## Global Constraints

- Every fixer is **non-destructive**: nothing is deleted that Git history or a backup copy cannot restore; anything overwritten is first copied to `<state_dir>/repair-backups/<UTC-stamp>/`.
- Every fixer is **idempotent** and safe to run concurrently with a scan (all repair runs under `engine.scan_lock()`; `engine.Busy` ⇒ skip this pass silently).
- Visible, not hidden (no-hidden-changes): every applied fix is logged (watcher log + `repairs.jsonl`) and surfaced in `lasting-plans doctor` and `status`; `auto_repair` setting (default `true`) is the native opt-out.
- New settings: `auto_repair: bool = True`, `alert_after_hours: int = 24` (min 1), `alert_min_attempts: int = 3` (min 1).
- Alert copy (exact): `⚠ %d problem(s) auto-repair could not fix (since %s) — details: \`lasting-plans doctor\``, date as `YYYY-MM-DD`.
- Hook must still always exit 0 and never block a session.
- Version 1.4.0 on EVERY surface: `VERSION`, `.claude-plugin/plugin.json`, `lib/lasting_plans/__init__.py` (currently drifted at 1.2.2), `CHANGELOG.md`.
- Tests run under the existing synthetic-HOME `home` fixture; macOS tmp dirs are case-insensitive, so case tests reproduce the real bug. Case tests must `pytest.skip` when the tmp FS is case-sensitive.

## Authority & preflight (executor = this session)

| Action | Allowed without asking? |
|---|---|
| Edit/commit on `feat/self-healing-doctor` in `~/.wt/lp-self-heal` | yes |
| Merge to `main`, tag `v1.4.0`, release, `claude plugin update` via rtc-ship | yes (user asked for the fix in a release) |
| Run repair against live `~/Claude-plans` / `~/Claude-playbooks` | yes, **only after** Task 7 Step 1 backup receipt exists |
| Force-push, move a published tag, delete archive files outside a fixer | no |

Phase 0 (before Task 1): `git -C ~/.wt/lp-self-heal status --porcelain` empty; `git ls-remote --tags origin v1.4.0` empty (tag free); full suite green on the branch base (`pytest -n auto tests`), record the pass count.

## Review Focus

1. **Case-only rename while content also changed** — must be one move + one update, never a "(2)" copy. Test in Task 1.
2. **Repair racing the watcher's scan** — repair must take `scan_lock`; a held lock ⇒ silent skip, no ledger attempt counted. Test in Task 3.
3. **An issue that disappears then returns** — the ledger resets `first_seen` when an issue resolves, so a fresh recurrence does not alert instantly. Test in Task 3.
4. **Unfixable-but-transient issues (offline remote push, file still changing)** — never alert before `alert_after_hours`, even with many attempts. Test in Task 3.
5. **Corrupt `repair-state.json`** — treated as empty ledger (backed up), never crashes hook or watcher. Test in Task 3.

---

### Task 1: Case-only renames never wedge Git (root-cause fix)

**Files:**
- Modify: `lib/lasting_plans/gitrepo.py` (`commit_paths`, new `index_case`)
- Modify: `lib/lasting_plans/engine.py` (`_scan_source`, `_free_relpath`, new `_handle_case_rename`)
- Test: `tests/test_case_rename.py` (create)

**Interfaces:**
- Produces: `gitrepo.index_case(root: str, paths: list[str]) -> list[str]` — each path rewritten to the spelling Git's index (else on-disk real case) uses; unknown paths returned unchanged.
- Produces: `engine.real_case(root: str, rel: str) -> str` — on-disk spelling of `rel`, walking `os.listdir` per component; returns `rel` unchanged for missing components.

- [ ] **Step 1: Write failing tests** in `tests/test_case_rename.py` (reuse fixture helpers by importing from `tests/test_engine.py` or copying `home`/`put`/`scan`/`git`):
  - `test_case_only_folder_rename_is_a_clean_move`: import `_PLAYBOOKS/P.md` (playbook text), `os.rename` the source dir to `_playbooks`, scan → `res.pending == []`, `res.errors == []`, archive `git status --porcelain` empty, no file matching `* (2).md` in archive, sidecar `source_relpath == "_playbooks/P.md"`, `archive_relpath == "_playbooks/P.md"`, `git ls-files` lists `_playbooks/P.md` and NOT `_PLAYBOOKS/P.md`, and `os.listdir(archive)` contains `_playbooks` (the case change reaches the archive: one spelling everywhere — user decision 2026-11-15, the source folder's own Git repo already indexes `_playbooks/`).
  - `test_case_only_rename_with_content_change`: same, plus content edited before the scan → events kinds contain `"moved"` and `"updated"` (whatever kind `_handle_update` emits today), no "(2)".
  - `test_commit_paths_accepts_wrong_case`: tracked `_PLAYBOOKS/A.md`, modify it, `commit_paths(root, ["_playbooks/A.md"], "m")` returns a SHA and leaves status clean.
- [ ] **Step 2: Run** `pytest tests/test_case_rename.py -v` → all three FAIL (pathspec error / "(2)" present).
- [ ] **Step 3: Implement.** `commit_paths` maps `paths` through `index_case` before `add`/`commit --only`. `index_case` = casefold lookup over `git ls-files -z` (and, for untracked paths, `engine`-free on-disk real case done locally in gitrepo). In `_scan_source`, when `by_src.get(rel)` is None, look up `rel.casefold()` in a casefold map of sidecar `source_relpath`s whose exact path is absent from `present`; on hit call `_handle_case_rename(lib, doc, rel, res)` (update `source_relpath`, append `source_history`; when the archive path mirrors the old source path case-insensitively, re-case it to match `rel` with `git mv` via a temp name (`git mv A A.lp-case-tmp && git mv A.lp-case-tmp a`, which also re-cases the directory entry on APFS), set `archive_relpath`, `write_sidecar`, commit old + new archive path + sidecar, event `("moved", id, new_arel, "case-only rename: old -> new")`), remove the doc from `orphans`, then fall through to the normal hash comparison for that doc. `_free_relpath`: compare `taken` by casefold.
- [ ] **Step 4: Run** `pytest tests/test_case_rename.py tests/test_engine.py -v` → PASS.
- [ ] **Step 5: Commit** `git add lib/lasting_plans/gitrepo.py lib/lasting_plans/engine.py tests/test_case_rename.py && git commit -m "fix: case-only source renames no longer wedge archive commits"`

### Task 2: Fixers for every foreseeable failure class

**Files:**
- Create: `lib/lasting_plans/repair.py` (fixers section)
- Test: `tests/test_repair.py` (create)

**Interfaces:**
- Consumes: `gitrepo.index_case`, `engine.real_case`, `engine.reclassify`, `engine.type_mismatches`, `engine.scan_lock`, `scheduler.install/state`.
- Produces: `Issue = dict(key: str, kind: str, path: str, detail: str, severity: "routine"|"emergency")`; `FIXERS: dict[str, Callable[[engine.Library, Issue, str], tuple[bool, str]]]` (third arg = backup dir); each returns `(fixed, note)`.

Issue kinds and fixer contract (one test each, named `test_fix_<kind>`):

| kind | detected from | fixer |
|---|---|---|
| `case_wedge` | working sidecar vs `git show HEAD:<sidecar>`: `source_relpath` differs only by case and `archive_relpath` differs | back up working sidecar; take the HEAD `archive_relpath`, drop the spurious ` (N)` suffix, re-case it to the new source spelling (same `git mv`-via-temp as Task 1), keep new `source_relpath`/`source_history`; `commit_paths` sidecar + every archive path involved. Test: build the exact damaged state the live archive has (`_PLAYBOOKS/X (2).md` staged, sidecar staged with `_playbooks/... (2)`) → after fix status clean, `git ls-files` = `_playbooks/X.md`, no "(2)", no `_PLAYBOOKS/`. |
| `uncommitted` | pending reason starts `uncommitted:` | `commit_paths` the doc + sidecar (now case-safe). |
| `no_identity` | doctor "has Git identity" ✗ / pending "no Git identity" | set repo-LOCAL `user.name`/`user.email` from `git config --global`, else `Lasting Plans` / `lasting-plans@localhost`. |
| `archive_missing` | doctor "every archive document present" ✗, or pending "removed by hand" | if `HEAD:<path>` exists → `git checkout HEAD -- <path>`; else find an unclaimed file in the root with `sha256 == archive_sha256` → point sidecar at it and commit. Else unfixed. |
| `sidecar_corrupt` | `lib.corrupt` | copy corrupt file to backup dir, `git checkout HEAD -- <sidecar>`; unfixed if HEAD lacks it. |
| `type_mismatch` | `engine.type_mismatches` | `engine.reclassify` then set `type_reason = "auto-reclassified by repair"` (not sticky like the user's). |
| `watcher_down` | `scheduler.supported()` and not `state()["running"]` and `scheduler_enabled` | `scheduler.install(LIB)`. |
| `transient` | pending "will retry", remote `pending remote` | no fixer (returns `(False, "waits for next pass")`). |
| `emergency` | git missing; archive root not a repo after `ensure_repo` | no fixer; `severity="emergency"`. |

- [ ] **Step 1: Write the failing tests** above (each builds its broken state in the `home` fixture, calls `repair.FIXERS[kind](lib, issue, backup_dir)`, asserts `fixed is True` and the doctor check now passes; `transient`/`emergency` assert `fixed is False`).
- [ ] **Step 2: Run** `pytest tests/test_repair.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** fixers + `collect_issues(lib, res: engine.ScanResult | None) -> list[Issue]` (key = `f"{kind}:{path}"`; `res=None` ⇒ use `engine.last_run()` items).
- [ ] **Step 4: Run** `pytest tests/test_repair.py -v` → PASS.
- [ ] **Step 5: Commit** `git add lib/lasting_plans/repair.py tests/test_repair.py && git commit -m "feat(repair): safe fixers for every known failure class"`

### Task 3: Repair loop, persistence ledger, alert policy, settings

**Files:**
- Modify: `lib/lasting_plans/repair.py` (run/ledger/alerts)
- Modify: `lib/lasting_plans/config.py` (three new keys, types, `parse_value`, minimums)
- Test: `tests/test_repair.py`

**Interfaces:**
- Produces: `repair.run(lib, res=None, dry_run=False) -> dict(fixed: list[Issue+note], remaining: list[Issue+first_seen_utc+attempts], skipped: bool)`; under `scan_lock` (Busy ⇒ `skipped=True`, ledger untouched); applies fixers in order `case_wedge, sidecar_corrupt, no_identity, archive_missing, uncommitted, type_mismatch, watcher_down`; if anything fixed → `engine.scan` once more (inside the same lock: call the lock-free inner, or release then re-scan) and re-collect.
- Produces: `repair.alerts(now: float | None = None) -> list[dict]` reading the ledger + config: `severity == "emergency"` OR (`attempts >= alert_min_attempts` AND age ≥ `alert_after_hours`).
- Produces: `repair.recent_fixes(days: int = 7) -> list[dict]` from `repairs.jsonl`.
- Ledger `<state_dir>/repair-state.json`: `{key: {kind, path, detail, severity, first_seen_utc, attempts, last_attempt_utc}}`; resolved keys removed and journaled `{"utc", "key", "event": "resolved"|"fixed", "note"}`.

- [ ] **Step 1: Failing tests:** `test_run_fixes_and_journals`, `test_alert_needs_age_and_attempts` (attempts=5, age 1h ⇒ none; age 25h attempts 3 ⇒ one), `test_emergency_alerts_immediately`, `test_resolved_issue_resets_first_seen` (Review Focus 3), `test_busy_lock_skips_without_counting` (Review Focus 2), `test_transient_never_alerts_early` (Review Focus 4), `test_corrupt_ledger_is_backed_up_and_reset` (Review Focus 5), `test_dry_run_changes_nothing` (archive `git status` + ledger byte-identical before/after), `test_settings_parse` (`auto_repair off` → False; `alert_after_hours 0` → ConfigError).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_repair.py -v` → PASS.
- [ ] **Step 5: Commit** `git add lib/lasting_plans/repair.py lib/lasting_plans/config.py tests/test_repair.py && git commit -m "feat(repair): ledger, alert policy, auto_repair setting"`

### Task 4: Wire into watcher, hook, CLI; docs

**Files:**
- Modify: `lib/lasting_plans/watch.py` (`_run_scan`: after scan, if `cfg["auto_repair"]` → `repair.run(lib, res)`; log each fix `repair: fixed <key> — <note>` and remaining count)
- Modify: `hooks/session-start.py:57-58` (replace pending note: if `auto_repair` → `repair.run(lib, res)`; note only `repair.alerts()` with the exact Global-Constraints copy; `auto_repair` false ⇒ the old `⚠ N item(s) pending — run \`lasting-plans doctor\`` line verbatim, since the user opted out of self-repair). Watcher-install failure and the generic `except` note are recorded as ledger issues (`watcher_down`, `hook_exception`) instead of printed, and surface only via `alerts()`.
- Modify: `lib/lasting_plans/cli.py` — new `repair [--dry-run] [--json]` subcommand (exit 0 nothing remaining, 5 otherwise); `doctor` appends an "auto-repair" section (last run, remaining with first-seen/attempts, fixes in last 7 days); `status` adds `  ✓ auto-repaired N issue(s) in the last 7 days` when N>0; `settings` show lists the new keys (automatic via DEFAULTS).
- Modify: `README.md`, `skills/lasting-plans/SKILL.md` (Health row: "automatic — `lasting-plans repair` to run it now; banner speaks only when it could not fix something"), `CHANGELOG.md` (1.4.0 entry).
- Test: `tests/test_repair.py` — `test_hook_silent_when_repair_fixes` (run `hooks/session-start.py` as a subprocess in the fixture with a planted `case_wedge` → stdout has no `pending` and no `⚠`), `test_hook_alerts_when_stuck` (planted ledger entry age 25h attempts 3 → stdout contains `auto-repair could not fix`), `test_hook_help_runs_nothing`, `test_cli_repair_dry_run_exit_code`.

- [ ] **Step 1: Write failing tests.** **Step 2: Run → FAIL.** **Step 3: Implement.** **Step 4:** `pytest -n auto tests` → all PASS, count ≥ Phase-0 count + new tests. Also run `hooks/session-start.py --help` and `bin/lasting-plans repair --help` by hand → usage printed, nothing executed.
- [ ] **Step 5: Commit** by path: watch.py, session-start.py, cli.py, README.md, SKILL.md, CHANGELOG.md, tests.

### Task 5: Version 1.4.0 everywhere + consistency test

**Files:** `VERSION`, `.claude-plugin/plugin.json`, `lib/lasting_plans/__init__.py`, `CHANGELOG.md`; Test: `tests/test_version_consistency.py` (create: reads all three, asserts equal and that CHANGELOG has a `## 1.4.0` heading).

- [ ] Write test → run (FAIL on 1.2.2 drift) → bump all → run PASS → commit `chore: 1.4.0 (aligns drifted __version__)`.

### Task 6: Ship

- [ ] Final whole-branch review (one fresh reviewer, most capable model) of `git diff origin/main...`.
- [ ] Ship via run-to-completion `ship` (rtc-ship with `rtc-ship.json`): gates, merge to `main`, tag `v1.4.0`, release, `claude plugin update lasting-plans`. Receipt: `git ls-remote --tags origin v1.4.0` shows a SHA; `claude plugin list` shows 1.4.0.

### Task 7: Live un-wedge + dogfood (live state — backup first)

- [ ] **Step 1: Backup receipt.** `git -C ~/Claude-playbooks bundle create <state_dir>/repair-backups/pre-1.4.0-playbooks.bundle --all` and same for plans; also `cp -R ~/Claude-playbooks/.lasting-plans <backup>/` (working-tree sidecars are uncommitted). Receipt: `git bundle verify` OK for both.
- [ ] **Step 2:** `lasting-plans repair --dry-run` → lists the 10 `case_wedge`/`uncommitted` items and the `archive_missing` polyglot item, changes nothing (status unchanged).
- [ ] **Step 3:** `lasting-plans repair` → exit 0. Known-bad discriminant: `git -C ~/Claude-playbooks status --porcelain` must be EMPTY and `git ls-files | grep -c "(2)"` must not exceed the pre-repair count of genuinely distinct "(2)" docs (verify each remaining one has its own sidecar).
- [ ] **Step 3b:** `git -C ~/Claude-playbooks ls-files | cut -d/ -f1 | sort -u` shows `_playbooks` and no `_PLAYBOOKS`, and `ls ~/Claude-playbooks` shows the lowercase folder — same spelling as `git -C ~/.claude/plans ls-files`.
- [ ] **Step 4:** `lasting-plans doctor` → every check ✓ (type mismatch auto-reclassified, journaled). Watcher log shows `repair:` lines from the installed 1.4.0 copy on its next pass.
- [ ] **Step 5: Dogfood the banner:** run the INSTALLED `hooks/session-start.py` → prints nothing (or only the one-time "watcher updated to 1.4.0" note on first run; a second run prints nothing).
