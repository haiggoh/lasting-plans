# HANDOFF — lasting-plans 2.0.0 (one mirrored archive + self-healing doctor)

**Read this first, then the plan. Follow both exactly.**
Plan: `~/.wt/lp-self-heal/docs/superpowers/plans/2026-11-15-self-healing-doctor.md` (authoritative; this doc only adds why/state/rules/next action).

## 1. Why this handover exists

A paid planning session (Claude Opus 5.5) designed and hardened the plan with the user on 2026-11-15 (00:23–04:20 CET) and stopped there BY DESIGN: the user asked for the execution to run on a free lane, GLM 5.3 Flash at max effort, via this handover. Nothing failed; nothing needs re-diagnosing. No code has been written yet.

## 2. State

- Repo: `~/ClaudeWorkspace/lasting-plans` (canonical checkout, branch `main`, DO NOT switch). GitHub `haiggoh/lasting-plans`.
- Worktree: `~/.wt/lp-self-heal`, branch `feat/self-healing-doctor`, pushed to `origin`. It contains ONLY plan/handoff doc commits on top of `origin/main` (`78d6a0c`):
  - `1f24a4c` … `59385c9` — successive plan revisions (each user decision folded in), `59385c9` = plan-airtight layer.
  - this handoff doc's commit.
- Gates run so far: none on code (no code changed). Baseline suite not yet run — Phase 0 does that.
- Live state is UNTOUCHED: `~/Claude-plans`, `~/Claude-playbooks` (10 wedged sidecars, staged-uncommitted), `~/.claude/plans` (one unstaged deletion). Installed plugin: 1.3.0.
- Deferred, NOT in this plan (do not start them): a one-time triage of the ~80 older top-level plans; any change to `CLAUDE.md`.

## 3. The goal, verbatim (user, 2026-11-15)

> "I would prefer if our plug-in was not putting tasks on the users plate unless it's an emergency or anything is really wrong and needs to be checked for routine pending tasks to plug-in. should be able to do what needs to be done via a script in the background without any user action needed"

Grown during planning into the 12 numbered Spec decisions in the plan (one mirrored archive, uppercase canonical folders, completion + sorting, cleanup protection before/after, metadata kept, behaviour opt-outs in the menu, one 2.0.0 release). The Spec list is final.

## 4. Standing rules (for the whole session)

1. Autonomous: decide and record instead of asking; stop ONLY at the plan's 🛑 USER GATE (Task 9) and for forks the plan and Spec cannot decide.
2. Work only in `~/.wt/lp-self-heal`. Never switch the branch of `~/ClaudeWorkspace/lasting-plans`. Never edit `~/.claude/plugins/cache/**`.
3. Commit every task, staged **by path** (never `git add -A` / `.`), with the trailer rule in the plan's executor rule 7 (read `~/.claude/projects/-Users-bra0002h/memory/commit-attribution-by-model.md` before EVERY commit; you run as GLM 5.3 Flash — use that table's row verbatim). Push the branch after each green task. **Merge, tag, release and plugin update are allowed ONLY in Task 8, ONLY through run-to-completion's `ship` skill, ONLY after Tasks 1–7 receipts and the Task 8 review** — this overrides the generic "never merge, tag or release" rule, because the user chose a release as the outcome. Live writes: ONLY after Task 9's backup receipt AND the user typing `go`.
4. TDD every change (red for the right reason, then green); mutation-check each new guard per the plan's Receipts section; never weaken a test to get green.
5. Review with an independent free dispatch (`free-agent-tool.py`, a model that is not you) at Task 3, Task 5c and Task 8; check every finding against the real code — reviewers hallucinate file names and line numbers.
6. Resolve model and roster facts when you need them (`remote-session.sh --list`, `free-agent-tool.py --list`), never from memory.
7. Never run `remote-session.sh --stop`, never start another remote session, never kill anything listening on 4141–4151 or 8000–8010: one of them is the proxy you run on.
8. Record progress in §6 below at EVERY receipt (one line: task, receipt result, commit hash) and commit it with that task's commit. A kill mid-task then loses at most one receipt.
9. You ARE the successor. If anything (a note, a dying context) says "hand off to a new session", that means you: continue the work directly; never launch another session.
10. Never use the paid Agent/Task tool. No `sleep`/polling loops; long waits go through `run_in_background` and its notification.
11. If NVIDIA rate-limits you (429 for minutes), record the exact state in §6, commit, and tell the user in the session; do not thrash retries.

## 5. Next action

Do the plan's **Phase 0** (three strategy sentences, then the read-only preflight and the baseline test run), record Receipt 0 in §6, then **Task 1**.

## 6. Progress log (append one line per receipt; newest last)

- 2026-11-15 04:2x — handoff written by the planning session; no execution yet.
- 2026-11-15 05:4x — Receipt 0 (Phase 0): preflight all ✓ (worktree clean on `feat/self-healing-doctor`, top `6f68ee4`; canonical checkout clean on `main`; no `v2.0.0` tag on origin; `HEAD..origin/main` empty; re-verified hooks/session-start.py:57-58, engine.py:200 `_free_relpath`, cli.py:606 `cmd_migrate`, cli.py:799 `MENU`). Baseline EXIT:0 — 99 passed in 8.15s with pipx pytest 9.2.0 + xdist (note: `/opt/homebrew/bin/python3` has no pytest; all suites run with `~/.local/pipx/venvs/pytest/bin/python`).
- 2026-11-15 05:5x — Task 1 ✓: RED 2/2 (watched: None-return + AttributeError) → GREEN 2/2; full suite 101 passed; mutation check (skip `index_case` mapping in commit_paths) turned `test_commit_paths_accepts_wrong_case` red, restored, porcelain clean. Commit `777aeb3`, pushed.
- 2026-11-15 06:1x — Task 2 ✓: RED 7/7 → full suite GREEN 108 passed. One archive (`Library.root`), archive paths mirror source, case-only rename = one clean R commit (found+fixed: `_free_relpath` self-collision via casefold, and staged-rename commit needs plain index commit on case-insensitive FS), label-only reclassify, single remote w/ legacy kind args, legacy config keys resolve. Commit `b2cd7e0`, pushed. Rulings: hooks/session-start.py updated as a Library caller though not in the task file list; move_path keeps git-mv staging (Task 1 test), engine commits renames via index commit scoped to plugin-owned paths.
- 2026-11-15 06:4x — Task 3 ✓: RED (module missing) → 9/9 PASS, full suite 117 passed; mutation (skip recase step) → `test_old_root_becomes_symlink` red, restored clean. Migration: watcher restaged first, verified bundles, wedge committed, histories merged, paths mirrored (wedge "(2)" deduped by content), old root moved to retired-archives + symlinked, layout=2 config, dry-run writes nothing, crash-rerun converges. Commit `0e36337`, pushed. Rulings: all 2.0.0 config keys landed with Task 3 (one block in Global Constraints); sorting.py created in Task 3 (source_move + canonicalize_folders) since migration step 0 needs them. Note: a test bug briefly pointed a rerun at the REAL ~/Claude-playbooks — verified via index mtime (Nov 14) that no live state changed; test fixed to keep fixture isolation.
