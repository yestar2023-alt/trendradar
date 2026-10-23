import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import discover

NOW = datetime(2026, 10, 23, 6, tzinfo=timezone.utc)
A = "AAAAAAAAAAA"
B = "BBBBBBBBBBB"
C = "CCCCCCCCCCC"
D = "DDDDDDDDDDD"
CFG = {"queries": [{"q":"AI dance","order":"viewCount"},
                   {"q":"AI generated shorts","order":"date"}],
       "max_searches_per_scan":2,"viral_min_views":1000000,
       "early_watch_min_views":100000}


def video(vid, title="AI generated cat dance #shorts", hours_old=3,
          duration="PT15S", views=50000, disclosed=True):
    return {"id": vid,
            "snippet": {"title":title,"description":"AI animation created as art",
                        "publishedAt":discover.utc_iso(NOW-timedelta(hours=hours_old)),
                        "channelTitle":"Independent Creator",
                        "channelId":"UCexamplechannel0000000",
                        "tags":["#aigenerated","#shorts"] if "tutorial" not in title.lower() else []},
            "contentDetails":{"duration":duration},
            "statistics":{"viewCount":str(views),"likeCount":"500","commentCount":"10"},
            "status":{"containsSyntheticMedia":disclosed}}


class Mock:
    def __init__(self, videos=None, fail_query=None, no_video=False, search_ids=None):
        self.videos = videos or {A:video(A)}
        self.fail_query=fail_query
        self.no_video=no_video
        self.search_ids=search_ids
        self.calls=[]

    def __call__(self,resource,params,key):
        self.calls.append((resource,dict(params)))
        assert key == "test-key"
        if resource == "search":
            if self.fail_query == params["q"]:
                raise RuntimeError("simulated search failure")
            return {"items":[{"id":{"kind":"youtube#video","videoId":vid}} for vid in (self.search_ids if self.search_ids is not None else self.videos)]}
        if resource == "videos":
            if self.no_video:
                raise RuntimeError("detail API unavailable")
            return {"items":[self.videos[vid] for vid in params["id"].split(",")
                             if vid in self.videos]}
        raise AssertionError("unsupported mock")


class TestDiscover(unittest.TestCase):
    def test_query_rotation_covers_all_without_burst(self):
        cfg = {"queries":[{"q":str(i)} for i in range(8)],"max_searches_per_scan":3}
        selected = []
        for offset in range(4):
            current = NOW + timedelta(hours=4*offset)
            q = discover.choose_queries(cfg, current)
            self.assertEqual(len(q), 3)
            selected.extend(item["q"] for item in q)
        self.assertEqual(set(selected),{str(i) for i in range(8)})
        self.assertEqual(discover.choose_queries(cfg,NOW),discover.choose_queries(cfg,NOW))

    def test_duration_and_short_is_not_verified(self):
        self.assertEqual(discover.duration_seconds("PT3M"),180)
        self.assertEqual(discover.duration_seconds("PT3M1S"),181)
        self.assertIsNone(discover.duration_seconds("garbage"))
        item=discover.normalized_video(A,video(A),["AI dance"],NOW)
        self.assertFalse(item["shorts_verified"])
        self.assertTrue(item["shorts_hint"])

    def test_strict_24h_and_age_and_duration(self):
        videos={A:video(A,views=1_200_000),B:video(B,hours_old=25),C:video(C,duration="PT3M2S"),
                D:video(D,title="AI editor tutorial",views=50000)}
        with tempfile.TemporaryDirectory() as d:
            out=discover.run(Path(d),CFG,key="test-key",get=Mock(videos),now=NOW)
            self.assertEqual(out["recent_24h_short_candidates"],2)
            self.assertEqual(out["million_view_ai_candidates"],1)
            self.assertEqual(out["metadata_ai_hot_candidates"],1)
            csvtext=(Path(d)/"reports/latest.csv").read_text(encoding="utf-8-sig")
            self.assertIn(A,csvtext)
            self.assertNotIn(B,csvtext)
            self.assertNotIn(C,csvtext)
            self.assertIn(D,csvtext)
            report=(Path(d)/"reports/latest.md").read_text()
            self.assertIn("首次成功采集只建基线",report)

    def test_first_baseline_second_true_delta_growth(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            first=discover.run(root,CFG,key="test-key",get=Mock({A:video(A,views=20000)}),now=NOW)
            self.assertEqual(first["first_observed_after_baseline"],0)
            later=discover.run(root,CFG,key="test-key",get=Mock({
                A:video(A,views=24000),
                B:video(B,hours_old=1,views=17000),
            }),now=NOW+timedelta(hours=2))
            self.assertEqual(later["first_observed_after_baseline"],1)
            state=json.loads((root/"data/state.json").read_text())
            self.assertEqual(state["videos"][A]["first_seen_at"],discover.utc_iso(NOW))
            self.assertEqual(len(state["videos"][A]["samples"]),2)
            self.assertEqual(discover.observed_growth(state["videos"][A]["samples"]),2000.0)
            self.assertIn("本轮无合格百万AI候选",(root/"reports/latest.md").read_text())

    def test_999999_is_not_viral_and_1000000_is_viral(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            api=Mock({A:video(A,views=999999),B:video(B,views=1000000)})
            out=discover.run(root,CFG,key="test-key",get=api,now=NOW)
            self.assertEqual(out["million_view_ai_candidates"],1)
            self.assertEqual(out["early_watch_not_viral"],1)
            report=(root/"reports/latest.md").read_text()
            main=report.split("## 百万爆款候选")[1].split("## 早期潜力观察")[0]
            early=report.split("## 早期潜力观察")[1].split("## 搜索覆盖")[0]
            self.assertIn(B,main)
            self.assertNotIn(A,main)
            self.assertIn(A,early)
            self.assertIn("≥100万",report)

    def test_old_query_discovery_remains_in_million_view_rank_with_fresh_stats(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            discover.run(root,CFG,key="test-key",
                         get=Mock({A:video(A,views=1_100_000)}),now=NOW)
            # Search in the rotated slot finds only B; videos.list still
            # refreshes the previously found million-view A from the DB.
            mock=Mock({A:video(A,views=1_350_000),B:video(B,views=125000)},
                      search_ids=[B])
            out=discover.run(root,CFG,key="test-key",get=mock,now=NOW+timedelta(hours=4))
            self.assertEqual(out["million_view_ai_candidates"],1)
            self.assertEqual(out["early_watch_not_viral"],1)
            report=(root/"reports/latest.md").read_text()
            self.assertIn(A,report.split("## 百万爆款候选")[1].split("## 早期潜力观察")[0])
            self.assertIn("1,350,000",report)
            state=json.loads((root/"data/state.json").read_text())
            self.assertEqual(len(state["videos"][A]["samples"]),2)

    def test_unrelated_million_view_tutorial_not_ai_viral(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            out=discover.run(root,CFG,key="test-key",
                             get=Mock({A:video(A,views=2_000_000,title="AI video tools review")}),
                             now=NOW)
            self.assertEqual(out["million_view_ai_candidates"],0)
            self.assertIn("全部候选中单条观看量≥1,000,000的视频：1",(root/"reports/latest.md").read_text())
            self.assertIn("本轮无合格百万AI候选",(root/"reports/latest.md").read_text())

    def test_search_queries_use_24h_cutoff_and_limited_calls(self):
        api=Mock()
        matches,status=discover.search_recent(CFG["queries"],"test-key",NOW,api)
        self.assertEqual(len(matches),1)
        self.assertEqual(len([c for c in api.calls if c[0]=="search"]),2)
        self.assertEqual(api.calls[0][1]["publishedAfter"],"2026-10-22T06:00:00Z")
        self.assertEqual(api.calls[0][1]["publishedBefore"],"2026-10-23T06:00:00Z")
        self.assertEqual(api.calls[0][1]["videoDuration"],"short")

    def test_missing_secret_does_not_create_fake_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            out=discover.run(root,CFG,key="",now=NOW)
            self.assertFalse(out["connected"])
            self.assertFalse((root/"data/state.json").exists())
            self.assertIn("抓取失败", (root/"reports/latest.md").read_text())

    def test_partial_failure_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            api=Mock(fail_query="AI dance")
            out=discover.run(root,CFG,key="test-key",get=api,now=NOW)
            self.assertTrue(out["connected"])
            self.assertEqual(out["queries_succeeded"],1)
            self.assertIn("simulated search failure",(root/"reports/latest.md").read_text())

    def test_all_search_fail_preserves_state(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            discover.run(root,CFG,key="test-key",get=Mock(),now=NOW)
            state=(root/"data/state.json").read_bytes()
            # A function that makes all search requests fail, but cannot leak the secret.
            def fail(resource, params, key):
                raise RuntimeError("API HTTP 403; reason=quotaExceeded")
            out=discover.run(root,CFG,key="test-key",get=fail,now=NOW+timedelta(hours=4))
            self.assertFalse(out["connected"])
            self.assertEqual((root/"data/state.json").read_bytes(),state)
            self.assertIn("不能确认今日新增",(root/"reports/latest.md").read_text())

    def test_metadata_does_not_prove_ai_video(self):
        confidence,reason,_,_=discover.classify_metadata("AI Video Tool Review","",[],False)
        self.assertEqual(confidence,"low")
        confidence,_,_,_=discover.classify_metadata("Cute cat dancing","ordinary entertainment",[],False)
        self.assertEqual(confidence,"unknown")


if __name__ == "__main__":
    unittest.main()
