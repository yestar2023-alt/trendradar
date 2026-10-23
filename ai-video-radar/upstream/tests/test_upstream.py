import sys, unittest, tempfile, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import upstream

def fake_feed(ids):
    ns='http://www.w3.org/2005/Atom'
    yt='http://www.youtube.com/xml/schemas/2015'
    entries=''.join('<entry><yt:videoId>'+vid+'</yt:videoId><title>Test</title><published>2026-10-20T00:00:00Z</published></entry>' for vid in ids)
    return ('<feed xmlns="'+ns+'" xmlns:yt="'+yt+'">'+entries+'</feed>').encode()

class TestPilot(unittest.TestCase):
    def setUp(self):
        self.conf={'channels':[{'id':'test','name':'Test','channel_id':'UC2t5bjwHdUX4vM2g8TRDq5g'}]}
    def test_parse(self):
        self.assertEqual(len(upstream.parse_feed(fake_feed(['abcdefghijk','bad']))),1)
    def test_baseline_and_delta(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.assertEqual(upstream.run(root,self.conf,lambda _: upstream.parse_feed(fake_feed(['abcdefghijk'])),'2026-10-20T00:00:00+00:00'),1)
            self.assertIn('无已确认新增',(root/'reports/latest.md').read_text())
            upstream.run(root,self.conf,lambda _: upstream.parse_feed(fake_feed(['abcdefghijk','12345678901'])),'2026-10-20T02:00:00+00:00')
            self.assertIn('12345678901',(root/'reports/latest.md').read_text())
    def test_failure_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            upstream.run(root,self.conf,lambda _: upstream.parse_feed(fake_feed(['abcdefghijk'])))
            def fail(_): raise OSError('offline')
            self.assertEqual(upstream.run(root,self.conf,fail),0)
            state=json.loads((root/'data/state.json').read_text())
            self.assertEqual(state['sources']['test']['ids'],['abcdefghijk'])
            self.assertIn('不能确认今日新增',(root/'reports/latest.md').read_text())
if __name__=='__main__': unittest.main()
