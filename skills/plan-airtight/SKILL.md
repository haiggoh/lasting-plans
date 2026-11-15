---
name: plan-airtight
description: 'Use together with a general plan-writing skill to harden a plan — a NEW plan before handoff, or an EXISTING plan that will be executed by a DIFFERENT executor than the session writing it (a handoff, a successor session, a free or local model, an overnight or unattended run), when it crosses permission boundaries beyond editing and committing (publishing, merging, tagging, releasing, deploying, live services, spending, downloads, process control), or when it touches shared or live state (a checkout other tooling resolves through, a running runtime). Adds the execution-safety layer: an authority matrix, a forced Phase 0 preflight, receipts with a known-bad discriminant, side-effect classification, and an adversarial review. Do NOT use alone for decomposition, and skip it when the writing session executes a repo-local plan itself.'
---

# plan-airtight — the execution-safety layer on top of a plan

A general plan-writing skill decides **what** gets built: decomposition, tasks, interfaces, test steps,
self-review, execution handoff. This layer does not restate any of that. It adds what a plan needs
when the reader is not its author: the executor has no chat history, may be a smaller model, and
cannot ask. Template: [references/plan-template.md](references/plan-template.md).

## When the layer is needed (any one is enough)

- **Different executor.** Someone other than this session runs it: a handoff, a successor, a delegated
  model, an unattended run.
- **Permission boundary.** Any operation past edit + local commit: publishing, merge, tag, release,
  deploy, live services or APIs, money, large downloads, killing or restarting processes, user config.
- **Shared or live state.** A checkout other tooling resolves through, uncommitted work that is not
  the executor's, a runtime that other sessions use.

None of these? The base plan is enough; do not add this layer for ceremony.

## What the layer adds

1. **Self-contained context.** Label every fact *confirmed live*, *dated observation*, *decision* or
   *unknown to inspect*. Never present a guessed path or command as proven. No secrets.
2. **Authority matrix.** For each operation: allowed now / allowed after a named gate / needs separate
   user permission / prohibited. Silence is not permission. Clearance for one boundary never implies
   the next: publishing a branch does not authorize a merge, a merge does not authorize a release.
   State the highest granted boundary in the opening rules AND in the final phase.
3. **Phase 0, forced preflight.** Before any mutation, the executor writes exactly three sentences
   connecting the first phase to the final outcome, then does read-only discovery: the right source
   (not a build output, cache or similarly named copy), dirty and untracked paths, the test command
   and a baseline run, tool availability. A new worktree starts from committed history; uncommitted
   work does not come along. Unverifiable prerequisite ⇒ pause the dependent work.
4. **Receipts, not checkboxes.** Every phase ends with the command run, its expected observation and
   exit status, and the state invariant checked. "Not tested" is said as such, never as passed. On an
   unexpected failure: stop that phase, diagnose, fix, rerun, show both runs.
5. **A known-bad discriminant per important behaviour.** A planted bad fixture or an isolated temporary
   mutation must turn the check red before the good case counts as green. Never plant faults in live
   files or services. If an assertion contradicts a verified fact, inspect the instrument; never weaken
   the test.
6. **Side-effect classification.** Name every step that can spend, download, change credentials, kill
   processes, overwrite data or alter terminal state, and route its routine verification through
   mocks, stubs, temp dirs, scratch ports and synthetic credentials. A `--dry-run` is not presumed
   harmless: the plan says how its implementation was checked.
7. **Adversarial review.** For each credible risk, one line: tempting shortcut → plausible false success
   → concrete harm → preventive rule → the test or receipt that detects it. Always consider: wrong
   checkout, dirty work missing from a worktree, guessed tool schema, a pipeline hiding a non-zero
   exit, a rewrite from a fragment, a green-but-inert test, secrets in receipts, one entry point
   updated while others are not, and a lower permission read as a higher one.
8. **Final delivery questions.** What is implemented versus only planned? Which receipts actually
   ran? Is user work preserved? Did the run stop at its authority boundary? State blockers plainly.

## Canonical completion signal (owned by lasting-plans 2.0.0)

Every plan this layer hardens MUST carry, in its first 40 lines, both:

- a line `**Status:** draft | approved | in-progress | completed` (start at `draft`/`in-progress`)
- a blockquote line `> **Lasting Plans:** when every task below is done, set the Status line to
  `completed` by running `lasting-plans complete "<this file>"` as the closing step.`

and its closing/receipt section ends with `lasting-plans complete "<plan path>"`. The executor runs
that command as its closing step; the signal is in-file, never a naming scheme.

**End-of-life — never leave a pushed-unmerged docs branch** (waypoint plan-airtight-must-specify,
incident 2026-11-15): when the plan is done,
- plan lives in `~/.claude/plans` → the closing `lasting-plans complete "<plan>"` sets
  `**Status:** completed` and moves the plan to `_ARCHIVED/` in one committed rename (the
  archive backup follows; `auto_sort` does the same automatically after `complete_quiet_days`
  for finished-looking plans). Done — nothing else to reap.
- plan lives in a repo (`docs/superpowers/plans/`) → flip `**Status:**` to `completed` on a
  short-lived `docs/plan-<x>-complete` branch and push it. That docs-only commit must be
  fast-forward merged to the default branch by the user (executors must not merge), or the
  plan moved to `_ARCHIVED/` instead — either way the worktree is removed and the remote
  branch deleted afterwards. Then bump the plugin version and ship through the normal
  release path (`rtc-ship` / `claude plugin update`).

## Writing for the executor

Execution method is NATIVE by standing user decision (2026-11-05): the plan header names
the `executing-plans` skill of the general plan-writing plugin (the one this layer builds on),
the executor implements every task in its own session plus one final
whole-branch review; never offer the subagent-driven alternative at handoff (memory: plans-execute-native).

Write standing rules blunt and numbered: the executor has no incident context, so a ban may outrun its
mechanism there. Keep one authoritative version of the plan; reread the delivered file itself before
handing it over.

## When NOT to use this

- Planning that this session will execute itself, inside one repository, with edits and tests only.
- As a replacement for the base plan-writing skill: decomposition, task granularity and test steps
  come from there.

## Branding (📜)

When you begin working under this skill, lead your first substantive reply with "📜 lasting-plans:" so the user can see which plugin just became active — whichever of the plugin's skills loaded.
