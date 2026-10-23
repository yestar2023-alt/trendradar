#!/usr/bin/env python3
"""Verified SEO metrics for the AI Video Radar. Missing inputs stay missing.

CSV is always supported. Paid DataForSEO lookups are opt-in via env vars.
KGR/EKGR are screening heuristics, not Google ranking signals.
KDROI here means (monthly search volume * USD CPC) / (KD + 1), a score,
NOT a predicted financial return or percentage.
"""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import date
import json
import os
from pathlib import Path
from urllib import request

CSV_FIELDS = ['keyword', 'volume', 'allintitle', 'kd', 'cpc', 'source',
              'checked_at', 'location', 'language']
DISPLAY_FIELDS = CSV_FIELDS + ['kgr', 'ekgr', 'kdroi_score', 'status']
API_ROOT = 'https://api.dataforseo.com'

def norm(s):
    return ' '.join(str(s or '').casefold().split())

def numeric(v):
    if v is None or v == '' or str(v).strip().lower() in ('-', 'n/a', 'null', 'none'):
        return None
    try:
        n = float(str(v).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    if not (-1e12 < n < 1e12):
        return None
    return n

def row_from_dict(d):
    # Do not conflate Google Ads competition with organic SEO KD.
    aliases = {'volume': ('volume', 'search_volume', 'monthly_search_volume'),
               'allintitle': ('allintitle', 'allintitle_count'),
               'kd': ('kd', 'keyword_difficulty'),
               'cpc': ('cpc', 'cpc_usd')}
    d = {str(k).lstrip('\ufeff').strip().lower(): v for k, v in d.items()}
    out = {'keyword': str(d.get('keyword', d.get('topic', ''))).strip()}
    for key, names in aliases.items():
        out[key] = next((numeric(d[name]) for name in names if name in d), None)
    out.update(source=d.get('source') or 'manual_csv',
               checked_at=d.get('checked_at') or '未注明',
               location=d.get('location') or '未注明',
               language=d.get('language') or '未注明')
    return out

def calculate(row):
    a = dict(row)
    vol, count, kd, cpc = (numeric(a.get(x)) for x in ('volume', 'allintitle', 'kd', 'cpc'))
    if vol is not None and vol < 0: vol = None
    if count is not None and count < 0: count = None
    if kd is not None and not 0 <= kd <= 100: kd = None
    if cpc is not None and cpc < 0: cpc = None
    a.update(volume=vol, allintitle=count, kd=kd, cpc=cpc)
    a['kgr'] = round(count / vol, 4) if vol and count is not None else None
    a['ekgr'] = round(count * (1 + kd / 100) / vol, 4) if vol and count is not None and kd is not None else None
    a['kdroi_score'] = round(vol * cpc / (kd + 1), 2) if vol is not None and cpc is not None and kd is not None else None
    a['status'] = ('指标齐全' if all(a[x] is not None for x in ('kgr', 'ekgr', 'kdroi_score'))
                   else ('部分指标缺失' if any(a[x] is not None for x in ('volume', 'allintitle', 'kd', 'cpc'))
                         else '等待真实数据'))
    if vol == 0:
        a['status'] = '月搜索量为0/样本不足，KGR不可计算'
    return a

def read_csv_metrics(path):
    if not path.exists(): return {}
    with path.open(encoding='utf-8-sig', newline='') as f:
        data = list(csv.DictReader(f))
    return {norm(r['keyword']): r for d in data if (r := row_from_dict(d))['keyword']}

def read_cache(path):
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict): return {}
        return {norm(k): row_from_dict(v) for k, v in payload.items() if isinstance(v, dict)}
    except (OSError, json.JSONDecodeError):
        return {}

def save_cache(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def _request_dfseo(endpoint, task, login, password):
    body = json.dumps([task], ensure_ascii=False).encode('utf-8')
    token = base64.b64encode((login + ':' + password).encode()).decode()
    q = request.Request(API_ROOT + endpoint, data=body, method='POST',
                        headers={'Authorization': 'Basic ' + token,
                                 'Content-Type': 'application/json', 'User-Agent': 'AI-Video-Radar/1.2'})
    with request.urlopen(q, timeout=35) as response:
        data = json.load(response)
    if data.get('status_code') != 20000: raise RuntimeError('DataForSEO status ' + str(data.get('status_code')))
    tasks = data.get('tasks') or []
    if not tasks or tasks[0].get('status_code') != 20000:
        raise RuntimeError('DataForSEO task status ' + str(tasks[0].get('status_code') if tasks else 'none'))
    return tasks[0].get('result') or []

def maybe_fetch_dataforseo(keywords, cache):
    """Only paid when explicitly opted in. No scraping of Google HTML."""
    if os.getenv('SEO_AUTO_FETCH') != '1': return cache
    login, password = os.getenv('DATAFORSEO_LOGIN'), os.getenv('DATAFORSEO_PASSWORD')
    if not login or not password:
        print('SEO: 自动取数已启用，但缺少 DATAFORSEO_LOGIN/PASSWORD；跳过。')
        return cache
    cap = max(0, min(10, int(os.getenv('SEO_MAX_KEYWORDS_PER_RUN') or '3')))
    # Reuse cache. No automatic refetch of cached entries to avoid recurring charges.
    missing = [k for k in dict.fromkeys(keywords) if norm(k) not in cache and len(k) <= 80 and len(k.split()) <= 10][:cap]
    if not missing: return cache
    loc = os.getenv('SEO_LOCATION') or 'United States'
    language = os.getenv('SEO_LANGUAGE') or 'English'
    try:
        results = _request_dfseo('/v3/dataforseo_labs/google/keyword_overview/live',
                                 {'keywords': missing, 'location_name': loc, 'language_name': language},
                                 login, password)
        items = [i for r in results for i in (r.get('items') or [])]
        now = date.today().isoformat()
        for kw in missing:
            cache[norm(kw)] = row_from_dict({'keyword': kw, 'source': 'DataForSEO: 无可用数据',
                'checked_at': now, 'location': loc, 'language': language})
        for item in items:
            key = norm(item.get('keyword'))
            if not key or key not in [norm(k) for k in missing]: continue
            info, props = item.get('keyword_info') or {}, item.get('keyword_properties') or {}
            cache[key] = row_from_dict({'keyword': item.get('keyword'),
                'volume': info.get('search_volume'), 'cpc': info.get('cpc'),
                'kd': props.get('keyword_difficulty'), 'source': 'DataForSEO keyword_overview',
                'checked_at': now, 'location': loc, 'language': language})
        if os.getenv('SEO_FETCH_ALLINTITLE') == '1':
            for kw in missing:
                key = norm(kw)
                if key not in cache: continue
                try:
                    result = _request_dfseo('/v3/serp/google/organic/live/advanced',
                        {'keyword': 'allintitle:"' + kw.replace('"', '') + '"',
                         'location_name': loc, 'language_name': language},
                        login, password)
                    counts = [numeric(r.get('se_results_count')) for r in result]
                    if counts and counts[0] is not None and counts[0] >= 0:
                        cache[key]['allintitle'] = counts[0]
                        cache[key]['source'] += ' + Google SERP allintitle(estimated)'
                except Exception as exc:
                    print('SEO: allintitle 查询失败：' + str(exc)[:150])
        print('SEO: DataForSEO 取数完成 ' + str(len(items)) + ' 条；匹配市场 ' + loc + '/' + language)
    except Exception as exc:
        print('SEO: DataForSEO 失败，保留已有数据：' + str(exc)[:180])
    return cache

def enrich(keywords, root, *, fetch=True):
    root = Path(root)
    manual = read_csv_metrics(root / 'data' / 'keyword_metrics.csv')
    cache_path = root / 'data' / 'seo_metrics_cache.json'
    cache = read_cache(cache_path)
    if fetch and os.getenv('SEO_AUTO_FETCH') == '1':
        old = json.dumps(cache, sort_keys=True)
        cache = maybe_fetch_dataforseo(keywords, cache)
        if json.dumps(cache, sort_keys=True) != old: save_cache(cache_path, cache)
    out = {}
    for word in dict.fromkeys(keywords):
        key = norm(word)
        value = manual.get(key) or cache.get(key) or row_from_dict({'keyword': word, 'source': '尚无数据源'})
        value = dict(value, keyword=word)
        out[word] = calculate(value)
    return out

def fmt(v):
    return '—' if v is None else str(v)

def write_metrics_csv(path, metrics):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=DISPLAY_FIELDS, extrasaction='ignore')
        writer.writeheader()
        for row in metrics.values(): writer.writerow(row)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', default=Path(__file__).parent)
    p.add_argument('--keyword', action='append', required=True, help='可重复，如 --keyword "firestarter dance ai"')
    args = p.parse_args()
    result = enrich(args.keyword, args.root)
    path = Path(args.root) / 'reports' / 'seo-manual.csv'
    write_metrics_csv(path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('Saved:', path)

if __name__ == '__main__':
    main()
