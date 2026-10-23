import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import emerging

NOW=datetime(2026,10,23,12,tzinfo=timezone.utc)
PUBLISHED="2026-10-23T05:00:00Z"
FIRST="2026-10-23T10:00:00Z"


def video(vid,title,channel="UCtesta",confidence="medium",views=15000,published=PUBLISHED,
          tags=()):
    return {
        "video_id":vid,"title":title,"url":"https://www.youtube.com/watch?v="+vid,
        "channel":channel,"channel_id":channel,
        "ai_metadata_confidence":confidence,
        "published_at":published,"first_seen_at":FIRST,
        "views":views,
        "source_tags":list(tags),
        "samples":[
            {"at":"2026-10-23T10:00:00Z","views":views-2500},
            {"at":"2026-10-23T11:00:00Z","views":views},
        ],
    }


def state(videos):
    return {"first_success_at":"2026-10-23T07:00:00Z",
            "scans":[{"time":"2026-10-23T11:50:00Z","successful_queries":8}],
            "videos":videos}


class TestEmerging(unittest.TestCase):
    def test_generic_ai_cat_dance_does_not_create_theme(self):
        left=video("AAAAAAAAAAA","AI Cat Dance funny shorts #aigenerated","UCone")
        right=video("BBBBBBBBBBB","Funny AI Cat Dance viral #shorts","UCtwo")
        r=emerging.build(state({"a":left,"b":right}),NOW)
        self.assertEqual(r["shared_name_groups"],0)
        self.assertEqual(r["independent_claimed_and_same_action_candidates"],0)
        self.assertEqual(r["confirmed_new_seo_keywords"],0)

    def test_rejects_broad_concatenated_social_hashtags(self):
        generic = [
            "#trendingshorts", "#AIDance", "#AITransformation",
            "#funnycats", "#cartoonshorts", "#catshorts",
            "#satisfying", "#aishort", "#AIGeneratedShorts",
        ]
        for tag in generic:
            self.assertTrue(emerging.is_generic_hashtag(tag), tag)
        a=video("AAAAAAAAAAA","Cool video #trendingShorts #aishort","UCone")
        b=video("BBBBBBBBBBB","Other video #trendingShorts #aishort","UCtwo")
        r=emerging.build(state({"a":a,"b":b}),NOW)
        self.assertEqual(r["shared_name_groups"],0)
        self.assertEqual(r["confirmed_new_seo_keywords"],0)

    def test_artificialintelligence_generic_tag_not_named_effect(self):
        a=video("AAAAAAAAAAA","POV ChatGPT 2080 #artificialintelligence","UCone")
        b=video("BBBBBBBBBBB","USA AI video #artificialintelligence","UCtwo")
        self.assertTrue(emerging.is_generic_hashtag("#artificialintelligence"))
        result=emerging.build(state({"a":a,"b":b}),NOW)
        self.assertFalse(any(g["anchor"]=="#artificialintelligence"
                             for g in result["cross_creator_groups"]))

    def test_generic_subject_tags_do_not_assert_shared_effect(self):
        for tag in ("#automobile", "#villagelife"):
            self.assertTrue(emerging.is_generic_hashtag(tag),tag)
        a=video("AAAAAAAAAAA","An AI football cartoon #automobile","UCone")
        b=video("BBBBBBBBBBB","AI car accident #automobile","UCtwo")
        result=emerging.build(state({"a":a,"b":b}),NOW)
        self.assertFalse(any(g["anchor"]=="#automobile" for g in result["cross_creator_groups"]))

    def test_dynamic_specific_phrase_across_creators(self):
        a=video("AAAAAAAAAAA","KDA Firestarter Dance AI #shorts #aigenerated","UCone")
        b=video("BBBBBBBBBBB","KDA Firestarter Dance Challenge #aivideo","UCtwo")
        r=emerging.build(state({"a":a,"b":b}),NOW)
        item=next(x for x in r["cross_creator_groups"] if x["anchor"]=="kda firestarter")
        self.assertEqual(item["unique_channels"],2)
        self.assertEqual(item["ai_claimed_channels"],2)
        self.assertEqual(item["classification"],"potential_same_action")
        self.assertEqual(r["confirmed_new_seo_keywords"],0)
        self.assertIn("同名且有共同动作",emerging.report(r))
        self.assertIn("https://www.youtube.com/watch?v=AAAAAAAAAAA",emerging.report(r))

    def test_same_author_multi_upload_not_cross_creator(self):
        a=video("AAAAAAAAAAA","KDA Firestarter Dance AI","UCone",views=150000)
        b=video("BBBBBBBBBBB","KDA Firestarter Dance AI part 2","UCone",views=140000)
        r=emerging.build(state({"a":a,"b":b}),NOW)
        self.assertEqual(r["shared_name_groups"],0)
        self.assertEqual(len(r["high_velocity_single_creator_watchlist"]),1)

    def test_identical_named_person_without_same_action_is_not_a_format(self):
        a=video("AAAAAAAAAAA","Lamine Yamal Lost His Dog #aigenerated","UCone")
        b=video("BBBBBBBBBBB","Lamine Yamal scores again #aivideo","UCtwo")
        r=emerging.build(state({"a":a,"b":b}),NOW)
        self.assertEqual(r["independent_claimed_and_same_action_candidates"],0)
        self.assertEqual(r["shared_name_groups"],0)

    def test_named_hashtag_discovery_works_across_languages(self):
        a=video("AAAAAAAAAAA","La nueva movida #KDAFirestarter #aigenerated","UCone")
        b=video("BBBBBBBBBBB","最新 AI 跳舞 #KDAFirestarter","UCtwo")
        r=emerging.build(state({"a":a,"b":b}),NOW)
        found=next(x for x in r["cross_creator_groups"] if x["anchor"]=="#kdafirestarter")
        self.assertEqual(found["classification"],"shared_phrase_only")
        self.assertEqual(found["unique_channels"],2)

    def test_education_and_older_than_24h_excluded(self):
        a=video("AAAAAAAAAAA","KDA Firestarter Dance AI tutorial","UCone")
        b=video("BBBBBBBBBBB","KDA Firestarter Dance AI #aivideo","UCtwo",
                published="2026-10-22T08:00:00Z")
        r=emerging.build(state({"a":a,"b":b}),NOW)
        self.assertEqual(r["shared_name_groups"],0)

    def test_known_existing_theme_not_recommended(self):
        a=video("AAAAAAAAAAA","Cat Clapping AI Dance #BlackCatClapping","UCone")
        b=video("BBBBBBBBBBB","Clapping Cat AI #BlackCatClapping","UCtwo")
        r=emerging.build(state({"a":a,"b":b}),NOW)
        matches=[x for x in r["cross_creator_groups"] if x["anchor"]=="#blackcatclapping"]
        self.assertTrue(matches)
        self.assertEqual(matches[0]["classification"],"known")
        self.assertEqual(matches[0]["priority_points_not_seo_score"],0)
        self.assertFalse(r["high_velocity_single_creator_watchlist"])

    def test_true_sample_growth_and_original_time(self):
        x=video("AAAAAAAAAAA","Zaitoon Se Bana Kaaba AI Transformation","UCone",views=130000)
        r=emerging.build(state({"a":x}),NOW)
        self.assertEqual(len(r["high_velocity_single_creator_watchlist"]),1)
        lead=r["high_velocity_single_creator_watchlist"][0]
        self.assertEqual(lead["observed_growth_per_hour"],2500.0)
        self.assertIn("早期观察",lead["view_tier"])
        self.assertEqual(lead["first_seen_at"],FIRST)
        self.assertEqual(lead["published_at"],PUBLISHED)

    def test_stale_or_failed_scan_must_not_claim_evidence(self):
        with self.assertRaisesRegex(ValueError,"No verified"):
            emerging.build({},NOW)
        with self.assertRaisesRegex(ValueError,"no successful"):
            emerging.build({"first_success_at":FIRST,"scans":[{"time":FIRST,"successful_queries":0}]},NOW)
        with self.assertRaisesRegex(ValueError,"stale"):
            emerging.build({"first_success_at":FIRST,
                           "scans":[{"time":"2026-10-20T12:00:00Z","successful_queries":8}]},NOW)

    def test_previous_observed_is_internal_only(self):
        a=video("AAAAAAAAAAA","KDA Firestarter Dance AI","UCone")
        b=video("BBBBBBBBBBB","KDA Firestarter Dance AI","UCtwo")
        old=video("CCCCCCCCCCC","KDA Firestarter Dance AI","UCold",
                  published="2026-10-21T10:00:00Z")
        r=emerging.build(state({"a":a,"b":b,"old":old}),NOW)
        item=next(x for x in r["cross_creator_groups"] if x["anchor"]=="kda firestarter")
        self.assertTrue(item["previously_observed_older_video"])
        self.assertEqual(item["video_count"],2)

    def test_bulk_cross_account_pasted_title_is_not_independent_imitation(self):
        title="Rocket Coconut Morph Effect AI #aigenerated"
        rows={
            "a":video("AAAAAAAAAAA",title,"UCone"),
            "b":video("BBBBBBBBBBB",title,"UCtwo"),
            "c":video("CCCCCCCCCCC",title,"UCthree"),
        }
        result=emerging.build(state(rows),NOW)
        matches=[g for g in result["cross_creator_groups"]
                 if g["anchor"]=="rocket coconut morph"]
        self.assertTrue(matches)
        self.assertEqual(matches[0]["classification"],"possible_reuploads")
        self.assertEqual(matches[0]["near_duplicate_caption_fraction"],1.0)
        self.assertLessEqual(matches[0]["priority_points_not_seo_score"],12)
        self.assertEqual(result["independent_claimed_and_same_action_candidates"],0)

    def test_jhinga_lala_is_old_even_with_cross_author_posts(self):
        a=video("AAAAAAAAAAA","Jhinga lala hu hu kaka dada mama #aivideo","UCone")
        b=video("BBBBBBBBBBB","Jhinga lala hu hu kaka dada mama #aishorts","UCtwo")
        result=emerging.build(state({"a":a,"b":b}),NOW)
        item=next(x for x in result["cross_creator_groups"]
                  if x["anchor"]=="jhinga lala hu hu")
        self.assertEqual(item["classification"],"known")
        self.assertEqual(item["priority_points_not_seo_score"],0)

    def test_shared_generic_non_ai_recipe_does_not_become_a_trend(self):
        a=video("AAAAAAAAAAA","Homemade Pizza Recipe","UCone",confidence="low")
        b=video("BBBBBBBBBBB","Homemade Pizza Sauce","UCtwo",confidence="medium")
        result=emerging.build(state({"a":a,"b":b}),NOW)
        self.assertEqual(result["shared_name_groups"],0)

    def test_identical_two_channel_headline_is_weak_not_confirmed_effect(self):
        title="Instagram New Profile Jump AI Video Trend #aivideo"
        a=video("AAAAAAAAAAA",title,"UCone",views=25)
        b=video("BBBBBBBBBBB",title,"UCtwo",views=4)
        result=emerging.build(state({"a":a,"b":b}),NOW)
        group=next(x for x in result["cross_creator_groups"]
                   if x["anchor"]=="profile jump")
        self.assertEqual(group["classification"],"possible_reuploads")
        self.assertLessEqual(group["priority_points_not_seo_score"],12)
        self.assertEqual(result["independent_claimed_and_same_action_candidates"],0)

    def test_hindi_howto_is_not_independent_ai_created_short(self):
        a=video("AAAAAAAAAAA","Instagram New Profile Jump AI Video Trend","UCone")
        b=video("BBBBBBBBBBB",
                "Instagram New Profile Jump AI Video Trend / अपनी फोटो से AI वीडियो कैसे बनाएं",
                "UCtwo")
        result=emerging.build(state({"a":a,"b":b}),NOW)
        self.assertEqual(result["shared_name_groups"],0)

    def test_a2o_lite_neon_already_has_competing_generator(self):
        a=video("AAAAAAAAAAA","A2O LITE NEON AI Dance","UCone")
        b=video("BBBBBBBBBBB","A2O LITE NEON AI Dance Cover","UCtwo")
        result=emerging.build(state({"a":a,"b":b}),NOW)
        group=next(x for x in result["cross_creator_groups"]
                   if x["anchor"]=="a2o lite neon")
        self.assertEqual(group["classification"],"known")
        self.assertEqual(group["priority_points_not_seo_score"],0)

    def test_report_json_persists_without_new_api_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"data").mkdir()
            (root/"data/state.json").write_text(
                json.dumps(state({"a":video("AAAAAAAAAAA","Zaitoon Se Bana Kaaba AI Transformation",views=130000)})),
                encoding="utf-8")
            result=emerging.run(root,NOW)
            self.assertEqual(result["confirmed_new_seo_keywords"],0)
            md=(root/"reports/emerging-latest.md").read_text(encoding="utf-8")
            self.assertIn("视频画面",md)
            self.assertIn("https://www.youtube.com/watch?v=AAAAAAAAAAA",md)
            self.assertTrue((root/"reports/emerging-latest.json").exists())
            self.assertTrue((root/"reports/2026-10-23-emerging.md").exists())


if __name__=="__main__":
    unittest.main()
