"""Post-processing options and optionally user-supplied authorized lyrics."""

from __future__ import annotations

import os
import json
import re
import subprocess
import tempfile
from pathlib import Path

from .settings import ALLOWED_AUDIO, ALLOWED_BITRATES, state_dir


def audio_postprocessors(fmt: str, bitrate: int, embed_artwork: bool) -> tuple[list[dict], bool]:
    if fmt not in ALLOWED_AUDIO or bitrate not in ALLOWED_BITRATES:
        raise ValueError("Unsupported audio format or MP3 bitrate")
    pps = [
        {"key": "FFmpegExtractAudio", "preferredcodec": fmt,
         "preferredquality": f"{bitrate}K" if fmt == "mp3" else "0"},
        {"key": "FFmpegMetadata", "add_metadata": True},
    ]
    # WAV has no reliable cover-art support. OPUS/FLAC use mutagen (dependency).
    artwork = embed_artwork and fmt in ("mp3", "m4a", "flac", "opus")
    if artwork:
        pps.append({"key": "EmbedThumbnail"})
    return pps, artwork


def _escape_ffmetadata(value: str) -> str:
    """Escape FFMETADATA1 syntax; multiline fields use a backslash-newline."""
    return (value.replace("\\", "\\\\").replace("=", "\\=")
            .replace(";", "\\;").replace("#", "\\#")
            .replace("\r\n", "\n").replace("\r", "\n")
            .replace("\n", "\\\n"))


def add_lyrics_from_file(media: Path, lyrics_path: Path) -> bool:
    """Attach user-owned lyrics without exposing them in process command arguments."""
    if not lyrics_path.is_file() or lyrics_path.stat().st_size > 128 * 1024:
        raise ValueError("Lyrics file missing or over 128 KiB")
    lyrics = lyrics_path.read_text(encoding="utf-8").strip()
    if not lyrics:
        raise ValueError("Lyrics file is empty")
    if media.suffix.lower() == ".wav":
        return False
    # FFmpeg -map_metadata replaces the mapped metadata set. Preserve existing
    # global title/artist/album tags in the same temporary FFmetadata input.
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(media)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    original = json.loads(probe.stdout or "{}")
    tags = original.get("format", {}).get("tags", {})
    if not isinstance(tags, dict):
        raise ValueError("Invalid original media tags")
    preserved = {key: value for key, value in tags.items()
                 if (isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_]{1,64}", key)
                     and isinstance(value, str) and len(value) < 64 * 1024
                     and key.lower() != "lyrics")}
    target = media.with_name(media.stem + ".cronos-lyrics" + media.suffix)
    private_root = state_dir() / "tmp"
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix="lyrics-", dir=private_root) as temporary:
            metadata = Path(temporary) / "metadata.ffmeta"
            fd = os.open(metadata, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(";FFMETADATA1\n")
                for key, value in preserved.items():
                    stream.write(f"{key}={_escape_ffmetadata(value)}\n")
                stream.write("lyrics=" + _escape_ffmetadata(lyrics) + "\n")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-i", str(media), "-f", "ffmetadata", "-i", str(metadata),
                 "-map", "0", "-map_metadata", "1", "-c", "copy", str(target)],
                capture_output=True, check=True, timeout=180,
            )
        target.replace(media)
        return True
    finally:
        target.unlink(missing_ok=True)
