import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import upstream

CID = "UC2t5bjwHdUX4vM2g8TRDq5g"
CONFIG = {"channels": [{"id": "riot", "name": "League of Legends", "channel_id": CID}], "max_pages": 1}
ONE = "abcdefghijk"
TWO = "12345678901"


class MockAPI:
    def __init__(self, ids=None, views=None, failing=None, incomplete=False):
        self.ids = ids if ids is not None else [ONE]
        self.views = views or {}
        self.failing = failing
        self.incomplete = incomplete
        self.calls = []

    def __call__(self, resource, params, key):
        assert key == "sample-test-key", "secret should be passed privately"
        self.calls.append((resource, dict(params)))
        if resource == self.failing:
            raise RuntimeError("YouTube Data API HTTP 403; reason=quotaExceeded")
        if resource == "channels":
            return {"items": [{"id": CID, "contentDetails": {"relatedPlaylists": {"uploads": "UU2t5bjwHdUX4vM2g8TRDq5g"}}}]}
        if resource == "playlistItems":
            return {"items": [{"contentDetails": {"videoId": vid}} for vid in self.ids]}
        if resource == "videos":
            return {"items": [
                {"id": vid,
                 "snippet": {"title": "KDA Dance " + vid, "publishedAt": "2026-10-20T00:00:00Z"},
                 "statistics": {"viewCount": str(self.views.get(vid, 12345))}}
                for vid in params["id"].split(",") if not self.incomplete
            ]}
        raise AssertionError("Unexpected API resource")


class TestDataApi(unittest.TestCase):
    def test_resolves_real_uploads_playlist_and_metadata(self):
        api = MockAPI([ONE, TWO], {ONE: 52, TWO: 77})
        out = upstream.load_channel_videos(CID, "sample-test-key", api, max_pages=1)
        self.assertEqual(out[TWO]["views"], 77)
        self.assertEqual(out[TWO]["published"], "2026-10-20T00:00:00Z")
        self.assertEqual([call[0] for call in api.calls], ["channels", "playlistItems", "videos"])
        self.assertEqual(api.calls[1][1]["maxResults"], 50)

    def test_first_success_baseline_then_real_delta(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = upstream.run(root, CONFIG, key="sample-test-key", get=MockAPI([ONE]),
                                 now="2026-10-21T00:00:00Z")
            self.assertEqual(first["new_video_urls"], 0)
            self.assertIn("首次建立基线", (root/"reports/latest.md").read_text())
            later = upstream.run(root, CONFIG, key="sample-test-key", get=MockAPI([ONE,TWO]),
                                 now="2026-10-22T00:00:00Z")
            self.assertEqual(later["new_video_urls"], 1)
            report=(root/"reports/latest.md").read_text()
            self.assertIn(TWO, report)
            self.assertIn("2026-10-20 08:00", report)
            self.assertIn("2026-10-22 08:00", report)
            repeat = upstream.run(root, CONFIG, key="sample-test-key", get=MockAPI([ONE,TWO]),
                                  now="2026-10-22T04:00:00Z")
            self.assertEqual(repeat["new_video_urls"], 0)

    def test_sample_history_and_growth(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            upstream.run(root, CONFIG, key="sample-test-key", get=MockAPI([ONE], {ONE: 100}),
                         now="2026-10-21T00:00:00Z")
            upstream.run(root, CONFIG, key="sample-test-key", get=MockAPI([ONE, TWO], {ONE: 180,TWO: 50}),
                         now="2026-10-21T04:00:00Z")
            state=json.loads((root/"data/state.json").read_text())
            self.assertEqual(len(state["videos"][ONE]["samples"]), 2)
            self.assertEqual(state["videos"][ONE]["samples"][1]["views"] - state["videos"][ONE]["samples"][0]["views"],80)

    def test_failure_preserves_successful_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            upstream.run(root, CONFIG, key="sample-test-key", get=MockAPI([ONE]))
            out=upstream.run(root, CONFIG, key="sample-test-key", get=MockAPI([ONE,TWO], failing="videos"))
            self.assertFalse(out["live_connected"])
            state=json.loads((root/"data/state.json").read_text())
            self.assertEqual(state["sources"]["riot"]["ids"], [ONE])
            self.assertIn("抓取失败", (root/"reports/latest.md").read_text())
            self.assertIn("不能确认今日新增", (root/"reports/latest.md").read_text())

    def test_no_secret_is_not_fake_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            out=upstream.run(root, CONFIG, key="")
            self.assertFalse(out["live_connected"])
            report=(root/"reports/latest.md").read_text()
            self.assertIn("YOUTUBE_API_KEY", report)
            self.assertIn("不能确认今日新增", report)
            self.assertNotIn("sample-test-key", report)

    def test_partial_response_prevents_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            out=upstream.run(root, CONFIG, key="sample-test-key", get=MockAPI([ONE],incomplete=True))
            self.assertFalse(out["live_connected"])
            state=json.loads((root/"data/state.json").read_text())
            self.assertFalse(state["sources"])

    def test_validate_ids_and_timezones(self):
        with self.assertRaises(ValueError):
            upstream.load_channel_videos("bad-channel", "key", MockAPI())
        self.assertEqual(upstream.beijing("2026-10-21T00:00:00Z"),"2026-10-21 08:00")
        self.assertEqual(upstream.beijing("invalid"),"未知")

if __name__ == "__main__":
    unittest.main()
