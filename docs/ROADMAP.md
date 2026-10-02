# Lasting Plans Roadmap

## Current released version

`0.4.0`

### Version 0.4.0 — Waypoints integration (2026-10-02) ✅ COMPLETE
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

---

## Planned

### Version 0.5 — Reverse import and recovery (Phase 8) ⬅ NEXT
- User drops ordinary plan into `Claude-plans`: opt-in explicit copy to Claude Code's configured plans folder
- Playbook stays only in `Claude-playbooks` unless explicitly requested
- Copies not symlinks; verify no loops, track last common hashes, never overwrite divergent source
- Restore by stable ID: dry-preview target, refuse differing destination by default
- Require exact explicit approval to replace; restore metadata supported by OS and report unsupported fields
- Missing/corrupt/incompatible Waypoints yields `unknown` with diagnostics, never false zero
- **Receipt 7:** fixture Waypoints contracts + tag round trip on macOS and no-op/portable equivalents on other OSes

### Version 0.5 — Reverse import and recovery (Phase 8)
- User drops ordinary plan into `Claude-plans`: opt-in explicit copy to Claude Code's configured plans folder
- Playbook stays only in `Claude-playbooks` unless explicitly requested
- Copies not symlinks; verify no loops, track last common hashes, never overwrite divergent source
- Restore by stable ID: dry-preview target, refuse differing destination by default
- Require exact explicit approval to replace; restore metadata supported by OS and report unsupported fields
- **Receipt 8:** seeded conflicts, dry-run and cancellation preserve bytes/tags

### Version 1.0 — Qualification/migration (Phase 9)
- Cross-platform installer/update/uninstaller tests
- Migration path for users with existing Git repo in Claude `plans/`
- Detached backups, privacy/secrets audit
- Two-repo corruption and disaster recovery drill
- Published-version install smoke test

---

## Additional candidate features (deliberately outside v0.1)
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