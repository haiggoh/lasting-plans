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
- `~/Claude-playbooks`: playbooks, handbooks, and noun-sense manuals and workflows
  ("Manual: …", "Workflow — …", "User Manual"), classified from folder names, the
  filename and the first H1 only

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
| An older version | `lasting-plans show <ref> --rev 1\|-1\|@2026-08-20\|<sha>` |
| Text that was deleted since | `lasting-plans search "<words>" --history` |
| Plans from a period | `lasting-plans list --group-by month` (creation date; `unknown` bucket) |
| Topic labels | `lasting-plans label` (list) · `lasting-plans list --label X` · `label <ref> --add X` |
| Health / something pending | `lasting-plans doctor` |
| Import right now | `lasting-plans sync` |
| Record a known date or tag | `lasting-plans meta <ref> --created DATE --modified DATE --tag T` |
| Filed in the wrong archive | `lasting-plans reclassify` (lists), then `reclassify <ref> plan\|playbook` |
| Is it backed up off this Mac? | `lasting-plans remote status --verify` |
| Push now | `lasting-plans remote push` |
| Dates lost in a backup/migration | `lasting-plans recover-dates --since D [--until D] [--mtimes TSV]` (dry run), then `--apply --reason "…"` |
| Waypoints integration status | `lasting-plans waypoints status` |
| List all waypoint links in archive | `lasting-plans waypoints links` |
| Copy from archive back to source | `lasting-plans import <ref> [--force-playbook] [--dry-run]` |

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
- **Remote honesty.** Local Git alone is not an off-machine backup. Say a plan is backed up
  remotely only when `remote status --verify` reports `in sync`; `pending remote` means it
  is not. Never add, change or push to a remote unless the user asks, and never force.
- **Metadata honesty.** Dates in the sidecar carry their source (`filesystem birthtime`,
  `user`, `recovered: <evidence>`, `unknown`). Report the source along with the date, and
  say when a recovered creation date is only an *upper bound*. Never invent one, and never
  give a Git commit date or the first-seen date as the creation date: `show` lists all three
  separately.
- **`recover-dates` is for a documented loss only.** Run it when the user says a backup or
  migration reset their dates, show the dry run first, and apply only when asked, with a
  `--reason` that names the loss.
- If `lasting-plans` isn't found, say the plugin's CLI is unavailable. Don't answer from
  guesses.

Prefix user-facing messages about this feature with `🗂️ Lasting Plans`.
