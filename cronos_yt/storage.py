"""YouTube URL and filesystem safety, plus optional Android integrations."""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com", "youtu.be"}
URL_REGEX = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def validate_url(value: str) -> str:
    """Only public HTTPS YouTube URLs; no credentials or nonstandard ports."""
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Invalid URL length")
    value = value.strip()
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("URL contains control characters")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Malformed URL") from exc
    if parsed.scheme.lower() != "https" or parsed.hostname not in YOUTUBE_HOSTS:
        raise ValueError("Only HTTPS YouTube / YouTube Music URLs are supported")
    if parsed.username or parsed.password or port not in (None, 443):
        raise ValueError("URL credentials and nonstandard ports are forbidden")
    if not parsed.path and not parsed.query:
        raise ValueError("URL does not point to media")
    return value


def parse_urls(text: str) -> list[str]:
    """Deduplicate a pasted set while preserving user order."""
    matches = URL_REGEX.findall(text)
    if not matches and text.strip():
        matches = [text.strip()]
    result: list[str] = []
    seen: set[str] = set()
    for match in matches:
        url = validate_url(match.rstrip(".,;"))
        if url not in seen:
            result.append(url)
            seen.add(url)
        if len(result) > 500:
            raise ValueError("Maximum 500 pasted URLs per batch")
    return result


def is_playlist_url(url: str) -> bool:
    parsed = urlsplit(validate_url(url))
    return (parsed.path.startswith("/playlist") or parsed.path.startswith("/browse")) or (
        bool(parse_qs(parsed.query).get("list")) and parsed.path in ("/watch", "/"))


def sanitize_filename(value: str, limit: int = 100) -> str:
    text = unicodedata.normalize("NFC", str(value))
    text = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|]", "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if text in ("", ".", ".."):
        text = "Untitled"
    return text[:limit].rstrip(" .") or "Untitled"


def output_folder(base: str | Path, playlist_title: str | None = None) -> Path:
    folder = Path(base).expanduser()
    if playlist_title:
        folder = folder / sanitize_filename(playlist_title, 72)
    return folder


def ensure_writable(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if not folder.is_dir():
        raise OSError(f"Not a directory: {folder}")
    # Access checks alone are unreliable on Android FUSE; actual writes are verified.
    import tempfile
    with tempfile.TemporaryFile(dir=folder):
        pass


def ensure_space(folder: Path, expected: int | None = None) -> None:
    """Conservative reserve for temporary streams and FFmpeg output."""
    check = folder
    while not check.exists() and check != check.parent:
        check = check.parent
    free = shutil.disk_usage(check).free
    reserve = 64 * 1024 * 1024
    # Downloads may require both source streams and merged/converted output.
    requirement = reserve + max(0, int(expected or 0)) * 2
    if free < requirement:
        raise OSError(f"Insufficient space: {free // (1024**2)} MiB free; need ~{requirement // (1024**2)} MiB")


def get_clipboard() -> str | None:
    cmd = shutil.which("termux-clipboard-get")
    if not cmd:
        return None
    try:
        proc = subprocess.run([cmd], capture_output=True, text=True, timeout=4, check=True)
        return proc.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def scan_media(path: Path) -> bool:
    """Best-effort scan; Android may require Termux:API and its companion app."""
    cmd = shutil.which("termux-media-scan")
    if not cmd or not path.is_file():
        return False
    try:
        subprocess.run([cmd, str(path)], capture_output=True, check=True, timeout=12)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def check_dependencies() -> list[str]:
    missing = []
    for program in ("ffmpeg", "ffprobe", "node"):
        if not shutil.which(program):
            missing.append(f"Missing {program}. Run: pkg install ffmpeg nodejs")
    node = shutil.which("node")
    if node:
        try:
            version = subprocess.run([node, "--version"], capture_output=True,
                                     text=True, check=True, timeout=5).stdout.strip()
            match = re.fullmatch(r"v?(\d+)\.\d+\.\d+", version)
            if not match or int(match.group(1)) < 22:
                missing.append("Node.js 22 or newer required by yt-dlp-ejs. Run: pkg upgrade && pkg install nodejs")
        except (OSError, subprocess.SubprocessError):
            missing.append("Could not validate Node.js. Run: pkg install nodejs")
    try:
        import yt_dlp  # noqa: F401
        import yt_dlp_ejs  # noqa: F401
    except ImportError:
        missing.append("Missing yt-dlp / yt-dlp-ejs. Run: cronos --update")
    return missing
