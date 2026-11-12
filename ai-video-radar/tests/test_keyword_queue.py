import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keyword_queue import build, canonical, classify


class KeywordQueueTests(unittest.TestCase):
    def test_canonical_uses_slug_not_marketing_title(self):
        self.assertEqual(canonical("https://www.makeviral.ai/templates/ai-pregnancy-reveal-trend"),
                         "ai pregnancy reveal trend")
        self.assertEqual(canonical("https://zooop.ai/templates/video/ice-ice-baby-duo"),
                         "ice ice baby duo")

    def test_full_url_coverage_beyond_top_thirty(self):
        rows = [{"url": "https://www.media.io/ai/explore/zone/trend-example-" + str(i),
                 "source": "Media.io", "url_type": "candidate_detail_url",
                 "first_observed_date": "2026-11-12"} for i in range(273)]
        result = build(rows, {}, "2026-11-12")
        self.assertEqual(result["unique_urls_in_batch"], 273)
        self.assertEqual(result["audited_url_rows"], 273)
        self.assertEqual(result["unique_keywords_in_ledger"], 273)
        self.assertEqual(result["pending_trends"], 273)

    def test_create_url_audited_but_not_promoted(self):
        rows = [{"url": "https://www.media.io/create/123", "source": "Media.io",
                 "url_type": "create_flow"}]
        result = build(rows, {}, "2026-11-12")
        self.assertEqual(result["unique_urls_in_batch"], 1)
        self.assertEqual(result["unique_keywords_in_ledger"], 0)
        self.assertEqual(result["audits"][0]["status"], "NOT_KEYWORD_CREATE_OR_NAV")

    def test_multi_source_and_previous_review_preserved(self):
        a = [{"url": "https://www.media.io/ai/explore/zone/dance-today",
              "source": "Media.io", "first_observed_date": "2026-11-10"}]
        first = build(a, {}, "2026-11-10")
        first["keywords"]["dance today"]["trends_status"] = "VERIFIED"
        b = [{"url": "https://www.makeviral.ai/templates/dance-today",
              "source": "MakeViral", "first_observed_date": "2026-11-12"}]
        second = build(b, first, "2026-11-12")
        self.assertEqual(len(second["keywords"]["dance today"]["sources"]), 2)
        self.assertEqual(second["keywords"]["dance today"]["trends_status"], "VERIFIED")
        self.assertEqual(second["keywords"]["dance today"]["first_observed_date"], "2026-11-10")

    def test_ambiguous_long_name_not_overclaimed(self):
        status, _ = classify({"url": "https://example.org/blog/a-very-long-phrase-that-reads-like-a-full-sentence-and-not-a-real-search-query-at-all"})
        self.assertEqual(status, "PENDING_NAME_REVIEW")


if __name__ == "__main__":
    unittest.main()
