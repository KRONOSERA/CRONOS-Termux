"""Interactive Rich/Questionary user interface and arguments."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable

import questionary
from rich.table import Table
from rich.text import Text
from rich import box

from .. import __version__, ui
from ..updater import update_engine, restore_engine
from ..authorization import AuthorizationDB
from ..downloader import DownloadJob, DownloadManager, redacted
from ..history import HistoryDB
from ..library import search_library, export_library
from ..playlist_tools import subset
from ..doctor import diagnostics
from ..backup import create_backup
from ..queue import QueueDB
from ..playlists import parse_playlist
from ..settings import (ALLOWED_AUDIO, ALLOWED_BITRATES, ALLOWED_HEIGHTS,
                       Settings, config_path, state_dir, load_settings, save_settings)
from ..share import install_share_handler
from ..storage import (check_dependencies, get_clipboard, is_playlist_url,
                      parse_urls, sanitize_filename, validate_url)
from ..ui import banner, console, dashboard, report, show_info
from ..video import available_heights, select_video


_clipboard_enabled = True



from .parser import parser
from .dispatch import dispatch, noninteractive, run_queue
from .menus import (ask_select, ask_text, ask_yes, positive_int, one_url, choose_video,
                    choose_music, maybe_custom_folder, confirm_rights, quick_download,
                    do_video, do_music, do_playlist, do_multi, show_history, edit_settings,
                    show_queue, show_stats, manage_queue, library_screen, doctor_screen,
                    backup_screen, appearance_settings, help_screen, tools_menu,
                    show_upgrade_notice, run_menu)

def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.install_share_handler:
        ok, message = install_share_handler()
        console.print(("[green]" if ok else "[yellow]") + message)
        return 0
    if args.update and args.update_unpinned:
        raise ValueError("Choose --update or --update-unpinned, not both")
    if args.update_unpinned:
        return update_engine(unpinned=True, yes=args.yes)
    if args.update:
        return update_engine()
    if args.restore_engine:
        return restore_engine()
    if args.ui_preview or args.motion_preview:
        settings = load_settings()
        if args.no_animation:
            settings = replace(settings, ui_animations=False)
        ui.configure(settings)
        if args.motion_preview:
            ui.motion_preview()
            banner()
            ui.notice("Offline animation preview complete. No network was used.")
            return 0
        history = HistoryDB()
        banner()
        dashboard(history, QueueDB(history.path), settings)
        ui.section("START HERE")
        ui.notice("Preview only. No network download was started.")
        return 0
    missing = check_dependencies()
    if args.check:
        for problem in missing:
            console.print(f"[red]{problem}[/red]")
        if not missing:
            console.print("[green]FFmpeg, FFprobe, Node.js, yt-dlp, EJS: ready.[/green]")
        return int(bool(missing))
    if missing and not args.doctor:
        console.print("[red]Missing dependencies:[/red]")
        for issue in missing:
            console.print(f"  • {issue}")
        return 1
    try:
        settings = load_settings()
        if args.no_animation:
            settings = replace(settings, ui_animations=False)
        if args.subtitles is not None or args.subtitle_languages is not None:
            settings = replace(settings, **({"subtitles_mode": args.subtitles} if args.subtitles else {}),
                               **({"subtitles_languages": args.subtitle_languages} if args.subtitle_languages else {}))
            settings.validate()
        manager = DownloadManager(settings)
        ui.configure(settings)
        from . import menus
        menus._clipboard_enabled = settings.ui_clipboard
        if args.doctor:
            doctor_screen(manager)
            return int(any(not check.ok for check in diagnostics(settings)))
        if args.backup is not None:
            path = create_backup(None if args.backup == "AUTO" else Path(args.backup))
            console.print(f"[green]Backup: {path}[/green]")
            return 0
        if args.library or args.library_export:
            if args.library_export:
                destination = Path(args.library_export).expanduser()
                ext = destination.suffix.lower()
                if ext not in (".csv", ".m3u"):
                    raise ValueError("--library-export path must end in .csv or .m3u")
                if destination.exists():
                    raise ValueError("Export path exists; choose a new filename to avoid overwriting it")
                path, count = export_library(manager.history, destination, format=ext[1:], kind=args.library_kind)
                console.print(f"[green]Exported {count} files to {path}[/green]")
                return 0
            items = search_library(manager.history, args.library_search, kind=args.library_kind)
            table = Table(title="SAVED MEDIA LIBRARY", box=box.ROUNDED, border_style="cyan")
            table.add_column("State")
            table.add_column("Kind")
            table.add_column("Title", overflow="fold")
            table.add_column("File", overflow="fold")
            for entry in items:
                table.add_row("Saved" if entry.present else "MISSING", entry.kind,
                              Text(entry.title[:90]), Text(entry.file_path))
            console.print(table if items else "[yellow]No matching media.[/yellow]")
            return 0
        if args.queue_set_priority:
            number, level = args.queue_set_priority
            if not QueueDB(manager.history.path).prioritize(number, level):
                raise ValueError("Queue item is missing or already running/completed")
            console.print(f"[green]Queue item #{number} priority set to {level}.[/green]")
            return 0
        if args.queue_list:
            show_queue(QueueDB(manager.history.path))
            return 0
        if args.stats:
            show_stats(manager, QueueDB(manager.history.path))
            return 0
        if args.run_queue:
            if not args.yes:
                raise ValueError("--run-queue requires --yes to affirm authorization for stored URLs")
            return run_queue(manager, QueueDB(manager.history.path), controls=False, yes=True,
                             confirm_queued=args.confirm_queued, confirm_large=args.confirm_large_batch)
        if args.enqueue and not args.url:
            raise ValueError("--enqueue requires one or more --url arguments")
        if args.url:
            return noninteractive(args, manager)
        if not sys.stdin.isatty():
            console.print("[red]Interactive menu requires a terminal. Use --url ... --mode ... --yes.[/red]")
            return 2
        return run_menu(manager)
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return 130
    except (OSError, ValueError) as exc:
        console.print(f"[red]{redacted(str(exc))}[/red]")
        return 2

