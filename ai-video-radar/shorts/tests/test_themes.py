import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import themes

NOW=datetime(2026,10,23,8,tzinfo=timezone.utc)
SEEN="2026-10-23T07:00:00Z"
PUBLISHED="2026-10-22T22:00:00Z"

def v(vid,title,account,views=10000,ai="medium",published=PUBLISHED):
    return {"video_id":vid,"title":title,"channel":"Channel "+account,
            "channel_id":"UC"+account,"url":"https://www.youtube.com/watch?v="+vid,
            "published_at":published,"first_seen_at":SEEN,
            "views":views,"ai_metadata_confidence":ai,
            "samples":[{"at":"2026-10-23T06:00:00Z","views":views-1000},
                       {"at":"2026-10-23T07:00:00Z","views":views}]}

def state(data):
    return {"first_success_at":"2026-10-23T06:00:00Z",
            "scans":[{"time":"2026-10-23T07:50:00Z","successful_queries":8}],
            "videos":data}

class ThemeTests(unittest.TestCase):
    def test_named_not_generic_clustering(self):
        data={"A":v("A","AI Funny Cat #shorts","creator1"),
              "B":v("B","AI Cat Dance #shorts","creator2")}
        result=themes.build(state(data),NOW)
        self.assertEqual(result["named_theme_count"],0)
        self.assertEqual(result["confirmed_new_seo_keywords"],0)
        self.assertEqual(len(result["unmatched_creative_candidates"]),2)

    def test_distinct_creator_not_same_channel_uploads(self):
        data={
            "A":v("A","ChatGPT Mixed 2 Random Photos Part 1","same1"),
            "B":v("B","ChatGPT Mixed 2 Random Photos Part 2","same1"),
            "C":v("C","ChatGPT Mixed Two Random Photos Part 3 tutorial","other")
        }
        r=themes.build(state(data),NOW)
        topic=next(x for x in r["themes"] if x["theme_id"]=="random_photo_mix")
        self.assertEqual(topic["videos"],3)
        self.assertEqual(topic["independent_claimed_creator_count"],1)
        self.assertEqual(topic["claimed_ai_creations"],2)
        self.assertIn("只有单账号",topic["verdict"])

    def test_reporter_not_creator_and_old_trend(self):
        data={"A":v("A","These Viral 4D Theater Videos Are Actually AI!","r1"),
              "B":v("B","Bioskop 4D Ini Viral, Tapi Ternyata Video AI","r2")}
        r=themes.build(state(data),NOW)
        theme=next(x for x in r["themes"] if x["theme_id"]=="cinema_breakout")
        self.assertEqual(theme["status"],themes.KNOWN_STOCK)
        self.assertEqual(theme["independent_claimed_creator_count"],0)
        self.assertIn("不算今日",themes.report(r))

    def test_cat_clapping_known_before(self):
        data={"A":v("A","Cat Clapping AI Video","account1"),
              "B":v("B","Clapping Cat Funny AI #shorts","account2")}
        r=themes.build(state(data),NOW)
        theme=next(x for x in r["themes"] if x["theme_id"]=="cat_clapping")
        self.assertEqual(theme["independent_claimed_creator_count"],2)
        self.assertEqual(theme["status"],themes.KNOWN_STOCK)
        self.assertEqual(r["claimed_multi_creator_themes"],0)

    def test_two_creators_remain_candidates_not_seo_confirmation(self):
        data={"A":v("A","Funny Living Food AI","account1"),
              "B":v("B","Living Food becomes alive","account2")}
        r=themes.build(state(data),NOW)
        theme=next(x for x in r["themes"] if x["theme_id"]=="living_food")
        self.assertEqual(theme["independent_claimed_creator_count"],2)
        self.assertEqual(r["claimed_multi_creator_themes"],1)
        self.assertEqual(r["confirmed_new_seo_keywords"],0)
        self.assertIn("核验是否同一具体玩法",theme["verdict"])

    def test_real_growth_only_from_two_samples(self):
        x=v("A","Robot Girl Dance AI","r1")
        self.assertEqual(themes.observed_rate(x),1000)
        x["samples"] = x["samples"][:1]
        self.assertIsNone(themes.observed_rate(x))

    def test_stale_and_missing_snapshot_fail(self):
        with self.assertRaisesRegex(ValueError,"Missing successful"):
            themes.build({"videos":{}},NOW)
        with self.assertRaisesRegex(ValueError,"Stale"):
            themes.build({"first_success_at":"2026-10-21T00:00:00Z",
                         "scans":[{"time":"2026-10-21T00:00:00Z"}],
                         "videos":{}},NOW)

    def test_real_io_and_report_link_not_fake(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"data").mkdir()
            data=state({"A":v("A","Cat Clapping AI","one")})
            (root/"data/state.json").write_text(json.dumps(data))
            result=themes.run(root,NOW)
            self.assertEqual(result["confirmed_new_seo_keywords"],0)
            content=(root/"reports/themes-latest.md").read_text()
            self.assertIn("https://www.youtube.com/watch?v=A",content)
            self.assertIn("9月已出现",content)
            self.assertTrue((root/"reports/themes-latest.json").exists())
            self.assertTrue((root/"reports/2026-10-23-themes.md").exists())

    def test_creators_without_channel_id_cannot_claim_diversity(self):
        a=v("A","Living Food animated","a");b=v("B","Funny Living Food","b")
        a["channel_id"]="";b["channel_id"]=""
        r=themes.build(state({"A":a,"B":b}),NOW)
        x=next(t for t in r["themes"] if t["theme_id"]=="living_food")
        self.assertEqual(x["independent_claimed_creator_count"],0)

if __name__=="__main__":
    unittest.main()
