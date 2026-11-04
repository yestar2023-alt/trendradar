"""Ensure that large sitemap sources cannot starve other websites."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import radar

class BalancedCandidateTests(unittest.TestCase):
    def test_round_robin_preserves_all_five_sources(self):
        names=['summrs','capcut','makeviral','zooop','mediaio']
        sources=[{'id':name,'name':name} for name in names]
        changes={}
        for sid in names:
            count=1500 if sid=='mediaio' else 12
            for n in range(count):
                if sid=='mediaio':
                    url=f'https://www.media.io/ai/explore/zone/effect-{n:04d}'
                else:
                    url=f'https://{sid}.test/templates/effect-{n:04d}'
                changes[url]={'site':sid,'source_id':sid,'url':url,'entry':{},'channel':'sitemap'}
        selected=radar.balanced_candidates(changes,sources,30)
        self.assertEqual(len(selected),30)
        self.assertEqual({sid:sum(item['source_id']==sid for _,item in selected) for sid in names},
                         {sid:6 for sid in names})

    def test_prioritize_mediaio_effects_not_prompts_and_exclude_create(self):
        sources=[{'id':'mediaio','name':'Media.io'}]
        urls=['https://www.media.io/ai-prompts/a.html',
              'https://www.media.io/ai/explore/zone/xyz',
              'https://www.media.io/ai/explore/zone/foo/create']
        changes={u:{'source_id':'mediaio','site':'Media.io','url':u,'entry':{},'channel':'sitemap'} for u in urls}
        selected=radar.balanced_candidates(changes,sources,2)
        self.assertEqual([u for u,_ in selected],urls[:2][::-1])

    def test_mediaio_video_detail_beats_old_photo_prompt(self):
        source=[{'id':'mediaio','name':'Media.io'}]
        urls=[
            'https://www.media.io/ai/explore/zone/14-august-ai-photo-prompts',
            'https://www.media.io/ai/explore/zone/ai-dog-dance-video-generator',
            'https://www.media.io/ai/explore/zone/closing-door-prank-ai-video',
            'https://www.media.io/ai/explore/zone/birthday-car-video-trend',
        ]
        changes={url:{'source_id':'mediaio','site':'Media.io','url':url,'entry':{},'channel':'sitemap'} for url in urls}
        selected=radar.balanced_candidates(changes,source,3)
        self.assertNotIn(urls[0], [url for url,_ in selected])
        self.assertEqual(len(selected),3)

    def test_archive_retains_source_and_does_not_invent_new_records(self):
        sources=[{'id':'zooop','name':'Zooop'}, {'id':'mediaio','name':'Media.io'}]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            root.joinpath('reports').mkdir()
            p=root/'reports'/'2026-11-04-all-new-urls.csv'
            with p.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.writer(f)
                w.writerow(['first_observed_date','source','url','channel','source_listing_title'])
                w.writerow(['2026-11-04','Zooop','https://zooop.ai/blog/new-a','sitemap',''])
                w.writerow(['2026-11-04','Media.io','https://www.media.io/ai/explore/zone/new-b','sitemap',''])
                w.writerow(['2026-11-03','Unknown','https://other.test/page','sitemap',''])
            found=radar.read_daily_url_candidates(root,'2026-11-04',sources)
            self.assertEqual(len(found),2)
            selected=radar.balanced_candidates(found,sources,2)
            self.assertEqual({x['source_id'] for _,x in selected},{'zooop','mediaio'})
            self.assertEqual(radar.read_daily_url_candidates(root,'2026-11-05',sources),{})

if __name__=='__main__':
    unittest.main()
