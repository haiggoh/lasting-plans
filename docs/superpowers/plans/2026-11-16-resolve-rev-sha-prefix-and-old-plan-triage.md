# resolve_rev sha-prefix fix + one-time triage of old top-level plans (lasting-plans 2.0.5) Implementation Plan

**Status:** draft

> **Lasting Plans:** when every task below is done, set the Status line to `completed` by running `lasting-plans complete "<this file>"` as the closing step.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (native execution by standing user decision, 2026-11-05).

## 🚨 System instructions for the executor — read first

1. This plan is self-contained. You have NO chat history. The Spec list below outranks anything you infer.
2. Before any file edit, write exactly three sentences linking Task 1 to the final outcome (Task 2's live triage verified), then do Phase 0 (read-only).
3. Work ONLY in the worktree `~/.wt/lp-plan` on branch `docs/plan-2026-11-16-resolve-rev-and-triage` (Task 1 may use a second worktree `~/.wt/lp-205` from `origin/main` for the code change). Never switch the branch of `~/ClaudeWorkspace/lasting-plans`. Never edit the installed plugin cache directory.
4. Native tools for files; the shell for git, tests, the CLI. Edit anchors from a FRESH Read, whole lines, exact indentation.
5. Shell is **zsh**: quote globs, no `$40`-style literals or backticks inside double quotes; never pipe a test run into `tail` — redirect to a file and read `EXIT:$?`.
6. Stage by path only (`git add <paths>`); never `git add -A`; `git diff --cached --stat` before each commit.
7. **Commit trailer:** you run on a FREE model. Before EVERY commit read `~/.claude/projects/-Users-bra0002h/memory/commit-attribution-by-model.md` and add the running model's trailer verbatim on the line BELOW `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never invent a trailer.
8. Authority: see the matrix. The highest granted boundary here is **release 2.0.5 via rtc-ship** and the **gated live triage** (Task 2, only after its backup receipt AND the user typing `go`).
9. Every task ends with a 🧪 Receipt. A failure ⇒ stop that task, diagnose (systematic-debugging), fix, rerun, show both runs. Never weaken a test to pass.
10. Never put secrets in receipts. Say "not tested" when something could not run safely.
11. Do NOT use the paid Agent/Task tool. Independent review goes through `free-agent-tool.py` (stateless dispatch, a model that is not you).
12. If a step's premise turns out false, STOP that step, write down what you found, and adapt only if the Spec decides the outcome.

## 📌 Context, evidence and unknowns

Labels: **[live]** confirmed by a command on 2026-11-16 · **[dated]** observation that may have changed · **[decision]** user decision · **[unknown]** inspect before relying.

- [live] lasting-plans 2.0.4 installed; `main` = `39be140`; releases v2.0.0–v2.0.4 live. The 2.0.0 plan and its handoff are `docs/superpowers/plans/2026-11-15-*` on main.
- [live] Waypoint `lasting-plans-resolve-rev`: `library.resolve_rev` treats an all-digit sha prefix (e.g. `26691924`) as a revision number — `if s.isdigit()` runs before the sha-prefix loop, so `show <ref> --rev 26691924` raises `LookupError: revision 26691924 does not exist (1..3)` even though that sha exists. The 2.0.4 test was made robust by picking a non-digit prefix; the behaviour is unfixed.
- [live] `~/.claude/plans` holds ~80 older top-level `.md` plans that the 2.0.0 migration deliberately did NOT triage (deferred by the 2.0.0 plan §2). The 2.0.x background repair already sorts (complete → `_ARCHIVED/`), classifies (playbook → `_PLAYBOOKS/`) and protects (at-risk → `_SAVED-FROM-CLEANUP/`) automatically; the triage is the one-time, user-reviewed pass to settle the remainder deliberately.
- [live] `~/.claude/plans` is a Git repo; the user may have uncommitted edits in it at any time (one such file existed on 2026-11-16) — never stage anything there except the exact paths the plugin's own helpers commit.
- [live] Backups from the 2.0.0 migration: `~/Claude-plans-premigration-2026-11-15/` (bundles verify OK). Task 2 takes a FRESH backup under a new stamp.
- [unknown] How many top-level plans are neither complete, playbook, nor at-risk (the "keep as-is" remainder) — Phase 0 measures it.

## Goal

Fix `resolve_rev` so a sha prefix is always honoured (2.0.5, released), then run the deferred one-time triage of the older top-level plans with the user reviewing the list before anything moves.

## Architecture

Task 1 is a small `library.py` semantic fix with tests, shipped as 2.0.5 through rtc-ship. Task 2 is an operational pass: fresh bundle backup → `repair --dry-run` list shown to the user → user `go` → `repair` → discriminants → receipts. No new plugin feature is added for the triage: the 2.0.x repair already implements every move; this plan only drives and verifies it.

**Tech Stack:** Python 3 stdlib, pytest (`-n auto`), Git CLI, the installed `lasting-plans` 2.0.x CLI.

**Spec:** the user's two deferrals, 2026-11-16:
1. **resolve_rev semantics** — a sha prefix must resolve to that revision even when it is all digits; a numeric selector (`1`, `-1`) keeps its current meaning. On genuine ambiguity (a selector that is both an in-range revision number and a unique sha prefix), prefer the sha prefix when it matches exactly one revision, and never guess silently — an ambiguous selector must error with both readings named when the prefix matches multiple shas.
2. **One-time triage** — the ~80 older top-level plans in `~/.claude/plans` are to be settled once, deliberately: completed plans → `_ARCHIVED/`, playbooks → `_PLAYBOOKS/`, at-risk old plans → `_SAVED-FROM-CLEANUP/`, everything else stays top-level. Nothing is ever deleted; every move is a committed rename; the list is shown to the user before the first move.

## Global Constraints

- `resolve_rev` keeps its public signature and its documented selectors (`N`, `-N`, `latest`, `first`, `@YYYY-MM-DD`, sha or sha prefix).
- Version 2.0.5 on EVERY surface: `VERSION`, `.claude-plugin/plugin.json`, `lib/lasting_plans/__init__.py`, `CHANGELOG.md` (top entry), `docs/ROADMAP.md`; portable/ regenerated (`scripts/build-portable.py`).
- All tests run with `~/.local/pipx/venvs/pytest/bin/python -m pytest` (the machine's only pytest); full suites with `-n auto`.
- Task 2 moves go ONLY through the installed 2.0.x `lasting-plans repair` (never by hand); a fresh `git bundle create --all` for `~/Claude-plans` AND `~/.claude/plans` must verify before any move.
- The user's uncommitted work in `~/.claude/plans` must still be uncommitted (and untouched) after Task 2 — proven by a before/after `git status --porcelain` diff of the non-plugin paths.
- `--help` runs nothing, on every script touched.

## 🔒 Authority matrix

| Operation | Status | Gate / evidence |
|---|---|---|
| Read-only inspection anywhere | allowed now | — |
| Edit + commit on `docs/plan-2026-11-16-resolve-rev-and-triage` (plan) or `~/.wt/lp-205` (code) | allowed now | staged diff reviewed per commit; trailer rule 7 |
| Push the code branch; merge to `main`, tag `v2.0.5`, release, refresh the plugin install | allowed after gate | Task 1 receipt + independent review findings resolved; done ONLY via run-to-completion's `ship` skill |
| Fresh backups (bundles + copies) | allowed now | Task 2 step 1 |
| Live moves in `~/.claude/plans` / `~/Claude-plans` via the installed CLI | allowed after gate | Task 2 backup receipt AND the 🛑 USER GATE (user reviewed the dry-run list and typed `go`) |
| `git add -A`, force-push, editing the installed plugin cache, switching the canonical checkout's branch, touching ports 4141-4151/8000-8010, paid Agent/Task subagents | prohibited | — |

## 🛑 Phase 0 — forced preflight (read-only)

1. Three strategy sentences (rule 2).
2. `cd ~/.wt/lp-plan && git status --porcelain && git branch --show-current && git log --oneline -2` → clean, the docs branch, top commit `39be140`.
3. `lasting-plans --version` → 2.0.4 (or newer); `which lasting-plans`.
4. Baseline: `~/.local/pipx/venvs/pytest/bin/python -m pytest -n auto tests > $TMPDIR/lp205-baseline.txt 2>&1; echo EXIT:$?` → record exit + counts.
5. Measure the triage surface: `lasting-plans repair --dry-run` on live state → save; count `sorted`/`rescued`/`cleanup_deletion`/`archive_missing`/`transient` lines; snapshot `git -C ~/.claude/plans status --porcelain` and `git -C ~/Claude-plans status --porcelain` into `$TMPDIR/*.before.txt`.
6. Re-observe the [live] facts Task 1 depends on: `grep -n "def resolve_rev" -A 12 lib/lasting_plans/library.py` (the digit branch precedes the sha loop).

**🧪 Receipt 0:** the outputs above; baseline EXIT and counts; the triage list size.

## 🧪 Receipts (every task)

Each task ends with: the exact test command, its EXIT read from a file, pass/fail/skip counts, `git log --oneline -1` of the task's commit, and one state assertion. **Discriminant rule:** each new test is shown FAILING before the implementation, and Task 1 additionally shows one isolated temporary mutation turning a key test red after it went green (commit the green state FIRST; mutate; run with `PYTHONDONTWRITEBYTECODE=1` after clearing `__pycache__`; `git restore <file>`; confirm `git status --porcelain` empty). Never `git stash`.

## Review Focus

1. **A selector that is both a revision number and a sha prefix** — e.g. three revisions and a sha starting `2…`: the user means the sha; a silent wrong pick is worse than an error.
2. **`-N` and `@date` still mean what they mean** — the fix must not disturb the other selectors.
3. **A plan that is complete AND a playbook AND at-risk** — sorting runs first (`_ARCHIVED/`), so the triage must never leave it in `_SAVED-FROM-CLEANUP/`.
4. **The user edits a plan while the triage runs** — the hot-file guard (10 min) must keep it in place; the receipt shows it.
5. **A top-level plan with no sidecar** (never imported) — `repair` imports it first; the triage must not move a file the backup has not seen yet.

---

### Task 1: `resolve_rev` honours a sha prefix (release 2.0.5)

**Files:**
- Modify: `lib/lasting_plans/library.py` (`resolve_rev`)
- Test: `tests/test_engine.py` (extend `test_revision_selectors_and_old_text`)
- Version surfaces: `VERSION`, `.claude-plugin/plugin.json`, `lib/lasting_plans/__init__.py`, `CHANGELOG.md`, `docs/ROADMAP.md`; regenerate `portable/`

**Interfaces — Produces:** `library.resolve_rev(doc, sel)` unchanged in signature; new behaviour: an all-digit selector that prefixes exactly one revision's sha resolves to that sha; an all-digit selector that is also an in-range revision number and matches no sha prefix keeps resolving as the number; a selector whose sha prefix matches more than one revision errors naming both readings.

- [ ] **Step 1: failing tests** (extend the existing test, do not rewrite it):
  `test_resolve_rev_digit_only_sha_prefix` — build `_three_revisions(home)`, take `p = revs[2]["sha"][:8]`; if not `p.isdigit()`: `pytest.skip("no all-digit sha in this fixture")`; `assert library.resolve_rev(d, p) == revs[2]["sha"]`.
  `test_resolve_rev_keeps_numeric_and_ambiguous` — `assert library.resolve_rev(d, "1") == revs[2]["sha"]`; for an ambiguous selector (monkeypatch `revisions` to return a rev whose sha starts with `"1"` while `"1"` is a valid revision): `with pytest.raises(LookupError, match="ambiguous")`.
- [ ] **Step 2: run** `… -m pytest tests/test_engine.py::test_resolve_rev_digit_only_sha_prefix tests/test_engine.py::test_resolve_rev_keeps_numeric_and_ambiguous -v` → FAIL.
- [ ] **Step 3: implement** in `resolve_rev`: move the sha-prefix matching BEFORE the `s.isdigit()` branch via a small helper `_sha_prefix_match(revs, s) -> list[str]`; when an all-digit selector matches exactly one sha prefix AND is an in-range revision number, raise `LookupError("ambiguous: %r is revision %d and sha prefix of %s" % …)`; when it matches exactly one sha prefix and is NOT an in-range revision, return that sha; otherwise keep today's behaviour.
- [ ] **Step 4: run** the same command → PASS; then the full suite `-n auto` → green.
- [ ] **Step 5: mutation check** — after committing green, remove the `_sha_prefix_match` call from the digit branch; `test_resolve_rev_digit_only_sha_prefix` must go red; `git restore`; porcelain clean.
- [ ] **Step 6: independent review** — `free-agent-tool.py` dispatch (a model that is not you) over the diff + Spec item 1; check every finding against the real code before acting.
- [ ] **Step 7: bump 2.0.5** on every surface, regenerate `portable/`, commit, push the code branch.
- [ ] **Step 8: ship** via run-to-completion's `ship` skill (gates → merge → tag `v2.0.5` → release → refresh the plugin install); receipts: `git ls-remote --tags origin v2.0.5` prints a SHA, `ls-remote origin main` equals the merge commit, the newest plugin cache dir reads 2.0.5.

**🧪 Receipt 1:** the commands, EXIT, counts, commit, tag SHA, installed version.

### Task 2: one-time triage of the older top-level plans (live, gated)

**Files:** none in the repo — the work is live state plus receipts appended to this plan file.

- [ ] **Step 1 — backup receipt.** `stamp=$(date -u +%Y%m%dT%H%M%SZ)`; `mkdir -p ~/Claude-plans-triage-$stamp`; `git -C ~/Claude-plans bundle create` and `git -C ~/.claude/plans bundle create … --all`; `git bundle verify` BOTH; `cp -R` both `.lasting-plans/` dirs; record sizes + verify output. Snapshot `git status --porcelain` of `~/Claude-plans` and `~/.claude/plans` into `$TMPDIR/triage-before-*.txt`.
- [ ] **Step 2 — the list.** `lasting-plans repair --dry-run` → save; extract the `sorted`/`rescued`/`cleanup_deletion` lines; ALSO a read-only count of top-level plans by disposition via a throwaway `python3 -` script using the installed library (`sorting.is_complete`, `classify.classify`) → a table: will-archive / will-sort-to-playbooks / will-rescue / stays. Show BOTH to the user in the reply.
- [ ] **Step 3 — 🛑 USER GATE.** Paste the table; STOP; wait for the user to type `go`. Anything else is a correction: apply it to the plan first.
- [ ] **Step 4 — apply.** `lasting-plans repair` → exit 0 (or 5 with only `transient:remote`, tolerated and named). Run it a second time; the second run must list ZERO `sorted`/`rescued`/`cleanup_deletion` (convergence).
- [ ] **Step 5 — discriminants (known-bad first).** (a) Pick one top-level plan the table says will move; after the apply assert it is at its new path AND `git log --follow` in `~/Claude-plans` reaches its original import commit. (b) No source document lost: every `~/.claude/plans/**/*.md` path either still exists or appears under `_ARCHIVED/`, `_PLAYBOOKS/` or `_SAVED-FROM-CLEANUP/` (list exceptions). (c) `git -C ~/.claude/plans status --porcelain` non-plugin paths byte-identical to the before-snapshot. (d) `lasting-plans doctor` → every check ✓. (e) `xattr -p com.apple.metadata:_kMDItemUserTags` and `stat -f '%Sm'` on one moved file unchanged.
- [ ] **Step 6 — receipts.** Append to THIS plan file: the stamp, the table, the two run outputs, the discriminant results, known-open items. Commit on the docs branch.

**🧪 Receipt 2:** the above, including the convergence run and the untouched-user-work proof.

## ⚠️ Side-effect classification

| Step | Side effect | How routine verification avoids it |
|---|---|---|
| Every test | writes to a synthetic HOME | the `home` fixture; no test touches the real `~/.claude/plans` |
| Task 1 ship | merge/tag/release/plugin refresh | rtc-ship only; receipts via `ls-remote` |
| Task 2 apply | moves + commits in `~/.claude/plans` and `~/Claude-plans` | the installed CLI's own scoped commits; the fresh verified bundles; the before/after status diff |
| Task 2 hot file | a plan edited minutes ago must not move | the 10-minute hot guard, asserted in the receipt |

## 🧨 Adversarial review

- Shortcut: treat the all-digit selector as a number because the old tests pass → false: green suite → harm: `show --rev <sha>` fails for real users → rule: the new test must fail first → detect: Step 2's FAIL.
- Shortcut: fix it by making all-digit selectors sha-only → false: the new test passes → harm: `--rev 1` stops meaning revision 1 → detect: `test_resolve_rev_keeps_numeric_and_ambiguous`.
- Shortcut: run the triage from the worktree's code instead of the INSTALLED CLI → false: it "works" → harm: a different build writes live state → rule: only the `lasting-plans` shim → detect: `lasting-plans --version` in Receipt 2.
- Shortcut: stage everything in `~/.claude/plans` to "tidy" → harm: the user's uncommitted work lands in a commit → rule: only the CLI's helpers write there → detect: discriminant (c).
- Shortcut: skip the backup because 2.0.0's still exists → harm: the triage's own moves have no independent rollback → rule: a FRESH stamp per pass → detect: Receipt 2's verify output.
- Shortcut: pipe a test run into `tail` → false exit 0 → rule 5 → detect: `EXIT:$?` from a file in every receipt.
- Lower permission read as higher: "the user asked for a plan" is not "the user approved the triage" → Task 2's gate is the only route into live moves.

## 🏁 Final review and delivery (answer each in the final reply)

1. What is released (tag, release URL, installed version) versus only planned?
2. Which receipts ran? Which tests did NOT run, with the reason?
3. Is the user's uncommitted work in `~/.claude/plans` untouched (show the status diff)?
4. Did anything move that the user's `go` did not cover? (Expected: nothing.)
5. Is the plan's own Status flipped to `completed`, and by which command?
6. Did any live/global system change beyond the matrix?
7. Was this plan file re-read after the last edit?
