import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from cronos_yt.downloader import DownloadJob, DownloadManager, redacted
from cronos_yt.history import HistoryDB, make_key
from cronos_yt.settings import Settings


class FakeYoutubeDL:
    calls = 0
    last_template = ""

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        data = {"id": "abc123def45", "title": "Mock title", "formats": [
            {"format_id": "137", "height": 1080, "fps": 30,
             "vcodec": "avc1.640028", "acodec": "none", "ext": "mp4"},
        ]}
        if download:
            FakeYoutubeDL.calls += 1
            FakeYoutubeDL.last_template = self.opts["outtmpl"]
            folder = Path(self.opts["paths"]["home"])
            filepath = folder / "Mock title [abc123def45].mp4"
            filepath.write_bytes(b"stub")
            for hook in self.opts["progress_hooks"]:
                hook({"status": "finished"})
            data["filepath"] = str(filepath)
        return data


class HistoryAndDownloaderTests(unittest.TestCase):
    def test_hash_key_distinguishes_output(self):
        a = make_key("abc123def45", "video", "mp4", "1080p", Path("/tmp/one"))
        b = make_key("abc123def45", "video", "mp4", "1080p", Path("/tmp/two"))
        self.assertNotEqual(a, b)

    def test_db_success_and_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = HistoryDB(root / "hist.db")
            key = "unique"
            path = root / "test.mp4"
            path.write_bytes(b"123")
            db.record(key=key, media_id="abc123def45", title="Example", kind="video",
                      fmt="mp4", quality="1080p", status="success", file_path=str(path))
            self.assertEqual(db.existing(key), path)
            self.assertEqual(len(db.recent()), 1)
            path.unlink()
            self.assertIsNone(db.existing(key))

    @patch("cronos_yt.downloader.YoutubeDL", FakeYoutubeDL)
    @patch("cronos_yt.downloader.scan_media", return_value=True)
    def test_mock_download_and_skip_duplicate(self, _scan):
        FakeYoutubeDL.calls = 0
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            settings = Settings(video_dir=str(root / "video"), music_dir=str(root / "music"))
            manager = DownloadManager(settings, HistoryDB(root / "hist.db"),
                                      console=Console(file=io.StringIO(), force_terminal=False))
            job = DownloadJob("https://youtu.be/abc123def45")
            from cronos_yt.authorization import AuthorizationDB
            auth = AuthorizationDB(manager.history.path)
            receipts = [auth.record(job, "interactive") for _ in range(2)]
            statuses = [item.status for item in manager.download([job, job], authorizations=receipts)]
            self.assertEqual(statuses.count("success"), 1)
            self.assertEqual(statuses.count("skipped"), 1)
            self.assertEqual(FakeYoutubeDL.calls, 1)
            self.assertIn("[1080p@30]", FakeYoutubeDL.last_template)

    def test_log_redaction(self):
        self.assertNotIn("private-token", redacted("https://youtube.com/watch?v=x&token=private-token"))


if __name__ == "__main__":
    unittest.main()
