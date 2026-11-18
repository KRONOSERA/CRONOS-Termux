import io
import json
import tempfile
import unittest
from pathlib import Path

from rich.console import Console

from cronos_yt.cli import parser
from cronos_yt.downloader import DownloadManager
from cronos_yt.settings import Settings, load_settings, save_settings
from cronos_yt.ui import banner, dashboard
from cronos_yt.history import HistoryDB
from cronos_yt.queue import QueueDB


class UpgradeTests(unittest.TestCase):
    def test_settings_upgrade_from_v1(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text(json.dumps({"video_dir": d, "mp3_bitrate": 320}))
            result = load_settings(path)
            self.assertEqual(result.mp3_bitrate, 320)
            self.assertEqual(result.rate_limit_kib, 0)
            self.assertEqual(result.fragment_concurrency, 2)
            result.rate_limit_kib = 512
            save_settings(result, path)
            self.assertEqual(load_settings(path).rate_limit_kib, 512)

    def test_reject_bad_network_settings(self):
        for obj in (Settings(rate_limit_kib=-10), Settings(rate_limit_kib=100000),
                    Settings(fragment_concurrency=0), Settings(fragment_concurrency=5)):
            with self.assertRaises(ValueError):
                obj.validate()

    def test_yt_dlp_option_mapping(self):
        manager = DownloadManager(Settings(rate_limit_kib=768, fragment_concurrency=3))
        opts = manager._base_options()
        self.assertEqual(opts["ratelimit"], 768 * 1024)
        self.assertEqual(opts["concurrent_fragment_downloads"], 3)

    def test_cli_queue_flags(self):
        args = parser().parse_args(["--url", "https://youtu.be/abc123def45", "--enqueue", "--yes"])
        self.assertTrue(args.enqueue)
        self.assertTrue(parser().parse_args(["--run-queue", "--yes"]).run_queue)
        self.assertTrue(parser().parse_args(["--queue-list"]).queue_list)

    def test_banner_narrow_and_dashboard(self):
        import cronos_yt.ui as ui
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            original = ui.console
            ui.console = Console(file=out, force_terminal=False, width=58)
            try:
                db = HistoryDB(Path(d) / "hist.db")
                queue = QueueDB(db.path)
                banner()
                dashboard(db, queue, Settings(video_dir=d))
                self.assertIn("CRONOS", out.getvalue())
                self.assertIn("QUEUE", out.getvalue())
            finally:
                ui.console = original


if __name__ == "__main__":
    unittest.main()
