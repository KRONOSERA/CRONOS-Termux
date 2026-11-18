import json
import tempfile
import unittest
from pathlib import Path

from cronos_yt.settings import Settings, load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            expected = Settings(concurrency=3, audio_format="flac", video_dir=str(Path(d) / "v"))
            save_settings(expected, path)
            self.assertEqual(load_settings(path), expected)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_reject_malformed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "broken.json"
            path.write_text(json.dumps({"concurrency": 999}))
            with self.assertRaises(ValueError):
                load_settings(path)

    def test_limits(self):
        with self.assertRaises(ValueError):
            Settings(playlist_limit=9999).validate()
        with self.assertRaises(ValueError):
            Settings(mp3_bitrate=900).validate()


if __name__ == "__main__":
    unittest.main()
