#!/data/data/com.termux/files/usr/bin/bash
# CRONOS security-hardening installer. Idempotent: does not delete personal media or configuration.
set -Eeuo pipefail
umask 077  # backups, settings and snapshot notices are private

printf '\033[1;35m\n  CRONOS v3.0.1 • Security Hardening\033[0m\n\n'
if ! command -v pkg >/dev/null 2>&1 || [[ "${PREFIX:-}" != *com.termux* ]]; then
    echo 'ERROR: This installer must run inside the Android Termux app.' >&2
    exit 1
fi
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$HOME/.local/share/cronos-yt"
VENV="$APP_ROOT/venv"
LAUNCHER="$PREFIX/bin/cronos"
LEGACY_LAUNCHER="$PREFIX/bin/cronos-yt"

# Check command ownership before making any changes; do not overwrite unrelated executables.
for target in "$LAUNCHER" "$LEGACY_LAUNCHER"; do
    if [[ -L "$target" ]]; then
        echo "ERROR: Symlink at $target was left unchanged." >&2
        exit 1
    fi
    if [[ -e "$target" ]] && ! grep -Eq '^# (CRONOS generated launcher|CRONOS YT generated launcher)$' "$target"; then
        echo "ERROR: Unrelated launcher at $target was left unchanged." >&2
        exit 1
    fi
done

for file in "$SOURCE_DIR/pyproject.toml" "$SOURCE_DIR/cronos_yt/main.py"; do
    [[ -f "$file" ]] || { echo "ERROR: Missing project file: $file" >&2; exit 1; }
done

printf '\n[1/7] Checking native Termux requirements...\n'
# Do not run pkg update/upgrade: avoid unrelated package upgrades.
pkg install -y python python-pip python-setuptools ffmpeg nodejs
if [[ "${CRONOS_SYSTEM_SITE:-0}" == 1 ]]; then
    echo 'Opt-in: allow Termux-provided native Python extensions.'
    pkg install -y python-brotli python-pycryptodomex
fi
printf '\n[2/7] Validating dependency trust mode...\n'
LOCK="$SOURCE_DIR/requirements.lock"
LOCK_VALID=0
if PYTHONPATH="$SOURCE_DIR" python - "$LOCK" <<'PYLOCK'
import sys
from pathlib import Path
from cronos_yt.updater import validate_lock
raise SystemExit(0 if validate_lock(Path(sys.argv[1])) else 1)
PYLOCK
then
    LOCK_VALID=1
fi
if (( ! LOCK_VALID )) && [[ ! -x "$VENV/bin/python" ]]; then
    echo 'ERROR: reviewed SHA-256 requirements.lock unavailable for fresh installation.' >&2
    echo 'Use scripts/generate_lock.sh explicitly on a trusted network, review hashes, then retry.' >&2
    exit 2
fi
if (( ! LOCK_VALID )); then
    echo 'WARNING: No validated lock; retaining existing installed dependencies (no dependency upgrades).'
fi

printf '\n[3/7] Making a safe pre-upgrade backup if existing data is present...\n'
# Snapshot the SQLite database with SQLite's online backup API (do not copy WAL files).
# A new uniquely named private archive is created; never remove previous backup copies.
CRONOS_YT_SOURCE_DIR="$SOURCE_DIR" python - <<'PYBACKUP'
import datetime
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
home = Path.home()
config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "cronos-yt" / "settings.json"
dbfile = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))) / "cronos-yt" / "history.sqlite3"
if config.is_file() or dbfile.is_file():
    outdir = Path(os.environ.get("XDG_STATE_HOME", str(home / ".local/state"))) / "cronos-yt" / "backups"
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    import tomllib
    with (Path(os.environ["CRONOS_YT_SOURCE_DIR"]) / "pyproject.toml").open("rb") as project:
        app_version = tomllib.load(project)["project"]["version"]
    output = outdir / f"pre-v{app_version}-{stamp}.zip"
    with tempfile.TemporaryDirectory() as temp:
        snapshot = Path(temp) / "history.sqlite3"
        if dbfile.is_file():
            with sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True, timeout=30) as src, \
                 sqlite3.connect(snapshot, timeout=30) as dst:
                src.backup(dst)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            if snapshot.is_file():
                archive.write(snapshot, "history.sqlite3")
            if config.is_file():
                archive.write(config, "settings.json")
    output.chmod(0o600)
    print(f"Saved backup: {output}")
else:
    print("Fresh installation: no existing user data to back up.")
PYBACKUP

printf '\n[4/7] Preparing isolated Python environment...\n'
mkdir -p "$APP_ROOT"
PREVIOUS_VERSION=""
if [[ -x "$VENV/bin/python" ]]; then
    PREVIOUS_VERSION="$("$VENV/bin/python" -c 'from importlib.metadata import version,PackageNotFoundError
try: print(version("cronos-yt"))
except PackageNotFoundError: pass' 2>/dev/null || true)"
fi
ACTIVE_VENV="$APP_ROOT/venv.candidate.$$"
if (( ! LOCK_VALID )); then
    # Already-installed legacy dependencies are reused only for upgrading this
    # user's existing application; no dependency resolver or network is used.
    cp -a "$VENV" "$ACTIVE_VENV"
fi
if (( LOCK_VALID )); then
    # Build a fresh isolated candidate; never destroy a working environment
    # before the dependency install and smoke check succeed.
    if [[ "${CRONOS_SYSTEM_SITE:-0}" == 1 ]]; then
        python -m venv --system-site-packages "$ACTIVE_VENV"
    else
        python -m venv "$ACTIVE_VENV"
    fi
    "$ACTIVE_VENV/bin/python" -m pip install --disable-pip-version-check --no-input \
        --require-hashes -r "$LOCK"
fi
printf '\n[5/7] Installing reviewed CRONOS source without resolving dependencies...\n'
# Build the local project using the system-provided build backend; network
# resolution is forbidden for project packaging.
WHEEL_DIR="$(mktemp -d)"
trap 'rm -rf "$WHEEL_DIR"' EXIT
python -m pip wheel --disable-pip-version-check --no-index --no-deps \
    --no-build-isolation --wheel-dir "$WHEEL_DIR" "$SOURCE_DIR"
shopt -s nullglob
WHEELS=("$WHEEL_DIR"/cronos_yt-*.whl)
[[ ${#WHEELS[@]} == 1 ]] || { echo 'ERROR: Expected one CRONOS wheel' >&2; exit 2; }
"$ACTIVE_VENV/bin/python" -m pip install --disable-pip-version-check --no-input \
    --no-index --no-deps "${WHEELS[0]}"
"$ACTIVE_VENV/bin/python" -c 'import yt_dlp, yt_dlp_ejs, rich, questionary, mutagen, cronos_yt'
if [[ -d "$VENV" ]]; then
    mv "$VENV" "$APP_ROOT/venv.previous.$(date +%Y%m%d%H%M%S)-$$"
fi
mv "$ACTIVE_VENV" "$VENV"
CURRENT_VERSION="$("$VENV/bin/python" -c 'from importlib.metadata import version; print(version("cronos-yt"))')"
printf '\n[6/7] Requesting shared storage permission...\n'
if command -v termux-setup-storage >/dev/null 2>&1; then
    termux-setup-storage || echo 'Storage setup was declined. You can retry: termux-setup-storage'
else
    echo 'WARNING: termux-setup-storage missing. Update Termux tools.'
fi
mkdir -p "$HOME/.config/cronos-yt" "$HOME/.local/state/cronos-yt"
if ! mkdir -p /storage/emulated/0/Movies/CRONOS-YT /storage/emulated/0/Music/CRONOS-YT 2>/dev/null; then
    echo 'WARNING: Media directories were not writable. Grant Android storage access and retry.'
fi

printf '\n[7/7] Creating the launcher and verifying...\n'
# Both launch commands route to the same upgraded environment.
cat > "$LAUNCHER" <<'LAUNCH'
#!/data/data/com.termux/files/usr/bin/bash
# CRONOS generated launcher
exec "$HOME/.local/share/cronos-yt/venv/bin/python" -m cronos_yt "$@"
LAUNCH
chmod 755 "$LAUNCHER"
cat > "$LEGACY_LAUNCHER" <<'LEGACY'
#!/data/data/com.termux/files/usr/bin/bash
# CRONOS generated launcher
exec "$HOME/.local/share/cronos-yt/venv/bin/python" -m cronos_yt "$@"
LEGACY
chmod 755 "$LEGACY_LAUNCHER"
"$VENV/bin/python" -c 'import yt_dlp, yt_dlp_ejs, rich, questionary, cronos_yt; print("Python dependencies OK; CRONOS " + cronos_yt.__version__)'
if [[ -n "$PREVIOUS_VERSION" && "$PREVIOUS_VERSION" != "$CURRENT_VERSION" ]]; then
    NOTICE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/cronos-yt"
    mkdir -p "$NOTICE_DIR"
    cat > "$NOTICE_DIR/whats-new-v3.0.1.txt" <<'NOTICE'
CRONOS v3.0.1 Security Hardening Update!
• Both cronos and cronos-yt launch commands continue to work.
• Queued work from previous sessions needs renewed authorization.
• Default engine updates require a reviewed SHA-256 dependency lock.
• Legacy settings, downloads, history and folder locations are retained.
• Backups are created before upgrades and old environments are preserved.
NOTICE
    chmod 600 "$NOTICE_DIR/whats-new-v3.0.1.txt"
fi
if ! "$LAUNCHER" --check; then
    echo 'WARNING: Dependency check was not clean; follow diagnostics above.'
fi
printf '\n\033[1;32mInstallation finished. Launch with: cronos\033[0m\n'
printf 'Optional share-sheet handler: cronos --install-share-handler\n\n'
if [[ -t 0 ]] && [[ "${CRONOS_NO_LAUNCH:-${CRONOS_YT_NO_LAUNCH:-0}}" != "1" ]]; then
    exec "$LAUNCHER"
fi
