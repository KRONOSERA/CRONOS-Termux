"""Atomic, validated local configuration. Never stores access tokens."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_NAME = "cronos-yt"
DEFAULT_VIDEO = "/storage/emulated/0/Movies/CRONOS-YT"
DEFAULT_MUSIC = "/storage/emulated/0/Music/CRONOS-YT"
ALLOWED_AUDIO = ("mp3", "m4a", "opus", "flac", "wav")
ALLOWED_BITRATES = (128, 192, 256, 320)
ALLOWED_HEIGHTS = (144, 240, 360, 480, 720, 1080, 1440, 2160)


def config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / APP_NAME / "settings.json"


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / APP_NAME


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / APP_NAME


@dataclass
class Settings:
    video_dir: str = DEFAULT_VIDEO
    music_dir: str = DEFAULT_MUSIC
    concurrency: int = 2
    playlist_limit: int = 50
    batch_confirmation_threshold: int = 10
    audio_format: str = "mp3"
    mp3_bitrate: int = 192
    video_height: int = 1080
    fps_preference: int = 60
    embed_artwork: bool = True
    rate_limit_kib: int = 0  # 0 = unlimited; caps each active download
    fragment_concurrency: int = 2
    subtitles_mode: str = "none"  # none, manual, automatic (video sidecar .srt)
    subtitles_languages: str = "en"  # comma-separated BCP47-style tags
    filename_style: str = "title"  # title, channel-title, date-title
    ui_theme: str = "neon"  # neon, ocean, minimal
    ui_compact: bool = False  # force narrow layout even on large screens
    ui_clear_screen: bool = True  # false preserves terminal scrollback
    ui_tips: bool = True  # show short navigation tips
    ui_clipboard: bool = True  # suggest a link copied from Android
    ui_animations: bool = True  # decorative terminal motion on interactive TTYs
    ui_reduced_motion: bool = False  # accessibility mode: no animation/sleep
    ui_intro: bool = True  # animated brand reveal at startup
    ui_motion_speed: str = "normal"  # calm, normal, swift
    ui_motion_style: str = "glide"  # glide, pulse, typewriter

    def validate(self) -> None:
        if not (1 <= self.concurrency <= 4):
            raise ValueError("Concurrency must be between 1 and 4")
        if type(self.batch_confirmation_threshold) is not int or not (1 <= self.batch_confirmation_threshold <= 500):
            raise ValueError("Batch confirmation threshold must be 1..500")
        if not (1 <= self.playlist_limit <= 500):
            raise ValueError("Playlist limit must be between 1 and 500")
        if self.audio_format not in ALLOWED_AUDIO:
            raise ValueError("Unsupported audio format")
        if self.mp3_bitrate not in ALLOWED_BITRATES:
            raise ValueError("Unsupported MP3 bitrate")
        if self.video_height not in ALLOWED_HEIGHTS:
            raise ValueError("Unsupported video resolution")
        if self.fps_preference not in (30, 60):
            raise ValueError("FPS preference must be 30 or 60")
        if type(self.rate_limit_kib) is not int or not 0 <= self.rate_limit_kib <= 10240:
            raise ValueError("Rate cap must be 0..10240 KiB/s")
        if type(self.fragment_concurrency) is not int or not 1 <= self.fragment_concurrency <= 4:
            raise ValueError("Fragment concurrency must be 1..4")
        if self.subtitles_mode not in ("none", "manual", "automatic"):
            raise ValueError("Invalid subtitle mode")
        if not isinstance(self.subtitles_languages, str) or len(self.subtitles_languages) > 80:
            raise ValueError("Invalid subtitle languages")
        import re
        languages = self.subtitles_languages.split(",")
        if not languages or any(not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,2}", language.strip())
                                for language in languages):
            raise ValueError("Languages must look like en, ar, en-US")
        if self.filename_style not in ("title", "channel-title", "date-title"):
            raise ValueError("Invalid filename style")
        if self.ui_theme not in ("neon", "ocean", "minimal"):
            raise ValueError("Unsupported UI theme")
        for name in ("ui_compact", "ui_clear_screen", "ui_tips", "ui_clipboard", "ui_animations", "ui_reduced_motion", "ui_intro"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        if self.ui_motion_speed not in ("calm", "normal", "swift"):
            raise ValueError("Invalid animation speed")
        if self.ui_motion_style not in ("glide", "pulse", "typewriter"):
            raise ValueError("Invalid animation style")
        if not isinstance(self.embed_artwork, bool):
            raise ValueError("embed_artwork must be a boolean")
        for dest in (self.video_dir, self.music_dir):
            if not isinstance(dest, str) or not dest.strip() or "\x00" in dest:
                raise ValueError("Invalid destination directory")


def load_settings(path: Path | None = None) -> Settings:
    target = path or config_path()
    if not target.exists():
        return Settings()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Settings must be a JSON object")
        allowed = {field.name for field in fields(Settings)}
        settings = Settings(**{k: v for k, v in raw.items() if k in allowed})
        settings.validate()
        return settings
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid settings at {target}: {exc}. Fix or rename the file.") from exc


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    settings.validate()
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=target.parent)
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(asdict(settings), fp, indent=2, ensure_ascii=False)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, target)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return target
