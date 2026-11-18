# CRONOS · Termux

**دليل التثبيت والتشغيل بالعربية: [افتح الشرح الكامل خطوة بخطوة](README.ar.md).**

CRONOS مشروع مفتوح المصدر لتنزيل الفيديو والصوت داخل Termux على أندرويد، مع اختيار الجودة والصيغة، وقوائم تشغيل، وطابور محفوظ، ومكتبة محلية وواجهة طرفية متحركة. يعمل دون روت أو خادم خاص.

**حالة 3.0.1:** التثبيت الجديد ينتظر اكتمال ملف الاعتماديات المقفل. الدليل يشرح تجهيز Termux، وجلب المشروع عبر Git أو ZIP، وترقية تثبيت سابق يعمل، والتشغيل والأوامر والطابور والإعدادات والنسخ الاحتياطي وحل الأخطاء. تحديث شيفرة المشروع من GitHub يختلف عن تحديث محرك التنزيل عبر `cronos --update`.

| ابدأ من هنا | المحتوى |
|---|---|
| [التثبيت والتشغيل بالتفصيل](README.ar.md) | مساران واضحان للتثبيت الجديد والترقية، مع رسائل الأخطاء الفعلية وأمثلة الأوامر. |
| [التغييرات المنشورة](CHANGELOG.md) | ما تغيّر وحالة التحقق من كل إصدار. |
| [تعليمات صيانة المشروع ونشره](AGENTS.md) | نشر تحديثات مشروع CRONOS المنجزة هنا في المستودع نفسه والتحقق من وصولها. |

**Version 3.0.1 · Verification candidate · MIT license**

[العربية](README.ar.md) · [Changelog](CHANGELOG.md) · [Architecture](ARCHITECTURE.md) · [Security status](SECURITY.md)

Animated video and music downloading in the Android terminal.

## Repository status

This repository contains the CRONOS 3.0.1 source project. It is a verification candidate: fresh installation is blocked by the intentionally unfinished dependency lock. Existing working 3.0.0 installations can use the code-only upgrade described below. Android device validation and a reviewed dependency lock are still required before a stable release.

## Get the source

```bash
pkg install -y git
git clone https://github.com/KRONOSERA/CRONOS-Termux.git
cd CRONOS-Termux
```

Review the installation status below before running `bash install.sh`. If you cloned this repository, use its `CRONOS-Termux` folder wherever the archive instructions refer to `~/CRONOS`.

## About CRONOS

**CRONOS** is a free, open-source Android Termux video/music downloader built with Python 3.12+, Rich, Questionary, yt-dlp, FFmpeg, SQLite and Node.js. **No root, ads, accounts, subscriptions or cloud servers.** The application is now branded **CRONOS**, without “YT” in the welcome screen, menus, CLI version banner, or launcher.

> **Authorized media only:** Save only videos or audio you own, have permission to download, or are licensed to retain. This application does not bypass DRM, authentication, private video access, geo restrictions or other access controls. Respect the platform's terms and content licenses.

## v3.0.1 security hardening status

This release is **a verification candidate, not a broadly distributable locked build**. It preserves the animations and media engine from v3.0.0 and adds session-bound download authorization receipts, additive SQLite schema versions, boot-aware leases, private FFmetadata lyrics, stronger redaction, an isolated installation path, offline wheel-cache rollback verification, a split CLI, and security tests. Existing queued jobs are *not* automatically granted authorization; they need fresh affirmation. Details: [SECURITY.md](SECURITY.md), [ARCHITECTURE.md](ARCHITECTURE.md).

**Important supply-chain limitation:** The offline build environment could not fetch direct/transitive PyPI dependencies or their official SHA-256 files. `requirements.lock` is therefore deliberately a fail-closed placeholder, **not a usable lock**. Fresh locked installs and `cronos --update` are blocked until a networked maintainer generates, reviews, audits, and ships a real lock. Existing v3.0.0 installations can upgrade just the local CRONOS Python code by reusing the installed dependencies without contacting the Python index. Do not present this source archive as a fully locked security release until the lock is completed.

## v3.0 — Animated terminal redesign

CRONOS now presents a **letter-by-letter animated startup**, followed by an animated homepage and subtle motion effects. Effects are rendered with **Rich Live** in the terminal; there is **no GUI overlay, external image dependency or special font**. Effects use transient displays so your existing terminal scrollback survives.

- **CRONOS intro**: a mobile-friendly kinetic wordmark; larger terminals reveal a six-letter block logo. A moving line and color shifts accompany the reveal.
- **Navigation transitions**: short sweeping, pulsing or typing transitions on entering different screens, with repeated redraws debounced.
- **Selection feedback**: a brief animated selection acknowledgment, and status pulses for completion and errors. Existing questionary arrow-key and `j`/`k` focus movements remain interactive.
- **Progress**: the existing live Rich transfer progress, speed, ETA, pause, resume and cancellation controls remain; a loading spinner identifies metadata inspection.
- **Motion customization**: `glide`, `pulse`, `typewriter` styles; `calm`, `normal`, `swift` speeds; intro ON/OFF; all animations ON/OFF; separate *reduced motion* mode.
- **Accessibility and performance**: animations are disabled automatically when output is redirected, there is no real terminal, `TERM=dumb`, `CI=1`, or `CRONOS_NO_MOTION=1`. Reduced-motion mode disables decorative animation; transfers still update their progress numerically. Animations are intentionally short and capped at a few frames to avoid excess CPU and flicker.
- **Two offline previews**: `cronos --ui-preview` draws the home dashboard; `cronos --motion-preview` plays the intro, a screen transition and confirmation, *without network requests*.

**Termux limitation:** Text terminals cannot provide full Android-native animation. The questionary menu highlight moves immediately as you press the navigation keys; ambient animation is shown between prompts rather than continually redrawing behind an active keyboard prompt (which could corrupt your input). Timing depends on terminal size, font and Android performance.

## Safe upgrade from CRONOS 3.0.0

1. Finish all active downloads, exit the application, and close other sessions running it.
2. Download **`CRONOS-v3.0.1.zip`** to the phone's `Download` folder.
3. In Termux run:

```bash
termux-setup-storage
pkg install -y unzip
cd ~
unzip -oq ~/storage/downloads/CRONOS-v3.0.1.zip
cd ~/CRONOS
bash install.sh
```

4. Launch with **`cronos`**. The previous command `cronos-yt` remains a compatible alias, and any existing Android share handler will continue working. The old **`~/CRONOS-YT`** *source-code directory* is left untouched (and can be removed manually later if you choose). The new source is in **`~/CRONOS`**.

**No data migration is forced.** The upgraded Python package still uses the existing private configuration, history, queue and virtualenv directories under `~/.config/cronos-yt`, `~/.local/share/cronos-yt`, and `~/.local/state/cronos-yt`. Existing video/audio files remain inside the original `Movies/CRONOS-YT` and `Music/CRONOS-YT` locations (or your customized destinations). These legacy *internal folder names* are kept deliberately to avoid splitting or losing your collection. Do not move or rename them unless you also change the output destinations in settings.

Before modifying the Python environment, the installer backs up SQLite and settings into a private `pre-v3.0.1-<timestamp>.zip` at `~/.local/state/cronos-yt/backups/`. User media is never deleted. The installer intentionally avoids upgrading unrelated Termux packages.

## Commands

```bash
cronos                         # Main interactive application, animated when in a TTY
cronos --motion-preview        # Network-free animation showcase
cronos --ui-preview            # Network-free home dashboard
cronos --no-animation          # Motion-free session; does not change saved preferences
CRONOS_NO_MOTION=1 cronos      # Environment-level motion override
cronos --doctor                # Local device diagnostics
cronos --check                 # Check runtime dependencies
cronos --backup                # Private backup of database and settings
cronos --stats                 # Local history statistics
cronos --library              # Search/list saved media
cronos --queue-list           # Inspect queue
cronos --update                # Update from a reviewed hash-pinned requirements.lock only
cronos --update-unpinned --yes # Explicit higher-risk update; displays exact wheel versions
cronos --run-queue --yes --confirm-queued # Renew older queued authorizations
cronos --confirm-large-batch  # Additional approval for batch size over threshold
cronos --restore-engine        # Reinstall saved engine versions (requires availability)
cronos --install-share-handler # Optional Termux share handler (no overwrite)
cronos --version
```

### Generating a candidate pinned lock on Termux (maintainer step)

The shipped `requirements.lock` intentionally contains no invented checksums. On a networked Termux device, review `requirements.in` first, then run:

```bash
cd ~/CRONOS
CRONOS_TRUST_INDEX=1 bash scripts/generate_lock.sh
# Inspect the resulting pinned versions/hashes in requirements.lock
bash scripts/ci_check.sh  # requires pip-audit + ruff/pyflakes; no media download
bash install.sh
```

`pip-compile` uses the configured package index to generate SHA-256 hashes, but this is a **trust-on-first-use operation** requiring independent review; it does not validate upstream publisher intent. The candidate lock should be checked on both supported Python versions and Android architecture before public distribution. `CRONOS_SYSTEM_SITE=1 bash install.sh` is an **opt-in fallback** only when native packages such as Brotli or PyCryptodome cannot be resolved as compatible Android wheels. This installs Termux's `python-brotli` and `python-pycryptodomex` packages and exposes system site packages to the candidate venv; for reproducibility, lock versions must match those installed native packages. No `pkg update` or `pkg upgrade` is run by the installer.

### Adjusting animation preferences

Open **Tools & settings → Appearance & motion**. You can change colors, animated intro, effects, speed, reduced motion, compact layout, clear-screen behavior, tips and clipboard suggestions. Changes are stored locally and saved atomically. Animated startup is deliberately suppressed in piped or scripted commands.

For motion-sensitive users, choose **Reduced motion: ON**. The setting survives app restarts. The application remains fully usable with animation completely disabled.

## What the downloader already supports

- **Videos**: MP4 with H.264 preference and merged audio/video using FFmpeg; quality presets 144p–4K when the source actually offers them; selectable FPS preference.
- **Audio**: MP3, M4A, OPUS, FLAC and WAV, optional artwork and tags; MP3 output bitrates 128/192/256/320 kbps. Lossy-to-320kbps conversion does not create missing audio detail.
- **Playlists**: YouTube videos, Shorts, YouTube Music, numbered selection (`1-5,9`), title filters, per-playlist folders, preserved original numbering, download limits, and duplicate skipping.
- **Queue**: persisted SQLite queue, priorities 0–9, pause/resume/cancel, retries, safe recovery from interruption where yt-dlp supports resuming, configurable concurrency, bandwidth caps and download progress.
- **Library**: local title/video ID search, explicit `path:` search, missing-file detection, CSV/M3U export, stats and backups.
- **Security**: explicit authorization confirmation for download/queue operations; non-interactive commands require `--yes`, and queued jobs require fresh authorization if from a previous session; sensitive URL queries, opaque path tokens and headers are redacted from error logs. No cookies, auth bypass, eval or untrusted `shell=True` calls.

Example of an explicitly authorized download:

```bash
cronos --url 'https://www.youtube.com/watch?v=YOUR_VIDEO_ID' --mode video --quality 720 --yes
cronos --url 'https://www.youtube.com/watch?v=YOUR_VIDEO_ID' --mode music --format mp3 --bitrate 192 --yes
cronos --playlist --items 1-5,9 --url 'https://www.youtube.com/playlist?list=YOUR_PLAYLIST' --mode music --yes
```

Only run those commands for media you have permission to save.

## Verify on your Android phone

```bash
cd ~/CRONOS
bash verify_termux.sh
cronos --motion-preview
```

The verification script checks the installed packages, runs the complete offline `unittest` suite, previews the home without networking, checks Termux dependencies, and compiles source. The preview is non-destructive and does not download media.

For **manual on-device validation**, check that the intro reveals CRONOS, selection effects are readable at portrait width, each of the three motion styles works, reduced motion disables decorative effects, settings survive restart, your existing library and queue remain visible, and a permitted download still completes. A live YouTube test may be affected by upstream extractor changes and network conditions.

**Test disclosure:** The release was statically checked and its offline tests were run on Python 3.13 using local test stand-ins for `yt-dlp` and `questionary` because those packages were unavailable in the build container. Those tests do not replace a clean Python 3.12 install with real dependencies or actual Android device testing.

## Troubleshooting

- **`cronos: command not found`**: rerun `cd ~/CRONOS && bash install.sh`, then reopen Termux. The old `cronos-yt` command also works.
- **Intro flickers, stutters or pushes content off-screen**: change animation speed to `swift`, turn on compact layout, or set reduced motion. Verify your Termux font fits your screen.
- **Terminal scrollback looks corrupted**: run `reset` then `cronos --no-animation`. CRONOS uses Rich transient displays rather than a permanent alternate screen.
- **No animation in redirected output**: intentional; run inside an interactive Termux session. Clear `CRONOS_NO_MOTION` and ensure `TERM` is not `dumb`.
- **Permission denied writing media**: run `termux-setup-storage` and grant Android permission, then use the built-in Doctor.
- **YouTube extraction error**: run `cronos --doctor`, then `cronos --update`; if the updated engine stops working, try `cronos --restore-engine`. Restoration is best effort and may require network access.
- **Playlist or video unavailable**: the app cannot bypass restricted/private media. Try only content you are authorized to save.
- **Existing files missing**: check your original `Movies/CRONOS-YT` and `Music/CRONOS-YT` directories. The upgrade does not relocate them.

## Build a source ZIP yourself

From the parent of the source folder, run:

```bash
zip -r CRONOS-v3.0.1.zip CRONOS/ -x '*/__pycache__/*' '*.pyc' '*.sqlite3' '*.part' '*.ytdl' '*/.venv/*'
```

The project is MIT-licensed. See `CHANGELOG.md`, `LICENSE` and `tests/`. The Python package and data directory retain the historical internal `cronos_yt` / `cronos-yt` identifiers **only for backward compatibility**; the product name and user launcher are now CRONOS.

## Security verification matrix

| Target | Offline unittest | Real dependency integration | Installation / rollback / smoke |
|---|---|---|---|
| Python 3.12 (clean environment) | Required; not yet executed here | `CRONOS_INTEGRATION=1 python -m unittest discover -s tests/integration` | Must be verified on a Python 3.12 Termux device |
| Python 3.13 (build environment) | 88 tests passed with temporary yt-dlp / Questionary stand-ins | Not run: real dependencies unavailable | Wheel build and shell syntax validated; Android not accessible |
| Android Termux | Run `bash verify_termux.sh` using actual venv | Opt-in without media/network traffic | Upgrade v3.0.0 → v3.0.1, queue reauthorization, and a consent-gated authorized media test remain manual |

The CI runner `bash scripts/ci_check.sh` compiles source, runs offline tests, optionally runs real-dependency integration tests, audits a valid lock with `pip-audit`, and lints with Ruff/pyflakes. It intentionally fails if a reviewed lock or the audit/lint tools are missing; it does not silently mark those checks as passing.

## Legal and platform terms

Users are responsible for following YouTube's terms of service, applicable copyright laws, and license permissions. CRONOS does not provide legal advice. Only download material you have the right to save, and do not use the tool to bypass technical restrictions or access controls.

## Migration note for existing v3.0.0 users

Finish active transfers and close other CRONOS sessions before upgrading. The local installer creates an SQLite/settings snapshot and stages a new Python environment; it preserves `~/.config/cronos-yt`, `~/.local/share/cronos-yt`, `~/.local/state/cronos-yt`, `Movies/CRONOS-YT`, and `Music/CRONOS-YT`. Both `cronos` and `cronos-yt` remain available. Queue and authorization tables receive additive migrations; **legacy queued jobs are not discarded**, but the next queue run requires explicit re-authorization. No manual media relocation or database conversion is necessary. The lock-generation step is only needed for fresh locked installation or locked engine updates, not for a code-only upgrade reusing an already-working v3.0.0 environment.
