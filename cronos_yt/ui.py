"""CRONOS's small-screen-first Rich UI. No special terminal is required.

All layout decisions are based on the terminal width; display strings are escaped,
so untrusted YouTube metadata cannot inject Rich markup.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
import shutil

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .settings import Settings
from .motion import Motion, MotionSettings, block_logo
from .video import available_heights, select_video

try:
    from questionary import Style
except ImportError:  # diagnostics may still be displayed without Questionary
    Style = None

console = Console(highlight=False)
motion = Motion(console)

THEMES = {
    "neon": ("bright_magenta", "bright_cyan", "#c084fc", "#22d3ee"),
    "ocean": ("deep_sky_blue1", "spring_green3", "#38bdf8", "#34d399"),
    "minimal": ("white", "grey70", "#ffffff", "#a3a3a3"),
}
_current_theme = "neon"
_force_compact = False

LOGO_WIDE = "\n".join(block_logo())


def play_intro(*, force: bool = False) -> None:
    motion.console = console
    motion.intro(force=force)


def motion_preview() -> None:
    motion.console = console
    motion.demo()


def arrive_home() -> None:
    motion.console = console
    motion.transition("Home")


@contextmanager
def activity(label: str):
    """Animated terminal spinner with a static accessibility fallback."""
    if motion.active:
        with console.status(Text(label, style=palette()[1]), spinner="dots"):
            yield
    else:
        console.print(Text(label, style="dim"))
        yield

def configure(settings: Settings | None = None) -> None:
    """Select colours and mobile layout; no mutation of stored user settings."""
    global _current_theme, _force_compact
    _current_theme = (settings.ui_theme if settings else "neon")
    _force_compact = (settings.ui_compact if settings else False)
    motion.console = console
    motion.reconfigure(settings or Settings())


def compact(width: int | None = None) -> bool:
    return _force_compact or (console.size.width if width is None else width) < 68


def palette() -> tuple[str, str, str, str]:
    return THEMES.get(_current_theme, THEMES["neon"])


def question_style():
    if Style is None:
        return None
    _, _, purple, cyan = palette()
    return Style([
        ("qmark", f"fg:{purple} bold"),
        ("question", f"fg:{cyan} bold"),
        ("answer", f"fg:{purple} bold"),
        ("pointer", f"fg:{cyan} bold"),
        ("highlighted", f"fg:{purple} bold"),
        ("selected", f"fg:{cyan}"),
        ("instruction", "fg:#9ca3af"),
    ])


# Legacy export retained for older callers and third-party scripts.
QUESTION_STYLE = question_style()


def clipped(value: object, limit: int = 36) -> str:
    """Shorten untrusted display strings; never cut off control escapes in-place."""
    clean = " ".join(str(value or "").split())
    clean = "".join(ch for ch in clean if ch.isprintable())
    if limit < 2:
        return clean[:max(0, limit)]
    return clean if len(clean) <= limit else clean[:limit - 1] + "…"


def human_size(size: int | float | None) -> str:
    if size is None or size < 0:
        return "Size unknown"
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "Size unknown"


def duration_label(seconds: int | float | None) -> str:
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "Unknown"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hours}:{mins:02}:{secs:02}" if hours else f"{mins}:{secs:02}"


@dataclass(frozen=True)
class QualityChoice:
    height: int | None
    label: str
    detail: str


def quality_choices(info: dict | None, fps: int) -> list[QualityChoice]:
    """Actual formats when available; only permitted heights for batch downloads."""
    heights = sorted(available_heights(info), reverse=True) if info else [2160, 1440, 1080, 720, 480, 360, 240, 144]
    if info is not None and not heights:
        return []
    entries: list[QualityChoice] = [QualityChoice(None, "BEST available", "Automatic, highest source quality")]
    for height in heights:
        label = f"{height}p" if height != 2160 else "4K / 2160p"
        if info:
            try:
                selected = select_video(info, height, fps)
                description = f"{selected.fps or '?'} FPS · {selected.codec} · {human_size(selected.estimated_bytes)}"
            except ValueError:
                description = "Stream details unavailable"
        else:
            description = "Falls back to closest available quality"
        entries.append(QualityChoice(height, label, description))
    return entries


def banner() -> None:
    primary, secondary, _, _ = palette()
    if compact():
        logo = Text("C  R  O  N  O  S", style=f"bold {primary}", justify="center")
    else:
        logo = Text(LOGO_WIDE, style=f"bold {primary}", justify="center")
    line = Text("M O T I O N  /  M E D I A", style=f"{secondary}", justify="center")
    console.print(Panel(Group(Align.center(logo), Align.center(line)),
                        title=f"[bold {secondary}]CRONOS  /  v{__version__}[/bold {secondary}]",
                        border_style=primary, padding=(0, 1)))


def section(title: str, subtitle: str = "") -> None:
    primary, secondary, _, _ = palette()
    console.print(f"[{primary}]━━[/] [bold {secondary}]{escape(title)}[/bold {secondary}]" +
                  (f"  [dim]{escape(subtitle)}[/dim]" if subtitle and not compact() else ""))


def screen_header(name: str, description: str = "", back: str = "Home") -> None:
    primary, secondary, _, _ = palette()
    console.print()
    motion.console = console
    motion.transition(name)
    console.print(f"[dim]{escape(back)}  /[/dim] [bold {primary}]{escape(name)}[/bold {primary}]")
    if description:
        console.print(Text(description, style=secondary))
    console.print()


def dashboard(history, queue, settings: Settings) -> None:
    primary, secondary, _, _ = palette()
    stats = history.statistics()
    counts = queue.counts()
    saved = stats['video'] + stats['music']
    waiting = counts.get('queued', 0)
    issues = counts.get('paused', 0) + counts.get('failed', 0)
    if compact():
        console.print(Panel(
            f"[{secondary}]{saved}[/] saved   ·   [{primary}]{waiting}[/] waiting   ·   "
            f"[yellow]{issues}[/] need attention",
            title="[bold]QUEUE & LIBRARY[/bold]", border_style="bright_black", padding=(0, 1)))
    else:
        cards = [
            Panel(f"[bold {secondary}]{saved}[/] saved", title="LIBRARY", border_style="bright_black"),
            Panel(f"[bold {primary}]{waiting}[/] waiting", title="QUEUE", border_style="bright_black"),
            Panel(f"[yellow]{issues}[/] need attention", title="STATUS", border_style="bright_black"),
        ]
        console.print(Columns(cards, expand=True, equal=True, padding=(0, 1)))
    try:
        path = Path(settings.video_dir).expanduser()
        if path.exists():
            free = shutil.disk_usage(path).free
            console.print(f"[dim]Free space: {human_size(free)}  ·  Storage: Movies (existing library)[/dim]")
    except OSError:
        pass
    if settings.ui_tips:
        console.print(f"[dim]Tip: { 'Use ↑ ↓ then Enter to choose.' if compact() else 'Paste a link into Quick Download for the shortest path.' }[/dim]")


def show_info(info: dict) -> None:
    primary, secondary, _, _ = palette()
    width = 32 if compact() else 82
    table = Table(show_header=False, box=box.SIMPLE, border_style=primary, expand=True, padding=(0, 1))
    table.add_column("", width=10, style=secondary, no_wrap=True)
    table.add_column("", overflow="fold")
    table.add_row("Title", Text(clipped(info.get("title") or "Unknown", width)))
    table.add_row("Creator", Text(clipped(info.get("channel") or info.get("uploader") or "Unknown", width)))
    table.add_row("Duration", duration_label(info.get("duration")))
    console.print(table)


def show_quality_guide(options: list[QualityChoice]) -> None:
    primary, secondary, _, _ = palette()
    table = Table(title="AVAILABLE QUALITY", border_style=primary, box=box.SIMPLE, expand=True, padding=(0, 1))
    table.add_column("Quality", style=secondary, no_wrap=True)
    if not compact():
        table.add_column("Source details", overflow="fold")
    for option in options:
        table.add_row(option.label, *((option.detail,) if not compact() else ()))
    console.print(table)
    if compact():
        console.print("[dim]Quality options reflect available video streams; audio will be merged when needed.[/dim]")


def download_summary(title: str, description: str, destination: str, size: int | None = None) -> None:
    primary, secondary, _, _ = palette()
    table = Table.grid(padding=(0, 1), expand=True)
    table.add_column(width=9, style=secondary)
    table.add_column(overflow="fold")
    table.add_row("Media", Text(clipped(title, 52 if not compact() else 28)))
    table.add_row("Format", Text(description))
    table.add_row("Save to", Text(clipped(destination, 65 if not compact() else 35)))
    if size is not None:
        table.add_row("Estimate", human_size(size))
    console.print(Panel(table, title="REVIEW DOWNLOAD", border_style=primary, padding=(0, 1)))


def notice(message: str, kind: str = "info") -> None:
    symbol, style = {"success": ("OK", "green"), "warning": ("!", "yellow"),
                     "error": ("X", "red"), "info": ("i", palette()[1])}.get(kind, ("i", "cyan"))
    console.print(f"[{style}][{symbol}][/{style}] {escape(message)}")
    if kind in ("success", "error"):
        motion.console = console
        motion.signal("Completed" if kind == "success" else "Check the message", success=kind == "success")


def report(results: list) -> None:
    primary, secondary, _, _ = palette()
    table = Table(title="TRANSFER RESULTS", border_style=primary, box=box.ROUNDED, expand=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Media", overflow="fold")
    if not compact():
        table.add_column("Quality", style=secondary)
        table.add_column("Saved file / note", overflow="fold")
    colors = {"success": "green", "skipped": "yellow", "failed": "red", "cancelled": "yellow"}
    for result in results:
        status = str(result.status)
        if compact():
            table.add_row(f"[{colors.get(status, 'white')}]{escape(status)}[/]",
                          Text(clipped(result.title, 32)))
        else:
            table.add_row(f"[{colors.get(status, 'white')}]{escape(status.upper())}[/]",
                          Text(clipped(result.title, 55)), Text(result.quality),
                          Text(clipped(result.file or result.reason, 85)))
    console.print(table)
    counts = {state: sum(r.status == state for r in results)
              for state in ("success", "skipped", "failed", "cancelled")}
    console.print(f"[green]{counts['success']} saved[/]  [yellow]{counts['skipped']} skipped[/]  "
                  f"[red]{counts['failed']} failed[/]  {counts['cancelled']} stopped")
    if counts["success"]:
        motion.signal(f"{counts['success']} saved")
