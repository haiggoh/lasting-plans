# Lasting Plans Roadmap

## Current released version

`0.5.0`

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

---

## Planned

### Version 1.0 — Qualification/migration (Phase 9) ⬅ NEXT
- Cross-platform installer/update/uninstaller tests
- Migration path for users with existing Git repo in Claude `plans/`
- Detached backups, privacy/secrets audit
- Two-repo corruption and disaster recovery drill
- Published-version install smoke test
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