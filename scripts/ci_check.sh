#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python -m compileall -q cronos_yt tests
python -m unittest discover -s tests -p 'test_*.py'
if [[ "${CRONOS_INTEGRATION:-0}" == 1 ]]; then
  python -m unittest discover -s tests/integration -p 'test_*.py'
else
  echo 'SKIP integration suite (set CRONOS_INTEGRATION=1 and install real dependencies)'
fi
python - <<'PY'
from pathlib import Path
from cronos_yt.updater import validate_lock
if not validate_lock(Path('requirements.lock')):
    raise SystemExit('UNVERIFIED LOCK: generate/review requirements.lock before audited release')
PY
if python -m pip_audit --version >/dev/null 2>&1; then
    python -m pip_audit -r requirements.lock
elif command -v pip-audit >/dev/null 2>&1; then
    pip-audit -r requirements.lock
else
    echo 'MISSING pip-audit; mandatory release gate cannot complete' >&2
    exit 2
fi
if command -v ruff >/dev/null 2>&1; then
    ruff check --select E4,E7,E9,F63,F7,F82 cronos_yt tests
elif command -v pyflakes >/dev/null 2>&1; then
    pyflakes cronos_yt tests
else
    echo 'MISSING ruff/pyflakes; mandatory release gate cannot complete' >&2
    exit 2
fi
