"""Offline, adversarial security regression tests for CRONOS v3.0.1."""
from __future__ import annotations
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rich.console import Console
from cronos_yt.audio import add_lyrics_from_file, _escape_ffmetadata
from cronos_yt.authorization import AuthorizationDB, SESSION_ID, url_hash
from cronos_yt.cli import parser
from cronos_yt.cli.dispatch import _batch_confirmation, dispatch, run_queue
from cronos_yt.downloader import DownloadJob, DownloadManager, DownloadResult, redacted
from cronos_yt.queue import QueueDB
from cronos_yt.settings import Settings
from cronos_yt.storage import validate_url
from cronos_yt import updater

URL = "https://youtu.be/abc123def45"


class RedactionSafety(unittest.TestCase):
    def test_20_edge_cases(self):
        cases = [
            ("https://youtu.be/a?auth=Secret55", "Secret55"),
            ("(https://youtube.com/watch?v=a&sig=CookieValue)", "CookieValue"),
            ("https://youtube.com/path", "?[redacted]"),
            ("https://youtube.com/abcdefghijklmnopqrstuvwxyz0123456789/v", "abcdefghijklmnopqrstuvwxyz0123456789"),
            ("https://youtube.com/path/AA1234567890123456789012", "AA1234567890123456789012"),
            ("Cookie: sid=secretValue; other=2", "secretValue"),
            ("Authentication failed Authorization: Bearer ABCDEF000", "ABCDEF000"),
            ("X-Goog-Visitor-Id: PRIVATE123", "PRIVATE123"),
            ("X-GOOG-API-KEY: abcSecret", "abcSecret"),
            ("proxy-authorization: userpass", "userpass"),
            ("bearer s3cr3t", "s3cr3t"),
            ("token: hidden", "hidden"),
            ("api_key=verysecret", "verysecret"),
            ("ACCESS_TOKEN=privatekey", "privatekey"),
            ("REFRESH-TOKEN: privateABC", "privateABC"),
            ("https://youtu.be/a?x=one and https://youtu.be/b?x=two", "one"),
            ("https://youtu.be/a?x=one and https://youtu.be/b?x=two", "two"),
            ("\nAuthorization: secret\nnormal", "secret"),
            ("http://user:password@example.com/path", "password"),
            ("https://youtube.com/test#my-private-fragment", "my-private-fragment"),
        ]
        for raw, secret in cases:
            with self.subTest(raw=raw):
                self.assertNotIn(secret, redacted(raw))
                self.assertLessEqual(len(redacted(raw)), 500)
        result = redacted("x" * 470 + " https://youtube.com/watch?v=A&sig=forbiddenKEY" + "y" * 3000)
        self.assertNotIn("forbiddenKEY", result)
        self.assertLessEqual(len(result), 500)
        self.assertNotIn("?[redacted]", redacted("https://youtu.be/abc123def45"))

    def test_logging_sanitizes_even_unfiltered_exceptions(self):
        import logging
        from cronos_yt.downloader import _SanitizeLog
        record = logging.LogRecord("cronos", logging.ERROR, __file__, 1,
                                   "Cookie: %s", ("a=SENSITIVE",), None)
        _SanitizeLog().filter(record)
        self.assertNotIn("SENSITIVE", record.getMessage())


class LyricsArgvSafety(unittest.TestCase):
    def test_lyrics_not_in_any_subprocess_argument(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            media = home / "song.m4a"
            lyrics = home / "licensed.txt"
            media.write_bytes(b"media")
            secret = "Unique secret Lyrics =;# \\ line 1\nline 2"
            lyrics.write_text(secret, encoding="utf-8")
            calls = []
            def fake_run(args, **kwargs):
                calls.append(args)
                self.assertNotIn(secret, " ".join(args))
                if args[0] == "ffprobe":
                    return SimpleNamespace(stdout=json.dumps({"format": {"tags": {
                        "title": "A title", "artist": "An artist"}}}))
                meta = Path(args[args.index("-f") + 3])
                self.assertEqual(meta.stat().st_mode & 0o777, 0o600)
                text = meta.read_text(encoding="utf-8")
                self.assertIn("A title", text)
                self.assertIn("An artist", text)
                self.assertIn("lyrics=", text)
                Path(args[-1]).write_bytes(media.read_bytes())
                return SimpleNamespace(returncode=0)
            with patch.dict(os.environ, {"XDG_STATE_HOME": str(home / "state")}), \
                 patch("cronos_yt.audio.subprocess.run", side_effect=fake_run):
                self.assertTrue(add_lyrics_from_file(media, lyrics))
            self.assertEqual(len(calls), 2)
            self.assertEqual(media.read_bytes(), b"media")
            self.assertEqual(list((home / "state" / "cronos-yt" / "tmp").glob("lyrics-*")), [])
            self.assertIn("\\=", _escape_ffmetadata(secret))
            self.assertIn("\\#", _escape_ffmetadata(secret))


class AuthAndLeaseSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "history.sqlite3"
        self.queue = QueueDB(self.db)
        self.job = DownloadJob(URL)

    def test_queue_without_receipt_rejected(self):
        with self.assertRaises(PermissionError):
            self.queue.add([self.job])
        self.assertEqual(self.queue.counts()["queued"], 0)

    def test_receipt_url_digest_and_mode(self):
        receipt = self.queue.auth.record(self.job, "--yes")
        self.assertEqual(receipt.url_sha256, hashlib.sha256(URL.encode()).hexdigest())
        self.assertTrue(self.queue.auth.verify(self.job, receipt))
        with sqlite3.connect(self.db) as db:
            row = db.execute("SELECT url_sha256,mode,session_id FROM job_authorizations WHERE id=?",
                             (receipt.id,)).fetchone()
            self.assertEqual(row, (url_hash(URL), "--yes", SESSION_ID))
            self.assertNotEqual(row[0], URL)

    def test_manager_requires_valid_current_session_receipts(self):
        from cronos_yt.history import HistoryDB
        mgr = DownloadManager(Settings(), HistoryDB(self.db), Console(file=io.StringIO()))
        with self.assertRaises(PermissionError):
            mgr.download([self.job])

    def test_legacy_queued_job_cannot_run_with_yes_alone(self):
        from cronos_yt.queue import fingerprint, utc_now
        from dataclasses import asdict
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO queue_items(job_json,fingerprint,status,created_at,updated_at) VALUES (?,?,?,?,?)",
                       (json.dumps(asdict(self.job)), fingerprint(self.job), "queued", utc_now(), utc_now()))
        class Manager:
            settings = Settings()
            def download(self, *args, **kwargs):
                raise AssertionError("Unauthorized network operation")
        with self.assertRaises(ValueError):
            run_queue(Manager(), self.queue, controls=False, yes=True)

    def test_boot_id_lease_and_pid_reuse(self):
        receipt = self.queue.auth.record(self.job, "queued")
        ids, _ = self.queue.add([self.job], [receipt])
        self.assertTrue(self.queue.start(ids[0], receipt))
        with sqlite3.connect(self.db) as con:
            con.execute("UPDATE queue_items SET lease_expires_at=0,owner_boot_id='different-boot' WHERE id=?", ids)
        with patch.object(QueueDB, "_pid_alive", return_value=True), \
             patch.object(QueueDB, "_boot_id", return_value="current-boot"):
            recovered = QueueDB(self.db)
        self.assertEqual(recovered.counts()["paused"], 1)

    def test_unexpired_lease_is_never_stolen(self):
        receipt = self.queue.auth.record(self.job, "queued")
        ids, _ = self.queue.add([self.job], [receipt])
        self.assertTrue(self.queue.start(ids[0], receipt))
        with patch.object(QueueDB, "_pid_alive", return_value=False):
            reopened = QueueDB(self.db)
        self.assertEqual(reopened.counts()["running"], 1)

    def test_schema_version_table_is_additive(self):
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT version FROM schema_versions WHERE component='queue'").fetchone()[0], 3)

    def test_batch_threshold_prompt(self):
        from cronos_yt.cli import menus
        with patch.object(menus, "ask_yes", return_value=False) as ask:
            self.assertFalse(_batch_confirmation(11, 10))
        ask.assert_called_once()
        with self.assertRaises(ValueError):
            _batch_confirmation(11, 10, noninteractive=True)
        self.assertTrue(_batch_confirmation(11, 10, noninteractive=True, confirm_large=True))

    def test_dispatch_yes_stores_receipt_and_never_calls_unapproved_engine(self):
        from cronos_yt.history import HistoryDB
        history = HistoryDB(self.db)
        class Manager:
            settings = Settings()
            history = None
            def download(self, jobs, **kwargs):
                self.assert_receipts = kwargs["authorizations"]
                return [DownloadResult("skipped", "test")]
        manager = Manager()
        manager.history = history
        import importlib
        with patch.object(importlib.import_module("cronos_yt.cli.dispatch"), "report"):
            self.assertEqual(dispatch(manager, [self.job], yes=True), 0)
        self.assertTrue(self.queue.auth.verify(self.job, manager.assert_receipts[0]))


class SupplyChainSafety(unittest.TestCase):
    def test_tampered_wheel_is_rejected_before_subprocess(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            folder = updater.cache_dir(root) / "rollback"
            folder.mkdir(parents=True)
            wheel = folder / "safe-1.0-py3-none-any.whl"
            wheel.write_bytes(b"trusted bytes")
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            updater.save_snapshot({"rich": "14.0.0"}, root,
                                  [{"filename":wheel.name, "sha256":digest}])
            self.assertTrue(updater.verify_wheels(root))
            wheel.write_bytes(b"tampered bytes")
            with self.assertRaises(ValueError):
                updater.verify_wheels(root)
            with patch.object(updater, "_invoke") as call:
                self.assertFalse(updater.rollback({"rich":"14.0.0"}, root=root))
                call.assert_not_called()

    def test_unpinned_requires_both_flags(self):
        self.assertEqual(updater.update_engine(unpinned=True, yes=False), 2)
        self.assertTrue(parser().parse_args(["--update-unpinned","--yes"]).update_unpinned)

    def test_hash_lock_rejects_unpinned(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "requirements.lock"
            p.write_text("rich>=14\n")
            self.assertFalse(updater.validate_lock(p))

    def test_fake_youtube_host_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_url("https://www.youtu.be/abc123def45")
        self.assertEqual(validate_url(URL), URL)

if __name__ == "__main__":
    unittest.main()
