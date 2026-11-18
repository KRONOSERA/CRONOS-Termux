"""Private, consistent backups for SQLite history/queue and local settings.

Archives never contain downloaded media; no restore command is provided because
blindly overwriting a live SQLite database would risk user data loss.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .settings import config_path, data_dir, state_dir


def create_backup(destination: Path | None = None, *, database: Path | None = None,
                  configuration: Path | None = None) -> Path:
    source_db = database if database is not None else data_dir() / "history.sqlite3"
    source_config = configuration if configuration is not None else config_path()
    if destination is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        destination = state_dir() / "backups" / f"cronos-yt-{timestamp}.zip"
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Backup already exists: {destination}")
    tmp_name: Path | None = None
    with tempfile.TemporaryDirectory(prefix="cronos-backup-") as tmpdir:
        snapshot = Path(tmpdir) / "history.sqlite3"
        if source_db.is_file():
            with sqlite3.connect(f"file:{source_db}?mode=ro", uri=True) as src, sqlite3.connect(snapshot) as dest:
                src.backup(dest)
        try:
            fd, name = tempfile.mkstemp(prefix=".cronos-backup-", suffix=".zip", dir=destination.parent)
            os.close(fd)
            tmp_name = Path(name)
            with zipfile.ZipFile(tmp_name, "w", compression=zipfile.ZIP_DEFLATED) as output:
                output.writestr("manifest.json", json.dumps({
                    "application": "CRONOS", "format_version": 1,
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "note": "Contains private download history and queued URLs; protect this archive. No media files included."
                }, indent=2))
                if snapshot.is_file():
                    output.write(snapshot, "history.sqlite3")
                if source_config.is_file():
                    output.write(source_config, "settings.json")
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, destination)
        finally:
            if tmp_name is not None:
                tmp_name.unlink(missing_ok=True)
    return destination
