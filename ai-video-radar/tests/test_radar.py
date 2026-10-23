import gzip
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import radar

BASE='https://example.test'
SRC={'id':'example','name':'Example','base':BASE,'listings':['/templates'], 'path_patterns':['/templates/']}
CFG={'timezone':'Asia/Shanghai','max_sitemaps_per_site':12,'max_urls_per_site':100,'max_detail_pages_per_run':20,'sources':[SRC],'aliases':{}}


def xml_urlset(urls):
    return ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{u}</loc><lastmod>2026-10-21</lastmod></url>' for u in urls)+'</urlset>').encode()


def xml_index(urls):
    return ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<sitemap><loc>{u}</loc></sitemap>' for u in urls)+'</sitemapindex>').encode()


class FakeFetcher:
    def __init__(self, pages): self.pages=pages
    def fetch(self,url,**kw):
        if url not in self.pages: raise OSError('not available')
        v=self.pages[url]
        if isinstance(v,Exception): raise v
        return v


def pages(urls):
    p={
        BASE+'/robots.txt':b'User-agent: *\nAllow: /\nSitemap: https://example.test/index.xml',
        BASE+'/index.xml':xml_index([BASE+'/part-1.xml',BASE+'/part-2.xml']),
        BASE+'/part-1.xml':xml_urlset(urls[:1]),
        BASE+'/part-2.xml':gzip.compress(xml_urlset(urls[1:])),
        BASE+'/templates':('<html>'+''.join(f'<a href="{url}">{url.split("/")[-1]}</a>' for url in urls)+'</html>').encode(),
    }
    p.update({url: ('<html><head><title>'+url.split('/')[-1].replace('-',' ')+' - Example</title></head><body></body></html>').encode() for url in urls})
    return p

class RadarTests(unittest.TestCase):
    def test_parse_namespaced_and_gzip(self):
        blob=gzip.compress(xml_urlset([BASE+'/templates/a']))
        typ,items=radar.parse_xml_urls(blob)
        self.assertEqual(typ,'urlset');self.assertEqual(items[0]['lastmod'],'2026-10-21')
    def test_empty_first_is_baseline_not_new(self):
        a=[BASE+'/templates/dance-one']
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            radar.run(root,CFG,FakeFetcher(pages(a)))
            report=(root/'reports'/'latest.md').read_text()
            self.assertIn('今日无已确认新增关键词',report)
            self.assertIn('新 URL：0 条',report)
            state=radar.load_state(root/'data'/'state.json.gz')
            self.assertEqual(len(state['sites']['example']['channels']['sitemap']['urls']),1)
            radar.run(root,CFG,FakeFetcher(pages(a)))
            self.assertIn('新 URL：0 条',(root/'reports'/'latest.md').read_text())
            b=a+[BASE+'/templates/new-cartoon-dance']
            m=radar.run(root,CFG,FakeFetcher(pages(b)))
            self.assertEqual(m['new_urls'],1)
            self.assertIn('new cartoon dance',(root/'reports'/'latest.md').read_text())
    def test_partial_sitemap_keeps_old_state(self):
        a=[BASE+'/templates/dance-one']
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            radar.run(root,CFG,FakeFetcher(pages(a)))
            bad=pages(a)
            bad.pop(BASE+'/part-2.xml')
            result=radar.run(root,CFG,FakeFetcher(bad))
            self.assertEqual(result['new_urls'],0)
            state=radar.load_state(root/'data'/'state.json.gz')
            self.assertEqual(len(state['sites']['example']['channels']['sitemap']['urls']),1)
    def test_listing_fallback_with_no_sitemap(self):
        src={**SRC,'use_sitemap':False}
        cfg={**CFG,'sources':[src]}
        one=pages([BASE+'/templates/one'])
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            radar.run(root,cfg,FakeFetcher(one))
            r=radar.run(root,cfg,FakeFetcher(pages([BASE+'/templates/one',BASE+'/templates/two'])))
            self.assertEqual(r['new_urls'],1)
    def test_seo_keyword_from_page_title(self):
        self.assertEqual(
            radar.seo_query('firestarter dance ai do the kda chorus from one photo',
                            'Firestarter Dance AI: Do the KDA Chorus From One Photo'),
            'firestarter dance ai')
        self.assertEqual(radar.seo_query('capcut kanne', 'CapCut template: Kanne Kanmaniye'),
                         'capcut kanne')

    def test_repeat_run_does_not_erase_daily_csv(self):
        src={**SRC,'use_sitemap':False}
        cfg={**CFG,'sources':[src]}
        a=[BASE+'/templates/dance-one']
        b=a+[BASE+'/templates/firestarter-dance']
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            radar.run(root,cfg,FakeFetcher(pages(a)))
            radar.run(root,cfg,FakeFetcher(pages(b)))
            csv_file=next((root/'reports').glob('????-??-??.csv'))
            first=csv_file.read_text(encoding='utf-8-sig')
            self.assertIn('firestarter dance',first)
            radar.run(root,cfg,FakeFetcher(pages(b)))
            self.assertEqual(csv_file.read_text(encoding='utf-8-sig'),first)

    def test_clean_and_same_host_only(self):
        self.assertEqual(radar.clean_url(BASE+'/templates/test/?utm=1'),BASE+'/templates/test')
        self.assertFalse(radar.allowed_host('https://example.test.evil.org/index.xml',BASE))
        self.assertFalse(radar.relevant(BASE+'/login',SRC))

if __name__=='__main__': unittest.main()