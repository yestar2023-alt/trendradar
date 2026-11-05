"""Dreamina source discovery regression tests."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import radar

BASE='https://dreamina.capcut.com'
TREND=BASE+'/ai-video/ai-trending'
HUB=BASE+'/ai-video'
DETAIL_1=BASE+'/ai-video/gas-station-dance-ai-trend'
DETAIL_2=BASE+'/ai-video/barca-giant-cushion-jump-ai-trend'

class FakeFetcher:
    def fetch(self,url,**kwargs):
        if url==TREND:
            return ('<html><a href="/ai-video/gas-station-dance-ai-trend">Gas Station Dance</a>'
                    '<a href="/ai-video/barca-giant-cushion-jump-ai-trend">Barca Giant Cushion Jump</a>'
                    '<a href="/ai-video/ai-trending">All trending</a>'
                    '<a href="/resource/trending-ai-video">Resources</a></html>').encode()
        if url==HUB:
            return ('<html><a href="/ai-video/gas-station-dance-ai-trend">Gas Station Dance</a></html>').encode()
        raise OSError('no page')

class DreaminaTests(unittest.TestCase):
    def setUp(self):
        config_path=Path(__file__).resolve().parents[1]/'config.json'
        cfg=json.loads(config_path.read_text(encoding='utf-8'))
        self.src=next(s for s in cfg['sources'] if s['id']=='dreamina')

    def test_dreamina_is_independent_from_capcut(self):
        self.assertEqual(self.src['base'],BASE)
        self.assertIn('/ai-video/ai-trending',self.src['listings'])
        self.assertTrue(radar.relevant(DETAIL_1,self.src))
        self.assertFalse(radar.relevant(TREND,self.src))
        self.assertFalse(radar.relevant(BASE+'/resource/trending-ai-video',self.src))
        self.assertFalse(radar.relevant('https://www.capcut.com/ai-video/example',self.src))

    def test_listings_find_details_not_hub(self):
        found,status,ok=radar.scan_listing(self.src,FakeFetcher())
        self.assertEqual(set(found),{DETAIL_1,DETAIL_2})
        self.assertEqual(len(ok),2)
        self.assertIn('2 links from 2/2 listings',status)

    def test_prioritize_trend_over_general_generator(self):
        generic=BASE+'/ai-video/ai-video-generator'
        changes={u:{'source_id':'dreamina','site':'Dreamina','url':u,'entry':{},'channel':'listing'}
                 for u in (generic,DETAIL_1,DETAIL_2)}
        selected=radar.balanced_candidates(changes,[self.src],2)
        self.assertEqual(set(u for u,_ in selected),{DETAIL_1,DETAIL_2})

if __name__=='__main__':
    unittest.main()
