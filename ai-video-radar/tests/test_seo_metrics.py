from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import seo_metrics


class SEOMetricsTests(unittest.TestCase):
    def test_exact_image_formulas(self):
        data = seo_metrics.row_from_dict({'keyword': 'dance ai', 'volume': 120,
            'daily_volume': 20, 'intitle': 12, 'kd': 20, 'required_backlinks': 2})
        result = seo_metrics.calculate(data)
        self.assertEqual(result['kgr'], 0.1)
        self.assertEqual(result['ekgr'], 0.12)
        self.assertEqual(result['kdroi_pct'], 265.0)
        self.assertEqual(result['backlinks_basis'], '直接提供')

    def test_daily_volume_derived_explicitly_from_monthly(self):
        result = seo_metrics.calculate(seo_metrics.row_from_dict({
            'keyword': 'new ai', 'volume': 120, 'intitle': 6, 'kd': 10,
            'required_backlinks': 2}))
        self.assertEqual(result['daily_volume_basis'], '由月均量×12/365推算')
        self.assertAlmostEqual(result['daily_volume'], 120 * 12 / 365, places=4)
        self.assertEqual(result['kdroi_pct'], -28.0)

    def test_kd_backlink_estimate_only_if_opted_in(self):
        data = seo_metrics.row_from_dict({'keyword': 'sample', 'volume': 500,
                                           'intitle': 10, 'kd': 20})
        a = seo_metrics.calculate(data)
        self.assertIsNone(a['kdroi_pct'])
        self.assertIsNone(a['required_backlinks'])
        b = seo_metrics.calculate(data, estimate_backlinks=True)
        self.assertEqual(b['required_backlinks'], 4)
        self.assertEqual(b['kdroi_pct'], 50.0)
        self.assertIn('估算', b['backlinks_basis'])
        self.assertIn('估算', b['status'])

    def test_old_allintitle_not_reused_as_intitle(self):
        data = seo_metrics.row_from_dict({'keyword': 'sample', 'volume': 100,
                                          'allintitle': 3, 'kd': 10, 'cpc': 0.7})
        result = seo_metrics.calculate(data)
        self.assertIsNone(result['intitle'])
        self.assertIsNone(result['kgr'])
        self.assertIsNone(result['ekgr'])
        self.assertIsNone(result['kdroi_pct'])

    def test_zero_denominators_and_invalid_data(self):
        x = seo_metrics.calculate(seo_metrics.row_from_dict({
            'keyword': 'bad', 'volume': 0, 'intitle': 10, 'kd': 101,
            'required_backlinks': 0}))
        self.assertIsNone(x['kgr'])
        self.assertIsNone(x['ekgr'])
        self.assertIsNone(x['kdroi_pct'])
        self.assertIsNone(x['kd'])
        y = seo_metrics.calculate(seo_metrics.row_from_dict({
            'keyword': 'negative', 'volume': -5, 'intitle': -10,
            'daily_volume': -20, 'required_backlinks': -2}))
        self.assertIsNone(y['volume'])
        self.assertIsNone(y['kdroi_pct'])

    def test_missing_inputs_stay_missing(self):
        r = seo_metrics.calculate(seo_metrics.row_from_dict({'keyword': 'viral ai'}))
        self.assertIsNone(r['kgr'])
        self.assertIsNone(r['ekgr'])
        self.assertIsNone(r['kdroi_pct'])
        self.assertEqual(r['status'], '等待真实数据')

    def test_manual_import_and_export(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SEO_AUTO_FETCH': '0'}, clear=True):
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data' / 'keyword_metrics.csv').write_text(
                'keyword,volume,daily_volume,intitle,kd,required_backlinks,source,checked_at,location,language\n'
                'Firestarter Dance AI,150,5,10,12,2,manual,2026-10-23,US,en\n', encoding='utf-8')
            rows = seo_metrics.enrich(['firestarter dance ai', 'missing trend'], root)
            self.assertEqual(rows['firestarter dance ai']['kgr'], 0.0667)
            self.assertEqual(rows['firestarter dance ai']['kdroi_pct'], -8.75)
            self.assertIsNone(rows['missing trend']['volume'])
            dest = root / 'reports' / 'seo-latest.csv'
            seo_metrics.write_metrics_csv(dest, rows)
            text = dest.read_text(encoding='utf-8-sig')
            self.assertIn('kdroi_pct', text)
            self.assertIn('intitle', text)
            self.assertNotIn('kdroi_score', text)

    def test_partial_manual_row_adds_backlink_count_to_api_cache(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SEO_AUTO_FETCH': '0'}, clear=True):
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data' / 'seo_metrics_cache.json').write_text(
                '{"dance ai":{"keyword":"dance ai","volume":200,"intitle":5,"kd":20,"source":"API"}}',
                encoding='utf-8')
            (root / 'data' / 'keyword_metrics.csv').write_text(
                'keyword,required_backlinks\ndance ai,4\n', encoding='utf-8')
            r = seo_metrics.enrich(['dance ai'], root)['dance ai']
            self.assertEqual(r['kgr'], 0.025)
            self.assertEqual(r['required_backlinks'], 4)
            self.assertEqual(r['kdroi_pct'], -40.0)

    def test_ads_competition_not_organic_kd(self):
        r = seo_metrics.row_from_dict({'keyword':'test','competition_index':95,'volume':100})
        self.assertIsNone(r['kd'])

    def test_paid_api_opt_in_only_and_intitle_query_correct(self):
        with patch.dict(os.environ, {'SEO_AUTO_FETCH': '0'}, clear=True):
            self.assertEqual(seo_metrics.maybe_fetch_dataforseo(['dance ai'], {}), {})
        with patch.dict(os.environ, {'SEO_AUTO_FETCH': '1'}, clear=True):
            self.assertEqual(seo_metrics.maybe_fetch_dataforseo(['dance ai'], {}), {})
        captured = []
        def fake(endpoint, params, login, password):
            captured.append((endpoint,params))
            if 'keyword_overview' in endpoint:
                return [{'items':[{'keyword':'dance ai', 'keyword_info':{'search_volume':300},
                                   'keyword_properties':{'keyword_difficulty':15}}]}]
            return [{'se_results_count':6}]
        with patch.dict(os.environ, {'SEO_AUTO_FETCH':'1','SEO_FETCH_INTITLE':'1',
                   'DATAFORSEO_LOGIN':'test', 'DATAFORSEO_PASSWORD':'test'}, clear=True), \
             patch.object(seo_metrics, '_request_dfseo', side_effect=fake):
            value=seo_metrics.maybe_fetch_dataforseo(['dance ai'], {})
        self.assertEqual(value['dance ai']['intitle'], 6)
        self.assertEqual(value['dance ai']['volume'], 300)
        self.assertEqual(captured[1][1]['keyword'], 'intitle:"dance ai"')


if __name__ == '__main__':
    unittest.main()
