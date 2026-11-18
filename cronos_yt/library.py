"""Read-only media-library views of the existing download history.

The library never deletes user files. Exports contain local paths and titles only.
"""
from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .history import HistoryDB


@dataclass(frozen=True)
class MediaEntry:
    id: int
    media_id: str
    title: str
    kind: str
    format: str
    quality: str
    file_path: str
    created_at: str
    present: bool
    size_bytes: int


def search_library(history: HistoryDB, query: str = "", *, kind: str = "all",
                   missing_only: bool = False, limit: int = 200) -> list[MediaEntry]:
    """Latest successful record per output path; filters are parameterized."""
    if kind not in ("all", "video", "music"):
        raise ValueError("Invalid library filter")
    if not 1 <= limit <= 2000:
        raise ValueError("Library limit must be 1..2000")
    # Search before LIMIT; if missing_only, inspect all matching rows (up to 10000).
    path_search = query.lower().startswith("path:")
    search_term = query[5:] if path_search else query
    pattern = "%" + search_term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with history._connect() as con:
        con.row_factory = __import__("sqlite3").Row
        rows = con.execute("""SELECT id,media_id,title,kind,format,quality,file_path,created_at
            FROM downloads WHERE status='success' AND file_path IS NOT NULL AND file_path!=''
            AND (?='all' OR kind=?)
            AND ((?=1 AND lower(file_path) LIKE ? ESCAPE '\\') OR
                 (?=0 AND (lower(title) LIKE ? ESCAPE '\\' OR lower(media_id) LIKE ? ESCAPE '\\')))
            ORDER BY id DESC LIMIT 10000""", (kind, kind, int(path_search), pattern,
                                                   int(path_search), pattern, pattern)).fetchall()
    seen: set[str] = set()
    entries: list[MediaEntry] = []
    for row in rows:
        path_string = row["file_path"]
        if path_string in seen:
            continue
        seen.add(path_string)
        try:
            stats = Path(path_string).stat()
            is_file = Path(path_string).is_file()
            size = stats.st_size if is_file else 0
        except (OSError, ValueError):
            is_file, size = False, 0
        if missing_only and is_file:
            continue
        entries.append(MediaEntry(id=row["id"], media_id=row["media_id"], title=row["title"],
                                  kind=row["kind"], format=row["format"], quality=row["quality"],
                                  file_path=path_string, created_at=row["created_at"],
                                  present=is_file, size_bytes=size))
        if len(entries) >= limit:
            break
    return entries


def _csv_safe(value: str) -> str:
    """Prevent CSV spreadsheet formula execution on exported untrusted titles."""
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value


def export_library(history: HistoryDB, destination: Path, *, format: Literal["csv", "m3u"] = "csv",
                   kind: str = "all") -> tuple[Path, int]:
    """Atomically create CSV inventory or M3U local playlist (present files only)."""
    if format not in ("csv", "m3u"):
        raise ValueError("Only CSV and M3U are supported")
    dest = Path(destination).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    entries = search_library(history, kind=kind, limit=2000)
    # Export always excludes missing files to avoid stale M3U entries.
    present = [entry for entry in entries if entry.present]
    tmp: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=".cronos-library-", dir=dest.parent)
        tmp = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            if format == "csv":
                writer = csv.writer(file)
                writer.writerow(["title", "type", "format", "quality", "path", "size_bytes", "downloaded_utc"])
                for item in present:
                    writer.writerow([_csv_safe(item.title), item.kind, item.format, item.quality,
                                     _csv_safe(item.file_path), item.size_bytes, item.created_at])
            else:
                file.write("#EXTM3U\n")
                for item in present:
                    # Strip line breaks to prevent injected #EXT directives.
                    title = item.title.replace("\n", " ").replace("\r", " ")
                    file.write(f"#EXTINF:-1,{title}\n{item.file_path}\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return dest, len(present)
