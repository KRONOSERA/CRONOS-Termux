"""Opt-in tests use actual installed libraries, but no HTTP or media downloads."""
from __future__ import annotations
import os
import unittest
from unittest.mock import patch

@unittest.skipUnless(os.environ.get("CRONOS_INTEGRATION") == "1",
                     "Set CRONOS_INTEGRATION=1 and install real dependencies")
class RealDependencyTests(unittest.TestCase):
    def test_actual_imports_and_inspect_with_http_blocked(self):
        from importlib.metadata import version
        for package in ("yt-dlp", "yt-dlp-ejs", "questionary", "rich", "mutagen"):
            self.assertTrue(version(package), f"Missing real distribution: {package}")
        import yt_dlp
        import yt_dlp_ejs
        import questionary
        import mutagen
        from rich.console import Console
        from cronos_yt.downloader import DownloadManager
        from cronos_yt.settings import Settings
        self.assertIsNotNone(yt_dlp_ejs)
        self.assertIsNotNone(questionary)
        self.assertIsNotNone(mutagen)
        self.assertIsInstance(Console(width=40), Console)
        url = "https://www.youtube.com/watch?v=BaW_jenozKc"
        sample = {"id": "BaW_jenozKc", "title": "CRONOS mocked public test fixture",
                  "duration": 1, "is_live": False, "formats": []}
        # Patch the real YoutubeDL method, not the module import, and reject network.
        with patch.object(yt_dlp.YoutubeDL, "extract_info", return_value=sample) as extract, \
             patch("socket.socket.connect", side_effect=AssertionError("No HTTP allowed")):
            manager = DownloadManager(Settings())
            info = manager.inspect(url)
        self.assertEqual(info["id"], "BaW_jenozKc")
        extract.assert_called_once_with(url, download=False)
