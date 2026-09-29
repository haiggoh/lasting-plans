---
name: lasting-plans
description: "Use when the user asks about their plans or playbooks — finding, reading, searching, comparing or restoring one, asking where a plan went, why a plan disappeared from ~/.claude/plans, when a plan was created or last changed, or whether their plans are backed up. Answers through the `lasting-plans` CLI, which reads the permanent Git archives in ~/Claude-plans and ~/Claude-playbooks."
---

# 🗂️ Lasting Plans

Claude Code deletes top-level plan files in its plans folder (`~/.claude/plans`, or
`plansDirectory`, or `$CLAUDE_CONFIG_DIR/plans`) once they are older than
`cleanupPeriodDays` (default 30). Lasting Plans copies every plan into its own archive
before that happens:

- `~/Claude-plans`: ordinary plans
- `~/Claude-playbooks`: playbooks, handbooks and noun-sense manuals ("Manual: …",
  "User Manual"), classified from the filename and first H1 only

Each archive is its own local Git repo. A sidecar (`.lasting-plans/docs/<id>.json`) per
document records its stable id, source path, content hashes, creation and modification
times with their provenance, and Finder tags. Git itself cannot store those.

## How to answer

Query the CLI. `lasting-plans` is on the Bash PATH. Don't read the archive by hand, and
don't dump the whole library into context.

| User wants | Run |
|---|---|
| Is everything safe? | `lasting-plans status` |
| Find a plan by topic | `lasting-plans search "<words>"` (full text, not previews) |
| List | `lasting-plans list [--type plan\|playbook] [--limit N --offset M]` |
| Read one | `lasting-plans show <id-or-name-fragment> [--full]` |
| What changed | `lasting-plans history <ref>` / `lasting-plans diff <ref> [REV_A [REV_B]]` |
| Health / something pending | `lasting-plans doctor` |
| Import right now | `lasting-plans sync` |
| Record a known date or tag | `lasting-plans meta <ref> --created DATE --modified DATE --tag T` |

Add `--json` for machine-readable output. Exit codes: 3 = no match, 4 = ambiguous
reference (it lists the candidates, so ask which one or narrow the query), 5 = something is
pending or unhealthy.

## Boundaries

- **Read-only unless asked.** Searching, listing and showing never change anything. Don't
  turn a "where is my plan" question into a restore, a `meta` write or a settings change.
- **It never deletes.** When a plan disappears from `~/.claude/plans`, its archive copy
  stays. If a user asks why a plan vanished, the sweep is the usual reason; `status` counts
  how many archived plans outlived their source.
- **Conflicts keep both copies.** If the archive copy was edited and the source changed
  too, the source version is saved next to it as `… (source edit <stamp>).md`. Merging the
  two is the user's call.
- **Local only.** The archives are local Git repos. That is not an off-machine backup, and
  v0.1 has no remote support. Never claim a plan is "backed up" to the cloud.
- **Metadata honesty.** Dates in the sidecar carry their source (`filesystem birthtime`,
  `user`, `unknown`). Report the source along with the date. Never invent one.
- If `lasting-plans` isn't found, say the plugin's CLI is unavailable. Don't answer from
  guesses.

Prefix user-facing messages about this feature with `🗂️ Lasting Plans`.
