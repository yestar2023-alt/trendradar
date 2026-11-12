import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trends_graph import ingest_seeds, evaluate


class TrendsGraphTests(unittest.TestCase):
    NOW = "2026-11-12T16:00:00+00:00"

    def test_all_seeds_preserved_without_explore_calls(self):
        ledger = {"entities": {str(i): {"title": "game " + str(i)}
                              for i in range(123)}}
        graph = {"nodes": {}, "edges": []}
        self.assertEqual(ingest_seeds(graph, ledger, self.NOW), 123)
        self.assertEqual(ingest_seeds(graph, ledger, self.NOW), 0)
        stats = evaluate(graph, self.NOW)
        self.assertEqual(stats["mode"], "DRY_RUN")
        self.assertEqual(stats["queued"], 123)

    def test_rising_top_parent_edges_and_depth(self):
        graph = {"nodes": {}, "edges": []}
        ingest_seeds(graph, {"keywords": {"ai dance": {"keyword": "ai dance"}}}, self.NOW)
        def fake(word, geo, timeframe):
            self.assertEqual((geo, timeframe), ("US", "now 7-d"))
            return {"related_queries": {"rising": [{"query": "dance style ai", "formatted_value": "Breakout"}],
                                        "top": [{"query": "ai dance generator", "value": 75}]},
                    "interest_over_time": [{"date": "2026-11-12", "value": 15}]}
        result = evaluate(graph, self.NOW, fake, max_queries=1)
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["new_terms"], 2)
        self.assertEqual(len(graph["edges"]), 2)
        self.assertEqual(graph["nodes"]["dance style ai"]["depth"], 1)
        self.assertEqual(graph["nodes"]["ai dance"]["status"], "CHECKED")
        self.assertEqual(len(graph["nodes"]["ai dance"]["interest_over_time"]), 1)

    def test_rate_limit_stops_without_fabricated_success(self):
        graph = {"nodes": {}, "edges": []}
        ingest_seeds(graph, {"entities": {str(i): {"title": "Game " + str(i)} for i in range(5)}}, self.NOW)
        class RateLimitError(Exception):
            pass
        calls = []
        def blocked(word, *_):
            calls.append(word)
            raise RateLimitError("HTTP 429")
        res = evaluate(graph, self.NOW, blocked, max_queries=5)
        self.assertEqual(res["attempted"], 1)
        self.assertEqual(res["success"], 0)
        self.assertTrue(res["rate_limited"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(x["status"] == "RATE_LIMITED" for x in graph["nodes"].values()), 1)


if __name__ == "__main__":
    unittest.main()
