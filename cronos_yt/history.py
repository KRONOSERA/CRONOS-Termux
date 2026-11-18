"""SQLite download journal; connections are thread-local to each operation."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from .settings import data_dir


def make_key(media_id: str, mode: str, fmt: str, quality: str, folder: Path) -> str:
    value = "\x1f".join((media_id, mode, fmt, quality, str(folder.resolve())))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class HistoryDB:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "history.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_key TEXT NOT NULL,
                media_id TEXT NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                format TEXT NOT NULL,
                quality TEXT NOT NULL,
                file_path TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_download_key ON downloads(item_key, status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_download_recent ON downloads(id DESC)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30)
        try:
            con.execute("PRAGMA busy_timeout=30000")
            con.execute("PRAGMA journal_mode=WAL")
            with con:
                yield con
        finally:
            con.close()

    def existing(self, key: str) -> Path | None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT file_path FROM downloads WHERE item_key=? AND status='success' ORDER BY id DESC", (key,)
            ).fetchall()
        for (path,) in rows:
            if path and Path(path).is_file():
                return Path(path)
        return None

    def record(self, *, key: str, media_id: str, title: str, kind: str,
               fmt: str, quality: str, status: str, file_path: str = "", error: str = "") -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO downloads
                (item_key,media_id,title,kind,format,quality,file_path,status,error,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                key, media_id, title[:250], kind, fmt, quality,
                file_path, status, error[:250], datetime.now(timezone.utc).isoformat(timespec="seconds")
            ))

    def recent(self, limit: int = 25) -> list[sqlite3.Row]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            return db.execute(
                "SELECT created_at, title, kind, format, quality, file_path, status, error "
                "FROM downloads ORDER BY id DESC LIMIT ?", (min(200, max(1, limit)),)
            ).fetchall()

    def statistics(self, include_size: bool = False) -> dict:
        """Summarize history; optional size calculation skips missing files."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT kind, COUNT(*), COUNT(DISTINCT media_id) FROM downloads "
                "WHERE status='success' GROUP BY kind"
            ).fetchall()
            failures = db.execute(
                "SELECT COUNT(*) FROM downloads WHERE status='failed'"
            ).fetchone()[0]
            paths = [row[0] for row in db.execute(
                "SELECT DISTINCT file_path FROM downloads WHERE status='success' AND file_path IS NOT NULL"
            )] if include_size else []
        on_disk = 0
        size_bytes = 0
        for candidate in paths:
            try:
                size_bytes += Path(candidate).stat().st_size
                on_disk += 1
            except (OSError, ValueError, TypeError):
                pass
        return {
            "files_on_disk": on_disk,
            "size_bytes": size_bytes,
            "video": next((r[1] for r in rows if r[0] == "video"), 0),
            "music": next((r[1] for r in rows if r[0] == "music"), 0),
            "unique_media": sum(r[2] for r in rows),
            "failed_attempts": failures,
        }
