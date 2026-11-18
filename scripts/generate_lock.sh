#!/data/data/com.termux/files/usr/bin/bash
# Intentionally manual: network-backed trust decision, never run by install.sh.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "${CRONOS_TRUST_INDEX:-}" == 1 ]] || {
  echo 'Refusing unreviewed index resolution. Set CRONOS_TRUST_INDEX=1 after reviewing requirements.in.' >&2
  exit 2
}
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
python -m venv "$TMP/venv"
"$TMP/venv/bin/python" -m pip install --disable-pip-version-check --no-input 'pip-tools>=7,<9'
"$TMP/venv/bin/pip-compile" --generate-hashes --allow-unsafe --resolver=backtracking \
   --output-file "$TMP/requirements.lock" "$ROOT/requirements.in"
# Move only after generated hashes have passed syntactic validation.
PYTHONPATH="$ROOT" "$TMP/venv/bin/python" - "$TMP/requirements.lock" <<'PY'
import sys
from pathlib import Path
from cronos_yt.updater import validate_lock
if not validate_lock(Path(sys.argv[1])):
    raise SystemExit('Generated lock failed CRONOS validation; no lock changed')
PY
cp "$TMP/requirements.lock" "$ROOT/requirements.lock.tmp"
chmod 600 "$ROOT/requirements.lock.tmp"
mv -f "$ROOT/requirements.lock.tmp" "$ROOT/requirements.lock"
echo "Generated candidate lock: $ROOT/requirements.lock"
echo 'Review and commit its exact versions and hashes before distribution.'
