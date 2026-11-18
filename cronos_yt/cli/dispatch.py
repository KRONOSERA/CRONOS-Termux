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

def _batch_confirmation(count: int, threshold: int, *, noninteractive: bool = False,
                        confirm_large: bool = False) -> bool:
    from .menus import ask_yes
    if count > 1:
        console.print(f"[cyan]Batch summary: {count} authorized media items are selected.[/cyan]")
    if count <= threshold:
        return True
    console.print(f"[yellow]Large batch: {count} items exceeds the {threshold}-item threshold.[/yellow]")
    if noninteractive:
        if not confirm_large:
            raise ValueError("Large batch requires --confirm-large-batch in noninteractive mode")
        return True
    return ask_yes(f"Explicitly confirm downloading or queueing all {count} items?", False)


def dispatch(manager: DownloadManager, jobs: list[DownloadJob], yes: bool = False,
             queue_mode: bool = False, authorization_mode: str | None = None,
             confirm_large: bool = False) -> int:
    from .menus import ask_yes, confirm_rights
    if not jobs:
        console.print("[yellow]Nothing to download.[/yellow]")
        return 0
    if not _batch_confirmation(len(jobs), manager.settings.batch_confirmation_threshold,
                               noninteractive=not sys.stdin.isatty(), confirm_large=confirm_large):
        return 0
    if not yes and not confirm_rights():
        console.print("[yellow]Download not started without authorization confirmation.[/yellow]")
        return 0
    should_queue = queue_mode or (not yes and ask_yes(
        "Add to the persistent queue instead of downloading now?", False))
    auth = AuthorizationDB(manager.history.path)
    mode = "queued" if should_queue else (authorization_mode or ("--yes" if yes else "interactive"))
    receipts = [auth.record(job, mode) for job in jobs]
    if should_queue:
        ids, duplicates = QueueDB(manager.history.path).add(jobs, receipts)
        console.print(f"[green]Added {len(ids)} job(s) to queue.[/green] "
                      f"[yellow]{duplicates} already queued.[/yellow]")
        return 0
    outcomes = manager.download(jobs, controls=not yes, authorizations=receipts)
    report(outcomes)
    if any(r.status == "failed" for r in outcomes):
        ui.notice("Some transfers failed. Check your connection and storage, then retry; for persistent errors run cronos --doctor.", "warning")
    return int(any(r.status in ("failed", "cancelled") for r in outcomes))


def noninteractive(args: argparse.Namespace, manager: DownloadManager) -> int:
    from .menus import ask_select, show_info, choose_video, choose_music
    if not args.url:
        raise ValueError("At least one --url is required")
    if not args.playlist and (args.items != "all" or args.playlist_search):
        raise ValueError("--items and --playlist-search require --playlist")
    urls = []
    for text in args.url:
        urls.extend(parse_urls(text))
    urls = list(dict.fromkeys(urls))
    if not urls:
        raise ValueError("No usable URLs")
    if args.playlist:
        if len(urls) != 1:
            raise ValueError("--playlist requires exactly one URL")
        if not args.mode:
            raise ValueError("--playlist requires --mode video or music")
        limit = args.limit or manager.settings.playlist_limit
        info = manager.inspect_playlist(urls[0], limit)
        name, entries = parse_playlist(info, limit)
        selected = subset(entries, args.items, search=args.playlist_search) if entries else []
        jobs_data = [(e.url, e.index) for e in selected]
        console.print(f"[cyan]Playlist: {name} ({len(selected)} selected from {len(entries)})[/cyan]")
        if not entries:
            return 1
    else:
        name = None
        jobs_data = [(url, None) for url in urls]
    if args.quality is None:
        height = manager.settings.video_height
    elif args.quality.lower() == "best":
        height = None
    else:
        try:
            height = int(args.quality)
        except ValueError as exc:
            raise ValueError("--quality must be 'best' or a supported resolution") from exc
        if height not in ALLOWED_HEIGHTS:
            raise ValueError("Unsupported video resolution")
    kind = args.mode or "video"
    jobs = [DownloadJob(
        url=url, kind=kind, height=height, fps=args.fps or manager.settings.fps_preference,
        audio_format=args.format or manager.settings.audio_format,
        bitrate=args.bitrate or manager.settings.mp3_bitrate,
        output_dir=args.output, filename=args.filename,
        lyrics_file=args.lyrics_file, playlist_title=name, index=index,
    ) for url, index in jobs_data]
    if not args.yes:
        if not sys.stdin.isatty():
            raise ValueError("Use --yes to affirm download authorization in noninteractive scripts")
        if not args.mode and not args.playlist:
            kind = ask_select("Download shared link as:", ["video", "music"])
            jobs = [replace(job, kind=kind) for job in jobs]
            if kind == "video":
                info = manager.inspect(jobs[0].url)
                show_info(info)
                height, fps = choose_video(info, manager.settings)
                jobs = [replace(job, height=height, fps=fps) for job in jobs]
            else:
                fmt, bitrate, lyrics = choose_music(manager.settings)
                jobs = [replace(job, audio_format=fmt, bitrate=bitrate, lyrics_file=lyrics) for job in jobs]
        return dispatch(manager, jobs, False, queue_mode=args.enqueue)
    return dispatch(manager, jobs, True, queue_mode=args.enqueue, confirm_large=args.confirm_large_batch)


def run_queue(manager: DownloadManager, queue: QueueDB, *, controls: bool = True,
              yes: bool = False, confirm_queued: bool = False,
              confirm_large: bool = False) -> int:
    from .menus import ask_yes
    items = queue.list(statuses=("queued",), limit=500)
    if not items:
        console.print("[yellow]No pending jobs. Resume paused or failed items in Queue Manager.[/yellow]")
        return 0
    console.print(f"[cyan]Queue summary: {len(items)} jobs waiting; "
                  f"{manager.settings.concurrency} parallel transfers.[/cyan]")
    if not _batch_confirmation(len(items), manager.settings.batch_confirmation_threshold,
                               noninteractive=yes, confirm_large=confirm_large):
        return 0
    receipts = [queue.auth.current_queue_receipt(item.job, item.id) for item in items]
    need_approval = sum(receipt is None for receipt in receipts)
    if need_approval:
        console.print(f"[yellow]{need_approval} job(s) lack current-session authorization. "
                      "Legacy and previous-session jobs are not approved automatically.[/yellow]")
        if yes and not confirm_queued:
            raise ValueError("Refusing stale/unauthorized queue: rerun with --confirm-queued after reviewing the job count")
        if not yes and not ask_yes(f"Authorize {need_approval} queued job(s) in this session?", False):
            return 0
        for i, receipt in enumerate(receipts):
            if receipt is None:
                receipts[i] = queue.auth.record(items[i].job, "queued", queue_id=items[i].id)
    # All receipts are verified again by DownloadManager before any network work.
    approved = [r for r in receipts if r is not None]
    if len(approved) != len(items):
        raise PermissionError("Missing queue authorization")

    def started(index: int) -> None:
        if not queue.start(items[index].id, approved[index]):
            raise PermissionError("Queue item lacks a valid session-scoped authorization")

    def finished(index: int, result) -> None:
        queue.finish(items[index].id, result)

    outcomes = manager.download([item.job for item in items], on_start=started,
                                on_result=finished, controls=controls,
                                authorizations=approved,
                                on_heartbeat=lambda i: queue.renew(items[i].id))
    report(outcomes)
    if any(r.status == "failed" for r in outcomes):
        ui.notice("Some transfers failed. Check your connection and storage, then retry; for persistent errors run cronos --doctor.", "warning")
    return int(any(r.status in ("failed", "cancelled") for r in outcomes))


