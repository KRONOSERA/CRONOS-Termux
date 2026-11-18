"""v2.1 UI and flow tests; no network or Android API calls."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from cronos_yt import ui
from cronos_yt.cli import quick_download, parser
from cronos_yt.settings import Settings, load_settings, save_settings
from cronos_yt.history import HistoryDB
from cronos_yt.queue import QueueDB
from cronos_yt.library import search_library

URL = "https://youtu.be/abc123def45"
INFO = {
    "id": "abc123def45", "title": "[bold] Test clip", "channel": "Creator [green]",
    "duration": 140, "formats": [
        {"format_id": "18", "height": 360, "fps": 30, "vcodec": "avc1.42E01E",
         "acodec": "mp4a", "ext": "mp4", "filesize": 1_000_000},
        {"format_id": "137", "height": 1080, "fps": 30, "vcodec": "avc1.640028",
         "acodec": "none", "ext": "mp4", "filesize": 25_000_000},
        {"format_id": "248", "height": 1080, "fps": 60, "vcodec": "vp09.00.51",
         "acodec": "none", "ext": "webm", "filesize": 30_000_000},
    ]
}


class FakeManager:
    def __init__(self):
        self.settings = Settings(video_height=1080)
        self.inspect_urls = []

    def inspect(self, url):
        self.inspect_urls.append(url)
        return INFO


class TestUi21(unittest.TestCase):
    def tearDown(self):
        ui.configure(Settings())

    def test_legacy_settings_and_preferences_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "settings.json"
            file.write_text(json.dumps({"video_height": 720, "concurrency": 4}))
            migrated = load_settings(file)
            self.assertEqual(migrated.ui_theme, "neon")
            self.assertTrue(migrated.ui_clipboard)
            modified = Settings(**{**migrated.__dict__, "ui_theme": "ocean", "ui_compact": True,
                                    "ui_clear_screen": False, "ui_tips": False, "ui_clipboard": False})
            save_settings(modified, file)
            self.assertEqual(load_settings(file), modified)
            self.assertEqual(load_settings(file).video_height, 720)

    def test_invalid_preferences_rejected(self):
        for item in (Settings(ui_theme="invalid"), Settings(ui_compact="false"),
                     Settings(ui_clear_screen=42), Settings(ui_clipboard=None)):
            with self.subTest(item=item), self.assertRaises(ValueError):
                item.validate()

    def test_responsive_and_themes_render(self):
        original = ui.console
        try:
            with tempfile.TemporaryDirectory() as d:
                db = HistoryDB(Path(d) / "history.sqlite3")
                queue = QueueDB(db.path)
                for theme in ui.THEMES:
                    for width in (38, 60, 100):
                        with self.subTest(theme=theme, width=width):
                            text = io.StringIO()
                            ui.console = Console(file=text, width=width, force_terminal=False)
                            ui.configure(Settings(ui_theme=theme))
                            ui.banner()
                            ui.dashboard(db, queue, Settings(video_dir=d))
                            ui.show_info(INFO)
                            ui.download_summary(INFO["title"], "MP4", d, 2048)
                            output = text.getvalue()
                            self.assertIn("CRONOS", output.replace(" ", ""))
                            self.assertIn("QUEUE", output)
                            self.assertIn("Test clip", output)
        finally:
            ui.console = original

    def test_quality_choices_are_real_streams(self):
        options = ui.quality_choices(INFO, 60)
        self.assertEqual([o.height for o in options], [None, 1080, 360])
        self.assertTrue(any("60 FPS" in o.detail for o in options))
        self.assertIn("4K", ui.quality_choices(None, 30)[1].label)
        self.assertEqual(ui.quality_choices({"formats": []}, 30), [])

    def test_friendly_formatters(self):
        self.assertEqual(ui.human_size(None), "Size unknown")
        self.assertEqual(ui.human_size(1048576), "1.0 MiB")
        self.assertEqual(ui.duration_label(3661), "1:01:01")
        self.assertEqual(ui.duration_label(99), "1:39")
        self.assertTrue(ui.clipped(" a  b ", 20) == "a b")

    def test_quick_video_authorizes_once_and_presets_resolution(self):
        manager = FakeManager()
        with patch("cronos_yt.cli.one_url", return_value=URL), \
             patch("cronos_yt.cli.ask_select", side_effect=[
                 "Video  ·  MP4", "Data saver  ·  up to 480p", "Save to queue"]), \
             patch("cronos_yt.cli.confirm_rights", return_value=True) as rights, \
             patch("cronos_yt.cli.dispatch", return_value=0) as dispatch:
            self.assertEqual(quick_download(manager), 0)
        job = dispatch.call_args.args[1][0]
        self.assertEqual(job.height, 480)
        self.assertEqual(job.fps, 30)
        self.assertTrue(dispatch.call_args.kwargs["queue_mode"])
        rights.assert_called_once()
        self.assertEqual(manager.inspect_urls, [URL])

    def test_quick_music_blocked_without_rights(self):
        manager = FakeManager()
        with patch("cronos_yt.cli.one_url", return_value=URL), \
             patch("cronos_yt.cli.ask_select", side_effect=[
                 "Music  ·  audio file", "MP3  ·  192 kbps", "Download now"]), \
             patch("cronos_yt.cli.confirm_rights", return_value=False), \
             patch("cronos_yt.cli.dispatch") as dispatch:
            self.assertEqual(quick_download(manager), 0)
        dispatch.assert_not_called()

    def test_quick_custom_name_requires_review_again(self):
        manager = FakeManager()
        with patch("cronos_yt.cli.one_url", return_value=URL), \
             patch("cronos_yt.cli.ask_select", side_effect=[
                 "Music  ·  audio file", "OPUS  ·  efficient compression",
                 "Change destination / filename", "Download now"]), \
             patch("cronos_yt.cli.ask_text", side_effect=["/tmp/media", "My Song"]), \
             patch("cronos_yt.cli.confirm_rights", return_value=True), \
             patch("cronos_yt.cli.dispatch", return_value=0) as dispatch:
            quick_download(manager)
        job = dispatch.call_args.args[1][0]
        self.assertEqual(job.output_dir, "/tmp/media")
        self.assertEqual(job.filename, "My Song")
        self.assertEqual(job.audio_format, "opus")

    def test_explicit_path_search_without_accidental_path_matching(self):
        with tempfile.TemporaryDirectory(prefix="my_underscore_") as d:
            db = HistoryDB(Path(d) / "db.sqlite3")
            song = Path(d) / "test_audio.mp3"
            song.write_bytes(b"mp3")
            db.record(key="k", media_id="abc123def45", title="Track", kind="music",
                      fmt="mp3", quality="192k", status="success", file_path=str(song))
            self.assertEqual(search_library(db, "_"), [])
            self.assertEqual(len(search_library(db, "path:test_audio")), 1)

    def test_ui_preview_command_available(self):
        args = parser().parse_args(["--ui-preview"])
        self.assertTrue(args.ui_preview)


if __name__ == "__main__":
    unittest.main()
