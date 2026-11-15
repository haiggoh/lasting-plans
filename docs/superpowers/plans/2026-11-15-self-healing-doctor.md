# One Mirrored Archive + Self-Healing Doctor (lasting-plans 2.0.0) Implementation Plan

**Status:** approved

> **Lasting Plans:** when every task below is done, set the Status line to `completed` by running `lasting-plans complete "<this file>"` as the closing step.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (native execution: the executor does every task, then one final whole-branch review). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The backup looks exactly like the original (one archive mirroring `~/.claude/plans`, playbooks inside `_playbooks/`), and Lasting Plans never puts routine maintenance on the user's plate: a background auto-repair resolves every foreseeable failure, and the SessionStart banner speaks only when a problem survived repeated automatic repair, or for a true emergency.

**Architecture:** `Library` gets ONE archive root whose paths equal source-relative paths. `plan`/`playbook` stays as sidecar metadata (search/filter label), never a location. A self-running migration (`migrate.py`) merges the v1 playbook archive into the plan archive with full history, relocates every document to its source path, and retires the old archive (kept, never deleted). A new `repair.py` turns doctor checks + scan pending/errors into keyed issues, applies a safe, idempotent fixer per kind (the migration is one such kind), and keeps a persistence ledger that decides when the banner may speak. Watcher and SessionStart hook both call `repair.run()`.

**Tech Stack:** Python 3 stdlib, Git CLI (≥2.30), pytest (`pytest -n auto` for full runs), launchd.

**Spec:** User decisions, this session (2026-11-15):
1. "not putting tasks on the user's plate unless it's an emergency … routine pending tasks … done via a script in the background without any user action."
2. Banner only "if stuck and the doctor script has already been run automatically and the issue still isn't resolved"; the script should "resolve any kind of error of this type … safe enough to be run without explicit user permission at any time."
3. Fix the case-only-rename bug in the same release; folder spelling: "whichever works best with git" → follow the SOURCE spelling everywhere (`~/.claude/plans`'s own Git repo indexes `_playbooks/`).
4. Layout: "One mirrored archive" — `~/Claude-plans` mirrors `~/.claude/plans`, playbooks in `_playbooks/`, type kept only as a label, `~/Claude-playbooks` history merged in, never deleted. Superseded detail (user, 2026-11-15): no retired note — `~/Claude-playbooks` becomes a symlink to `~/Claude-plans/_playbooks`, the old folder is moved (kept) under the state dir, the GitHub repo is left untouched.
5. "One combined release" → 2.0.0 — and "All in 2.0.0" again for items 6–8.
6. Deletions in the BACKUP: "Restore unless trashed" — a vanished archive document is restored from Git unless a same-content file sits in `~/.Trash` (the user deleted it in Finder); other policies selectable.
7. Completion: "Executor marks + strong signals" — executor runs `lasting-plans complete <plan>` as its closing step; automatic for unambiguous signals after 3 quiet days. Completed plans move to `_ARCHIVED/` in the source AND the backup. User addition: plans written with `plan-airtight` (now owned by lasting-plans) carry a canonical in-file signal that tells the executor to mark completion — in-file, not a naming scheme.
8. Sorting: "Yes, both" — top-level playbook-classified docs move into `_playbooks/`; playbooks headed HISTORICAL move to `_ARCHIVED/`; a user's move back is a sticky override.

## Global Constraints

- Every fixer and the migration are **non-destructive** (nothing removed that Git history or a backup cannot restore; anything overwritten first copied to `<state_dir>/repair-backups/<UTC-stamp>/`) and **idempotent** (re-running after a crash at any step converges).
- All repair and migration run under `engine.scan_lock()`; `engine.Busy` ⇒ skip this pass silently, no attempt counted.
- Visible, not hidden: every fix/migration step is logged (watcher log + `<state_dir>/repairs.jsonl`) and shown in `lasting-plans doctor` and `status`. Native opt-out: setting `auto_repair` (default `true`).
- Config: new `archive_root` (default `~/Claude-plans`), `remote` (single URL or null), `auto_repair: bool = True`, `alert_after_hours: int = 24` (min 1), `alert_min_attempts: int = 3` (min 1), `layout: int` (absent/1 = v1, 2 = migrated), `retired_archives: list[str]`. Legacy `plans_root` → `archive_root`, `playbooks_root` → `retired_archives`, `remotes.plan` → `remote` (read-compatible; written only by the migration).
- Never create an archive folder that holds no documents; prune folders emptied by a move.
- Further settings: `archive_deletions: "restore-unless-trashed" | "restore" | "honor"` (default first), `auto_sort: bool = True`, `archive_subdir: str = "_ARCHIVED"`, `playbooks_subdir: str = "_playbooks"` (matched casefold against the existing source folder), `complete_quiet_days: int = 3` (min 0).
- Canonical completion signal (exact, first 40 lines of a doc): a line `**Status:** <value>`; values `draft | approved | in-progress | completed`; `completed` (also `done`, `shipped`, case-insensitive) = complete. Plus a blockquote line starting `> **Lasting Plans:**` naming the closing command.
- Sort moves in the SOURCE (`~/.claude/plans`, the user's own Git repo) are plain `os.rename` — never `git add`/stage/commit there; never move a file modified less than 10 minutes ago (live plan-mode use); collisions use `_free_relpath`. The ONE exception is Task 5c's put-back of a cleanup deletion, which the user chose to stage and commit as a move (only those two paths, `commit --only`).
- User-facing copy never says "tidy", "clean" or "cleanup" for Lasting Plans' own behaviour; "cleanup" refers ONLY to Claude Code's 30-day sweep, which this plugin protects against. The sorting feature is "Sort plans into folders" with the explanation: "moves completed plans to _ARCHIVED/ and playbooks to _playbooks/. Moves only, never deletes anything. Not related to Claude Code's 30-day cleanup, which this plugin protects you from."
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
| Fast-forward push to `haiggoh/Claude-plans` | yes (the existing auto-push behaviour) |
| Move live `~/Claude-playbooks` into `retired-archives/` and symlink it | yes, after the Task 9 backup receipt (user decision) |
| Any write to `haiggoh/Claude-playbooks` on GitHub | no (left untouched) |
| Sort moves in the live `~/.claude/plans` | yes, after Task 9 Step 7's dry-run list is shown to the user (user decision: sorting is automatic) |
| Put-back commits in `~/.claude/plans` (only the two paths, `--only`) | yes, after Task 9 Step 7b's list is shown (user decision: stage and commit) |
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
6. Replace the old playbook archive folder with a **symlink** (user decision 2026-11-15: no retired note): `os.rename(playbooks_root, <state_dir>/retired-archives/<basename>-<UTC-stamp>)` (the WHOLE folder moves, incl. untracked files and `.git`, so nothing is lost even outside Git), then `os.symlink(<archive_root>/_playbooks, playbooks_root)` — target = the source's playbook folder name as mirrored (resolved by casefold, so `_playbooks`). Only when the target folder exists; otherwise skip the symlink and record why. Idempotent: an existing symlink to the right target is a no-op; a symlink elsewhere or a real folder that is not the v1 repo ⇒ stop, record an issue, touch nothing. The old GitHub remote is not written to.
7. Config: `archive_root` = old `plans_root`, `retired_archives += [playbooks_root]`, `remote` = old `remotes.plan`, `layout = 2`; keep the legacy keys' values under `legacy` for audit.
`dry_run=True` prints the plan of steps 3–7 and writes nothing (archive status + config byte-identical).

- [ ] Step 1: failing tests: `test_migration_merges_history` (every v1 playbook doc's `git log --follow` in the new root reaches its v1 first commit); `test_migration_mirrors_source` (`archive_root/_playbooks/` lists exactly the source's 10-style fixture files; no `(2)`, no `_PLAYBOOKS`); `test_migration_restages_watcher_first`; `test_migration_collision_keeps_both`; `test_migration_rerun_converges` (crash injected after step 4 via monkeypatch → second `run` ends in the same tree as a clean run); `test_migration_dry_run_writes_nothing`; `test_old_root_becomes_symlink` (`os.path.islink(playbooks_root)`, `os.readlink` → `<archive_root>/_playbooks`, listing through it shows the playbooks; the moved v1 folder under `retired-archives/` is byte-identical to the pre-migration tree incl. an untracked planted file); `test_symlink_step_refuses_foreign_folder` (a non-repo folder at `playbooks_root` ⇒ issue recorded, folder untouched); `test_prepare_roots_ignores_symlinked_retired_root` (no `ensure_repo`/overlap error on the symlink).
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
| `archive_missing` | doctor "every archive document present" ✗ / pending "removed by hand" | first an unclaimed file in the root with `sha256 == archive_sha256` → repoint sidecar, commit (it was moved, not deleted). Otherwise apply `archive_deletions`: `restore` → `git checkout HEAD -- <path>`; `honor` → mark sidecar `deleted_utc`, `deleted_by: "user"`, commit the removal; `restore-unless-trashed` → a same-sha256 file in `~/.Trash` ⇒ honor, else restore. If `~/.Trash` raises `PermissionError` (launchd TCC) ⇒ return `(False, "deferred: Trash unreadable here")` without counting an attempt; the SessionStart hook (inside Claude Code, Trash readable — verified 2026-11-15 from the Bash tool) decides on its next run. Tests: `test_fix_archive_missing_trashed_is_honoured`, `test_fix_archive_missing_rm_is_restored`, `test_fix_archive_missing_moved_is_repointed`, `test_fix_archive_missing_trash_unreadable_defers`, one per policy value. |
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

### Task 5b: Completion + sorting (moves only, never deletes)

**Files:** Create `lib/lasting_plans/sorting.py`; modify `engine.py` (sidecar fields), `skills/plan-airtight/SKILL.md`, `skills/lasting-plans/SKILL.md`; Test: `tests/test_sorting.py` (create).

**Interfaces — Produces:**
- `sorting.status_of(text: str) -> str | None` — the canonical `**Status:**` value, lower-cased, or None.
- `sorting.is_complete(doc, text, now) -> tuple[bool, str]` — True when (a) status ∈ {completed, done, shipped}, or (b) the doc has ≥1 checkbox and all are ticked, or (c) a playbook whose first heading or first 5 lines contain `HISTORICAL`; and for (b)/(c) and status-set-by-hand, the source is untouched ≥ `complete_quiet_days`. Reason string names the signal.
- `sorting.complete(lib, path_or_id) -> str` — explicit: sets the Status line to `completed` (inserting one under the H1 if absent), moves the source to `<archive_subdir>/<same name>` immediately (no quiet wait), returns the new source path. CLI: `lasting-plans complete <path|id> [--dry-run]`.
- `sorting.sort_pass(lib, now) -> list[event]` — run by `repair.run` when `auto_sort`: for each source doc NOT under `archive_subdir`: complete ⇒ move to `archive_subdir`; top-level doc classified `playbook` and not under `playbooks_subdir` ⇒ move into it. Skips docs with sidecar `sort_override: true`. The next scan sees each move as an ordinary move, so the backup follows (Task 2 mirroring).
- Sticky override: every sort move is recorded in the sidecar `sort_moves: [{from, to, utc}]`; a later move by someone else of a doc OUT of where sorting put it sets `sort_override: true` (never re-moved).
- `plan-airtight` SKILL.md: every plan it hardens MUST carry the canonical `**Status:**` line and the `> **Lasting Plans:**` closing-step line (exact format above), and its closing/receipt section ends with `lasting-plans complete "<plan path>"`. `lasting-plans` SKILL.md: "When you finish executing any plan, run `lasting-plans complete <plan>`; when you start one, set Status to `in-progress`."

- [ ] Step 1: failing tests: `test_status_of_parses_canonical_line`; `test_explicit_complete_moves_now_and_sets_status`; `test_all_ticked_waits_quiet_days` (2 days ⇒ stays, 4 days ⇒ moves); `test_open_checkbox_never_moves`; `test_status_approved_never_moves`; `test_historical_playbook_archived`; `test_top_level_playbook_sorted_into_playbooks_subdir`; `test_recent_file_never_moved` (mtime 5 min ⇒ stays); `test_user_move_back_is_sticky`; `test_backup_mirrors_sort_move` (after `sort_pass` + scan, archive has the doc under `_ARCHIVED/`, history follows); `test_source_git_repo_never_staged` (source is a git repo with the doc tracked ⇒ after the move `git diff --cached` is empty); `test_name_collision_in_archived`.
- [ ] Step 2: run → FAIL. Step 3: implement; update both SKILL.md files. Step 4: `pytest tests/test_sorting.py -v` → PASS. Step 5: commit by path: `feat(sorting): completed plans to _ARCHIVED, playbooks to _playbooks, plan-airtight completion signal`.

### Task 5c: Protect plans from Claude Code's 30-day cleanup — before it deletes, and after

User decisions 2026-11-15: folder `_saved-from-cleanup/` (says what happened, NOT that the plan is done — never `_ARCHIVED/`); stage AND commit as a move; backfill past losses once during the migration, list shown first; user asked to move plans out of the cleanup's reach BEFORE it deletes them, so restoring later is the fallback, not the norm. Setting `cleanup_protection: "before" | "after" | "off"` (default `before`; `after` = only put back after a deletion; `before` also includes `after` as the safety net); folder name setting `cleanup_rescue_subdir: str = "_saved-from-cleanup"`.

Measured facts this task rests on (2026-11-15): the sweep deletes by **mtime** at **session start, ~daily** (`~/.claude/.last-cleanup`; official docs, code.claude.com/docs/en/claude-directory); it touches **top-level files only** (147 subfolder `.md` files untouched >30 days still present; 0 top-level >30 days; 115 historical deletions in `~/.claude/plans` git history, all top-level). Known bugs make it use the 30-day default even when the user configured more (anthropics/claude-code#45903 `--setting-sources local`; pinned old SDKs dropping `cleanupPeriodDays`) — so the period we protect against is `min(configured, 30)`.

Metadata (user-reported earlier losses when restoring via plain Git): Git stores none of birthtime, mtime or Finder tags/colour labels. Every Lasting Plans path that writes a document back into the source MUST re-apply the sidecar's `created_utc`, `modified_utc`, `tags`, `finderinfo_hex` via `engine._apply_sidecar_meta` and verify by re-reading `metadata.observe`; mismatches are recorded as `metadata_unapplied` (new repair kind, fixer = re-apply). The proactive move uses `os.rename` within one volume, which keeps the inode and therefore all metadata untouched.

**Files:** Create `lib/lasting_plans/rescue.py`; modify `repair.py` (new issue kind `cleanup_deletion`, fixer = `rescue.put_back`), `migrate.py` (backfill step 8); Test: `tests/test_rescue.py` (create).

**Interfaces — Produces:**
- `rescue.cleanup_period_days() -> int` — `cleanupPeriodDays` from Claude Code settings (`$CLAUDE_CONFIG_DIR` or `~/.claude`/`settings.json`; same resolution `config.py` already uses for `source_dir`), default 30.
- `rescue.effective_period_days() -> int` — `min(cleanup_period_days(), 30)` (see the bugs above); `rescue.MARGIN_DAYS = 2`.
- `rescue.at_risk(lib, now) -> list[str]` — top-level source docs whose CURRENT mtime age ≥ `effective_period_days() - MARGIN_DAYS`, excluding any that `sorting.is_complete` would send to `_ARCHIVED/` (sorting runs first, so a finished plan lands in `_ARCHIVED/`, an unfinished one in `_saved-from-cleanup/`).
- `rescue.move_before_cleanup(lib, rel) -> str` — `os.rename` to `<cleanup_rescue_subdir>/<name>` (`_free_relpath` on collision), then the same `--only` commit as `put_back` with message `"Lasting Plans: moved <name> out of reach of Claude Code's 30-day cleanup"`; asserts `metadata.observe` before == after (birthtime, mtime, tags). Run by `repair.run` every pass when `cleanup_protection == "before"`.
- `rescue.looks_like_cleanup(lib, doc, now) -> tuple[bool, str]` — True when ALL hold: the source path is top-level (no `/`); the doc's last recorded source mtime (`sc["modified_utc"]`) is older than `cleanup_period_days()` at detection; no same-sha256 file in `~/.Trash` (`PermissionError` ⇒ `(False, "deferred: Trash unreadable here")`, the SessionStart hook decides later, as for `archive_missing`); the doc has no `deleted_by: "user"`.
- `rescue.put_back(lib, doc) -> str` — copies the archive bytes to `<source>/<cleanup_rescue_subdir>/<name>` (`_free_relpath` on collision, metadata re-applied), returns the new source rel. If the source folder is a Git repo with the old path tracked: `git rm --cached --quiet -- <old>` (only if still in the index) then `git add -- <new>` then `git commit --only -m "Lasting Plans: kept <name> (removed by Claude Code's 30-day cleanup)" -- <old> <new>` — the user's other staged changes are never included (`--only`) and nothing else is added. No Git identity in that repo ⇒ file put back, staged, not committed, recorded as `uncommitted` (auto-retried).
- The next scan sees the file at the new path with the same hash ⇒ an ordinary move; the backup mirrors it under `_saved-from-cleanup/`.
- `migrate.py` step 8 (backfill, idempotent): every backup doc with `origin == "source"` whose top-level source is gone and passes `looks_like_cleanup` (age measured at its last-seen time) ⇒ `put_back`. `dry_run` lists them.

- [ ] Step 1: failing tests: `test_old_top_level_deletion_is_put_back` (source git repo, doc mtime 40 days, delete it ⇒ file under `_saved-from-cleanup/`, `git log -1 --name-status` shows `R` old → new, nothing else in that commit; a planted unrelated staged change is still staged and uncommitted afterwards); `test_recent_deletion_is_not_cleanup` (mtime 5 days ⇒ untouched); `test_subfolder_deletion_is_not_cleanup`; `test_trashed_deletion_is_honoured`; `test_trash_unreadable_defers`; `test_cleanup_period_from_settings` (`cleanupPeriodDays: 7` ⇒ 10-day-old doc rescued); `test_not_a_git_repo_just_puts_back`; `test_backfill_lists_then_restores_past_losses` (doc committed as deleted in source history ⇒ dry-run lists it; run restores and commits it as an ADD with the same message); `test_setting_off_leaves_deletions_alone`; `test_never_lands_in_archived`; `test_at_risk_moved_before_cleanup` (top-level mtime 29 days ⇒ moved, commit `R`, birthtime/mtime/tags identical before and after); `test_28_days_with_period_30_is_moved` and `test_27_days_is_not`; `test_configured_3650_still_protects_at_30` (effective period is the min); `test_finished_at_risk_plan_goes_to_archived` (all-ticked + quiet ⇒ `_ARCHIVED/`, not `_saved-from-cleanup/`); `test_put_back_restores_metadata` (sidecar birthtime/mtime/colour tag ⇒ the put-back file has all three, verified via `metadata.observe`; skip off macOS); `test_restore_to_source_restores_metadata` (the existing `restore` command — today `restore_to_source`, `engine.py:802-840`, copies bytes only and loses all three: regression test for that gap); `test_restore_of_old_doc_avoids_top_level` (restoring a doc whose restored mtime is already past the at-risk age lands in `_saved-from-cleanup/` with a note — at the top level it would be swept again at the next session start); `test_metadata_unapplied_is_retried`.
- [ ] Step 2: run → FAIL. Step 3: implement. Step 4: `pytest tests/test_rescue.py -v` → PASS. Step 5: commit by path: `feat(rescue): put back plans removed by Claude Code's 30-day cleanup, committed as a move`.

### Task 6: Wire into watcher, hook, CLI; docs

**Files:** `lib/lasting_plans/watch.py`, `hooks/session-start.py`, `lib/lasting_plans/cli.py`, `README.md`, `skills/lasting-plans/SKILL.md`, `CHANGELOG.md`; Test: `tests/test_repair.py`.

- `watch._run_scan`: after the scan, if `auto_repair` → `repair.run(lib, res)`; log `repair: fixed <key> — <note>` per fix and the remaining count.
- `session-start.py`: replace lines 57–58. With `auto_repair` → `repair.run(lib, res)`, note only `repair.alerts()` in the exact alert copy; the watcher-install failure and the generic `except` are recorded as ledger issues (`watcher_down`, `hook_exception`) instead of printed. With `auto_repair` false → the old `⚠ N item(s) pending — run \`lasting-plans doctor\`` line verbatim (user opted out). The first-run "set up" note names one archive.
- CLI: `repair [--dry-run] [--json]` (exit 0 nothing remaining, 5 otherwise; the layout migration runs only through this — NO new `migrate` subcommand: `migrate` already exists at `cli.py:606` for importing a source Git repo and stays unchanged); `complete <path|id> [--dry-run]` (Task 5b); `doctor` appends an "auto-repair" section (last run, remaining with first-seen/attempts, fixes in the last 7 days); `status` adds `  ✓ auto-repaired N issue(s) in the last 7 days` when N>0.
- **Interactive menu — behaviour opt-outs (user request 2026-11-15).** One table `BEHAVIOUR_SETTINGS` in `config.py` is the single source for each user-facing behaviour: `(key, label, choices, explanation)`; both `settings show` and the menu read it (one constant per shared label). Rows, in order:
  1. `auto_repair` — "Fix problems automatically in the background" — on/off — "off: the banner lists pending items again, as before 2.0."
  2. `archive_deletions` — "When a document vanishes from the backup" — `restore-unless-trashed` "restore it, unless you put it in the Trash" / `restore` "always restore it" / `honor` "leave it deleted (Git keeps it)".
  3. `auto_sort` — "Sort plans into folders" — on/off — the exact explanation from Global Constraints (moves only, never deletes; not Claude Code's 30-day cleanup).
  3b. `cleanup_protection` — "Protect plans from Claude Code's 30-day cleanup" — `before` "move plans into _saved-from-cleanup/ shortly before the cleanup would delete them (dates and colour labels kept)" / `after` "only put them back there after the cleanup deleted them" / `off` "leave them; they stay only in the backup". The menu row also shows the measured period: "Claude Code deletes top-level plans after N days (protected at min(N, 30) − 2)".
  4. `complete_quiet_days` — "Days a finished-looking plan waits before it is archived" — integer ≥ 0.
  5. `alert_after_hours` — "Hours a problem must persist before the banner mentions it" — integer ≥ 1.
  MENU gains, after `doctor`: `("repair", "Repair now (what the background does)", [])`, `("repair --dry-run", "Preview repairs and sort moves", [])`, `("complete", "Mark a plan completed (moves it to _ARCHIVED)", ["ref"])`, `("behaviour", "Behaviour settings (opt-outs)", [])`. New `behaviour` subcommand: on a TTY shows the rows numbered with the current value and its explanation; a number picks the row; an on/off row toggles, a choice row lists its numbered choices, an integer row prompts; every change goes through `cfgmod.parse_value` + the existing settings write path (invalid input ⇒ message, nothing written); `b` back, `q` quit (menu grammar: numbers = actions, b/q = Back/Quit). Off a TTY it prints the table and exits 0; `behaviour --help` runs nothing. Tests in `tests/test_repair.py`: `test_behaviour_table_covers_new_settings` (every key in the table exists in `DEFAULTS` and parses each listed choice), `test_behaviour_menu_toggle_writes_setting` (feed stdin `1\nq\n` with a TTY shim → `auto_repair` flipped in the config file), `test_behaviour_menu_rejects_invalid` (`5\n0\nq\n` → `alert_after_hours` unchanged, error shown), `test_settings_show_uses_table_labels`.
- Docs: README layout section rewritten (one mirrored archive, type = label, migration + symlinked old folder explained, auto-repair + opt-outs incl. the `behaviour` menu); SKILL.md Health row ("automatic — `lasting-plans repair` runs it now; the banner speaks only when it could not fix something"); CHANGELOG `## 2.0.0` entry flagging the layout change as BREAKING.

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
- [ ] Step 4 — known-bad discriminants: `~/Claude-plans/_playbooks/` holds every file in `~/.claude/plans/_playbooks/` (`diff -rq` on documents shows no missing files); `git -C ~/Claude-plans ls-files | grep -c "_PLAYBOOKS/\| (2)\.md"` = 0 unless a listed collision; both repos `git status --porcelain` empty; `readlink ~/Claude-playbooks` = `~/Claude-plans/_playbooks` and `ls ~/Claude-playbooks/` lists the playbooks; `diff -rq` of the moved `retired-archives/Claude-playbooks-*` against the Step 1 copy shows only the pre-migration commit's changes; `git ls-remote` shows the Claude-plans remote at the local HEAD.
- [ ] Step 5: `lasting-plans doctor` → every check ✓, with the auto-repair section listing what it did.
- [ ] Step 6 — dogfood the banner: run the INSTALLED `hooks/session-start.py` twice → the second run prints nothing.
- [ ] Step 7 — dogfood sorting: INSTALLED `lasting-plans repair --dry-run` lists the sort moves it would make in `~/.claude/plans` (expected: the 2 all-ticked plans if quiet ≥3 days, top-level playbook-classified docs, HISTORICAL playbooks); show that list to the user in the reply before the first live sort pass runs (first-run visibility; later passes are silent). Then run it and verify one moved plan appears under `~/Claude-plans/_ARCHIVED/` with `git log --follow` intact.
- [ ] Step 7a — before-cleanup moves: the same dry-run lists the top-level plans now at risk (2 were 25–30 days old on 2026-11-15); after the run, for one of them compare `stat -f '%SB %Sm'` and `xattr -p com.apple.metadata:_kMDItemUserTags` before/after → identical.
- [ ] Step 7b — cleanup put-back: the same dry-run lists the backfill (past cleanup losses, e.g. from commits `19329ae`, `8bd275e`) and the current unstaged deletion (`Plan — free-agents 0.36.0 oMLX session backend…`); show the list to the user BEFORE running. After the run: `git -C ~/.claude/plans status --porcelain` no longer shows ` D` for it, `git -C ~/.claude/plans log -1 --name-status` shows the `R` (or backfill `A`) into `_saved-from-cleanup/`, and the user's other uncommitted changes in that repo are still uncommitted.
- [ ] Step 8 — close this plan with its own mechanism: `lasting-plans complete "<this plan>"` → Status `completed`, file under `_ARCHIVED/`.
