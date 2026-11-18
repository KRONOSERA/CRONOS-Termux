"""Playlist-to-job planning with safe indexed filenames."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .storage import sanitize_filename, validate_url


@dataclass(frozen=True)
class PlaylistEntry:
    url: str
    index: int
    title: str


def parse_playlist(info: dict[str, Any], limit: int) -> tuple[str, list[PlaylistEntry]]:
    if info.get("_type") != "playlist" and "entries" not in info:
        raise ValueError("URL did not return a playlist; use single video/music")
    name = sanitize_filename(info.get("title") or info.get("id") or "Playlist", 72)
    items: list[PlaylistEntry] = []
    for pos, entry in enumerate(info.get("entries") or [], 1):
        if len(items) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        youtube_id = entry.get("id")
        if not youtube_id or not isinstance(youtube_id, str):
            continue
        # Flat entries from YouTube can contain an arbitrary 'url'. Use canonical ID instead.
        if not __import__("re").fullmatch(r"[A-Za-z0-9_-]{11}", youtube_id):
            continue
        url = validate_url(f"https://www.youtube.com/watch?v={youtube_id}")
        try:
            index = int(entry.get("playlist_index") or pos)
        except (ValueError, TypeError):
            index = pos
        items.append(PlaylistEntry(url=url, index=index, title=entry.get("title") or youtube_id))
    return name, items
