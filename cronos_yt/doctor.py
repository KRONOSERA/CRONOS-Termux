"""Read-only diagnostic checks for the Android/Termux environment."""
from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .settings import Settings, config_path, data_dir


@dataclass(frozen=True)
class Diagnostic:
    name: str
    ok: bool
    detail: str


def _program_version(command: str, args: list[str]) -> str | None:
    program = shutil.which(command)
    if not program:
        return None
    try:
        process = subprocess.run([program, *args], capture_output=True, text=True,
                                 timeout=6, check=False)
        if process.returncode:
            return None
        return (process.stdout or process.stderr).strip().splitlines()[0][:100]
    except (OSError, IndexError, subprocess.SubprocessError):
        return None


def diagnostics(settings: Settings) -> list[Diagnostic]:
    results: list[Diagnostic] = []
    results.append(Diagnostic("Python", sys.version_info >= (3, 12),
                              platform.python_version()))
    for tool, arguments in (("ffmpeg", ["-version"]), ("ffprobe", ["-version"]),
                            ("node", ["--version"])):
        detected = _program_version(tool, arguments)
        good = bool(detected)
        if tool == "node" and detected:
            import re
            match = re.match(r"v?(\d+)\.", detected)
            good = bool(match and int(match.group(1)) >= 22)
        results.append(Diagnostic(tool, good, detected or f"Not available; pkg install {('nodejs' if tool == 'node' else 'ffmpeg')}"))
    for package in ("yt-dlp", "yt-dlp-ejs", "rich", "questionary"):
        try:
            found = version(package)
            results.append(Diagnostic(package, True, found))
        except PackageNotFoundError:
            results.append(Diagnostic(package, False, "Not installed"))
    cfg = config_path()
    results.append(Diagnostic("Settings", not cfg.exists() or cfg.is_file(),
                              "Default settings" if not cfg.exists() else "Configuration exists"))
    db = data_dir() / "history.sqlite3"
    if db.is_file():
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3) as con:
                good = con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            results.append(Diagnostic("Database", good, "SQLite integrity: " + ("OK" if good else "FAILED")))
        except sqlite3.Error as exc:
            results.append(Diagnostic("Database", False, str(exc)[:100]))
    else:
        results.append(Diagnostic("Database", True, "Not created yet"))
    for kind, raw in (("Video storage", settings.video_dir), ("Music storage", settings.music_dir)):
        path = Path(raw).expanduser()
        if path.is_dir():
            try:
                free = shutil.disk_usage(path).free // (1024 ** 2)
                results.append(Diagnostic(kind, os.access(path, os.W_OK), f"{free} MiB free"))
            except OSError:
                results.append(Diagnostic(kind, False, "Storage unavailable"))
        else:
            results.append(Diagnostic(kind, False, "Folder missing or storage permission not granted"))
    api = bool(shutil.which("termux-media-scan"))
    results.append(Diagnostic("Media scan (optional)", True,
                              "Command found" if api else "Optional: install pkg termux-api and Termux:API app"))
    return results
