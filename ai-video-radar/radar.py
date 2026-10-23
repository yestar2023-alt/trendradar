#!/usr/bin/env python3
"""AI video keyword discovery: auditable daily URL delta, not a popularity oracle.

Python stdlib only. Run with: python radar.py --root .
"""
from __future__ import annotations

import argparse
import csv
import gzip
import html
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone
from urllib import error, parse, request, robotparser
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
from seo_metrics import enrich, fmt, write_metrics_csv

AGENT = 'AIVideoKeywordRadar/1.0 (+read-only; daily site-monitoring)'
SKIP_EXT = ('.png','.jpg','.jpeg','.gif','.webp','.svg','.css','.js','.woff','.woff2','.pdf','.mp4','.webm','.ico','.map','.xml','.gz','.json','.txt')
NOISE = {'en', 'zh', 'es', 'ko', 'ru', 'fr', 'blog', 'templates', 'video', 'effects', 'new', 'trending', 'viral', 'all', 'discover'}


def clean_url(url: str) -> str:
    p = parse.urlsplit(url)
    path = re.sub(r'/+', '/', p.path)
    path = path.rstrip('/') or '/'
    # Treat tracking parameters as the same URL. Video template IDs are generally in path.
    return parse.urlunsplit((p.scheme.lower(), p.netloc.lower(),path,'',''))


def allowed_host(url: str, base: str) -> bool:
    """Only same host and www alias; never fetch sitemap-advertised third-party hosts."""
    h = parse.urlsplit(url).hostname or ''
    b = parse.urlsplit(base).hostname or ''
    return h.removeprefix('www.') == b.removeprefix('www.') and parse.urlsplit(url).scheme in ('https','http')


def relevant(url: str, src: dict) -> bool:
    p = parse.urlsplit(url)
    path = parse.unquote(p.path).lower()
    if not allowed_host(url, src['base']) or path.endswith(SKIP_EXT): return False
    if path.rstrip('/') in ('', '/blog', '/templates', '/video-effects', '/effects', '/meme', '/viral', '/apps/trending-templates', '/explore/latest-trend'): return False
    if any(a in path for a in ('/login','/signin','/signup','/dashboard','/account','/pricing','/terms','/privacy','/api/','/docs/')): return False
    return any(path.startswith(pattern) for pattern in src['path_patterns'])


class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.a = None
        self.results = {}
        self.in_title = False
        self.title = ''
        self.og_title = ''
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == 'a' and d.get('href'):
            self.a = [d['href'],[]]
        if tag == 'title': self.in_title = True
        if tag == 'meta' and d.get('property') in ('og:title','twitter:title'):
            self.og_title = d.get('content','')
    def handle_data(self, d):
        if self.a: self.a[1].append(d)
        if self.in_title: self.title += d
    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False
        if tag == 'a' and self.a:
            url, parts = self.a
            title = ' '.join(''.join(parts).split())[:180]
            if url not in self.results or len(title) > len(self.results[url]): self.results[url] = title
            self.a = None


def parse_xml_urls(blob: bytes):
    """Parse XML sitemap-index or urlset, including namespaced XML."""
    if blob[:2] == b'\x1f\x8b': blob = gzip.decompress(blob)
    if len(blob) > 45_000_000: raise ValueError('uncompressed sitemap too large')
    root = ET.fromstring(blob)
    typ = root.tag.rsplit('}',1)[-1]
    if typ not in ('sitemapindex','urlset'): raise ValueError('not a sitemap XML document')
    out = []
    expected = 'sitemap' if typ == 'sitemapindex' else 'url'
    for el in root:
        if el.tag.rsplit('}',1)[-1] != expected: continue
        record = {}
        for child in el:
            key = child.tag.rsplit('}',1)[-1]
            if key in ('loc','lastmod'): record[key] = (child.text or '').strip()
        if record.get('loc'): out.append(record)
    return typ, out


class Fetcher:
    def __init__(self, timeout=16, delay=.3):
        self.timeout=timeout; self.delay=delay
        self.last_by_host = {}
        self.robots = {}
    def fetch(self, url: str, *, max_bytes=20_000_000, for_robots=False) -> bytes:
        host = parse.urlsplit(url).netloc
        remaining = self.delay-(time.monotonic()-self.last_by_host.get(host,0))
        if remaining>0: time.sleep(remaining)
        self.last_by_host[host]=time.monotonic()
        if not for_robots and not self.can_fetch(url): raise PermissionError('robots.txt disallows URL')
        q=request.Request(url,headers={'User-Agent':AGENT,'Accept':'application/xml,text/xml,text/html,*/*;q=0.5','Accept-Encoding':'gzip'})
        with request.urlopen(q, timeout=self.timeout) as resp:
            # restrict redirects to the original host family
            if resp.geturl() and not allowed_host(resp.geturl(), 'https://'+host): raise ValueError('redirect to foreign host')
            size = resp.read(max_bytes+1)
            if len(size)>max_bytes: raise ValueError('response exceeded safety limit')
            if resp.headers.get('Content-Encoding') == 'gzip': size = gzip.decompress(size)
            return size
    def can_fetch(self,url:str) -> bool:
        base = parse.urlsplit(url)
        key=base.scheme+'://'+base.netloc
        if key not in self.robots:
            rp=robotparser.RobotFileParser()
            try:
                blob=self.fetch(key+'/robots.txt',max_bytes=200_000,for_robots=True)
                rp.parse(blob.decode('utf-8','replace').splitlines()); self.robots[key]=rp
            except error.HTTPError as e:
                if e.code == 404: self.robots[key]=None
                else: self.robots[key]='unavailable'
            except Exception:
                self.robots[key]='unavailable'
        value=self.robots[key]
        # Unknown robots status -> no bulk crawling; fail closed rather than evade restriction.
        if value=='unavailable': raise PermissionError('robots.txt not accessible (fail closed)')
        return True if value is None else value.can_fetch(AGENT,url)


def discover_robots_sitemaps(fetcher, base):
    url = base.rstrip('/')+'/robots.txt'
    try:
        data=fetcher.fetch(url,for_robots=True,max_bytes=200_000).decode('utf-8','replace')
    except Exception: return []
    return [m.group(1).strip() for line in data.splitlines() if (m:=re.match(r'^\s*Sitemap\s*:\s*(https?://\S+)',line,re.I))]


def scan_sitemap(src, fetcher, config):
    """Discover XML sitemaps. Missing children invalidate snapshot; missing guesses do not."""
    if not src.get('use_sitemap', True):
        return None, 'not a sitemap-based feed'
    base = src['base']; declared = discover_robots_sitemaps(fetcher, base)
    defaults = [base.rstrip('/') + p for p in ('/sitemap.xml', '/sitemap_index.xml', '/sitemap-index.xml')]
    # Try declared ones first; fallback if none are accessible.
    roots = declared if declared else defaults
    last_error = ''; children = 0
    for initial in (roots, defaults) if declared else (roots,):
        queue = list(dict.fromkeys(initial)); visited = set(); urls = {}; found_root = False
        missing_child = False
        while queue:
            url, is_child = queue.pop(0) if isinstance(queue[0], tuple) else (queue.pop(0), False)
            if url in visited or not allowed_host(url, base): continue
            visited.add(url); children += 1
            if children > config['max_sitemaps_per_site']:
                missing_child=True;last_error='sitemap document cap reached';break
            try:
                typ, records = parse_xml_urls(fetcher.fetch(url))
            except Exception as exc:
                last_error=f'{type(exc).__name__}: {str(exc)[:110]}'
                if is_child or (declared and initial is roots): missing_child=True
                continue
            found_root=True
            if typ == 'sitemapindex':
                queue.extend((r['loc'],True) for r in records if allowed_host(r['loc'],base))
            else:
                for r in records:
                    u=clean_url(r['loc'])
                    if relevant(u,src): urls[u]={'lastmod':r.get('lastmod','')}
                if len(urls)>config['max_urls_per_site']:
                    missing_child=True;last_error='URL cap reached';break
        if found_root:
            if missing_child: return None,'partial sitemap, snapshot not updated: '+last_error
            return urls,f'{len(urls)} relevant URLs in sitemap'
    return None,'no accessible sitemap: '+last_error


def scan_listing(src, fetcher):
    found={}; successful=[]; errors=[]
    for path in src.get('listings', []):
        url=parse.urljoin(src['base'],path)
        try:
            page=fetcher.fetch(url,max_bytes=5_000_000).decode('utf-8','replace')
            parser=AnchorParser();parser.feed(page)
            for href, text in parser.results.items():
                abs_url=clean_url(parse.urljoin(url,href))
                if relevant(abs_url,src) and abs_url not in found:
                    found[abs_url]={'label':text}
            successful.append(path)
        except Exception as exc:
            errors.append(f'{path}: {type(exc).__name__}: {str(exc)[:100]}')
    if not successful: return None,'unavailable: '+'; '.join(errors[:2]),[]
    if len(found)<1: return None,'no server-rendered template links (possibly JS/login)',successful
    status=f'{len(found)} links from {len(successful)}/{len(src.get("listings",[]))} listings'
    if errors: status += '; inaccessible: '+', '.join(x.split(':')[0] for x in errors[:3])
    return found,status,successful


def canonical_topic(title, url, aliases):
    """Conservative matching: normalize punctuation and known synonyms, do NOT merge loosely related dances."""
    slug = parse.unquote(parse.urlsplit(url).path.strip('/').split('/')[-1])
    label=html.unescape(title or '')
    if not label or len(label)<4 or label.lower() in {'view','try now','try it','start','generate','learn more','read more'}:
        label=slug
    label=re.sub(r'\s*\|.*$', '',label).strip()
    label=re.sub(r'\b(?:how to make|free online|generator|template|tutorial)\b', ' ',label,flags=re.I)
    label=re.sub(r'[^\w\u00c0-\u024f\u4e00-\u9fff]+',' ',label.replace('-', ' ')).lower()
    label=' '.join(label.split())
    if len(label)<4 or label in NOISE: label=slug.replace('-',' ')
    # use title only when short; website titles often contain large marketing phrases
    if len(label.split())>13: label=' '.join(re.sub(r'[-_]',' ',slug).split())
    return aliases.get(label,label)


def new_deltas(previous, current, site, channel):
    """Only positive changes for a previously successful channel; first run is baseline."""
    old=previous.get(site,{}).get('channels',{}).get(channel)
    if old is None: return [],'baseline'
    return sorted(set(current)-set(old.get('urls',{}))), 'delta'


def title_for_url(url, entry, fetcher):
    label=entry.get('label','')
    try:
        blob=fetcher.fetch(url,max_bytes=1_500_000)
        parser=AnchorParser(); parser.feed(blob.decode('utf-8','replace'))
        title=parser.og_title or parser.title or label
        if not title: raise ValueError('no readable page title')
        return html.unescape(title.strip()),True
    except Exception: return label or parse.unquote(url.split('/')[-1]).replace('-',' '),False


def save_json_atomic(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_suffix('.tmp')
    blob=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    with open(tmp,'wb') as f:
        with gzip.GzipFile(fileobj=f,mode='wb',mtime=0,filename='') as g: g.write(blob)
    tmp.replace(path)


def load_state(path: Path):
    if not path.exists(): return {'version':1,'sites':{},'first_seen_topics':{}}
    with gzip.open(path,'rt',encoding='utf-8') as f: return json.load(f)


def seo_query(topic, title):
    """Prefer the concise name BEFORE a descriptive marketing subtitle."""
    label = re.sub(r'^CapCut template\s*:\s*', '', title or '', flags=re.I).strip()
    if ':' in label:
        lead = label.split(':', 1)[0].strip()
        if 2 <= len(lead.split()) <= 8:
            return ' '.join(lead.casefold().split())
    return topic


def recent_seo_topics(root, candidates, max_topics=40):
    """Keep recently discovered opportunities visible after their first delta day."""
    recent = [seo_query(r['topic'], r['pages'][0].get('title', '') if r.get('pages') else '')
              for r in candidates]
    for p in sorted((root / 'reports').glob('????-??-??.csv'), reverse=True)[:7]:
        try:
            with p.open(encoding='utf-8-sig', newline='') as f:
                recent.extend(seo_query(r.get('topic', ''), r.get('title', ''))
                              for r in csv.DictReader(f))
        except (OSError, UnicodeError):
            continue
    unique = list(dict.fromkeys(t for t in recent if t))
    # Prefer AI-related queries for limited paid lookup slots; keep original source evidence.
    return sorted(unique, key=lambda s: (0 if 'ai' in s.casefold().split() else 1,
                                         unique.index(s)))[:max_topics]


def write_report(root, today, checks, candidates, meta, seo_rows=None):
    reports=root/'reports'; reports.mkdir(parents=True,exist_ok=True)
    lines=[f'# AI 视频新增词日报 | {today}（北京时间）','',f'- 本次完成检查：{meta["ok"]} 个频道；失败/不可用：{meta["bad"]} 个频道',f'- **有历史快照比对的新 URL：{meta["new_urls"]} 条**',f'- **需核实的新关键词候选：{len(candidates)} 个**','']
    if not candidates:
        lines+=['## 结论','', '**今日无已确认新增关键词。** 可能是本次属于首次建档，或目标网站没有可验证增量。','']
    else:
        lines+=['## 候选新词（基于 URL 差集，热度尚未核实）','', '| 首次发现 | 候选规范词 | 网站 | 新出现的链接 | 检测类型 |','|---|---|---|---|---|']
        for row in candidates:
            pages=row['pages'][:3]; example=pages[0]
            names=', '.join(dict.fromkeys(p['site'] for p in pages))
            link=' '.join(f'[页面{i+1}]({p["url"]})' for i,p in enumerate(pages))
            lines.append(f'| {row["first_seen"]} | {row["topic"].replace("|","/")} | {names} | {link} | {"进入 Sitemap" if example["channel"]=="sitemap" else "模板列表首次出现"} |')
        lines+=['','> 注意：这里的“新增”是自上次**成功快照**以来新增的 URL，不等于网页在当天发布；发现词 ≠ 已确认爆火。','','## 可点开的核查入口（供运营核实趋势和竞品）','']
        for row in candidates[:10]:
            keyword=row['topic']; q=parse.quote_plus(keyword)
            lines.append(f'- **{keyword}**： [TikTok](https://www.tiktok.com/search?q={q}) · [YouTube](https://www.youtube.com/results?search_query={q}) · [Google](https://www.google.com/search?q={q}) · [Google Trends](https://trends.google.com/trends/explore?q={q})')
        lines+=['','本期不输出未经验证的搜索量、视频播放数，也不为了凑足 Top 3 推荐旧词。','']
    lines += ['## SEO 指标复核（最近 7 份日报中的候选）', '',
              '> 指标来自导入文件或显式启用的第三方付费 API。— 代表未取得数据，不表示搜索量为 0。'
              ' KGR/EKGR 仅是选词参考，尤其不适合以月搜索量数据判断刚爆发的新词。',
              '> KDROI 是 \`月搜索量 × CPC ÷ (KD + 1)\` 的**机会分数**，不是投资回报率百分比；'
              ' 默认美国/英语 API 取数不等于全球搜索量。',
              '',
              '| 候选词 | 月量 | Allintitle | KD | CPC($) | KGR | EKGR | KDROI 分数 | 市场 | 来源 / 日期 | 数据状态 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|']
    if seo_rows:
        for keyword, m in seo_rows.items():
            market = str(m.get('location', '—')) + '/' + str(m.get('language', '—'))
            source = str(m.get('source', '—')) + ' / ' + str(m.get('checked_at', '—'))
            values = [keyword, fmt(m.get('volume')), fmt(m.get('allintitle')),
                      fmt(m.get('kd')), fmt(m.get('cpc')), fmt(m.get('kgr')),
                      fmt(m.get('ekgr')), fmt(m.get('kdroi_score')), market, source,
                      str(m.get('status', '—'))]
            lines.append('| ' + ' | '.join(str(x).replace('|','/').replace('\\n',' ') for x in values) + ' |')
    else:
        lines.append('| 暂无可复核候选 | — | — | — | — | — | — | — | — | — | — |')
    lines += ['','可通过 \`data/keyword_metrics.csv\` 导入真实数据。全自动付费取数需单独启用，未启用时不编造数字。','']
    lines+=['## 各站检查状态','', '| 来源 | Sitemap | 模板/榜单列表 |','|---|---|---|']
    for r in checks: lines.append(f'| {r["name"]} | {r["sitemap"].replace("|","/")} | {r["listing"].replace("|","/")} |')
    lines+=['','## 说明','', '首次成功抓取只建立基线，不产生新增词。部分网站是 JS 动态页面，HTML/Sitemap 可能不公开，失败会如实显示。Sitemap `lastmod` 仅作为修改时间参考，不作为发布日期。','']
    content='\n'.join(lines)
    (reports/(today+'.md')).write_text(content,encoding='utf-8')
    (reports/'latest.md').write_text(content,encoding='utf-8')
    # Do not erase the first discovery's historical CSV during another same-day run.
    # latest.md is still regenerated with this run's actual count.
    daily_csv = reports / (today + '.csv')
    if candidates or not daily_csv.exists():
        with daily_csv.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(['first_seen','topic','source','url','title','title_verified','channel','status'])
            for r in candidates:
                for page in r['pages']:
                    w.writerow([r['first_seen'],r['topic'],page['site'],page['url'],page['title'],page['title_verified'],page['channel'],'observed_new_since_previous_snapshot'])
    return content


def run(root, cfg, fetcher):
    local_now=datetime.now(ZoneInfo(cfg.get('timezone','Asia/Shanghai')))
    today=local_now.strftime('%Y-%m-%d')
    statefile=root/'data'/'state.json.gz'; state=load_state(statefile)
    state.setdefault('sites',{});state.setdefault('first_seen_topics',{})
    checks=[]; changes={}; new_count=0; ok=bad=0
    for site in cfg['sources']:
        sid=site['id']; current=state['sites'].setdefault(sid,{'channels':{}})
        sitemap, s_status=scan_sitemap(site,fetcher,cfg)
        listing, l_status, listing_paths=scan_listing(site,fetcher)
        for channel, result in [('sitemap',sitemap),('listing',listing)]:
            if result is None:
                bad+=1; continue
            ok+=1
            old_channel=current['channels'].get(channel)
            if channel=='listing' and old_channel and old_channel.get('paths_ok',[])!=listing_paths:
                bad+=1;ok-=1
                l_status += '; page set changed, delta skipped for safety'
                continue
            new_urls, reason=new_deltas({sid:current},result,sid,channel)
            if reason=='delta':
                for url in new_urls:
                    # same URL found in multiple channels => coalesce
                    changes.setdefault(url,{'site':site['name'],'url':url,'source_id':sid,'entry':result[url],'channel':channel})
            current['channels'][channel]={'urls':result,'checked_at':local_now.isoformat()}
            if channel=='listing': current['channels'][channel]['paths_ok']=listing_paths
        checks.append({'name':site['name'],'sitemap':s_status,'listing':l_status})
        print(f'{site["name"]}: sitemap={s_status}; listing={l_status}',flush=True)
    new_count=len(changes)
    candidates={}
    for url,item in list(changes.items())[:cfg.get('max_detail_pages_per_run',30)]:
        title,verified=title_for_url(url,item['entry'],fetcher)
        topic=canonical_topic(title,url,cfg.get('aliases',{}))
        if topic in NOISE or len(topic)<4: continue
        state['first_seen_topics'].setdefault(topic,today)
        r=candidates.setdefault(topic,{'topic':topic,'first_seen':state['first_seen_topics'][topic],'pages':[]})
        r['pages'].append({'site':item['site'],'url':url,'title':title,'title_verified':verified,'channel':item['channel']})
    save_json_atomic(statefile,state)
    meta={'new_urls':new_count,'ok':ok,'bad':bad}
    selected = recent_seo_topics(root, list(candidates.values()))
    seo_rows = enrich(selected, root)
    write_metrics_csv(root / 'reports' / (today + '-seo.csv'), seo_rows)
    write_metrics_csv(root / 'reports' / 'seo-latest.csv', seo_rows)
    result=write_report(root,today,checks,list(candidates.values()),meta,seo_rows)
    print('\n'+result[:4000],flush=True)
    return meta


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default=Path(__file__).parent);p.add_argument('--config',default='config.json')
    args=p.parse_args();root=Path(args.root).resolve()
    cfg=json.loads((root/args.config).read_text(encoding='utf-8'))
    return run(root,cfg,Fetcher(cfg['timeout_seconds'],cfg['delay_seconds']))

if __name__=='__main__': main()