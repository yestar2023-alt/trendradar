#!/usr/bin/env python3
"""Auditable SEO screening metrics using the user's reference formulas.

KGR    = intitle results / monthly volume
EKGR   = intitle results * (1 + organic KD/100) / monthly volume
KDROI% = (daily volume * 0.1 * 365 / (required backlinks * 100) - 1) * 100

Inputs may be imported via CSV. Paid DataForSEO is strictly opt-in.
Nothing is inferred from CPC. 'intitle' and 'allintitle' are NOT interchangeable.
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

BASE_FIELDS = ['keyword', 'volume', 'daily_volume', 'intitle', 'kd', 'required_backlinks',
               'source', 'checked_at', 'location', 'language']
DISPLAY_FIELDS = BASE_FIELDS + ['kgr', 'ekgr', 'kdroi_pct', 'daily_volume_basis',
                               'backlinks_basis', 'status']
API_ROOT = 'https://api.dataforseo.com'


def norm(value):
    return ' '.join(str(value or '').casefold().split())


def numeric(value):
    if value is None or str(value).strip().lower() in ('', '-', 'n/a', 'null', 'none'):
        return None
    try:
        n = float(str(value).replace(',', '').strip())
    except (ValueError, TypeError):
        return None
    return n if -1e12 < n < 1e12 else None


def row_from_dict(value):
    data = {str(k).lstrip('\ufeff').strip().lower(): v for k, v in value.items()}
    aliases = {
        'volume': ('volume', 'search_volume', 'monthly_search_volume'),
        'daily_volume': ('daily_volume', 'daily_search_volume'),
        'intitle': ('intitle', 'intitle_results', 'intitle_count'),
        'kd': ('kd', 'keyword_difficulty'),
        'required_backlinks': ('required_backlinks', 'backlinks_required', 'required_backlink_count'),
    }
    row = {'keyword': str(data.get('keyword') or data.get('topic') or '').strip()}
    for field, names in aliases.items():
        row[field] = next((numeric(data[name]) for name in names if name in data), None)
    row.update(
        source=data.get('source') or '未注明',
        checked_at=data.get('checked_at') or '未注明',
        location=data.get('location') or '未注明',
        language=data.get('language') or '未注明',
    )
    # Preserve the source's explicit provenance fields on cache reload.
    row['daily_volume_basis'] = data.get('daily_volume_basis') or ''
    row['backlinks_basis'] = data.get('backlinks_basis') or ''
    return row


def calculate(value, *, estimate_backlinks=False):
    result = dict(value)
    for field in ('volume', 'daily_volume', 'intitle', 'kd', 'required_backlinks'):
        result[field] = numeric(result.get(field))
    for field in ('volume', 'daily_volume', 'intitle', 'required_backlinks'):
        if result[field] is not None and result[field] < 0:
            result[field] = None
    if result['kd'] is not None and not (0 <= result['kd'] <= 100):
        result['kd'] = None

    volume, intitle, kd = (result[f] for f in ('volume', 'intitle', 'kd'))
    result['kgr'] = round(intitle / volume, 4) if volume and intitle is not None else None
    result['ekgr'] = round(intitle * (1 + kd / 100) / volume, 4) if volume and intitle is not None and kd is not None else None

    daily = result['daily_volume']
    daily_basis = result.get('daily_volume_basis') or ('直接提供' if daily is not None else '')
    if daily is None and volume is not None:
        daily = volume * 12 / 365
        daily_basis = '由月均量×12/365推算'
    backlinks = result['required_backlinks']
    backlinks_basis = result.get('backlinks_basis') or ('直接提供' if backlinks is not None else '')
    # Never silently equate organic KD with a real backlink requirement.
    if backlinks is None and estimate_backlinks and kd is not None and kd > 0:
        backlinks = kd / 5
        backlinks_basis = 'KD÷5粗略估算(非实测)'
    result['daily_volume'] = round(daily, 4) if daily is not None else None
    result['required_backlinks'] = round(backlinks, 4) if backlinks is not None else None
    result['daily_volume_basis'] = daily_basis or '缺失'
    result['backlinks_basis'] = backlinks_basis or '缺失'
    # 0 backlinks cannot form a meaningful financial denominator.
    result['kdroi_pct'] = round(((daily * 0.1 * 365 / (backlinks * 100)) - 1) * 100, 2) if daily is not None and backlinks is not None and backlinks > 0 else None

    available = [result.get(x) is not None for x in ('volume', 'daily_volume', 'intitle', 'kd', 'required_backlinks')]
    result['status'] = ('指标齐全（含估算）' if result['kdroi_pct'] is not None and '估算' in result['backlinks_basis']
                        else '指标齐全' if all(x is not None for x in (result['kgr'], result['ekgr'], result['kdroi_pct']))
                        else '部分指标缺失' if any(available) else '等待真实数据')
    if volume == 0:
        result['status'] = '月搜索量为0，KGR/EKGR无法计算'
    if backlinks == 0:
        result['status'] = '所需外链为0，KDROI除数无效'
    return result


def read_csv_metrics(path):
    if not path.exists():
        return {}
    with path.open(encoding='utf-8-sig', newline='') as file:
        rows = list(csv.DictReader(file))
    parsed = [row_from_dict(r) for r in rows]
    return {norm(row['keyword']): row for row in parsed if row['keyword']}


def read_cache(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return {norm(key): row_from_dict(value) for key, value in data.items() if isinstance(value, dict)} if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def _request_dfseo(endpoint, params, login, password):
    token = base64.b64encode((login + ':' + password).encode()).decode()
    body = json.dumps([params], ensure_ascii=False).encode('utf-8')
    req = request.Request(API_ROOT + endpoint, data=body, method='POST',
        headers={'Authorization': 'Basic ' + token, 'Content-Type': 'application/json',
                 'User-Agent': 'AI-Video-Radar/1.3'})
    with request.urlopen(req, timeout=35) as response:
        data = json.load(response)
    if data.get('status_code') != 20000:
        raise RuntimeError('DataForSEO status ' + str(data.get('status_code')))
    tasks = data.get('tasks') or []
    if not tasks or tasks[0].get('status_code') != 20000:
        raise RuntimeError('DataForSEO task status ' + str(tasks[0].get('status_code') if tasks else 'none'))
    return tasks[0].get('result') or []


def maybe_fetch_dataforseo(keywords, cache):
    if os.getenv('SEO_AUTO_FETCH') != '1':
        return cache
    login, password = os.getenv('DATAFORSEO_LOGIN'), os.getenv('DATAFORSEO_PASSWORD')
    if not login or not password:
        print('SEO: 未设置 DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD，不调用付费 API')
        return cache
    cap = max(0, min(10, int(os.getenv('SEO_MAX_KEYWORDS_PER_RUN') or '3')))
    candidates = [k for k in dict.fromkeys(keywords) if 0 < len(k) <= 80 and len(k.split()) <= 10]
    uncached = [k for k in candidates if norm(k) not in cache][:cap]
    market = os.getenv('SEO_LOCATION') or 'United States'
    language = os.getenv('SEO_LANGUAGE') or 'English'
    now = date.today().isoformat()

    if uncached:
        try:
            response = _request_dfseo('/v3/dataforseo_labs/google/keyword_overview/live',
                {'keywords': uncached, 'location_name': market, 'language_name': language}, login, password)
            items = [i for block in response for i in (block.get('items') or [])]
            for keyword in uncached:
                cache[norm(keyword)] = row_from_dict({'keyword': keyword, 'source': 'DataForSEO: 未提供指标',
                    'checked_at': now, 'location': market, 'language': language})
            for item in items:
                keyword = norm(item.get('keyword'))
                if keyword not in [norm(k) for k in uncached]:
                    continue
                info = item.get('keyword_info') or {}
                props = item.get('keyword_properties') or {}
                cache[keyword] = row_from_dict({
                    'keyword': item.get('keyword'), 'volume': info.get('search_volume'),
                    'kd': props.get('keyword_difficulty'), 'source': 'DataForSEO Keyword Overview',
                    'checked_at': now, 'location': market, 'language': language})
        except Exception as exc:
            print('SEO: Keyword Overview 查询失败: ' + str(exc)[:180])

    # Never silently reuse old 'allintitle' cached counts as 'intitle' results.
    if os.getenv('SEO_FETCH_INTITLE') == '1':
        remaining = [k for k in candidates if norm(k) in cache and cache[norm(k)].get('intitle') is None][:cap]
        for keyword in remaining:
            try:
                response = _request_dfseo('/v3/serp/google/organic/live/advanced',
                    {'keyword': 'intitle:"' + keyword.replace('"', '') + '"',
                     'location_name': market, 'language_name': language},
                    login, password)
                counts = [numeric(block.get('se_results_count')) for block in response]
                if counts and counts[0] is not None and counts[0] >= 0:
                    cache[norm(keyword)]['intitle'] = counts[0]
                    cache[norm(keyword)]['source'] += ' + Google intitle结果数(估计)'
                    cache[norm(keyword)]['checked_at'] = now
            except Exception as exc:
                print('SEO: intitle 结果估计查询失败: ' + str(exc)[:180])
    return cache


def enrich(keywords, root, *, fetch=True):
    root = Path(root)
    manual = read_csv_metrics(root / 'data' / 'keyword_metrics.csv')
    cache_path = root / 'data' / 'seo_metrics_cache.json'
    cache = read_cache(cache_path)
    if fetch and os.getenv('SEO_AUTO_FETCH') == '1':
        before = json.dumps(cache, sort_keys=True)
        cache = maybe_fetch_dataforseo(keywords, cache)
        if before != json.dumps(cache, sort_keys=True):
            save_cache(cache_path, cache)
    output = {}
    estimate = os.getenv('SEO_ESTIMATE_BACKLINKS_FROM_KD') == '1'
    for keyword in dict.fromkeys(keywords):
        key = norm(keyword)
        value = dict(cache.get(key) or row_from_dict({'keyword': keyword, 'source': '尚无数据源'}))
        if key in manual:
            manual_row = manual[key]
            for field in ('volume', 'daily_volume', 'intitle', 'kd', 'required_backlinks'):
                if manual_row[field] is not None:
                    value[field] = manual_row[field]
            for field in ('source', 'checked_at', 'location', 'language'):
                if manual_row.get(field) and manual_row[field] != '未注明':
                    value[field] = manual_row[field]
        value['keyword'] = keyword
        output[keyword] = calculate(value, estimate_backlinks=estimate)
    return output


def fmt(value):
    return '—' if value is None else str(value)


def write_metrics_csv(path, metrics):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, fieldnames=DISPLAY_FIELDS, extrasaction='ignore')
        writer.writeheader()
        for row in metrics.values():
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default=Path(__file__).parent)
    parser.add_argument('--keyword', action='append', required=True)
    args = parser.parse_args()
    results = enrich(args.keyword, args.root)
    dest = Path(args.root) / 'reports' / 'seo-manual.csv'
    write_metrics_csv(dest, results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print('Saved:', dest)


if __name__ == '__main__':
    main()
