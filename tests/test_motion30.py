"""CRONOS v3 Motion Edition: settings, accessibility and zero-network previews."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from cronos_yt.motion import (
    Motion, MotionSettings, block_logo, logo_frame,
    terminal_motion_supported, transition_frame,
)
from cronos_yt.settings import Settings, load_settings, save_settings
from cronos_yt import ui
from cronos_yt.cli import main, parser


class MotionTests(unittest.TestCase):
    def test_cronos_brand_has_six_letters(self):
        self.assertEqual(len(block_logo()), 5)
        self.assertTrue(all("█" in line for line in block_logo()))
        self.assertEqual(len(block_logo(0)), 5)
        self.assertNotIn("YT", "".join(block_logo()))

    def test_frames_render_at_mobile_and_wide_sizes(self):
        for width in (25, 38, 53, 54, 80, 120):
            for style in ("glide", "pulse", "typewriter"):
                with self.subTest(width=width, style=style):
                    stream = io.StringIO()
                    c = Console(file=stream, width=width, force_terminal=False)
                    c.print(logo_frame(6, 4, width, style, "neon"))
                    c.print(transition_frame("Queue", 3, width, style, "neon"))
                    self.assertIn("Queu" if style == "typewriter" else "Queue", stream.getvalue())
                    self.assertNotIn("CRONOS YT", stream.getvalue())

    def test_default_and_legacy_preferences(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "settings.json"
            dest.write_text('{"ui_theme": "ocean", "video_height": 720}')
            settings = load_settings(dest)
            self.assertTrue(settings.ui_animations)
            self.assertEqual(settings.ui_motion_speed, "normal")
            self.assertEqual(settings.ui_motion_style, "glide")
            settings = replace(settings, ui_motion_speed="swift", ui_motion_style="typewriter",
                               ui_reduced_motion=True, ui_intro=False)
            save_settings(settings, dest)
            self.assertEqual(load_settings(dest), settings)
            self.assertEqual(load_settings(dest).video_height, 720)

    def test_invalid_preferences_rejected(self):
        for setting in (
            Settings(ui_animations="yes"),
            Settings(ui_reduced_motion=None),
            Settings(ui_intro=0),
            Settings(ui_motion_speed="hyper"),
            Settings(ui_motion_style="flash"),
        ):
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                setting.validate()

    def test_motion_never_runs_on_non_tty(self):
        c = Console(file=io.StringIO(), force_terminal=False)
        motion = Motion(c, MotionSettings())
        self.assertFalse(motion.active)
        with patch("cronos_yt.motion.time.sleep", side_effect=AssertionError("Sleep on non-TTY")):
            motion.intro(force=True)
            motion.transition("Downloads")
            motion.tap("Video")
            motion.signal("Completed")
            motion.demo()

    def test_reduce_motion_and_environment_override(self):
        c = Console(file=io.StringIO(), force_terminal=True)
        self.assertFalse(terminal_motion_supported(c, MotionSettings(reduced=True)))
        self.assertFalse(terminal_motion_supported(c, MotionSettings(enabled=False)))
        with patch.dict(os.environ, {"CRONOS_NO_MOTION": "1", "TERM": "xterm"}):
            self.assertFalse(terminal_motion_supported(c, MotionSettings()))
        with patch.dict(os.environ, {"TERM": "dumb"}):
            self.assertFalse(terminal_motion_supported(c, MotionSettings()))

    def test_real_tty_frames_are_bounded_and_fast(self):
        c = Console(file=io.StringIO(), force_terminal=True, width=64)
        motion = Motion(c, MotionSettings(speed="swift"))
        with patch.dict(os.environ, {"TERM": "xterm", "CRONOS_NO_MOTION": "0", "CI": "0"}), \
             patch("cronos_yt.motion.time.sleep", return_value=None) as sleep:
            motion.intro()
            self.assertLessEqual(sleep.call_count, 9)
            sleep.reset_mock()
            motion.transition("Library")
            self.assertLessEqual(sleep.call_count, 5)
            sleep.reset_mock()
            motion.tap("Library")
            self.assertLessEqual(sleep.call_count, 2)

    def test_transition_debouncing(self):
        c = Console(file=io.StringIO(), force_terminal=True)
        motion = Motion(c)
        with patch.dict(os.environ, {"TERM": "xterm", "CI": "0"}), \
             patch.object(motion, "_frames") as frames:
            motion.transition("Settings")
            motion.transition("Settings")
            self.assertEqual(frames.call_count, 1)
            motion.transition("Library")
            self.assertEqual(frames.call_count, 2)

    def test_cli_aliases_and_previews(self):
        self.assertTrue(parser().parse_args(["--motion-preview"]).motion_preview)
        self.assertTrue(parser().parse_args(["--no-animation"]).no_animation)

    def test_offline_motion_preview_skips_dependencies_and_network(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("cronos_yt.cli.load_settings", return_value=Settings(ui_animations=False)), \
                 patch("cronos_yt.cli.check_dependencies", side_effect=AssertionError("Deps checked")), \
                 patch("cronos_yt.cli.DownloadManager", side_effect=AssertionError("Network manager started")), \
                 patch("socket.socket.connect", side_effect=AssertionError("Network used")):
                self.assertEqual(main(["--motion-preview", "--no-animation"]), 0)

    def test_ui_uses_cronos_title_only(self):
        original = ui.console
        try:
            stream = io.StringIO()
            ui.console = Console(file=stream, width=38, force_terminal=False)
            ui.configure(Settings())
            ui.banner()
            self.assertNotIn("Y T", stream.getvalue())
            self.assertIn("C", stream.getvalue())
        finally:
            ui.console = original
            ui.configure(Settings())


if __name__ == "__main__":
    unittest.main()
