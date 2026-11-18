"""Optional single-key TTY controls for interactive download sessions."""
from __future__ import annotations

import os
import select
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console
    from .downloader import DownloadManager


class DownloadControls:
    def __init__(self, manager: "DownloadManager", console: "Console") -> None:
        self.manager = manager
        self.console = console
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        self.fd: int | None = None
        self.old_attrs = None

    def __enter__(self) -> "DownloadControls":
        if not sys.stdin.isatty():
            return self
        try:
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.old_attrs = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            self.worker = threading.Thread(target=self._listen, daemon=True, name="cronos-keys")
            self.worker.start()
        except (OSError, ValueError, ImportError):
            self.fd = None
        return self

    def handle_key(self, key: str) -> None:
        if key.lower() == "p":
            self.manager.paused.set()
            self.console.print("[yellow]Paused after current transfer chunk. Press r to resume.[/yellow]")
        elif key.lower() == "r":
            self.manager.paused.clear()
            self.console.print("[green]Resuming downloads.[/green]")
        elif key.lower() == "c":
            self.manager.cancel.set()
            self.manager.paused.clear()
            self.console.print("[yellow]Stopping downloads; partial files retained.[/yellow]")

    def _listen(self) -> None:
        while not self.stop.is_set() and not self.manager.cancel.is_set():
            try:
                if self.fd is not None and select.select([self.fd], [], [], .15)[0]:
                    key = os.read(self.fd, 1)
                    if key:
                        self.handle_key(key.decode("utf-8", errors="ignore"))
            except (OSError, ValueError):
                return

    def __exit__(self, *_exc: object) -> None:
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=1)
        if self.fd is not None and self.old_attrs is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_attrs)
