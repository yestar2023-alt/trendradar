import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opportunity_filter import build, assess, classify_result

TIME = "2026-11-13T08:00:00+00:00"

class OpportunityFilterTests(unittest.TestCase):
    def mock_graph(self):
        return {"nodes":{
            "roblox": {"keyword":"roblox","seed_type":"CURATED_ROOT","first_observed_at":TIME},
            "glorybound roblox codes":{"keyword":"glorybound roblox codes","depth":1,"first_observed_at":TIME},
            "what is phantom vibration syndrome":{"keyword":"what is phantom vibration syndrome","depth":1}
        }, "edges":[
            {"parent":"roblox","child":"glorybound roblox codes","type":"rising",
             "observed_at":TIME,"value":750,"formatted_value":"+750%"},
            {"parent":"roblox","child":"what is phantom vibration syndrome","type":"rising",
             "observed_at":TIME,"value":25350,"formatted_value":"Breakout"}]}

    def mock_ledger(self):
        return {"entities":{"guide-name:glorybound":{"entity_id":"guide-name:glorybound",
                "title":"Glorybound","sources":["PCGamesN"],
                "evidence":[{"url":"https://www.pcgamesn.com/roblox/glorybound-codes"}]}}}

    def test_all_graph_nodes_included_and_bad_breakout_rejected(self):
        rows = assess(self.mock_graph(), self.mock_ledger(), "game", TIME)
        self.assertEqual(len(rows), 3)
        main = next(x for x in rows if x["keyword"]=="glorybound roblox codes")
        bad = next(x for x in rows if "phantom" in x["keyword"])
        self.assertEqual(main["quality_status"], "HIGH_PRIORITY_RESEARCH")
        self.assertEqual(main["highest_rising_growth_pct"], 750)
        self.assertEqual(main["source_count"], 1)
        self.assertEqual(bad["quality_status"], "EXCLUDED_NOISE")
        self.assertEqual(bad["score"], 0)

    def test_ai_video_focus_excludes_generic_software_topics(self):
        g = {"nodes":{"ai dance generator":{"keyword":"ai dance generator"},
                      "ai guardrails in software":{"keyword":"ai guardrails in software"},
                      "î€ broken video text":{"keyword":"î€ broken video text"}},
             "edges":[{"parent":"ai dance","child":"ai dance generator","type":"rising",
                       "observed_at":TIME,"value":200,"formatted_value":"+200%"}]}
        rows = assess(g,{}, "ai", TIME)
        self.assertEqual(len(rows), 3)
        self.assertNotEqual(rows[0]["quality_status"], "EXCLUDED_NOISE")
        self.assertEqual(sum(x["quality_status"]=="EXCLUDED_NOISE" for x in rows),2)

    def test_serp_no_key_stays_explicitly_unverified(self):
        result, cache = build(self.mock_graph(), self.mock_ledger(),
                             vertical="game", now_iso=TIME, api_key="",max_calls=2)
        self.assertEqual(result["serp_summary"]["calls"],0)
        main = next(x for x in result["rows"] if x["keyword"]=="glorybound roblox codes")
        self.assertEqual(main["serp_status"],"NOT_CONFIGURED")
        self.assertEqual(main["decision"],"NOT_BUILD_APPROVED")
        self.assertEqual(result["total_nodes"],3)

    def test_verified_top10_requires_ten_rows_and_reuses_cache(self):
        calls=[]
        def provider(word, key):
            calls.append(word)
            return ([{"url":"https://example.org/guide","title":"Glorybound roblox codes",
                      "rank":1,"type":"GUIDE","focused":True}] +
                    [{"url":"https://example.org/page/"+str(i),"title":"Other page "+str(i),
                      "rank":i,"type":"OTHER","focused":False} for i in range(2,11)])
        a, cache=build(self.mock_graph(),self.mock_ledger(), vertical="game",
                       now_iso=TIME, api_key="TEST",max_calls=1,provider=provider)
        row=next(x for x in a["rows"] if x["keyword"]=="glorybound roblox codes")
        self.assertEqual(a["serp_summary"]["calls"],1)
        self.assertEqual(row["serp_status"],"VERIFIED_TOP10")
        self.assertEqual(row["serp"]["focused_specialized_results"],1)
        self.assertEqual(row["decision"],"EDITORIAL_RESEARCH_READY_NOT_DOMAIN_APPROVAL")
        b, cache=build(self.mock_graph(),self.mock_ledger(), vertical="game",
                       now_iso=TIME, api_key="",max_calls=0,cache=cache,provider=provider)
        self.assertEqual(b["serp_summary"]["calls"],0)
        self.assertEqual(next(x for x in b["rows"] if x["keyword"]=="glorybound roblox codes")["serp_status"],"VERIFIED_TOP10")
        self.assertEqual(len(calls),1)

    def test_partial_serp_is_not_verified(self):
        def tiny(word,key):
            return [{"title":"Only","url":"https://example.org","type":"OTHER","focused":False}]
        result,_=build(self.mock_graph(),self.mock_ledger(),vertical="game",
                       now_iso=TIME,api_key="test",max_calls=1,provider=tiny)
        row=next(x for x in result["rows"] if x["keyword"]=="glorybound roblox codes")
        self.assertEqual(row["serp_status"],"PARTIAL_RESULTS")
        self.assertEqual(row["decision"],"NOT_BUILD_APPROVED")

if __name__=="__main__":
    unittest.main()
