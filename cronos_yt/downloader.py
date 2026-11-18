"""yt-dlp engine, resumable transfers, progress, duplicate prevention and reports."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit
from typing import Any, Callable

from rich.console import Console
from rich.progress import (BarColumn, DownloadColumn, Progress, SpinnerColumn,
                           TaskProgressColumn, TextColumn, TimeRemainingColumn,
                           TransferSpeedColumn)
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .audio import add_lyrics_from_file, audio_postprocessors
from .authorization import AuthorizationDB, Receipt
from .history import HistoryDB, make_key
from .settings import Settings, state_dir
from .storage import ensure_space, ensure_writable, output_folder, sanitize_filename, scan_media, validate_url
from .video import VideoSelection, select_video

LOG = logging.getLogger("cronos_yt")


_URL = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.IGNORECASE)
_SECRET_HEADER = re.compile(
    r"(?i)\b(cookie|authorization|proxy-authorization|x-goog-[a-z0-9_-]+|x-api-key)\s*[:=]\s*[^\r\n]+"
)
_SECRET_PAIR = re.compile(r"(?i)\b(token|api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[^\s;,]+")
_BEARER = re.compile(r"(?i)\bbearer\s+[^\s;,]+")
_OPAQUE = re.compile(r"[A-Za-z0-9_-]{20,}\Z")


def _safe_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    # Do not retain trailing punctuation that belongs to surrounding prose.
    body = raw.rstrip(".,;!:")
    tail = raw[len(body):]
    try:
        parts = urlsplit(body)
        pieces = ["[redacted]" if (_OPAQUE.fullmatch(unquote(x)) or
                  (len(x) >= 32 and "%" in x)) else x
                  for x in parts.path.split("/")]
        path = "/".join(pieces)
        hostname = parts.hostname or ""
        # Drop embedded basic-auth credentials even from diagnostic error URLs.
        host = hostname + (f":{parts.port}" if parts.port else "")
        safe = urlunsplit((parts.scheme, host, path, "", ""))
        if parts.query:
            safe += "?[redacted]"
        if parts.fragment:
            safe += "#[redacted]"
        return safe + tail
    except ValueError:
        return "[redacted URL]" + tail


def redacted(message: str) -> str:
    """Redact sensitive diagnostic text *before and after* length bounding."""
    text = str(message)[:4096]  # Bound untrusted input before regex work.
    text = _URL.sub(_safe_url, text)
    text = _SECRET_HEADER.sub(lambda m: m.group(1) + ": [redacted]", text)
    text = _SECRET_PAIR.sub(lambda m: m.group(1) + "=[redacted]", text)
    text = _BEARER.sub("Bearer [redacted]", text)
    return text[:500]


class _SanitizeLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redacted(record.getMessage())
        record.args = ()
        record.exc_info = None  # Never render an unsanitized traceback.
        record.stack_info = None
        return True


def setup_logging() -> None:
    if LOG.handlers:
        return
    path = state_dir() / "errors.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=512_000, backupCount=2, encoding="utf-8")
    handler.addFilter(_SanitizeLog())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.WARNING)
    LOG.propagate = False


class YtdlpLogger:
    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        LOG.warning("yt-dlp: %s", redacted(message))

    def error(self, message: str) -> None:
        LOG.error("yt-dlp: %s", redacted(message))


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class DownloadJob:
    url: str
    kind: str = "video"  # video or music
    height: int | None = 1080  # None = best
    fps: int = 60
    audio_format: str = "mp3"
    bitrate: int = 192
    output_dir: str | None = None
    playlist_title: str | None = None
    index: int | None = None
    filename: str | None = None
    lyrics_file: str | None = None

    def __post_init__(self) -> None:
        validate_url(self.url)
        if self.kind not in ("video", "music"):
            raise ValueError("Download kind must be video or music")
        if self.fps not in (30, 60):
            raise ValueError("FPS must be 30 or 60")
        if self.index is not None and self.index < 1:
            raise ValueError("Playlist index must be positive")


@dataclass(frozen=True)
class DownloadResult:
    status: str  # success, skipped, failed, cancelled
    title: str
    file: str = ""
    reason: str = ""
    quality: str = ""


class DownloadManager:
    def __init__(self, settings: Settings, history: HistoryDB | None = None,
                 console: Console | None = None):
        self.settings = settings
        self.history = history or HistoryDB()
        self.console = console or Console()
        self.cancel = threading.Event()
        self.paused = threading.Event()
        self._key_lock_guard = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}
        setup_logging()

    def _wait_until_resumed(self) -> None:
        """Cooperative pause between yt-dlp progress events; never discards .part files."""
        while self.paused.is_set():
            if self.cancel.wait(0.15):
                raise Cancelled("Cancelled while paused")
        if self.cancel.is_set():
            raise Cancelled("Cancelled by user")

    def _base_options(self) -> dict[str, Any]:
        return {
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "logger": YtdlpLogger(),
            "socket_timeout": 25,
            "retries": 5,
            "fragment_retries": 5,
            "extractor_retries": 3,
            "file_access_retries": 3,
            "js_runtimes": {"node": {}},
            "remote_components": [],  # No remote scripts are executed.
            "ratelimit": self.settings.rate_limit_kib * 1024 or None,
            "concurrent_fragment_downloads": self.settings.fragment_concurrency,
        }

    def inspect(self, url: str) -> dict[str, Any]:
        validate_url(url)
        with YoutubeDL({**self._base_options(), "noplaylist": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict) or not info.get("id"):
            raise ValueError("No accessible media metadata returned")
        if info.get("is_live"):
            raise ValueError("Live streams are not supported")
        return info

    def inspect_playlist(self, url: str, limit: int) -> dict[str, Any]:
        validate_url(url)
        if not (1 <= limit <= 500):
            raise ValueError("Playlist limit must be 1..500")
        with YoutubeDL({**self._base_options(), "noplaylist": False,
                        "extract_flat": "in_playlist", "playlistend": limit,
                        "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict):
            raise ValueError("Playlist metadata unavailable")
        return info

    def _lock(self, key: str) -> threading.Lock:
        with self._key_lock_guard:
            return self._key_locks.setdefault(key, threading.Lock())

    def _folder(self, job: DownloadJob) -> Path:
        base = job.output_dir or (self.settings.video_dir if job.kind == "video" else self.settings.music_dir)
        return output_folder(base, job.playlist_title)

    def _format_settings(self, job: DownloadJob, info: dict[str, Any]) -> tuple[dict[str, Any], str, str, int | None]:
        if job.kind == "video":
            video: VideoSelection = select_video(info, job.height, job.fps)
            quality = f"{video.height or '?'}p@{video.fps or '?'}"
            return ({
                "format": video.format_selector,
                "merge_output_format": "mp4",
                "postprocessors": [
                    {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
                    {"key": "FFmpegMetadata", "add_metadata": True},
                ],
                **({
                    "writesubtitles": True,
                    "writeautomaticsub": self.settings.subtitles_mode == "automatic",
                    "subtitleslangs": [language.strip() for language in self.settings.subtitles_languages.split(",")],
                    "subtitlesformat": "srt/best",
                    "convertsubtitles": "srt",
                } if self.settings.subtitles_mode != "none" else {}),
            }, "mp4", quality, video.estimated_bytes)
        pps, artwork = audio_postprocessors(job.audio_format, job.bitrate, self.settings.embed_artwork)
        # yt-dlp downloads a thumbnail for EmbedThumbnail; it is cleaned up on success.
        return ({
            "format": "bestaudio[ext=m4a]/bestaudio" if job.audio_format == "m4a" else "bestaudio",
            "postprocessors": pps,
            "writethumbnail": artwork,
        }, job.audio_format, f"{job.bitrate}k" if job.audio_format == "mp3" else "source", None)

    @staticmethod
    def _final_file(folder: Path, media_id: str, ext: str,
                    info: dict[str, Any]) -> Path | None:
        # The final yt-dlp info dict has filepath on recent versions.
        candidates = [info.get("filepath"), info.get("_filename")]
        candidates.extend(d.get("filepath") for d in info.get("requested_downloads", []) if isinstance(d, dict))
        for value in candidates:
            if value:
                path = Path(value)
                if path.is_file() and path.suffix.lower() == "." + ext:
                    return path
        # FFmpeg may change the extension after requested_downloads was captured.
        marker = f"[{media_id}]"
        matching = [p for p in folder.iterdir() if p.is_file() and marker in p.name
                    and p.suffix.lower() == "." + ext]
        return max(matching, key=lambda p: p.stat().st_mtime) if matching else None

    def _one(self, job: DownloadJob, progress: Progress, task: int,
             heartbeat: Callable[[], None] | None = None) -> DownloadResult:
        title = "Media"
        key = ""
        media_id = ""
        quality = ""
        fmt = ""
        try:
            self._wait_until_resumed()
            progress.update(task, phase="Inspecting", title="Reading metadata")
            info = self.inspect(job.url)
            title = str(info.get("title") or info["id"])
            media_id = str(info["id"])
            if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", media_id):
                raise ValueError("Invalid media identifier")
            progress.update(task, title=sanitize_filename(title, 28), phase="Preparing")
            self._wait_until_resumed()
            format_opts, fmt, quality, estimate = self._format_settings(job, info)
            folder = self._folder(job)
            ensure_writable(folder)
            ensure_space(folder, estimate)
            key = make_key(media_id, job.kind, fmt, quality, folder)
            with self._lock(key):
                existing = self.history.existing(key)
                if existing:
                    progress.update(task, completed=100, total=100, phase="Already saved")
                    return DownloadResult("skipped", title, str(existing), quality=quality)
                self._wait_until_resumed()
                if job.filename:
                    basename = sanitize_filename(job.filename, 90).replace("%", "%%")
                elif self.settings.filename_style == "channel-title":
                    channel = sanitize_filename(info.get("uploader") or info.get("channel") or "Unknown", 55)
                    basename = channel.replace("%", "%%") + " - %(title).100B"
                elif self.settings.filename_style == "date-title":
                    date = str(info.get("upload_date") or "Undated")
                    date = re.sub(r"[^0-9]", "", date)[:8] or "Undated"
                    basename = date + " - %(title).100B"
                else:
                    basename = "%(title).140B"
                prefix = f"{job.index:04d} - " if job.index is not None else ""
                variant = f" [{quality}]" if (job.kind == "video" or fmt == "mp3") else ""
                template = prefix + basename + " [%(id)s]" + variant + ".%(ext)s"
                last_progress = [0.0]
                last_heartbeat = [0.0]

                def hook(data: dict[str, Any]) -> None:
                    self._wait_until_resumed()
                    now = time.monotonic()
                    if heartbeat and now - last_heartbeat[0] >= 30:
                        last_heartbeat[0] = now
                        heartbeat()
                    if now - last_progress[0] < .12 and data.get("status") == "downloading":
                        return
                    last_progress[0] = now
                    if data.get("status") == "downloading":
                        total = data.get("total_bytes") or data.get("total_bytes_estimate")
                        received = int(data.get("downloaded_bytes") or 0)
                        progress.update(task, total=total or None, completed=received, phase="Downloading")
                    elif data.get("status") == "finished":
                        progress.update(task, phase="Processing")

                def post_hook(data: dict[str, Any]) -> None:
                    self._wait_until_resumed()
                    if data.get("status") == "started":
                        progress.update(task, phase="FFmpeg / tags")

                options = {
                    **self._base_options(), **format_opts,
                    "noplaylist": True,
                    "paths": {"home": str(folder)},
                    "outtmpl": template,
                    "windowsfilenames": True,
                    "overwrites": False,
                    "continuedl": True,
                    "nopart": False,
                    "progress_hooks": [hook],
                    "postprocessor_hooks": [post_hook],
                }
                with YoutubeDL(options) as ydl:
                    outcome = ydl.extract_info(job.url, download=True)
                if not isinstance(outcome, dict):
                    raise ValueError("No media information returned after download")
                saved = self._final_file(folder, media_id, fmt, outcome)
                if not saved:
                    raise FileNotFoundError(f"Expected .{fmt} output was not created")
                if job.lyrics_file and job.kind == "music":
                    try:
                        add_lyrics_from_file(saved, Path(job.lyrics_file).expanduser())
                    except (OSError, ValueError, subprocess.SubprocessError) as exc:
                        LOG.warning("Lyrics tag not embedded: %s", redacted(str(exc)))
                self.history.record(key=key, media_id=media_id, title=title, kind=job.kind,
                                    fmt=fmt, quality=quality, status="success", file_path=str(saved))
                scan_media(saved)
                progress.update(task, total=100, completed=100, phase="Saved")
                return DownloadResult("success", title, str(saved), quality=quality)
        except (Cancelled, KeyboardInterrupt):
            progress.update(task, phase="Cancelled")
            return DownloadResult("cancelled", title, reason="Cancelled; partial file can be resumed")
        except Exception as exc:
            # yt-dlp may wrap hook-raised Cancelled in DownloadError.
            if self.cancel.is_set():
                progress.update(task, phase="Stopped")
                return DownloadResult("cancelled", title, reason="Stopped; partial download retained")
            # Keep logs and history free of source query strings and credentials.
            safe = redacted(str(exc))
            LOG.error("Download failed (%s): %s", type(exc).__name__, safe)
            if key and media_id:
                try:
                    self.history.record(key=key, media_id=media_id, title=title,
                                        kind=job.kind, fmt=fmt, quality=quality,
                                        status="failed", error=safe)
                except sqlite3.Error as exc:
                    LOG.error("Unable to record failure: %s", redacted(str(exc)))
            progress.update(task, phase="Failed")
            return DownloadResult("failed", title, reason=safe, quality=quality)

    def download(
        self, jobs: list[DownloadJob], *,
        on_start: Callable[[int], None] | None = None,
        on_result: Callable[[int, DownloadResult], None] | None = None,
        controls: bool = False,
        authorizations: list[Receipt] | None = None,
        on_heartbeat: Callable[[int], None] | None = None,
    ) -> list[DownloadResult]:
        """Download a batch; callbacks track FIFO queue progress by input index.

        Controls (TTY only): p=pause, r=resume, c=cancel pending/active.
        Pause is cooperative: the current network read/FFmpeg step may finish first.
        """
        if not jobs:
            return []
        if (authorizations is None or len(authorizations) != len(jobs) or
                not all(isinstance(receipt, Receipt) for receipt in authorizations) or
                len({receipt.id for receipt in authorizations}) != len(jobs) or
                any(not AuthorizationDB(self.history.path).verify(job, receipt)
                    for job, receipt in zip(jobs, authorizations))):
            raise PermissionError("Every transfer requires current-session authorization")
        from contextlib import nullcontext
        from .controls import DownloadControls

        self.cancel.clear()
        self.paused.clear()
        results: list[DownloadResult | None] = [None] * len(jobs)
        from . import ui
        primary, secondary, _, _ = ui.THEMES.get(self.settings.ui_theme, ui.THEMES["neon"])
        if controls and self.console.is_terminal:
            self.console.print("[bold]LIVE TRANSFER[/bold]  [cyan]P[/cyan] pause · "
                               "[cyan]R[/cyan] resume · [yellow]C[/yellow] stop")
        input_controls = DownloadControls(self, self.console) if controls else nullcontext()
        if self.settings.ui_compact or self.console.size.width < 44:
            # Especially small portrait windows: never push progress off-screen.
            progress_columns = [
                TextColumn(f"[{primary}]{{task.fields[title]:10.10}}"),
                BarColumn(bar_width=5, complete_style=primary, finished_style=secondary),
                TaskProgressColumn(),
            ]
        elif self.console.size.width < 70:
            progress_columns = [
                TextColumn(f"[{primary}]{{task.fields[title]:13.13}}"),
                BarColumn(bar_width=8, complete_style=primary, finished_style=secondary),
                TaskProgressColumn(), TransferSpeedColumn(),
            ]
        else:
            progress_columns = [
                *([SpinnerColumn(style=secondary)] if self.settings.ui_animations and not self.settings.ui_reduced_motion else []),
                TextColumn(f"[{primary}]{{task.fields[title]:28.28}}"),
                BarColumn(bar_width=18, complete_style=primary, finished_style=secondary),
                TaskProgressColumn(), DownloadColumn(), TransferSpeedColumn(),
                TimeRemainingColumn(), TextColumn(f"[{secondary}]{{task.fields[phase]}}"),
            ]
        with input_controls, Progress(*progress_columns,
                                     console=self.console, refresh_per_second=(5 if self.settings.ui_animations and not self.settings.ui_reduced_motion else 2)) as progress:
            tasks = [progress.add_task("Download", total=100, completed=0,
                                       title=f"Item {i + 1}", phase="Queued")
                     for i in range(len(jobs))]
            pool = ThreadPoolExecutor(max_workers=self.settings.concurrency)
            futures: dict[Future[DownloadResult], int] = {}

            def worker(index: int, job: DownloadJob) -> DownloadResult:
                if self.cancel.is_set():
                    return DownloadResult("cancelled", f"Item {index + 1}")
                if on_start:
                    on_start(index)
                return self._one(job, progress, tasks[index],
                                 (lambda: on_heartbeat(index)) if on_heartbeat else None)

            try:
                futures = {pool.submit(worker, i, job): i for i, job in enumerate(jobs)}
                for future in as_completed(futures):
                    i = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = DownloadResult("failed", f"Item {i + 1}", reason=redacted(str(exc)))
                    results[i] = result
                    if on_result:
                        on_result(i, result)
            except KeyboardInterrupt:
                self.cancel.set()
                self.paused.clear()
                for future in futures:
                    future.cancel()
                self.console.print("\n[yellow]Stopping; partial downloads are kept for resume.[/yellow]")
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
                self.paused.clear()
            for future, i in futures.items():
                if results[i] is None:
                    if future.cancelled():
                        results[i] = DownloadResult("cancelled", f"Item {i + 1}")
                    else:
                        try:
                            results[i] = future.result()
                        except Exception as exc:
                            results[i] = DownloadResult("failed", f"Item {i + 1}", reason=redacted(str(exc)))
                    if on_result:
                        on_result(i, results[i])
        return [r for r in results if r is not None]
