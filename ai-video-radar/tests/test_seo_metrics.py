from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import seo_metrics


class SEOMetricsTests(unittest.TestCase):
    def test_correct_formulas(self):
        r = seo_metrics.calculate(seo_metrics.row_from_dict({
            'keyword': 'dance ai', 'volume': 120, 'allintitle': 12, 'kd': 20, 'cpc': 1.5}))
        self.assertEqual(r['kgr'], 0.1)
        self.assertEqual(r['ekgr'], 0.12)
        self.assertEqual(r['kdroi_score'], 8.57)
        self.assertEqual(r['status'], '指标齐全')

    def test_zero_volume_is_not_unknown(self):
        r = seo_metrics.calculate(seo_metrics.row_from_dict({
            'keyword': 'new ai trend', 'volume': 0, 'kd': 0, 'cpc': 0}))
        self.assertEqual(r['volume'], 0)
        self.assertIsNone(r['kgr'])
        self.assertEqual(r['kdroi_score'], 0)
        self.assertIn('KGR不可计算', r['status'])

    def test_missing_input_does_not_fabricate(self):
        r = seo_metrics.calculate(seo_metrics.row_from_dict({'keyword': 'viral ai'}))
        self.assertIsNone(r['volume'])
        self.assertIsNone(r['kgr'])
        self.assertIsNone(r['ekgr'])
        self.assertIsNone(r['kdroi_score'])
        self.assertEqual(r['status'], '等待真实数据')

    def test_ads_competition_not_mistaken_for_kd(self):
        r = seo_metrics.row_from_dict({'keyword': 'test', 'competition_index': 95,
                                        'volume': 120, 'allintitle': 12})
        self.assertIsNone(r['kd'])

    def test_csv_import_and_export(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'SEO_AUTO_FETCH': '0'}):
            root = Path(d)
            (root / 'data').mkdir()
            (root / 'data' / 'keyword_metrics.csv').write_text(
                'keyword,volume,allintitle,kd,cpc,source,checked_at,location,language\n'
                'Firestarter Dance AI,150,10,12,0.5,Ahrefs/manual,2026-10-23,US,en\n',
                encoding='utf-8')
            results = seo_metrics.enrich(['firestarter dance ai', 'missing trend'], root)
            self.assertEqual(results['firestarter dance ai']['volume'], 150)
            self.assertEqual(results['firestarter dance ai']['kgr'], 0.0667)
            self.assertIsNone(results['missing trend']['volume'])
            out = root / 'reports' / 'seo-latest.csv'
            seo_metrics.write_metrics_csv(out, results)
            self.assertIn('Ahrefs/manual', out.read_text(encoding='utf-8-sig'))

    def test_opt_in_paid_provider(self):
        cache = {}
        with patch.dict(os.environ, {'SEO_AUTO_FETCH': '0'}):
            self.assertEqual(seo_metrics.maybe_fetch_dataforseo(['test ai'], cache), {})
        with patch.dict(os.environ, {'SEO_AUTO_FETCH': '1'}, clear=True):
            self.assertEqual(seo_metrics.maybe_fetch_dataforseo(['test ai'], cache), {})


if __name__ == '__main__':
    unittest.main()
