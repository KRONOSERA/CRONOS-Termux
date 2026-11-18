"""v2 regressions: no network calls, no Android device required."""
import csv
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from cronos_yt.backup import create_backup
from cronos_yt.downloader import DownloadJob, DownloadManager
from cronos_yt.history import HistoryDB
from cronos_yt.library import export_library, search_library
from cronos_yt.playlists import PlaylistEntry
from cronos_yt.playlist_tools import choose_positions, subset
from cronos_yt.queue import QueueDB
from cronos_yt.settings import Settings, load_settings, save_settings

URL = "https://youtu.be/abc123def45"


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = HistoryDB(self.root / "history.sqlite3")
        self.media = self.root / "example.mp3"
        self.media.write_bytes(b"abcde")
        self.db.record(key="key", media_id="abc123def45", title="Example Tune", kind="music",
                       fmt="mp3", quality="192k", status="success", file_path=str(self.media))
        self.db.record(key="key", media_id="abc123def45", title="Example Tune", kind="music",
                       fmt="mp3", quality="192k", status="success", file_path=str(self.media))
        self.db.record(key="key2", media_id="abc123def47", title="No Longer Present", kind="video",
                       fmt="mp4", quality="720p", status="success", file_path=str(self.root / "missing.mp4"))

    def test_search_is_deduplicated_filtered_and_detects_missing(self):
        self.assertEqual(len(search_library(self.db)), 2)
        self.assertEqual(search_library(self.db, "tune")[0].title, "Example Tune")
        self.assertEqual(search_library(self.db, kind="music")[0].size_bytes, 5)
        self.assertEqual(search_library(self.db, missing_only=True)[0].title, "No Longer Present")
        self.assertEqual(search_library(self.db, "_"), [])  # escaped LIKE syntax
        with self.assertRaises(ValueError):
            search_library(self.db, kind="invalid")

    def test_csv_export_and_m3u_skip_missing(self):
        csv_path, count = export_library(self.db, self.root / "list.csv")
        self.assertEqual(count, 1)
        with csv_path.open(encoding="utf-8", newline="") as fp:
            rows = list(csv.DictReader(fp))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Example Tune")
        m3u, count = export_library(self.db, self.root / "list.m3u", format="m3u")
        self.assertEqual(count, 1)
        self.assertIn(str(self.media), m3u.read_text())
        self.assertNotIn("missing.mp4", m3u.read_text())

    def test_csv_title_formula_injection_is_neutralized(self):
        self.db.record(key="x", media_id="abc123def48", title="=HYPERLINK('bad')", kind="music",
                       fmt="mp3", quality="192k", status="success", file_path=str(self.media))
        _, count = export_library(self.db, self.root / "safe.csv")
        self.assertEqual(count, 1)  # per path latest
        with (self.root / "safe.csv").open(encoding="utf-8") as fp:
            contents = fp.read()
        self.assertIn("'=HYPERLINK", contents)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.entries = [PlaylistEntry(URL, i + 10, title)
                        for i, title in enumerate(("Alpha", "Beta", "Gamma", "Alpha two"))]

    def test_ranges_preserve_original_playlist_index(self):
        self.assertEqual(choose_positions("1-2,4", 4), {1, 2, 4})
        self.assertEqual([e.index for e in subset(self.entries, "1-2,4")], [10, 11, 13])
        self.assertEqual([e.title for e in subset(self.entries, search="alpha")], ["Alpha", "Alpha two"])
        self.assertEqual(choose_positions("ALL", 4), {1, 2, 3, 4})

    def test_bad_ranges(self):
        for bad in ("0", "6", "2-1", "1-6", "1,,2", "3,xyz", "1-2-3"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                choose_positions(bad, 4)


class QueueAndSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_queue_priority_and_migration(self):
        db = self.root / "legacy.sqlite3"
        with sqlite3.connect(db) as con:
            con.execute("""CREATE TABLE queue_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_json TEXT NOT NULL,
                fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, owner_pid INTEGER,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT '', last_file TEXT NOT NULL DEFAULT ''
            )""")
        queue = QueueDB(db)
        one, two = queue.add([DownloadJob(URL), DownloadJob("https://youtu.be/def123abc45")], [queue.auth.record(DownloadJob(URL), "queued"), queue.auth.record(DownloadJob("https://youtu.be/def123abc45"), "queued")])[0]
        self.assertTrue(queue.prioritize(two, 9))
        self.assertEqual([item.id for item in queue.list(statuses=("queued",))], [two, one])
        self.assertFalse(queue.prioritize(9999, 9))
        with self.assertRaises(ValueError):
            queue.prioritize(one, 11)
        self.assertEqual(QueueDB(db).list(statuses=("queued",))[0].priority, 9)

    def test_settings_migrate_and_subtitles(self):
        config = self.root / "settings.json"
        config.write_text(json.dumps({"audio_format": "opus", "unknown_future": "ignored"}))
        settings = load_settings(config)
        self.assertEqual(settings.audio_format, "opus")
        self.assertEqual(settings.subtitles_mode, "none")
        settings.subtitles_mode = "automatic"
        settings.subtitles_languages = "en,ar"
        settings.filename_style = "date-title"
        save_settings(settings, config)
        self.assertEqual(load_settings(config).filename_style, "date-title")
        for bad in ("../en", "en;ar", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Settings(subtitles_languages=bad).validate()

    def test_download_options_include_subtitles_and_naming(self):
        settings = Settings(subtitles_mode="manual", subtitles_languages="en,ar")
        manager = DownloadManager(settings, HistoryDB(self.root / "history.sqlite3"))
        info = {"id": "abc123def45", "title": "Demo", "formats": [
            {"format_id": "137", "height": 720, "fps": 30,
             "vcodec": "avc1.123", "acodec": "none", "ext": "mp4"}]}
        opts, ext, quality, _ = manager._format_settings(DownloadJob(URL), info)
        self.assertEqual(opts["subtitleslangs"], ["en", "ar"])
        self.assertTrue(opts["writesubtitles"])
        self.assertFalse(opts["writeautomaticsub"])
        self.assertEqual(ext, "mp4")

    def test_backup_is_consistent_and_no_media(self):
        db = HistoryDB(self.root / "history.sqlite3")
        file = self.root / "not_in_backup.mp4"
        file.write_bytes(b"private media payload")
        db.record(key="abc", media_id="abc123def45", title="Track", kind="video",
                  fmt="mp4", quality="720p", status="success", file_path=str(file))
        queue = QueueDB(db.path)
        queue.add([DownloadJob(URL)], [queue.auth.record(DownloadJob(URL), "queued")])
        settings = self.root / "settings.json"
        save_settings(Settings(), settings)
        dest = create_backup(self.root / "backup.zip", database=db.path, configuration=settings)
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
        with zipfile.ZipFile(dest) as z:
            self.assertEqual(set(z.namelist()), {"manifest.json", "history.sqlite3", "settings.json"})
            self.assertEqual(json.loads(z.read("manifest.json"))["format_version"], 1)
            extracted = self.root / "restored-snapshot.sqlite3"
            extracted.write_bytes(z.read("history.sqlite3"))
        with sqlite3.connect(extracted) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM downloads").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM queue_items").fetchone()[0], 1)
        with self.assertRaises(FileExistsError):
            create_backup(dest, database=db.path, configuration=settings)


if __name__ == "__main__":
    unittest.main()
