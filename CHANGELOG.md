# CRONOS release history

## v3.0.1 — Security hardening candidate (2026-11-17)

- Enforce per-job session-bound authorization receipts and explicit reapproval for older queue jobs, with a configurable large-batch threshold.
- Add versioned, additive SQLite migrations and owner-boot-ID/PID/lease-based stale recovery.
- Move authorized lyrics from process argv into private FFmetadata, preserving original global media tags.
- Harden log/exception redaction, enforce bounded log entries and 0600 file permissions.
- Cache old engine wheels before updates, store SHA-256 digests, verify before offline rollback and reject tampering.
- Default engine updates and fresh installs fail closed without a verified requirements.lock; unpinned override requires `--update-unpinned --yes`.
- Use isolated candidate venv for locked installs; explicit system-site opt-in for Android native wheel limitations; preserve existing venv on code-only upgrades.
- Split CLI into parser/menus/dispatch/entry compatibility layer. Add integration fixtures, CI script, SECURITY.md and ARCHITECTURE.md.
- Local verification: 88 offline tests with stand-ins, Python 3.13 compilation, wheel build, shell syntax. Full hash lock, Python 3.12, real deps, pip-audit/ruff and Android smoke test remain unverified.



## v3.0.0 — Motion Edition (2026-11-17)

### Brand and compatibility
- Public brand, splash screen, version flag, dialogs and primary launch command are now **CRONOS**.
- New `cronos` CLI entry point; keep `cronos-yt` as a legacy alias for existing shortcuts and share-sheet handlers.
- New source archive extracts into `~/CRONOS`. Existing settings, SQLite queue/history, media directories and the shared venv remain in their previous locations without automatic migration. Automatic private SQLite/settings pre-upgrade backup stays enabled.

### Terminal motion and visual design
- New pure-Python `cronos_yt.motion` module built on Rich Live, with transitory frames and a responsive logo.
- Animated CRONOS letter reveal with block lettering on wide terminals and clean kinetic typography on narrow phones.
- Short animated page transitions, visual menu-selection acknowledgments, status feedback and a motion showcase.
- Style choices **glide**, **pulse**, **typewriter**; speeds **calm**, **normal**, **swift**.
- Added ON/OFF animation, startup intro and explicit reduced-motion preferences, persisted atomically.
- Automatic motion suppression for non-TTY output, inaccessible/dumb terminals, CI and `CRONOS_NO_MOTION=1`. No animations or sleep in the disabled path.
- Added `--motion-preview` (offline), `--no-animation`, and updated the existing `--ui-preview`.
- Rich transfer progress retains pause/resume with a non-spinning reduced-motion variant.

### Engineering
- Kept existing download extraction/authorization/queue/data behavior. No database migration required.
- Improved installer preflight to avoid overwriting unrelated executables; avoided upgrading unrelated Termux packages.
- Added 11 motion/accessibility/regression tests; 72 offline test cases passed in the build container with stand-ins for unavailable yt-dlp and Questionary libraries.
- Real Termux rendering, complete Python 3.12 dependency run, and live authorized download remain unverified until on-device smoke tests.

# Changelog

## 2.1.1 — Reliability hardening (verification-limited)

- Added engine/UI package version snapshot and an import smoke-check after user-initiated `--update`.
- Added best-effort automatic rollback after failed updates and manual `--restore-engine` option; rollback requires access to pinned versions.
- Generated installer backup names from `pyproject.toml` release version instead of a hardcoded suffix.
- Added a one-time post-upgrade note, actionable failed-transfer hints, and approximate MP3 review size when duration is known.
- Added `verify_termux.sh` (offline device smoke suite), and tests covering rollback outcomes, privacy of version snapshots, network-isolated `--ui-preview`, narrow-width boundaries, settings corruption preservation, and SQLite history/queue compatibility.
- **Verification:** 61 tests with 30 subtests pass on Python 3.13 with local test doubles for the unavailable `yt-dlp` and `questionary` packages. Original dependencies and Python 3.12 could not be installed in this environment. Live Android installation, real media downloads, and real v2.0 -> v2.1.1 upgrade remain unverified; wider distribution is not certified.


## 2.1.0 — Mobile UI Edition

- Rebuilt Rich home screen with responsive compact and wide dashboards.
- Added a Quick Download flow with video/music presets and a final review stage.
- Added no-network `--ui-preview` and improved source-quality browsing.
- Added persistent appearance settings: neon/ocean/minimal themes, force compact, clear-screen, hints and clipboard suggestions.
- Reorganized queue tools and library navigation for portrait Termux.
- Adaptive transfer progress for very narrow, standard mobile, and desktop-width terminals.
- Preserved existing v2.0 features, SQLite data format, download folders and upgrade installer.
- Added UI-focused offline regression tests and corrected library path searches using explicit `path:` prefix.


## 2.0.0 — Library Edition (major upgrade)

- Added SQLite-powered searchable local media library, missing-file detection and privacy-safe CSV/M3U exports.
- Added numbered range and title selection for playlists while preserving original indexes.
- Added priority scheduling (0–9) for pending queue items, with additive v1.1 SQLite migration.
- Added optional sidecar subtitles with manual/automatic modes and language selection.
- Added selectable filename styles (title, channel-title, date-title).
- Added Termux environment diagnostics and private SQLite/settings backups.
- Upgraded installer to snapshot existing queue/history/settings before installing app code.
- Expanded interactive menu and v2 command line flags.
- Retained v1.1 download pipeline, storage layout, settings compatibility and history.
- Added offline regression tests for library, exports, queue priorities, migrations, subtitles, backup.


## 1.1.0 — Advanced download queue and terminal dashboard

- Added SQLite-backed persistent queue with status, attempts and resumable recovery.
- Added start, pause, resume, retry, bulk pause/resume and safe queue-entry removal.
- Added cooperative interactive hotkeys: **p** pause, **r** resume, **c** stop.
- Added responsive Rich dashboard with status cards and storage information.
- Added download statistics and local on-disk file size totals.
- Added per-transfer speed limit and concurrent fragment settings.
- Added `--enqueue`, `--run-queue`, `--queue-list`, and `--stats` CLI options.
- Retained v1.0 media destinations, configuration format and download history.
- Added tests for persistence, migration, controller behavior and status transitions.

## 1.0.0 — Initial release

- Interactive yt-dlp video, music, playlist and batch downloads for Termux.
- Audio conversion, video quality selection, FFmpeg merging and media metadata.
- Automated Termux installation, Android storage integration and SQLite history.
