import unittest

from cronos_yt.audio import audio_postprocessors
from cronos_yt.playlists import parse_playlist
from cronos_yt.video import available_heights, select_video


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.info = {"formats": [
            {"format_id": "137", "height": 1080, "fps": 30,
             "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "tbr": 3000},
            {"format_id": "299", "height": 1080, "fps": 60,
             "ext": "mp4", "vcodec": "avc1.64002a", "acodec": "none", "tbr": 4000},
            {"format_id": "303", "height": 1080, "fps": 60,
             "ext": "webm", "vcodec": "vp9", "acodec": "none", "tbr": 4900},
            {"format_id": "136", "height": 720, "fps": 30,
             "ext": "mp4", "vcodec": "avc1", "acodec": "none", "tbr": 1000},
        ]}

    def test_stream_preference_60fps_h264(self):
        choice = select_video(self.info, 1080, 60)
        self.assertTrue(choice.format_selector.startswith("299+"))
        self.assertTrue(choice.compatible)
        self.assertEqual(choice.fps, 60)
        self.assertEqual(available_heights(self.info), [720, 1080])

    def test_60fps_is_selected_when_only_vp9_has_60fps(self):
        only_60_vp9 = dict(self.info)
        only_60_vp9["formats"] = [f for f in self.info["formats"] if f["format_id"] != "299"]
        choice = select_video(only_60_vp9, 1080, 60)
        self.assertEqual(choice.fps, 60)
        self.assertEqual(choice.codec, "vp9")

    def test_fps_limit_30(self):
        self.assertEqual(select_video(self.info, 1080, 30).fps, 30)

    def test_lower_quality_fallback(self):
        self.assertEqual(select_video(self.info, 480).height, 720)

    def test_audio(self):
        post, artwork = audio_postprocessors("mp3", 320, True)
        self.assertTrue(artwork)
        self.assertEqual(post[0]["preferredquality"], "320K")
        self.assertEqual(post[-1]["key"], "EmbedThumbnail")
        _, opus_artwork = audio_postprocessors("opus", 128, True)
        self.assertTrue(opus_artwork)
        _, wav_artwork = audio_postprocessors("wav", 128, True)
        self.assertFalse(wav_artwork)

    def test_flat_playlist(self):
        name, entries = parse_playlist({
            "_type": "playlist", "title": "My / playlist", "entries": [
                {"id": "abc123def45", "title": "Track", "playlist_index": 4},
                {"id": "PRIVATE", "title": "Skip"},
                {"id": "def123abc45", "title": "Track 2"},
            ]
        }, 50)
        self.assertEqual(name, "My _ playlist")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].index, 4)
        self.assertIn("watch?v=abc123def45", entries[0].url)


if __name__ == "__main__":
    unittest.main()
