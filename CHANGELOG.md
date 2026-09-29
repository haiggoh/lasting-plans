# Changelog

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
