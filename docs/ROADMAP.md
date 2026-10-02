# Lasting Plans Roadmap

## Current released version

`1.0.0`

### Version 1.0.0 — Qualification/migration (Phase 9) (2026-10-02) ✅ COMPLETE
- **Migration path:** `lasting-plans migrate [--apply]` detects existing Git repo in Claude's
  plans folder, performs read-only audit of all files, and imports missing files on `--apply`.
  Never deletes or rewrites history.
- **Disaster recovery drill:** `lasting-plans disaster-drill` tests Git history checkout,
  metadata-aware restore, and Finder tag preservation.
- **Privacy/secrets audit:** `lasting-plans privacy-audit` scans archives for potential
  API keys, tokens, passwords, and private keys using regex patterns.
- **Skill update:** documents `migrate`, `disaster-drill`, and `privacy-audit` commands.
- **Tests:** 7 new tests covering migration detection, import of missing files, CLI dry-run,
  disaster drill, and privacy audit.
- **Cross-platform readiness:** local-only forever, no account/network required for core
  functionality; optional private remotes tested.

---

## Completed versions

### Version 0.5.0 — Reverse import and recovery (Phase 8) (2026-10-02) ✅ COMPLETE
- **Reverse import:** `lasting-plans import <ref> [--dry-run] [--force-playbook]` copies a document
  from archive back to the source folder (`~/.claude/plans`). Opt-in only — never automatic.
- **Playbook protection:** playbooks in `Claude-playbooks` require explicit `--force-playbook` to
  import; plans import by default. Source copy never overwritten without confirmation.
- **Divergence detection:** `--dry-run` previews destination and detects if source has diverged
  from last imported hash (conflict = source edited externally since last scan).
- **Sidecar update:** successful import updates `last_import_sha256` and `source_relpath` in sidecar,
  commits if Git identity configured.
- **Skill update:** documents `import` command.
- **Tests:** 5 new tests in `test_engine.py` covering preview, conflict detection, playbook flag,
  CLI dry-run, and full import with apply.

### Version 0.4.0 — Waypoints integration (Phase 7) (2026-10-02) ✅ COMPLETE
- **Waypoints integration:** read `waypoints list --json` and `waypoints archive list --json`
  via documented public CLI (contract 3 / 1), find explicit path/ID links in document
  title/summary/detail, surface `[linked]` badge with status indicator.
- **CLI commands:** `waypoints status` (diagnostics: live/archive counts, contracts, checkout),
  `waypoints links` (list all documents with waypoint links, `--json` for machine output).
- **Status dashboard:** includes waypoints integration line with live/archive counts and contracts.
- **Show command:** displays `[linked ✓]` for done waypoints, `[linked ⏳]` for waiting, `[linked]`
  for open, with title preview.
- **Skill update:** documents `waypoints status` and `waypoints links` commands.
- **Tests:** 8 new tests in `tests/test_waypoints.py` covering diagnostics, loading, link extraction,
  status/badge formatting.
- **Version consistency:** `VERSION` file and `docs/ROADMAP.md` added; all four version sources
  (plugin.json, CHANGELOG, ROADMAP, VERSION) now agree and are validated by test.

### Version 0.3.0 — Library usability (2026-09-29) ✅ COMPLETE
- Revisions: `show --rev` and `diff REV_A [REV_B]` with N, -N, first, latest, @YYYY-MM-DD, or sha
- Historical search: `search --history` finds text in any committed revision
- Dates kept apart: `show` reports created (with provenance), first seen, and last content edit separately
- Grouping: `list --group-by month|year|day` groups by creation date with `unknown` bucket last
- Labels: explicit topic labels stored in sidecar, portable across OSes
- Search paging: `search` gains `--offset`

### Version 0.2.0 — Private remotes (2026-09-29) ✅ COMPLETE
- Optional private remote per archive (`create-github`, `set`, `push`, `status`, `off`, `clone`)
- Folder tags mirrored to archive
- Tool resolution guard

### Version 0.1.0 — First release (2026-09-28) ✅ COMPLETE
- Preservation engine copies plans to `~/Claude-plans` and `~/Claude-playbooks`
- Watch-folder LaunchAgent (macOS)
- CLI: status, sync, list, search, show, history, diff, meta, doctor, settings, scheduler, watch, setup

---

## Post-1.0 Candidate Features

- Generated findable index
- Saved searches (e.g., open-linked playbooks)
- Explicit promote/demote between repos with provenance-safe move
- Duplicate-content suggestions, never auto-delete
- User-supplied topical labels
- Optional privacy-safe export/import
- Offline remote-queue visibility
- Periodic recovery drills
- Conflict review queue
- Manual backup destination beyond Git remotes