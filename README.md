# 🗂️ Lasting Plans

**Claude Code deletes your plans.** At session start it removes top-level files in its
plans folder (`~/.claude/plans`) that are older than `cleanupPeriodDays`, which defaults to
**30 days**. That is the setting's documented retention behaviour, not a bug. A Git repo
*inside* that folder does not help: the old blobs stay in history, but the working
documents vanish and nothing tells you. Lasting Plans keeps a permanent, visible copy of
every plan somewhere the sweep never looks:

- `~/Claude-plans`: ordinary plans
- `~/Claude-playbooks`: playbooks, handbooks, workflows and manuals

Each is its own **local Git repo**, so every revision is kept. Nothing is ever deleted
when the source copy disappears. It needs no account and no network, and never pushes.
Local Git history is *not* an off-machine backup; say so to yourself too.

## Install

```
/plugin marketplace add haiggoh/get-haiggoh
/plugin install lasting-plans@haiggoh
```

The first Claude Code session after install sets everything up:

1. It creates both archive repos, refusing to touch a non-empty folder that isn't
   already a Git repo, or one nested inside another repo.
2. It imports every plan in your plans folder, subfolders included.
3. On macOS, it installs the watcher LaunchAgent, `com.haiggoh.lasting-plans`.

A one-line notice tells you it happened. To opt out of the watcher:

```
lasting-plans scheduler uninstall                     # removes only its own job
lasting-plans settings set scheduler_enabled false    # and keep it off on later sessions
```

## How it stays current

The watcher is a **watch folder**, not a timer. It holds kqueue watches on every
directory in the source tree and in both archives, so it wakes the moment a file
*enters, leaves, or moves between subdirectories*. A catch-up scan every
`interval_seconds` (default 900 = 15 min) picks up in-place edits, which don't change a
directory, and anything missed while the Mac slept. It runs without Claude Code open.

The LaunchAgent runs a stable copy of the code in `~/.local/share/lasting-plans/`, never
the versioned plugin cache, so a plugin update can't leave it pointing at a deleted path.
The session hook re-stages that copy when the plugin version changes.

## What it guarantees

- **No deletion propagation.** When the source copy disappears (swept or deleted), the
  archive copy stays, and nothing is untracked or committed as a deletion.
- **No silent overwrite.** If you edited the archive copy and the source changed too, the
  source version is saved alongside as `… (source edit <stamp>).md`. A file with the same
  name that is a different document gets `… (2).md`. Prose is never auto-merged.
- **Moves are followed.** Moving a plan between subfolders moves its archive copy and
  keeps its identity and history.
- **Only its own paths are staged.** Unrelated files in an archive stay untracked.
- **Symlinks, hidden files and anything outside the source root are ignored.**
- **Half-written files wait.** A file must be unchanged for 2 s and read identically
  before it is imported.

## Metadata Git can't store

Git records neither creation (birth) time nor Finder colour tags. Each document therefore
has a sidecar, `.lasting-plans/docs/<id>.json`, holding:

- its stable id and source path history
- content hashes
- creation and modification times, **each with its provenance** (`filesystem birthtime`,
  `user`, `recovered: …`, `unknown`). The 1984-01-24 date macOS shows for a file with no
  creation date is recorded as `unknown`, not as a date.
- Finder tags

The archive file itself also gets the dates and tags applied. Tags are **additive**: tags
you put on an archive copy are never removed. After a fresh clone, `lasting-plans meta
<ref> --apply` puts the recorded metadata back on the file. If you know a better date
than the filesystem does (from an old backup, say), record it:
`lasting-plans meta <ref> --created 2026-07-01 --modified 2026-08-03T10:15`.

### Recovering dates after a documented loss

If a backup or migration reset many documents' dates to the moment they were copied,
`recover-dates` repairs them. It never runs on its own: you name the window in which the
wrong dates landed.

```
lasting-plans recover-dates --since 2026-09-24T00:00Z --until 2026-09-25T00:00Z \
    [--mtimes recovery.tsv]                       # dry run: shows every proposed change
lasting-plans recover-dates … --apply --reason "restored from claude-migration backup"
```

For each document whose recorded creation date falls in that window (or is unknown), it
uses the strongest evidence available: a backup-verified modification time from
`--mtimes` (rows with verdict `exact` only), a labelled date near the top of the text
(`**Date:** 2026-08-19`, `Created: …`, `Written: …`), a date in the H1, a date in the file
name, or, failing all of those, the recovered last edit as an **upper bound**. It only ever
moves a date *earlier*, never later than the last edit or today. The evidence is written
into `created_source`, the old value and your `--reason` are kept in `date_recovery`, and
later scans never overwrite a recovered date.

## CLI

`lasting-plans` on a terminal shows a dashboard and a numbered menu. Each choice echoes
the equivalent command and runs the same code. Piped or with a subcommand, it never
prompts.

```
lasting-plans status                  # what's protected, what isn't, watcher state
lasting-plans sync [-v]               # scan once now
lasting-plans list [--type plan|playbook] [--limit N --offset M]
lasting-plans search "words" [--regex]   # FULL text, not previews
lasting-plans show <ref> [--full]
lasting-plans history <ref>           # content vs metadata-only commits
lasting-plans diff <ref> [REV_A [REV_B]]
lasting-plans meta <ref> --created D --modified D --tag T | --apply
lasting-plans reclassify [<ref> plan|playbook]   # no ref: list what the classifier would move
lasting-plans recover-dates --since D [--until D] [--mtimes TSV] [--apply --reason R]
lasting-plans doctor
lasting-plans settings show|set KEY VALUE|reset KEY
lasting-plans scheduler install|uninstall|status
lasting-plans watch [--once]          # what launchd runs
lasting-plans setup [--no-scheduler]  # what the first session runs
```

`--json` on every command. `<ref>` is an id, an id prefix, or a unique path fragment.
Exit codes: 0 ok, 1 error, 2 usage, 3 not found, 4 ambiguous, 5 pending/unhealthy.

Settings live in `~/.config/lasting-plans/config.json`, outside the plugin cache. You can
change the source (`source_dir`; by default it is discovered from `CLAUDE_CONFIG_DIR` /
`plansDirectory`), both archive roots, the interval, and per-file classification
overrides. Unknown keys are preserved.

## Classification

Only the **folder names, filename and first Markdown H1** are read, never the body. A
document is a playbook when:

- it sits in a folder named `playbooks`, `handbooks` or `workflows` (a leading `_` is fine,
  so `_PLAYBOOKS/` counts), or
- its filename or H1 *starts or ends* with *playbook* or *handbook*
  (`Playbook_ …`, `… — Playbook`, `Release Playbook (v2)`), or
- it uses *manual* or *workflow* as a noun (`Manual: …`, `Workflow — …`, `User Manual`,
  `Plugin Release Workflow`, `…-manual.md`).

A mention mid-sentence doesn't count: "…plan and playbook preservation…" is a plan, and so
are `manual-installation-plan.md` and `workflow-fix-plan.md`. Override per file with
`settings set classify_overrides '{"path.md": "playbook"}'`.

A rule change never moves documents on its own. `lasting-plans doctor` lists documents the
current rule would file differently, and `lasting-plans reclassify <ref> plan|playbook`
moves one: it adds it to the other archive and removes it from the first, one commit in
each, with the same id and a `type_history` entry. A reclassified document stays put.

## Platform support (v0.1)

| | Import, CLI, Git | Watcher | Birth time / Finder tags |
|---|---|---|---|
| macOS | ✅ tested | ✅ launchd + kqueue, tested | ✅ tested (birth time via `SetFile`, Xcode CLT) |
| Linux | preview (untested) | manual: run `lasting-plans watch` | recorded as `unknown` / not applied |
| Windows | not supported | none | none |

## Not in v0.1

Remote backup (planned for v0.2, opt-in private remotes only), Waypoints link badges,
reverse import back into Claude's plans folder, and restore-by-id.

## License

MIT
