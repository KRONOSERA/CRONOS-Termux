import tempfile
import unittest
from pathlib import Path

from cronos_yt.storage import (ensure_space, ensure_writable, is_playlist_url,
                               parse_urls, sanitize_filename, validate_url)


class StorageTests(unittest.TestCase):
    def test_allowed_urls(self):
        for link in (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/shorts/dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://music.youtube.com/playlist?list=PL12345678",
        ):
            self.assertEqual(validate_url(link), link)

    def test_blocks_credentials_and_external_hosts(self):
        for bad in (
            "http://youtube.com/watch?v=123",
            "https://youtube.com.evil.test/watch?v=123",
            "https://example.org/watch?v=123",
            "https://user:pass@youtube.com/watch?v=123",
            "https://youtube.com:6000/watch?v=123",
            "javascript:alert(1)",
            "https://youtube.com/watch?v=abc\nrm -rf /",
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_url(bad)

    def test_multiple_urls_deduplicated(self):
        first = "https://youtu.be/dQw4w9WgXcQ"
        second = "https://youtube.com/shorts/dQw4w9WgXcQ"
        self.assertEqual(parse_urls(f"{first}\n{second}\n{first}"), [first, second])

    def test_safe_filename(self):
        self.assertEqual(sanitize_filename("../a:b\\c?*"), "_a_b_c__")
        self.assertEqual(sanitize_filename("..."), "Untitled")
        self.assertEqual(sanitize_filename("a/b"), "a_b")

    def test_playlist_url(self):
        self.assertTrue(is_playlist_url("https://www.youtube.com/playlist?list=PL123"))
        self.assertFalse(is_playlist_url("https://www.youtube.com/watch?v=abc123def45"))

    def test_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "Movies" / "CRONOS-YT"
            ensure_writable(dest)
            ensure_space(dest, 1024)
            self.assertTrue(dest.is_dir())


if __name__ == "__main__":
    unittest.main()
