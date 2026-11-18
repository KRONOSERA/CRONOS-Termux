#!/data/data/com.termux/files/usr/bin/bash
# Device verification: no media downloads; safe for existing settings/history.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$HOME/.local/share/cronos-yt/venv/bin/python"
[[ -x "$PYTHON" ]] || { echo 'ERROR: Install CRONOS first using bash install.sh' >&2; exit 2; }
cd "$ROOT"
printf '\n[1/5] Runtime and dependencies...\n'
"$PYTHON" --version
"$PYTHON" -c 'import cronos_yt, yt_dlp, yt_dlp_ejs, rich, questionary, mutagen; print("CRONOS", cronos_yt.__version__)'
printf '\n[2/5] Offline test suite...\n'
"$PYTHON" -m unittest discover -s tests -v
printf '\n[3/5] Offline UI preview (network-free)...\n'
"$PYTHON" -m cronos_yt --ui-preview --no-animation
"$PYTHON" -m cronos_yt --motion-preview --no-animation
printf '\n[4/5] Dependency/Android check...\n'
"$PYTHON" -m cronos_yt --check
printf '\n[5/5] Source compilation...\n'
"$PYTHON" -m compileall -q cronos_yt
printf '\nPASS: CRONOS local Termux smoke test.\n'
printf 'LIVE downloads and v3.0.0 -> v3.0.1 upgrades must be verified separately using only authorized media.\n'
