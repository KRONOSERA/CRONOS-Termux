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
from .dispatch import dispatch, run_queue, noninteractive

def ask_select(title: str, choices: list[str], default: str | None = None) -> str:
    result = questionary.select(title, choices=choices, default=default, style=ui.question_style(), use_jk_keys=True).ask()
    if result is None:
        raise KeyboardInterrupt
    ui.motion.tap(result)
    return result


def ask_text(title: str, default: str = "", validator: Callable[[str], str | bool] | None = None) -> str:
    result = questionary.text(title, default=default, validate=validator, style=ui.question_style()).ask()
    if result is None:
        raise KeyboardInterrupt
    return result.strip()


def ask_yes(title: str, default: bool = False) -> bool:
    result = questionary.confirm(title, default=default, style=ui.question_style()).ask()
    if result is None:
        raise KeyboardInterrupt
    ui.motion.tap("Confirmed" if result else "Not confirmed")
    return bool(result)


def positive_int(title: str, default: int, upper: int) -> int:
    def valid(s: str) -> bool | str:
        if not s.isdigit() or not (1 <= int(s) <= upper):
            return f"Enter a number from 1 to {upper}"
        return True
    return int(ask_text(title, str(default), validator=valid))


def one_url(default: str = "") -> str:
    if not default and _clipboard_enabled:
        clip = get_clipboard()
        if clip:
            try:
                default = validate_url(clip)
                console.print("[dim]A YouTube URL was detected in the clipboard.[/dim]")
            except ValueError:
                pass
    def valid(s: str) -> bool | str:
        try:
            validate_url(s)
            return True
        except ValueError as exc:
            return str(exc)
    return validate_url(ask_text("Paste an HTTPS YouTube / YouTube Music URL:", default, valid))


def choose_video(info: dict | None, settings: Settings) -> tuple[int | None, int]:
    """Show real stream options with a fallback to the user's FPS preference."""
    fps = settings.fps_preference
    options = ui.quality_choices(info, fps)
    if not options:
        raise ValueError("No supported quality levels available for this media")
    ui.show_quality_guide(options)
    labels = [entry.label for entry in options]
    suggested = next((entry.label for entry in options if entry.height == settings.video_height), labels[0])
    label = ask_select("Choose video quality", labels, suggested)
    height = next(entry.height for entry in options if entry.label == label)
    fps = int(ask_select("Prefer FPS (only if source offers it)", ["60", "30"], str(fps)))
    if info:
        choice = select_video(info, height, fps)
        ui.notice(f"Selected: {choice.height}p · {choice.fps or '?'} FPS · {choice.codec}")
        if not choice.compatible:
            ui.notice("H.264 is not available for this stream; Android compatibility may vary.", "warning")
        if height and choice.height != height:
            ui.notice(f"{height}p unavailable; using {choice.height}p.", "warning")
    return height, fps


def choose_music(settings: Settings) -> tuple[str, int, str | None]:
    fmt = ask_select("Audio format:", ["mp3", "m4a", "opus", "flac", "wav"], settings.audio_format)
    bitrate = settings.mp3_bitrate
    if fmt == "mp3":
        bitrate = int(ask_select("MP3 output bitrate:", [str(n) for n in ALLOWED_BITRATES], str(bitrate)))
        console.print("[dim]Note: converting lossy YouTube audio to 320 kbps does not restore lost detail.[/dim]")
    elif fmt in ("flac", "wav"):
        console.print("[yellow]Lossless output format does not make the YouTube source lossless.[/yellow]")
    lyrics = None
    if ask_yes("Embed lyrics from your own licensed UTF-8 .txt or .lrc file?", default=False):
        text = ask_text("Full path to lyrics file:")
        file = Path(text).expanduser()
        if not file.is_file():
            raise ValueError("Lyrics file does not exist")
        lyrics = str(file)
    return fmt, bitrate, lyrics


def maybe_custom_folder() -> str | None:
    return (ask_text("Custom output directory (blank = default):") or None) if ask_yes(
        "Use a custom output directory?", default=False) else None


def confirm_rights() -> bool:
    return ask_yes("Confirm you own, are licensed to save, or are authorized to download this media?", False)


def quick_download(manager: DownloadManager) -> int:
    """One-link workflow: inspect, choose a sensible preset, review, act.

    In contrast with Advanced Video/Music, this path asks only essential questions.
    Authorization is confirmed before any download or queue insertion.
    """
    from . import one_url, ask_select, confirm_rights, dispatch, ask_text
    ui.screen_header("Quick Download", "Paste → choose → review → save")
    url = one_url()
    if is_playlist_url(url):
        ui.notice("Playlist detected. Opening Playlist Studio.")
        return do_playlist(manager, url)
    with ui.activity("Reading available media formats…"):
        info = manager.inspect(url)
    show_info(info)
    kind = ask_select("Download as", ["Video  ·  MP4", "Music  ·  audio file", "Cancel"])
    if kind == "Cancel":
        return 0
    is_video = kind.startswith("Video")
    job: DownloadJob
    if is_video:
        options = ui.quality_choices(info, manager.settings.fps_preference)
        if not options:
            ui.notice("No compatible video streams found.", "error")
            return 1
        recommended = next((entry for entry in options if entry.height == manager.settings.video_height), options[0])
        preset = ask_select("Video preset", [
            f"Recommended  ·  {recommended.label} / {manager.settings.fps_preference} FPS",
            "Best available  ·  highest source quality",
            "Data saver  ·  up to 480p",
            "Choose quality & FPS…",
            "Cancel",
        ])
        if preset == "Cancel":
            return 0
        if preset.startswith("Recommended"):
            height, fps = recommended.height, manager.settings.fps_preference
        elif preset.startswith("Best available"):
            height, fps = None, manager.settings.fps_preference
        elif preset.startswith("Data saver"):
            height, fps = 480, 30
        else:
            height, fps = choose_video(info, manager.settings)
        actual = select_video(info, height, fps)
        if not actual.compatible:
            ui.notice("Selected format may not be H.264; playback compatibility varies.", "warning")
        job = DownloadJob(url, height=height, fps=fps)
        description = f"MP4 · {actual.height}p · {actual.fps or '?'} FPS · {actual.codec}"
        estimated = actual.estimated_bytes
        folder = manager.settings.video_dir
    else:
        choice = ask_select("Music preset", [
            f"Recommended  ·  {manager.settings.audio_format.upper()} {manager.settings.mp3_bitrate if manager.settings.audio_format == 'mp3' else ''}",
            "MP3  ·  192 kbps",
            "M4A  ·  original lossy stream where available",
            "OPUS  ·  efficient compression",
            "Choose format, bitrate & lyrics…",
            "Cancel",
        ])
        if choice == "Cancel":
            return 0
        fmt, bitrate, lyrics = manager.settings.audio_format, manager.settings.mp3_bitrate, None
        if choice.startswith("MP3"):
            fmt, bitrate = "mp3", 192
        elif choice.startswith("M4A"):
            fmt = "m4a"
        elif choice.startswith("OPUS"):
            fmt = "opus"
        elif choice.startswith("Choose"):
            fmt, bitrate, lyrics = choose_music(manager.settings)
        job = DownloadJob(url, kind="music", audio_format=fmt, bitrate=bitrate, lyrics_file=lyrics)
        description = f"{fmt.upper()}" + (f" · {bitrate} kbps output" if fmt == "mp3" else "")
        folder = manager.settings.music_dir
        duration = info.get("duration")
        estimated = int(duration * bitrate * 1000 / 8) if fmt == "mp3" and isinstance(duration, (int, float)) and duration > 0 else None
    while True:
        ui.download_summary(info.get("title") or "Untitled", description, folder, estimated)
        action = ask_select("What next?", ["Download now", "Save to queue", "Change destination / filename", "Cancel"])
        if action == "Cancel":
            return 0
        if action == "Change destination / filename":
            folder = ask_text("Output directory", folder)
            filename = ask_text("Filename (blank = video title):", job.filename or "")
            job = replace(job, output_dir=folder, filename=filename or None)
            continue
        if not confirm_rights():
            ui.notice("No download started without authorization.", "warning")
            return 0
        return dispatch(manager, [job], yes=True, queue_mode=(action == "Save to queue"), authorization_mode="interactive")


def do_video(manager: DownloadManager, url: str = "", *, yes: bool = False) -> int:
    url = one_url(url)
    info = manager.inspect(url)
    show_info(info)
    height, fps = choose_video(info, manager.settings)
    output = maybe_custom_folder()
    custom = ask_text("Custom filename without extension (blank = title):") or None if ask_yes(
        "Customize the filename?", default=False) else None
    return dispatch(manager, [DownloadJob(url, height=height, fps=fps, output_dir=output,
                                          filename=custom)], yes)


def do_music(manager: DownloadManager, url: str = "", *, yes: bool = False) -> int:
    url = one_url(url)
    show_info(manager.inspect(url))
    fmt, bitrate, lyrics = choose_music(manager.settings)
    output = maybe_custom_folder()
    return dispatch(manager, [DownloadJob(url, kind="music", audio_format=fmt,
                                          bitrate=bitrate, output_dir=output,
                                          lyrics_file=lyrics)], yes)


def do_playlist(manager: DownloadManager, url: str = "", *, yes: bool = False,
                limit: int | None = None) -> int:
    url = one_url(url)
    if not is_playlist_url(url):
        console.print("[yellow]This URL does not look like a playlist; checking anyway.[/yellow]")
    limit = limit or positive_int("Maximum items:", manager.settings.playlist_limit, 500)
    playlist_data = manager.inspect_playlist(url, limit)
    name, entries = parse_playlist(playlist_data, limit)
    console.print(f"[bold cyan]Playlist:[/bold cyan] {name} • {len(entries)} accessible items")
    if not entries:
        console.print("[red]No public or accessible videos were found in that playlist.[/red]")
        return 1
    kind = ask_select("Playlist output:", ["video", "music"])
    kwargs: dict = {"kind": kind, "playlist_title": name,
                    "output_dir": maybe_custom_folder()}
    if kind == "video":
        height, fps = choose_video(None, manager.settings)
        kwargs.update(height=height, fps=fps)
    else:
        fmt, bitrate, lyrics = choose_music(manager.settings)
        kwargs.update(audio_format=fmt, bitrate=bitrate, lyrics_file=lyrics)
    table = Table(title="PLAYLIST PREVIEW", box=box.SIMPLE, border_style="cyan")
    table.add_column("#", style="magenta", justify="right")
    table.add_column("Title", overflow="fold")
    for i, entry in enumerate(entries[:60], 1):
        table.add_row(str(i), Text(entry.title[:90]))
    console.print(table)
    if len(entries) > 60:
        console.print(f"[dim]Showing the first 60 of {len(entries)} entries.[/dim]")
    selection_mode = ask_select("Which playlist entries?", ["All", "Select number ranges", "Search titles"])
    if selection_mode == "Select number ranges":
        expression = ask_text("Positions (e.g. 1-5,8,12):")
        selected = subset(entries, expression)
    elif selection_mode == "Search titles":
        selected = subset(entries, search=ask_text("Title contains:"))
    else:
        selected = entries
    console.print(f"[cyan]{len(selected)} entries selected.[/cyan]")
    jobs = [DownloadJob(entry.url, index=entry.index, **kwargs) for entry in selected]
    return dispatch(manager, jobs, yes)


def do_multi(manager: DownloadManager, *, yes: bool = False, enqueue: bool = False) -> int:
    console.print("[cyan]Paste one or more URLs per line. Submit an empty line to finish.[/cyan]")
    pasted: list[str] = []
    while True:
        line = ask_text(f"URL line {len(pasted)+1} (blank = start):")
        if not line:
            break
        pasted.append(line)
    urls = parse_urls("\n".join(pasted))
    if not urls:
        return 0
    kind = ask_select(f"Download {len(urls)} individual URL(s) as:", ["video", "music"])
    output = maybe_custom_folder()
    if kind == "video":
        height, fps = choose_video(None, manager.settings)
        jobs = [DownloadJob(url, height=height, fps=fps, output_dir=output) for url in urls]
    else:
        fmt, bitrate, lyrics = choose_music(manager.settings)
        jobs = [DownloadJob(url, kind="music", audio_format=fmt,
                            bitrate=bitrate, output_dir=output, lyrics_file=lyrics) for url in urls]
    return dispatch(manager, jobs, yes, queue_mode=enqueue)


def show_history(db: HistoryDB, *, pause: bool = True) -> None:
    rows = db.recent(25)
    table = Table(title="Recent downloads", border_style="bright_magenta", box=box.ROUNDED)
    table.add_column("Date (UTC)")
    table.add_column("Status")
    table.add_column("Title", overflow="fold", max_width=35)
    table.add_column("Format")
    table.add_column("Location / Error", overflow="fold", max_width=35)
    for row in rows:
        table.add_row(row["created_at"][:16], row["status"], Text(row["title"][:75]),
                      f"{row['format']} {row['quality']}", Text(row["file_path"] or redacted(row["error"] or "")))
    console.print(table if rows else "[dim]History is empty.[/dim]")
    if pause:
        ask_text("Press Enter to return to the main menu:")


def edit_settings(settings: Settings) -> Settings:
    keys = {
        "Video folder": "video_dir",
        "Music folder": "music_dir",
        "Concurrent downloads (1–4)": "concurrency",
        "Playlist item limit (1–500)": "playlist_limit",
        "Batch confirmation threshold (1–500)": "batch_confirmation_threshold",
        "Default MP3 bitrate": "mp3_bitrate",
        "Default audio format": "audio_format",
        "Default video resolution": "video_height",
        "Default FPS preference": "fps_preference",
        "Embed artwork": "embed_artwork",
        "Rate limit KiB/s per download (0=unlimited)": "rate_limit_kib",
        "Concurrent fragments per download (1–4)": "fragment_concurrency",
        "Video subtitle downloads": "subtitles_mode",
        "Subtitle languages (comma separated)": "subtitles_languages",
        "Filename style": "filename_style",
    }
    while True:
        choice = ask_select("Settings (saved locally):", [*keys, "Back"])
        if choice == "Back":
            return settings
        field = keys[choice]
        value = getattr(settings, field)
        if field in ("video_dir", "music_dir", "subtitles_languages"):
            new = ask_text(f"{choice}:", str(value))
        elif field == "subtitles_mode":
            new = ask_select(choice, ["none", "manual", "automatic"], str(value))
        elif field == "filename_style":
            new = ask_select(choice, ["title", "channel-title", "date-title"], str(value))
        elif field == "concurrency":
            new = positive_int(choice, value, 4)
        elif field in ("playlist_limit", "batch_confirmation_threshold"):
            new = positive_int(choice, value, 500)
        elif field == "fragment_concurrency":
            new = positive_int(choice, value, 4)
        elif field == "rate_limit_kib":
            text = ask_text("Rate limit in KiB/s (0..10240):", str(value),
                            lambda s: True if s.isdecimal() and 0 <= int(s) <= 10240 else "Enter 0..10240")
            new = int(text)
        elif field == "mp3_bitrate":
            new = int(ask_select(choice, [str(n) for n in ALLOWED_BITRATES], str(value)))
        elif field == "audio_format":
            new = ask_select(choice, list(ALLOWED_AUDIO), str(value))
        elif field == "video_height":
            new = int(ask_select(choice, [str(n) for n in ALLOWED_HEIGHTS], str(value)))
        elif field == "fps_preference":
            new = int(ask_select(choice, ["30", "60"], str(value)))
        else:
            new = ask_yes(choice, bool(value))
        new_settings = replace(settings, **{field: new})
        save_settings(new_settings)
        settings = new_settings
        console.print("[green]Saved.[/green]")


def show_queue(queue: QueueDB, limit: int = 75) -> None:
    items = queue.list(statuses=("queued", "paused", "running", "failed", "done"), limit=limit)
    counts = queue.counts()
    ui.section("QUEUE", f"{len(items)} recent entries")
    console.print("  ".join(f"[{color}]{name} {counts[name]}[/]" for name, color in
                           (("queued", "cyan"), ("running", "green"), ("paused", "yellow"),
                            ("failed", "red"), ("done", "magenta"))))
    if not items:
        ui.notice("No jobs yet. Add a link from Quick Download.")
        return
    table = Table(box=box.SIMPLE, border_style=ui.palette()[0], expand=True)
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("State", no_wrap=True)
    if not ui.compact():
        table.add_column("Kind")
        table.add_column("Pri", justify="right")
    table.add_column("Item", overflow="ellipsis")
    for item in items:
        name = item.job.filename or item.job.url.split("?")[0].rsplit("/", 1)[-1]
        if not name or name == "watch":
            from urllib.parse import parse_qs, urlsplit
            name = parse_qs(urlsplit(item.job.url).query).get("v", ["YouTube"])[0]
        state_style = {"queued":"cyan", "running":"green", "paused":"yellow", "failed":"red", "done":"magenta"}[item.status]
        common = [str(item.id), f"[{state_style}]{item.status}[/]"]
        if not ui.compact():
            common.extend([item.job.kind, str(item.priority)])
        table.add_row(*common, Text(ui.clipped(name, 25 if ui.compact() else 55)))
    console.print(table)


def show_stats(manager: DownloadManager, queue: QueueDB) -> None:
    stats = manager.history.statistics(include_size=True)
    counts = queue.counts()
    table = Table(title="CRONOS  /  STATISTICS", border_style="cyan", show_header=False)
    for label, number in (
        ("Videos saved", stats["video"]),
        ("Audio files saved", stats["music"]),
        ("Unique items (by type)", stats["unique_media"]),
        ("Historical failures", stats["failed_attempts"]),
        ("Queued", counts["queued"]),
        ("Paused", counts["paused"]),
        ("Failed in queue", counts["failed"]),
        ("Completed in queue", counts["done"]),
        ("Saved files currently on disk", stats["files_on_disk"]),
        ("Disk space occupied", f"{stats['size_bytes'] / (1024 ** 2):,.1f} MiB"),
    ):
        table.add_row(label, str(number))
    console.print(table)
    console.print("[dim]Counts reflect local history, not deleted or externally moved files.[/dim]")


def manage_queue(manager: DownloadManager) -> None:
    queue = QueueDB(manager.history.path)
    while True:
        if manager.settings.ui_clear_screen:
            console.clear()
        ui.screen_header("Download Queue", "Your transfers, even after closing Termux")
        show_queue(queue)
        action = ask_select("Queue actions", [
            "Start waiting downloads", "Add multiple links", "Pause / resume jobs",
            "Change priority", "Remove / clean up", "Statistics", "Back to home",
        ])
        if action == "Back to home":
            return
        if action == "Start waiting downloads":
            run_queue(manager, queue)
        elif action == "Add multiple links":
            do_multi(manager, enqueue=True)
        elif action == "Pause / resume jobs":
            operation = ask_select("Queue state", [
                "Pause one", "Resume one", "Pause all waiting", "Resume all paused/failed", "Back",
            ])
            if operation in ("Pause one", "Resume one"):
                choices = queue.list(statuses=("queued",) if operation == "Pause one" else ("paused", "failed"))
                if not choices:
                    ui.notice("There are no matching jobs.", "warning")
                else:
                    labels = {f"#{item.id}  {item.status}  {ui.clipped(item.job.filename or item.job.url, 36)}": item.id
                              for item in choices}
                    selection = ask_select("Choose a job", [*labels, "Back"])
                    if selection != "Back":
                        destination = "paused" if operation == "Pause one" else "queued"
                        queue.change(labels[selection], destination)
                        ui.notice("Job state updated.", "success")
            elif operation == "Pause all waiting":
                if ask_yes("Pause ALL waiting jobs?", False):
                    ui.notice(f"Paused {queue.change_all('paused')} job(s).", "success")
            elif operation == "Resume all paused/failed":
                if ask_yes("Requeue ALL paused or failed jobs?", False):
                    ui.notice(f"Requeued {queue.change_all('queued')} job(s).", "success")
        elif action == "Change priority":
            candidates = queue.list(statuses=("queued", "paused", "failed"))
            if not candidates:
                ui.notice("No waiting jobs to prioritize.", "warning")
            else:
                labels = {f"#{item.id}  P{item.priority} · {ui.clipped(item.job.filename or item.job.url, 38)}": item.id
                          for item in candidates}
                selected = ask_select("Pick an item", [*labels, "Back"])
                if selected != "Back":
                    level = int(ask_select("Priority (9 = highest)", [str(n) for n in range(9, -1, -1)], "5"))
                    queue.prioritize(labels[selected], level)
                    ui.notice("Priority changed.", "success")
        elif action == "Remove / clean up":
            operation = ask_select("Cleanup", ["Remove one queue entry", "Clear completed records", "Back"])
            if operation == "Remove one queue entry":
                labels = {f"#{item.id}  {item.status}": item.id
                          for item in queue.list() if item.status != "running"}
                if labels:
                    selected = ask_select("Choose item", [*labels, "Back"])
                    if selected != "Back" and ask_yes("Remove queue record only? Media files are kept.", False):
                        queue.remove(labels[selected])
                        ui.notice("Queue record removed; media files kept.", "success")
                else:
                    ui.notice("No removable queue entries.", "warning")
            elif operation == "Clear completed records":
                if ask_yes("Clear completed records? Downloaded files stay on disk.", False):
                    ui.notice(f"Cleared {queue.clear_completed()} records.", "success")
        elif action == "Statistics":
            show_stats(manager, queue)
        ask_text("Enter to continue")


def library_screen(manager: DownloadManager) -> None:
    """Browse local history without touching or deleting any media."""
    while True:
        if manager.settings.ui_clear_screen:
            console.clear()
        ui.screen_header("Media Library", "Search, check, and export saved media")
        selected = ask_select("Library actions", [
            "Browse recent", "Search by title or ID", "Find missing files",
            "Export CSV inventory", "Export M3U playlist", "Back to home",
        ])
        if selected == "Back to home":
            return
        if selected in ("Browse recent", "Search by title or ID", "Find missing files"):
            query = ask_text("Search for") if selected == "Search by title or ID" else ""
            kind = ask_select("Show", ["all", "video", "music"], "all")
            rows = search_library(manager.history, query, kind=kind,
                                  missing_only=selected == "Find missing files", limit=100)
            table = Table(title=f"LIBRARY  /  {len(rows)} records", box=box.SIMPLE,
                          border_style=ui.palette()[0], expand=True)
            table.add_column("State", no_wrap=True)
            if not ui.compact():
                table.add_column("Type")
            table.add_column("Title", overflow="ellipsis")
            if not ui.compact():
                table.add_column("Size", justify="right")
            for entry in rows:
                cols = ["[green]OK[/green]" if entry.present else "[red]Gone[/red]"]
                if not ui.compact():
                    cols.append(entry.kind)
                cols.append(Text(ui.clipped(entry.title, 32 if ui.compact() else 72)))
                if not ui.compact():
                    cols.append(ui.human_size(entry.size_bytes) if entry.present else "—")
                table.add_row(*cols)
            console.print(table if rows else "[yellow]No matching media.[/yellow]")
        else:
            fmt = "csv" if selected == "Export CSV inventory" else "m3u"
            kind = ask_select("Include", ["all", "video", "music"])
            output = ask_text(f"Export path (.{fmt}), leave blank for default")
            dest = Path(output).expanduser() if output else state_dir() / "exports" / f"library.{fmt}"
            if dest.exists() and not ask_yes("Export exists. Replace it?", False):
                continue
            path, number = export_library(manager.history, dest, format=fmt, kind=kind)
            ui.notice(f"Exported {number} saved files to {path}", "success")
        ask_text("Enter to continue")


def doctor_screen(manager: DownloadManager) -> None:
    table = Table(title="CRONOS  /  DEVICE DIAGNOSTICS", box=box.ROUNDED,
                  border_style="cyan")
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Details", overflow="fold")
    for line in diagnostics(manager.settings):
        table.add_row(line.name, "[green]OK[/green]" if line.ok else "[red]ISSUE[/red]",
                      Text(redacted(line.detail)))
    console.print(table)
    console.print("[dim]This report does not send device information to a server.[/dim]")


def backup_screen() -> None:
    console.print("[cyan]Backs up settings and SQLite queue/history, not media files.[/cyan]")
    console.print("[yellow]The archive contains private queued URLs; keep it secure.[/yellow]")
    if ask_yes("Create a private local backup now?", False):
        path = create_backup()
        console.print(f"[green]Backup saved to {path}[/green]")


def appearance_settings(settings: Settings, history: HistoryDB) -> Settings:
    """Customize colors, responsive layout, motion and accessibility."""
    global _clipboard_enabled
    while True:
        ui.screen_header("Appearance & Motion", "Make CRONOS yours — your settings stay on-device")
        selection = ask_select("Change a preference", [
            f"Theme: {settings.ui_theme}",
            f"Animations: {'ON' if settings.ui_animations else 'OFF'}",
            f"Reduced motion: {'ON' if settings.ui_reduced_motion else 'OFF'}",
            f"Animated intro: {'ON' if settings.ui_intro else 'OFF'}",
            f"Motion style: {settings.ui_motion_style}",
            f"Motion speed: {settings.ui_motion_speed}",
            f"Compact layout: {'ON' if settings.ui_compact else 'AUTO'}",
            f"Clear screens: {'ON' if settings.ui_clear_screen else 'OFF'}",
            f"Navigation tips: {'ON' if settings.ui_tips else 'OFF'}",
            f"Clipboard suggestions: {'ON' if settings.ui_clipboard else 'OFF'}",
            "Play animation showcase", "Preview home screen", "Back",
        ])
        if selection == "Back":
            return settings
        if selection == "Play animation showcase":
            ui.motion_preview()
            continue
        if selection == "Preview home screen":
            banner()
            dashboard(history, QueueDB(history.path), settings)
            ui.notice("The preview reflects your current appearance preferences.")
            continue
        if selection.startswith("Theme"):
            value = ask_select("Color theme", ["neon", "ocean", "minimal"], settings.ui_theme)
            key = "ui_theme"
        elif selection.startswith("Motion style"):
            value = ask_select("Motion style", ["glide", "pulse", "typewriter"], settings.ui_motion_style)
            key = "ui_motion_style"
        elif selection.startswith("Motion speed"):
            value = ask_select("Motion speed", ["calm", "normal", "swift"], settings.ui_motion_speed)
            key = "ui_motion_speed"
        else:
            key = next((name for prefix, name in (
                ("Animations", "ui_animations"),
                ("Reduced motion", "ui_reduced_motion"),
                ("Animated intro", "ui_intro"),
                ("Compact layout", "ui_compact"),
                ("Clear screens", "ui_clear_screen"),
                ("Navigation tips", "ui_tips"),
                ("Clipboard suggestions", "ui_clipboard"),
            ) if selection.startswith(prefix)), None)
            if key is None:
                continue
            value = not getattr(settings, key)
        changed = replace(settings, **{key: value})
        save_settings(changed)
        settings = changed
        ui.configure(settings)
        _clipboard_enabled = settings.ui_clipboard
        ui.notice("Appearance saved.", "success")


def help_screen() -> None:
    ui.screen_header("Help & Controls", "Designed for Android keyboards")
    table = Table(show_header=False, box=box.SIMPLE, expand=True, border_style=ui.palette()[0])
    table.add_column(style=ui.palette()[1], no_wrap=True)
    table.add_column(overflow="fold")
    for key, value in [
        ("↑ / ↓", "Move through menus"), ("Enter", "Choose an item"),
        ("Ctrl+C", "Cancel the current prompt or transfer"),
        ("P", "Pause active transfers after current chunk"),
        ("R", "Resume transfers"), ("C", "Stop active transfers; keep partial files"),
        ("Quick Download", "Simplest flow: link → preset → review"),
        ("Back", "Return without changing settings"),
        ("Animations", "Appearance & motion → enable, speed, style or reduce motion"),
    ]:
        table.add_row(key, value)
    console.print(table)
    ui.notice("Use media you own, have a license for, or are authorized to save.")


def tools_menu(manager: DownloadManager, queue: QueueDB) -> None:
    while True:
        if manager.settings.ui_clear_screen:
            console.clear()
        ui.screen_header("Tools & Settings", "Keep your media and settings under control")
        selection = ask_select("Tools", [
            "History & statistics", "Download preferences", "Appearance & motion",
            "Device diagnostics", "Back up data", "Update download engine",
            "Help & keyboard shortcuts", "Back to home",
        ])
        if selection == "Back to home":
            return
        if selection == "History & statistics":
            show_history(manager.history, pause=False)
            show_stats(manager, queue)
        elif selection == "Download preferences":
            manager.settings = edit_settings(manager.settings)
            continue
        elif selection == "Appearance & motion":
            manager.settings = appearance_settings(manager.settings, manager.history)
            continue
        elif selection == "Device diagnostics":
            doctor_screen(manager)
        elif selection == "Back up data":
            backup_screen()
        elif selection == "Update download engine":
            if ask_yes("Update engine packages? Previous versions will be recorded for rollback.", False):
                code = update_engine()
                ui.notice("Engine update verified." if code == 0 else "Engine update unsuccessful; see details above.",
                          "success" if code == 0 else "warning")
        elif selection == "Help & keyboard shortcuts":
            help_screen()
        ask_text("Enter to continue")


def show_upgrade_notice() -> None:
    """Show an installer-generated notice exactly once on an interactive launch."""
    path = next((candidate for candidate in (
        state_dir() / "whats-new-v3.0.1.txt",
        state_dir() / "whats-new-v3.0.0.txt",
        state_dir() / "whats-new-v2.1.1.txt") if candidate.is_file()), None)
    if path is None:
        return
    try:
        content = path.read_text(encoding="utf-8")[:2500]
        path.unlink()
    except OSError:
        return
    from . import ask_text as patched_ask_text
    ui.screen_header("What's new", f"CRONOS {__version__}")
    console.print(Text(content))
    patched_ask_text("Press Enter to continue")


def run_menu(manager: DownloadManager) -> int:
    queue = QueueDB(manager.history.path)
    ui.configure(manager.settings)
    ui.play_intro()
    show_upgrade_notice()
    while True:
        if manager.settings.ui_clear_screen:
            console.clear()
        ui.arrive_home()
        banner()
        dashboard(manager.history, queue, manager.settings)
        ui.section("START HERE")
        mobile = ui.compact()
        labels = {
            ("Quick Download" if mobile else "Quick Download   ·   one link, three steps"): "quick",
            ("Video / advanced" if mobile else "Download video   ·   advanced options"): "video",
            ("Music / advanced" if mobile else "Download music   ·   formats & metadata"): "music",
            ("Playlists" if mobile else "Playlist Studio   ·   select individual tracks"): "playlist",
            ("Multiple URLs" if mobile else "Batch links   ·   paste multiple URLs"): "batch",
            ("Queue" if mobile else "Download queue   ·   pause, resume & priorities"): "queue",
            ("Library" if mobile else "Media library   ·   search your downloads"): "library",
            "Tools & settings": "tools",
            "Exit CRONOS": "exit",
        }
        choice = labels[ask_select("Choose an action", list(labels))]
        try:
            if choice == "quick":
                quick_download(manager)
            elif choice == "video":
                do_video(manager)
            elif choice == "music":
                do_music(manager)
            elif choice == "playlist":
                do_playlist(manager)
            elif choice == "batch":
                do_multi(manager)
            elif choice == "queue":
                manage_queue(manager)
                continue
            elif choice == "library":
                library_screen(manager)
                continue
            elif choice == "tools":
                tools_menu(manager, queue)
                continue
            else:
                ui.motion.signal("Goodbye from CRONOS")
                return 0
        except KeyboardInterrupt:
            ui.notice("Action cancelled. Your existing downloads were not deleted.", "warning")
        except Exception as exc:
            ui.notice(f"Operation failed: {redacted(str(exc))}", "error")
            console.print("[dim]Details: ~/.local/state/cronos-yt/errors.log[/dim]")
        ask_text("Enter to return home")


