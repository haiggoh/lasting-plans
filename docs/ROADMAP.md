# Lasting Plans Roadmap

## Current released version

`0.3.0`

### Version 0.3.0 — Library usability (2026-09-29)
- Revisions: `show --rev` and `diff REV_A [REV_B]` with N, -N, first, latest, @YYYY-MM-DD, or sha
- Historical search: `search --history` finds text in any committed revision
- Dates kept apart: `show` reports created (with provenance), first seen, and last content edit separately
- Grouping: `list --group-by month|year|day` groups by creation date with `unknown` bucket last
- Labels: explicit topic labels stored in sidecar, portable across OSes
- Search paging: `search` gains `--offset`

---

## Planned

### Version 0.4 — Waypoints and portable status (Phase 7) ⬅ NEXT
- Read `waypoints list --json` and `waypoints archive list --json` via documented public CLI
- Find explicit path/ID links in document title/summary/detail
- Surface `[linked]` as display badge (not filename rewrite)
- Open linked item → yellow presentation tag on macOS
- Only done/archived links → green; mixed → yellow with all statuses shown
- Portable sidecar/CLI label authoritative on Linux/Windows
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