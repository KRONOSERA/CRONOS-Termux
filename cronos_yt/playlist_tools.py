"""Select playlist entries by their displayed position, preserving original numbering."""
from __future__ import annotations

import re
from .playlists import PlaylistEntry


def choose_positions(expression: str, count: int) -> set[int]:
    """1-based ranges: '1-5,8,10-12' or 'all'; reject malformed/huge input."""
    if not 1 <= count <= 500:
        raise ValueError("Playlist has no selectable entries")
    text = expression.strip().lower()
    if text in ("all", "*"):
        return set(range(1, count + 1))
    if not text or len(text) > 1000:
        raise ValueError("Enter positions such as 1-5,8,12")
    result: set[int] = set()
    for part in text.split(","):
        match = re.fullmatch(r"\s*(\d{1,3})(?:\s*-\s*(\d{1,3}))?\s*", part)
        if not match:
            raise ValueError("Use comma-separated numbers or ranges, e.g. 1-5,8")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if not 1 <= start <= end <= count:
            raise ValueError(f"Select positions between 1 and {count}")
        result.update(range(start, end + 1))
    return result


def subset(entries: list[PlaylistEntry], expression: str = "all", *, search: str = "") -> list[PlaylistEntry]:
    positions = choose_positions(expression, len(entries))
    term = search.strip().casefold()
    return [entry for position, entry in enumerate(entries, 1)
            if position in positions and (not term or term in entry.title.casefold())]
