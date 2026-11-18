"""Low-overhead, accessible terminal motion for CRONOS.

Animations are decorative: they never perform network or file I/O, and never
intercept keys. They use Rich's transient Live display instead of raw ANSI
sequences, and automatically become no-ops for non-interactive output.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Iterator

from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

COLORS = {
    "neon": ("#c084fc", "#22d3ee"),
    "ocean": ("#38bdf8", "#34d399"),
    "minimal": ("#e4e4e7", "#a3a3a3"),
}

# 5-line block letterforms. On narrow screens, the lettering is typography-only.
GLYPHS = {
    "C": (" ███ ", "█    ", "█    ", "█    ", " ███ "),
    "R": ("████ ", "█   █", "████ ", "█  █ ", "█   █"),
    "O": (" ███ ", "█   █", "█   █", "█   █", " ███ "),
    "N": ("█   █", "██  █", "█ █ █", "█  ██", "█   █"),
    "S": (" ████", "█    ", " ███ ", "    █", "████ "),
}


@dataclass(frozen=True)
class MotionSettings:
    enabled: bool = True
    reduced: bool = False
    intro: bool = True
    speed: str = "normal"  # calm, normal, swift
    style: str = "glide"  # glide, pulse, typewriter
    theme: str = "neon"

    @classmethod
    def from_settings(cls, settings: object) -> "MotionSettings":
        return cls(
            enabled=bool(getattr(settings, "ui_animations", True)),
            reduced=bool(getattr(settings, "ui_reduced_motion", False)),
            intro=bool(getattr(settings, "ui_intro", True)),
            speed=str(getattr(settings, "ui_motion_speed", "normal")),
            style=str(getattr(settings, "ui_motion_style", "glide")),
            theme=str(getattr(settings, "ui_theme", "neon")),
        )


def terminal_motion_supported(console: Console, settings: MotionSettings) -> bool:
    """Honor explicit preferences, TTY support and common accessibility signals."""
    if not settings.enabled or settings.reduced or not console.is_terminal:
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    if os.environ.get("CRONOS_NO_MOTION", "").lower() in {"1", "true", "yes"}:
        return False
    if os.environ.get("CI", "").lower() in {"1", "true"}:
        return False
    return True


def block_logo(revealed: int = 6) -> list[str]:
    """Generate a glyph canvas without external fonts or terminal escapes."""
    word = "CRONOS"[:max(0, min(revealed, 6))]
    return [" ".join(GLYPHS[letter][line] for letter in word).rstrip() for line in range(5)]


def logo_frame(revealed: int, tick: int, width: int, style: str, theme: str) -> RenderableType:
    """Pure frame generator; testable without terminal, sleeps or side effects."""
    a, b = COLORS.get(theme, COLORS["neon"])
    width = max(20, width)
    visible = max(0, min(6, revealed))
    if width < 54:
        letters = Text(justify="center")
        for i, char in enumerate("CRONOS"):
            letters.append(char if i < visible else "·", style=f"bold {a if (i + tick) % 2 else b}")
            if i != 5:
                letters.append(" ")
        main = Align.center(letters)
    else:
        lines = block_logo(visible)
        logo = Text("\n".join(lines), style=f"bold {a if tick % 2 == 0 else b}", justify="center")
        main = Align.center(logo)
    bar_width = max(8, min(width - 10, 32))
    if style == "pulse":
        step = (tick % 4) + 1
        indicator = "◆" * step + "·" * (bar_width - step)
    elif style == "typewriter":
        step = max(0, min(bar_width, int(bar_width * visible / 6)))
        indicator = "━" * step + "·" * (bar_width - step)
    else:
        indicator = "".join("━" if (i - tick * 3) % bar_width < 6 else "·" for i in range(bar_width))
    foot = Text("\n" + indicator + "\n", justify="center", style=b)
    tagline = Text("YOUR MEDIA  /  YOUR DEVICE", justify="center", style="dim")
    return Panel(Group(main, Align.center(foot), Align.center(tagline)),
                 title=Text("●  CRONOS  ●", style=f"bold {a}"), border_style=a,
                 padding=(1, 1), expand=True)


def transition_frame(title: str, tick: int, width: int, style: str, theme: str) -> RenderableType:
    a, b = COLORS.get(theme, COLORS["neon"])
    size = min(28, max(8, width - 8))
    if style == "typewriter":
        name = title[:tick + 1]
        line = "─" * min(size, tick * 4)
    elif style == "pulse":
        name = title
        line = "═" * (size // 2 + tick % (size // 2))
    else:
        name = title
        line = "".join("━" if (i - tick * 3) % size < 7 else "·" for i in range(size))
    title_text = Text(name, style=f"bold {a}")
    return Panel(Group(title_text, Text(line, style=b)), border_style="bright_black",
                 padding=(0, 1), expand=True)


class Motion:
    def __init__(self, console: Console, settings: MotionSettings | None = None) -> None:
        self.console = console
        self.settings = settings or MotionSettings()
        self.last_screen = ""
        self._last_transition = 0.0

    @property
    def active(self) -> bool:
        return terminal_motion_supported(self.console, self.settings)

    def reconfigure(self, settings: object) -> None:
        self.settings = MotionSettings.from_settings(settings)

    def _delay(self) -> float:
        return {"calm": 0.095, "normal": 0.061, "swift": 0.035}.get(self.settings.speed, 0.061)

    def _frames(self, frames: Iterator[RenderableType], *, max_frames: int = 12) -> None:
        if not self.active:
            return
        try:
            # No alternate-screen buffer: never erase the user's previous commands.
            with Live(console=self.console, transient=True, auto_refresh=False,
                      vertical_overflow="ellipsis") as live:
                for idx, renderable in enumerate(frames):
                    if idx >= max_frames:
                        break
                    live.update(renderable, refresh=True)
                    time.sleep(self._delay())
        except (KeyboardInterrupt, EOFError):
            raise
        except (OSError, RuntimeError):
            # An unsupported or resized terminal must not prevent downloads.
            pass

    def intro(self, *, force: bool = False) -> None:
        if not (force or self.settings.intro) or not self.active:
            return
        width = self.console.size.width
        if width < 24:
            return
        frames = (logo_frame(min(6, max(0, index - 1)), index, width,
                             self.settings.style, self.settings.theme) for index in range(9))
        self._frames(frames, max_frames=9)

    def transition(self, title: str) -> None:
        """Debounce repeated submenu redraws; never animate non-TTY commands."""
        now = time.monotonic()
        if title == self.last_screen and now - self._last_transition < 4:
            return
        self.last_screen, self._last_transition = title, now
        if not self.active or self.console.size.width < 24:
            return
        self._frames((transition_frame(title, i, self.console.size.width,
                                       self.settings.style, self.settings.theme) for i in range(5)),
                     max_frames=5)

    def tap(self, label: str) -> None:
        """Brief, non-blocking-feeling acknowledgment after menu choice."""
        if not self.active:
            return
        safe = "".join(ch for ch in str(label) if ch.isprintable())[:32]
        a, b = COLORS.get(self.settings.theme, COLORS["neon"])
        self._frames((Align.center(Text(f"{marker}  {safe}", style=f"bold {a if i else b}"))
                      for i, marker in enumerate(("›", "»"))), max_frames=2)

    def signal(self, label: str, *, success: bool = True) -> None:
        if not self.active:
            return
        color = "green" if success else "yellow"
        frames = (Align.center(Text(f"{'✓' if success else '!'}  {label}  {'●' * i}",
                                    style=f"bold {color}")) for i in range(1, 4))
        self._frames(frames, max_frames=3)

    def demo(self) -> None:
        """Offline preview of all effects, including low-motion fallback."""
        if not self.active:
            self.console.print("[dim]Animations are disabled or this is not a TTY.[/dim]")
            return
        self.intro(force=True)
        self.transition("Motion Showcase")
        self.signal("Animation ready")
