# Changelog

## 0.1.1 — 2026-09-29

Fixes from the first run against a real plans folder (199 documents).

- **Classifier:** *playbook* / *handbook* now count only as the leading or trailing word of
  the filename or H1. "…plan and playbook preservation…" was being filed as a playbook.
  *Workflow* is a new trigger word, in noun position only (`Workflow — …`, `… Release
  Workflow`), like *manual*. A folder named `playbooks`, `handbooks` or `workflows`
  (`_PLAYBOOKS/`) now decides on its own.
- **`reclassify`:** a rule change never moves documents on its own. `doctor` lists the ones
  the current rule would file differently, and `lasting-plans reclassify <ref>
  plan|playbook` moves one between the archives, one commit in each, keeping its id.
- **`recover-dates`:** repairs creation and modification dates after a *documented* loss
  (a backup that stored no birth times). You give it the window the wrong dates fell in,
  and it takes the strongest evidence available: backup-verified mtimes, a labelled date
  in the text, the H1, the file name, or an upper bound from the last edit. It only moves
  dates earlier, is a dry run unless `--apply --reason`, and records the evidence.
  Recovered dates are never overwritten by later scans.
- The 1984-01-24 no-creation-date placeholder is recorded as `unknown`, not as a date.

## 0.1.0 — 2026-09-28

First release.

- The preservation engine copies plans from Claude Code's plans folder into two local Git
  archives, `~/Claude-plans` and `~/Claude-playbooks`.
  - Each document gets a stable id and a sidecar with hashes, dates plus their provenance,
    and Finder tags.
  - A source copy disappearing never deletes anything.
  - A hand-edited archive copy is never overwritten; the source version is saved next to
    it.
  - Moves between subfolders are followed.
  - Only the document's own paths are ever staged.
  - Symlinks and escapes out of the source root are ignored.
  - A file that is still being written waits for the next scan.
- Metadata: creation and modification times and Finder tags are captured and applied to
  the archive copy. Tag writes are additive. `meta` records dates from better sources,
  such as old backups.
- Watch-folder LaunchAgent (macOS): kqueue watches on every directory react when a file
  enters, leaves or moves, and a catch-up scan runs every 15 minutes. It runs from a
  stable copy of the code, not the plugin cache.
- The first session after install creates the archives, imports and installs the
  watcher. Opt out with `scheduler uninstall`.
- CLI: status, sync, list, search (full text), show, history, diff, meta, doctor,
  settings, scheduler, watch and setup. Every command takes `--json`. On a TTY, a flat
  menu runs the same commands.
- A skill routes plan questions to the CLI.
