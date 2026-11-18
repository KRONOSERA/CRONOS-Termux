"""Queue guarantees and download lifecycle tested without requesting media."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from cronos_yt.controls import DownloadControls
from cronos_yt.downloader import Cancelled, DownloadJob, DownloadManager, DownloadResult
from cronos_yt.history import HistoryDB
from cronos_yt.queue import QueueDB, fingerprint
from cronos_yt.settings import Settings

URL1 = "https://youtu.be/abc123def45"
URL2 = "https://youtu.be/def123abc45"


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "history.sqlite3"
        self.q = QueueDB(self.path)
        self.video = DownloadJob(URL1, height=720)
        self.audio = DownloadJob(URL2, kind="music", audio_format="m4a")

    def authorized_add(self, jobs):
        receipts = [self.q.auth.record(job, "queued") for job in jobs]
        return self.q.add(jobs, receipts)

    def authorized_start(self, item_id):
        item = next((i for i in self.q.list() if i.id == item_id), None)
        receipt = self.q.auth.current_queue_receipt(item.job, item_id) if item else None
        return self.q.start(item_id, receipt)

    def test_enqueue_duplicate_and_persistence(self):
        ids, duplicates = self.authorized_add([self.video, self.video, self.audio])
        self.assertEqual(len(ids), 2)
        self.assertEqual(duplicates, 1)
        self.assertEqual(self.q.counts()["queued"], 2)
        self.assertEqual([i.id for i in QueueDB(self.path).list(statuses=("queued",))], ids)
        self.assertEqual(self.q.list(statuses=("queued",))[0].job, self.video)
        self.assertNotEqual(fingerprint(self.video), fingerprint(self.audio))

    def test_resume_pause_failure_and_recovery(self):
        ids, _ = self.authorized_add([self.video, self.audio])
        a, b = ids
        self.assertTrue(self.q.change(a, "paused"))
        self.assertFalse(self.authorized_start(a))
        self.assertTrue(self.q.change(a, "queued"))
        self.assertTrue(self.authorized_start(a))
        self.assertTrue(self.q.finish(a, DownloadResult("failed", "demo", reason="Network down")))
        self.assertEqual(self.q.counts()["failed"], 1)
        self.assertTrue(self.q.change(a, "queued"))
        self.assertTrue(self.authorized_start(a))
        self.assertTrue(self.q.finish(a, DownloadResult("success", "demo", file="/tmp/file")))
        self.assertEqual(self.q.counts()["done"], 1)
        self.assertTrue(self.authorized_start(b))
        # A second live Termux process must not reset active work.
        self.assertEqual(QueueDB(self.path).counts()["running"], 1)
        # Simulate an abandoned job after a process exited.
        import sqlite3
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE queue_items SET owner_pid=99999999,lease_expires_at=0 WHERE id=?", (b,))
        recovered = QueueDB(self.path)
        self.assertEqual(recovered.counts()["paused"], 1)
        self.assertTrue(recovered.change(b, "queued"))
        self.assertTrue(recovered.start(b, recovered.auth.current_queue_receipt(self.audio, b)))
        self.assertTrue(recovered.finish(b, DownloadResult("cancelled", "later")))
        self.assertEqual(self.q.counts()["paused"], 1)
        self.assertEqual(self.q.clear_completed(), 1)
        self.assertEqual(self.q.counts()["done"], 0)

    def test_bulk_queue_actions(self):
        self.authorized_add([self.video, self.audio])
        self.assertEqual(self.q.change_all("paused"), 2)
        self.assertEqual(self.q.counts()["paused"], 2)
        self.assertEqual(self.q.change_all("queued"), 2)
        self.assertEqual(self.q.counts()["queued"], 2)
        self.assertEqual(self.q.change_all("queued"), 0)
        with self.assertRaises(ValueError):
            self.q.change_all("done")

    def test_remove_does_not_touch_downloaded_file(self):
        ids, _ = self.authorized_add([self.video])
        path = Path(self.tmp.name) / "test.mp4"
        path.write_bytes(b"test")
        self.assertTrue(self.authorized_start(ids[0]))
        self.assertFalse(self.q.remove(ids[0]))
        self.q.finish(ids[0], DownloadResult("success", "title", file=str(path)))
        self.assertTrue(self.q.remove(ids[0]))
        self.assertEqual(path.read_bytes(), b"test")

    def test_legacy_history_and_queue_share_db(self):
        old = HistoryDB(self.path)
        old.record(key="abc", media_id="abc123def45", title="Demo", kind="video",
                   fmt="mp4", quality="720p", status="success", file_path="/tmp/x")
        self.authorized_add([self.video])
        self.assertEqual(len(old.recent()), 1)
        self.assertEqual(self.q.counts()["queued"], 1)
        self.assertEqual(old.statistics()["video"], 1)

    def test_queue_controller_callback_mock(self):
        class FakeDL:
            def __init__(self, opts):
                self.opts = opts
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def extract_info(self, url, download=False):
                data = {"id": "abc123def45", "title": "Mock", "formats": [
                    {"format_id": "137", "height": 720, "fps": 30,
                     "vcodec": "avc1", "acodec": "none", "ext": "mp4"}]}
                if download:
                    path = Path(self.opts["paths"]["home"]) / "Mock [abc123def45].mp4"
                    path.write_bytes(b"stub")
                    data["filepath"] = str(path)
                return data
        ids, _ = self.authorized_add([self.video])
        manager = DownloadManager(Settings(video_dir=str(Path(self.tmp.name) / "Movies")),
                                  HistoryDB(self.path), Console(file=io.StringIO(), force_terminal=False))
        with patch("cronos_yt.downloader.YoutubeDL", FakeDL), \
             patch("cronos_yt.downloader.scan_media", return_value=True):
            result = manager.download([self.video], authorizations=[self.q.auth.current_queue_receipt(self.video, ids[0])],
                on_start=lambda i: self.authorized_start(ids[i]),
                on_result=lambda i, r: self.q.finish(ids[i], r))
        self.assertEqual([r.status for r in result], ["success"])
        self.assertEqual(self.q.counts()["done"], 1)
        self.assertEqual(self.q.list(statuses=("done",))[0].attempts, 1)

    def test_pause_resume_and_cancel_without_tty(self):
        manager = DownloadManager(Settings(), HistoryDB(self.path),
                                  Console(file=io.StringIO(), force_terminal=False))
        controls = DownloadControls(manager, manager.console)
        controls.handle_key("p")
        self.assertTrue(manager.paused.is_set())
        controls.handle_key("r")
        self.assertFalse(manager.paused.is_set())
        controls.handle_key("c")
        with self.assertRaises(Cancelled):
            manager._wait_until_resumed()


if __name__ == "__main__":
    unittest.main()
