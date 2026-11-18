"""Opt-in Android share-sheet handler; never replace existing user handlers."""

from pathlib import Path

HANDLER = """#!/data/data/com.termux/files/usr/bin/bash
# CRONOS share handler. Asks for options/authorization inside the application.
url="${1:-}"
if [ -z "$url" ]; then
    IFS= read -r url || exit 1
fi
[ -n "$url" ] || exit 1
exec cronos --url "$url"
"""


def install_share_handler(home: Path | None = None) -> tuple[bool, str]:
    root = home or Path.home()
    target = root / "bin" / "termux-url-opener"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        return False, f"Existing share handler left unchanged: {target}"
    try:
        with target.open("x", encoding="utf-8") as fp:
            fp.write(HANDLER)
        target.chmod(0o700)
    except FileExistsError:
        return False, f"Existing share handler left unchanged: {target}"
    return True, f"Installed safe share handler: {target}"
