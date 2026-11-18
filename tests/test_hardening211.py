"""v2.1.1 update/rollback, no-network preview, UI limits and data-safety tests."""
from __future__ import annotations

import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cronos_yt import updater
from cronos_yt.settings import Settings, load_settings
from cronos_yt.queue import QueueDB
from cronos_yt.history import HistoryDB


class UpdateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.previous = {"yt-dlp": "2026.10.26", "yt-dlp-ejs": "0.4.0",
                         "rich": "14.0.0", "questionary": "2.1.0", "mutagen": "1.47.0"}
        self.read_version = lambda name: self.previous[name]

    def test_snapshot_is_private_and_round_trips(self):
        path = updater.save_snapshot(self.previous, self.root)
        self.assertEqual(updater.read_snapshot(self.root), self.previous)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_snapshot_rejects_unexpected_packages_and_injection(self):
        for versions in ({"something-else": "1.0"}, {"rich": "1;echo x"}):
            with self.assertRaises(ValueError):
                updater.save_snapshot(versions, self.root)
        file = updater.save_snapshot(self.previous, self.root)
        file.write_text('{"packages":{"rich":"1.0 --extra-index-url=https://bad"}}')
        with self.assertRaises(ValueError):
            updater.read_snapshot(self.root)

    def test_update_success_is_verified(self):
        calls = []
        def run(args):
            calls.append(args)
            return 0
        with patch.object(updater, "validate_lock", return_value=True), \
             patch.object(updater, "_cache_prior", return_value=[{"filename":"sample.whl","sha256":"a"*64}]):
            status = updater.update_engine(run=run, read_version=self.read_version, root=self.root)
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 3)  # locked wheel download, install, smoke
        self.assertIn("--require-hashes", calls[1])

    def test_failed_upgrade_restores_exact_versions(self):
        calls = []
        def run(args):
            calls.append(args)
            return 1 if len(calls) == 2 else 0
        with patch.object(updater, "validate_lock", return_value=True), \
             patch.object(updater, "_cache_prior", return_value=[{"filename":"sample.whl","sha256":"a"*64}]), \
             patch.object(updater, "rollback", return_value=True) as restore:
            status = updater.update_engine(run=run, read_version=self.read_version, root=self.root)
        self.assertEqual(status, 1)
        restore.assert_called_once()
        self.assertEqual(len(calls), 2)

    def test_smoke_failure_and_unavailable_rollback_returns_error(self):
        calls = []
        def run(args):
            calls.append(args)
            return 1 if len(calls) == 3 else 0
        with patch.object(updater, "validate_lock", return_value=True), \
             patch.object(updater, "_cache_prior", return_value=[{"filename":"sample.whl","sha256":"a"*64}]), \
             patch.object(updater, "rollback", return_value=False):
            status = updater.update_engine(run=run, read_version=self.read_version, root=self.root)
        self.assertEqual(status, 2)
        self.assertEqual(len(calls), 3)

    def test_user_requested_rollback(self):
        updater.save_snapshot(self.previous, self.root)
        with patch.object(updater, "rollback", return_value=True) as restore:
            self.assertEqual(updater.restore_engine(root=self.root), 0)
        restore.assert_called_once()
        self.assertEqual(restore.call_args.args[0], self.previous)


class ApplicationHardeningTests(unittest.TestCase):
    def test_preview_does_not_probe_network_or_downloader(self):
        from cronos_yt.cli import main
        with tempfile.TemporaryDirectory() as d:
            environment = {"XDG_CONFIG_HOME": str(Path(d) / "config"),
                           "XDG_DATA_HOME": str(Path(d) / "data"),
                           "XDG_STATE_HOME": str(Path(d) / "state")}
            with patch.dict(os.environ, environment), \
                 patch("socket.socket.connect", side_effect=AssertionError("Network connection attempted")) as connect, \
                 patch("cronos_yt.cli.check_dependencies", side_effect=AssertionError("Unexpected dependency check")), \
                 patch("cronos_yt.cli.DownloadManager", side_effect=AssertionError("Unexpected downloader initialization")):
                self.assertEqual(main(["--ui-preview"]), 0)
                connect.assert_not_called()

    def test_legacy_history_and_queue_survive_open(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "history.sqlite3"
            history = HistoryDB(path)
            history.record(key="k", media_id="abc123def45", title="Recorded", kind="music",
                           fmt="mp3", quality="192k", status="success", file_path="/tmp/test.mp3")
            queue = QueueDB(path)
            self.assertEqual(queue.counts()["queued"], 0)
            self.assertEqual(history.recent(1)[0]["title"], "Recorded")

    def test_corrupt_settings_fail_without_overwriting_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text("{malformed-json\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_settings(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "{malformed-json\n")

    def test_width_boundaries(self):
        from cronos_yt.ui import compact
        self.assertTrue(compact(width=43))
        self.assertTrue(compact(width=67))
        self.assertFalse(compact(width=68))
        self.assertFalse(compact(width=70))

    def test_upgrade_notice_is_once_only(self):
        from cronos_yt.cli import show_upgrade_notice
        with tempfile.TemporaryDirectory() as d:
            environment = {"XDG_STATE_HOME": d}
            target = Path(d) / "cronos-yt" / "whats-new-v2.1.1.txt"
            target.parent.mkdir(parents=True)
            target.write_text("New menu", encoding="utf-8")
            with patch.dict(os.environ, environment), patch("cronos_yt.cli.ask_text") as ask:
                show_upgrade_notice()
                show_upgrade_notice()
            self.assertFalse(target.exists())
            ask.assert_called_once()


if __name__ == "__main__":
    unittest.main()
