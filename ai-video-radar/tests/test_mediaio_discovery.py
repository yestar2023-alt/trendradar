"""Regression tests for Media.io discovery and listing-coverage migration."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest
from urllib import error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import radar

BASE = 'https://www.media.io'
OLD = BASE + '/ai/explore/zone/old-video-generator'
NEW = BASE + '/ai/explore/zone/closing-door-prank-ai-video-generator'
GALLERY = BASE + '/ai/viral-studio'
TREND_HUB = BASE + '/ai/explore/zone/ai-video-trend-generator'

def html_links(urls):
    return ('<html><body>' + ''.join(
        f'<a href="{url}">{url.rsplit("/",1)[-1]}</a>' for url in urls
    ) + '</body></html>').encode()

class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
    def fetch(self, url, **kwargs):
        if url not in self.pages:
            raise OSError('site unreachable')
        return self.pages[url]

def configuration(listings):
    return {
        'timezone': 'Asia/Shanghai',
        'sources': [{
            'id': 'mediaio',
            'name': 'Media.io',
            'base': BASE,
            'use_sitemap': False,
            'listings': listings,
            'path_patterns': ['/ai/explore/zone/', '/ai-'],
        }],
        'aliases': {},
        'max_detail_pages_per_run': 30,
    }

def pages(new=False, missing_old=False):
    p = {
        GALLERY: html_links([OLD, NEW] if new else [OLD]),
        OLD: b'<html><title>Old AI effect</title></html>',
        NEW: b'<html><title>Closing Door Prank AI</title></html>',
    }
    if not missing_old:
        p[BASE+'/video-effects/'] = html_links([OLD])
    return p

class MediaIODiscoveryTests(unittest.TestCase):
    def test_viral_studio_links_and_directory_exclusion(self):
        cfg = configuration(['/video-effects/', '/ai/viral-studio'])
        src = cfg['sources'][0]
        found, status, paths = radar.scan_listing(src, FakeFetcher(pages(new=True)))
        self.assertIn(OLD, found)
        self.assertIn(NEW, found)
        self.assertNotIn(TREND_HUB, found)
        self.assertNotIn(GALLERY, found)
        self.assertIn('2/2 listings', status)
        self.assertEqual(paths, src['listings'])

    def test_listing_expansion_rebaselines_once_then_reports_new_urls(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            one = configuration(['/video-effects/'])
            both = configuration(['/video-effects/', '/ai/viral-studio'])
            radar.run(root, one, FakeFetcher(pages()))
            second = radar.run(root, both, FakeFetcher(pages()))
            self.assertEqual(second['new_urls'], 0)
            state = radar.load_state(root/'data'/'state.json.gz')
            self.assertEqual(state['sites']['mediaio']['channels']['listing']['paths_ok'],
                             both['sources'][0]['listings'])
            third = radar.run(root, both, FakeFetcher(pages(new=True)))
            self.assertEqual(third['new_urls'], 1)
            raw = next((root/'reports').glob('*-all-new-urls.csv'))
            with raw.open(encoding='utf-8-sig', newline='') as h:
                self.assertIn(NEW, {r['url'] for r in csv.DictReader(h)})

    def test_existing_listing_failure_keeps_previous_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            both = configuration(['/video-effects/', '/ai/viral-studio'])
            radar.run(root, both, FakeFetcher(pages()))
            radar.run(root, both, FakeFetcher(pages(new=True, missing_old=True)))
            state = radar.load_state(root/'data'/'state.json.gz')
            urls = state['sites']['mediaio']['channels']['listing']['urls']
            self.assertNotIn(NEW, urls)
            with (root/'reports'/'health-latest.csv').open(
                encoding='utf-8-sig', newline=''
            ) as h:
                health = [r for r in csv.DictReader(h) if r['channel']=='listing'][0]
            self.assertEqual(health['status'], 'partial')

    def test_robots_http_status_reported_but_not_bypassed(self):
        fetcher = radar.Fetcher()
        err = error.HTTPError(BASE+'/robots.txt', 429, 'Too Many Requests', {}, None)
        with patch.object(fetcher, 'fetch', side_effect=err):
            with self.assertRaisesRegex(PermissionError, 'robots HTTP 429'):
                fetcher.can_fetch(BASE+'/ai/viral-studio')

if __name__ == '__main__':
    unittest.main()
