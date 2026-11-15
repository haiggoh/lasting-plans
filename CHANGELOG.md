# Changelog

## [2.0.3] — 2026-11-16 — hotfix: live-migration robustness (rehearsed on a full copy of live state)

- `move_path`: paths not in HEAD (untracked/staged-new wedge copies) move via
  os.rename+add instead of `git mv` ("not under version control"); stale `.lp-case-tmp`
  temps from crashed runs are removed first (git rm when tracked).
- `commit_staged_paths`: no index_case mapping (it collapsed rename pairs); the dirty
  check only fails on staged leftovers — unstaged deletions of moved-away paths are
  committed by the next pass.
- `commit_paths` keeps its index_case mapping (wrong-case commits) — a refactor had
  briefly removed it.
- `migrate._step_relocate` maps the rescue subdir prefix through `archive_rel_for`
  (backup never mirrors it) and only `git add`s paths that exist in the archive.
- doctor's "archive documents present" carries the missing list as a real list
  (comma-containing filenames no longer split); new `stale_wedge` repair kind repoints
  sidecars from `(N).md`/`.lp-case-tmp` junk to the tracked base and git-rms the copy.

## [2.0.2] — 2026-11-15 — hotfix

- `gitrepo.move_path` no longer calls `git mv` for paths not in HEAD (staged-new or
  untracked wedge copies): those move via os.rename + add. The live migration's
  canonical re-case hit 'not under version control' on an untracked `_playbooks/… (2).md`.
  Regression test: test_move_path_staged_but_never_committed (mutation-checked).

## [2.0.1] — 2026-11-15 — hotfix

- `gitrepo.commit_paths` no longer fatals on staged-deleted paths (gone from index AND
  disk): they are skipped for `git add` but kept in the `commit --only` pathspec, so the
  deletion still commits. This unblocked the live 2.0.0 migration wedge (a playbook doc
  staged-deleted by 1.3.0). Regression test: test_commit_paths_skips_add_for_staged_deleted_paths.

## [2.0.0] — 2026-11-15 — BREAKING layout change + self-healing

**BREAKING:** one archive instead of two. `~/Claude-plans` now mirrors the source layout
exactly; `type` (plan/playbook) is a sidecar label, not a location. On upgrade, the watcher
or session hook migrates automatically (`lasting-plans repair` runs it now): both archives'
history is merged into `~/Claude-plans`, every document moves to its source path, and
`~/Claude-playbooks` becomes a symlink to `~/Claude-plans/_PLAYBOOKS` (the old folder is
moved, never deleted, under `~/.local/state/lasting-plans/retired-archives/`). Config keys
`plans_root`/`playbooks_root`/`remotes.plan` resolve read-compatibly to `archive_root`/
`retired_archives`/`remote`; the migration writes the new keys (`layout: 2`). The GitHub
repos are untouched. `remote` commands drop the `plan|playbook` kind (still accepted,
ignored).

- **Background auto-repair** on every watcher/hook pass: fixers for every foreseeable
  failure class (migration, uncommitted, no-identity, archive-missing with
  restore/restore-unless-trashed/honor policies and Trash checks, corrupt sidecars,
  type mismatches, empty folders, watcher down). The SessionStart banner speaks only when
  auto-repair could not fix something (after `alert_min_attempts`/`alert_after_hours`) or
  for emergencies — routine pending items no longer put tasks on your plate. Opt out in the
  menu (`behaviour`) or `settings set auto_repair off`.
- **Case-safe Git**: case-only renames are single `R` commits everywhere (`gitrepo.index_case`,
  `move_path`, `commit_staged_paths`); the 1.x `_PLAYBOOKS`/`_playbooks` wedge bug is fixed.
- **Completion + sorting**: canonical in-file `**Status:**` signal (+ plan-airtight plans
  carry it and end with `lasting-plans complete "<plan>"`); `lasting-plans complete` moves a
  plan to `_ARCHIVED/` now; automatic sort moves completed plans to `_ARCHIVED/`, playbooks
  to `_PLAYBOOKS/`, HISTORICAL playbooks to `_ARCHIVED/` — moves only, committed as renames,
  sticky user overrides honored.
- **Cleanup protection**: top-level plans at risk of Claude Code's 30-day sweep are moved to
  `_SAVED-FROM-CLEANUP/` before it deletes them (dates/colour labels kept — verified), and
  anything it already took is put back from the archive (committed as a move, metadata
  re-applied). The backup never mirrors the rescue folder. `cleanup_protection`
  (before/after/off), `complete_quiet_days`, `alert_after_hours`, `alert_min_attempts`,
  `archive_deletions`, `auto_sort`, `auto_repair` settings; `behaviour` menu.
- New `repair [--dry-run] [--json]` command (exit 5 when something remains); `doctor` shows an
  auto-repair section; `status` counts recent auto-fixes. `migrate` (source-repo import) is
  unchanged.
## [1.3.1] — 2026-11-15

### Added — Phase 5 Wave C: committed portable package (COORDINATION C1/C2)

- New `scripts/build-portable.py` (from the reviewed pilot pattern) generates the committed
  `portable/` package: same-name manifest, VERSION surface, the skill, the SessionStart hook,
  the CLI at `scripts/lasting-plans` (moved from `bin/`), and the 14-module
  `lib/lasting_plans/` closure at the portable ROOT — both the CLI and the hook resolve it as
  `dirname(HERE)/lib`, which is one level up from `scripts/` and `hooks/` alike, so the
  verbatim copies work unchanged. Emits `portable/PORTABLE-BUILD.json`
  (haiggoh-portable-build/1) and a deterministic dist zip.
- `tests/test_portable.py` pins freshness, same-name manifest, no `bin/`, the host->portable
  set (byte-identical), closure, C2 schema, deterministic zip, and a functional check that
  the portable CLI lists its full subcommand tree from the portable root.

## [1.3.0] — 2026-11-14

### Added — `plan-airtight`, the execution-safety layer for handed-off plans

- New skill `skills/plan-airtight` (+ `references/plan-template.md`): hardens a plan — a NEW one
  before handoff, or an EXISTING one — that will be executed by a different executor, crosses
  permission boundaries (publish/merge/tag/release/deploy/spend), or touches shared or live state.
  Adds the authority matrix, a forced Phase 0 preflight, receipts with a known-bad discriminant,
  side-effect classification, and an adversarial review. Ported from run-to-completion's
  `writing-execution-plans` (waypoint run-to-completion-rename; user decision 2026-11-13: name =
  plan-airtight, home = lasting-plans); the rtc copy is removed in run-to-completion 1.6.0.
- plugin.json description widened to the user-approved text ("plans that last — kept safe AND made
  dependable"); the same text lands in get-haiggoh's marketplace.json + approved-descriptions
  record, and the catalog's adds count moves to 2 skills.

## [1.2.2] — 2026-10-31

## [1.2.2] — 2026-10-31

### Changed — description rewritten to current capabilities (rtc-1.0.0 plan, Part B2)

- plugin.json description set to the user-approved text
  (2026-10-31-approved-plugin-descriptions.json); identical text lands in the
  get-haiggoh catalog in the same rollout. Version 1.2.1 → 1.2.2.

## [1.2.1] — 2026-10-31

### Changed — About-mark alignment (emoji branding rollout, Task 13)

- The GitHub About mark is 📜; the code's `PREFIX` used 🗂️. `PREFIX` is now
  `📜 Lasting Plans`, which brands every user-facing emit at once: the SessionStart
  hook's systemMessage (actionable notes only — silent-on-success stays silent), all
  CLI `PREFIX: …` lines, the `status` banner, and the `--help` description. README h1
  and plugin.json description carry 📜; SKILL.md gained the standard ≤3-line
  `## Branding (📜)` invocation-attribution section.
- Tests: new tests/test_branding.py pins `PREFIX == "📜 Lasting Plans"` exactly, the
  `--help` banner (📜 present, 🗂️ gone), and the `status` first line. RED→GREEN,
  mutation-checked. R1: no fleet consumer parses the old glyph.
- Version 1.2.0 → 1.2.1 (plugin.json, lib __version__, VERSION, CHANGELOG, ROADMAP).

## [1.2.0] — 2026-10-03

A `shortcuts` file at the plugin root declares `lasting-plans`, so `get-haiggoh` (0.8.0 or
later) can put it on your own shell `PATH` through a version-independent shim.

## [1.1.0] — 2026-10-02

Post-1.0 features: saved searches, duplicate detection, manual backup destination.

- **Saved searches:** `search-save`, `search-list`, `search-run`, `search-rm` — save named
  searches with full query parameters (regex, history, type, labels) for instant reuse.
- **Duplicate detection:** `duplicates [--threshold N] [--exact-only]` finds exact SHA256
  duplicates and near-duplicates via Jaccard similarity on token sets. Supports threshold
  tuning and exact-only mode.
- **Manual backup destination:** `backup <path> [--kind plan|playbook]` mirrors archive(s)
  to a local folder (external drive, etc.) without Git — copies files and sidecars directly.
- **Skill update:** documents `search-save/run/list/rm`, `duplicates`, `backup` commands.
- **Tests:** 2 new tests covering saved search CRUD and duplicate detection CLI.

## [1.0.0] — 2026-10-02

Qualification/migration (Phase 9).

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

## [0.5.0] — 2026-10-02

Reverse import and recovery (Phase 8).

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

## [0.4.0] — 2026-10-02

Waypoints integration.

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

## [0.3.0] — 2026-09-29

Library usability.

- **Revisions:** `show --rev` and `diff REV_A [REV_B]` take `N` (1 = first imported text),
  `-N`, `first`, `latest`, `@YYYY-MM-DD` or a sha. Only text-changing commits count, so
  moves, tag and label changes, and empty scans don't. `history` numbers each content
  revision.
- **Historical search:** `search --history` finds text in any committed revision (case
  insensitive), and marks hits that exist *only* in older revisions.
- **Dates kept apart:** `show` reports created (with its provenance), first seen, and last
  content edit separately, plus the update count and updates per 30 days. A commit date is
  never used as a creation date.
- **Grouping:** `list --group-by month|year|day` groups by creation date, with an
  `unknown` bucket last.
- **Labels:** `label <ref> --add/--remove` for your own topic labels (validated, portable,
  stored in the sidecar), `label` lists them with counts, and `list --label` filters.
- `search` gains `--offset` for paging.

## 0.2.0 — 2026-09-29

- **Optional private remote per archive** (`lasting-plans remote …`): `create-github`
  makes a PRIVATE repo via `gh`, `set` takes any Git URL after a privacy check (a public
  GitHub repo is refused), and `push`, `status [--verify]`, `off` and `clone` do the rest.
  A push counts only once the remote's tip is read back and matches. Rejected, failed and
  offline pushes stay `pending remote` and make `status` exit 5. Nothing is ever forced.
  Auto push after each committing scan is the default once a remote is set.
  `remote clone` restores an archive on a new machine and re-applies dates and tags.
- **Folder tags:** Finder tags on source folders are mirrored onto the archive folders,
  recorded in `.lasting-plans/folders.json` (additive), and restored by `clone`.
- **Tool resolution guard:** system tools are run by absolute path from one module
  (`tools.py`), and a test fails the build if any other module runs one by bare name.
  `doctor` notes when your PATH shadows a system tool, such as pipx's `xattr`.

## 0.1.2 — 2026-09-29

- `recover-dates` now also repairs documents that 0.1.0 had already recorded with the
  1984-01-24 no-date placeholder, giving them their last modification as an upper bound.
  Search for them with `--since 1984-01-23 --until 1984-01-26`.
- `scheduler install` now writes the staged-code version stamp itself, so a manual
  re-install no longer leaves it reporting the old version.

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
