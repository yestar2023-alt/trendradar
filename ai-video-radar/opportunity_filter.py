#!/usr/bin/env python3
"""Evidence-gated keyword quality and optional, limited Google SERP verification.

No Web.Cafe, no invented volume/KD. Without SERPER_API_KEY this runs offline,
preserving all discovered terms, review links and explicit unverified status.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT_GENERIC = {"roblox", "roblox games", "roblox codes", "steam games", "indie game",
 "game wiki", "game guide", "new games", "game release date", "game walkthrough",
 "ai video", "ai dance", "image to video", "ai model", "video generator",
 "ai video generator", "ai animation", "ai image", "ai gif", "ai music",
 "ai logo generator", "generator", "ai"}
BAD_PHRASES = ("î€", "ï¿", "�", "\ue000", "\ue001", "nsfw", "uncensored",
 "porn", "phantom vibration", "qwerty keyboard", "compact discs",
 "ai guardrails", "software development", "how video game surgeons",
 "what is ", "what are ", "why ", "meaning of ", "how to pronounce",
 "first vcr size")
VIDEO_WORDS = ("video", "dance", "animation", "photo", "image", "gif", "lip sync",
 "lipsync", "effect", "filter", "template", "model", "shorts", "meme",
 "generator", "face swap", "motion", "movie", "film")
GAME_WORDS = ("roblox", "game", "codes", "wiki", "guide", "walkthrough", "steam",
 "boss", "quest", "map", "tips", "release", "nintendo", "ps5", "xbox",
 "switch", "build", "mastery", "tier list", "horror", "survival")

def read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default

def norm(value):
    return " ".join(str(value or "").casefold().strip().split())

def parse_date(value):
    try:
        point = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return point if point.tzinfo else point.replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None

def age_days(value, now):
    point = parse_date(value)
    return (now - point).total_seconds() / 86400 if point else None

def support_index(entries):
    # Index by first title token to avoid N_graph_nodes * N_all_ledger_entries.
    result = {}
    for ident, entry in entries.items():
        title = norm(entry.get("title") or entry.get("keyword"))
        tokens = re.findall(r"[a-z0-9]+", title)
        if tokens and len(title) >= 5:
            result.setdefault(tokens[0], []).append((ident, entry, title))
    return result


def support_for(keyword, entries, index=None):
    # Preserve identities independently: matching a name is not ID verification.
    term = norm(keyword)
    ids, sources, urls = [], set(), set()
    candidates = (index or support_index(entries))
    tokens = set(re.findall(r"[a-z0-9]+", term))
    matches = {}
    for token in tokens:
        for ident, entry, title in candidates.get(token, []):
            matches[ident] = (entry, title)
    for ident, (entry, title) in matches.items():
        if title == term or (len(title) >= 7 and
          re.search(r"(?<![a-z0-9])" + re.escape(title) + r"(?![a-z0-9])", term)):
            ids.append(ident)
            sources.update(str(x) for x in (entry.get("sources") or []))
            urls.update(x.get("url") for x in (entry.get("evidence") or [])
                        if isinstance(x, dict) and x.get("url"))
            if entry.get("url"):
                urls.add(entry["url"])
        if len(ids) >= 12:
            break
    hosts = set()
    for url in urls:
        host = urllib.parse.urlsplit(url).hostname
        if host:
            hosts.add(host.lower().removeprefix("www."))
    return {"ids": ids, "sources": sorted(sources), "urls": sorted(urls)[:8],
            "independent_source_domains": len(hosts)}

def noise_reason(keyword, vertical, source_urls):
    term = norm(keyword)
    if not term or term in ROOT_GENERIC:
        return "GENERIC_ROOT"
    if len(term) < 4 or len(term) > 85 or len(term.split()) > 9:
        return "BAD_LENGTH"
    if any(b in term for b in BAD_PHRASES):
        return "GARBLED_OR_OFFTOPIC"
    if term.startswith(("http", "#")) or re.fullmatch(r"[\W\d_]+", term):
        return "NOT_QUERY"
    if vertical == "ai":
        visual = any(v in term for v in VIDEO_WORDS)
        has_ai = bool(re.search(r"\bai\b", term) or "image to video" in term
                      or "text to video" in term)
        if not (visual and (has_ai or source_urls)):
            return "NO_VIDEO_GENERATION_INTENT"
    elif not any(g in term for g in GAME_WORDS) and not source_urls:
        return "NO_GAME_INTENT"
    return None

def classify_result(url, title, keyword):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    t = norm(title)
    kind = ("FORUM" if "reddit.com" in host or "steamcommunity.com" in host else
            "VIDEO_SOCIAL" if any(x in host for x in ("youtube.com", "youtu.be", "tiktok.com")) else
            "WIKI" if "wikipedia.org" in host or "fandom.com" in host or "wiki" in host else
            "GUIDE" if "guide" in host or "codes" in t or "walkthrough" in t or "guide" in t else
            "TOOL_TEMPLATE" if any(x in t for x in ("generator", "create ", "make ", "template", "online tool")) else
            "OTHER")
    phrase = norm(keyword)
    significant = [w for w in re.findall(r"[a-z0-9]+", phrase)
                   if w not in ("ai", "game", "video", "roblox", "online", "free")]
    focus = phrase in t or (len(significant) >= 2 and
                           sum(w in t for w in significant) / len(significant) >= 0.75)
    return {"type": kind, "focused": focus}

def serper_search(keyword, api_key):
    body = json.dumps({"q": keyword, "gl": "us", "hl": "en", "num": 10}).encode("utf-8")
    req = urllib.request.Request("https://google.serper.dev/search",
        data=body, method="POST",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.load(r)
    if not isinstance(payload, dict) or not isinstance(payload.get("organic"), list):
        raise ValueError("SERP result missing organic array")
    rows, used = [], set()
    for item in payload["organic"]:
        if not isinstance(item, dict):
            continue
        url = item.get("link") or ""
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname or url in used:
            continue
        used.add(url)
        title = str(item.get("title") or "")
        rows.append({"rank": item.get("position"), "title": title, "url": url,
                     **classify_result(url, title, keyword)})
        if len(rows) >= 10:
            break
    return rows

def assess(graph, ledger, vertical, now_iso):
    now = parse_date(now_iso)
    if now is None or vertical not in ("game", "ai"):
        raise ValueError("valid time and vertical required")
    entries = ledger.get("entities") or ledger.get("keywords") or {}
    index = support_index(entries)
    edges_by_child = {}
    for edge in graph.get("edges") or []:
        if isinstance(edge, dict) and edge.get("child"):
            edges_by_child.setdefault(norm(edge["child"]), []).append(edge)
    rows = []
    for key, node in (graph.get("nodes") or {}).items():
        term = str(node.get("keyword") or key).strip()
        sources = support_for(term, entries, index)
        reason = noise_reason(term, vertical, sources["urls"])
        edges = edges_by_child.get(norm(key), [])
        rising = [e for e in edges if e.get("type") == "rising" and
                  age_days(e.get("observed_at"), now) is not None and
                  0 <= age_days(e.get("observed_at"), now) <= 14]
        top = [e for e in edges if e.get("type") == "top"]
        growth = [float(e["value"]) for e in rising
                  if isinstance(e.get("value"), (int, float))]
        breakout = any("breakout" in str(e.get("formatted_value", "")).lower()
                       for e in rising)
        parents = sorted({norm(e.get("parent")) for e in edges if e.get("parent")})
        score = 0
        if not reason:
            score = (35 if rising else 8 if top else 0)
            score += 20 if sources["ids"] else 0
            score += 10 if sources["independent_source_domains"] >= 2 else (5 if sources["urls"] else 0)
            score += 13 if 2 <= len(term.split()) <= 6 else 2
            score += 8 if len(parents) >= 2 else 0
            score += 5 if breakout else 0
            score += 9 if (vertical == "game" and any(x in norm(term) for x in
                       ("codes", "guide", "wiki", "walkthrough", "map", "mastery"))) or (
                       vertical == "ai" and any(x in norm(term) for x in
                       ("dance", "video", "effect", "generator", "template"))) else 0
        status = ("EXCLUDED_NOISE" if reason else
                  "HIGH_PRIORITY_RESEARCH" if score >= 60 and rising else
                  "RESEARCH_QUEUE" if score >= 35 else "WATCH_ONLY")
        rows.append({"keyword": term, "quality_status": status, "noise_reason": reason,
                     "score": min(100, score), "origin": node.get("seed_type") or
                     ("RELATED_QUERY" if edges else "MONITORED_NAME"),
                     "first_observed_at": node.get("first_observed_at"),
                     "parents": parents, "rising_evidence": len(rising),
                     "top_evidence": len(top), "breakout_label": breakout,
                     "highest_rising_growth_pct": max(growth) if growth else None,
                     "trends_geo": "US", "trends_window": "now 7-d",
                     "source_count": sources["independent_source_domains"],
                     "source_urls": sources["urls"], "identity_ids": sources["ids"],
                     "trends_url": "https://trends.google.com/trends/explore?" +
                     urllib.parse.urlencode({"date":"now 7-d","geo":"US","q":term}),
                     "google_url": "https://www.google.com/search?" +
                     urllib.parse.urlencode({"q":term,"gl":"us","hl":"en"}),
                     "serp_status": "NOT_CHECKED", "serp_checked_at": None, "serp": {},
                     "decision": "NOT_BUILD_APPROVED"})
    rows.sort(key=lambda x: (x["score"], x["rising_evidence"], x["source_count"]), reverse=True)
    return rows

def verify_serp(rows, cache, now_iso, *, api_key="", max_calls=2, provider=serper_search):
    now = parse_date(now_iso)
    checks = cache.setdefault("checks", {})
    calls = errors = 0
    for row in rows:
        if row["quality_status"] == "EXCLUDED_NOISE":
            row["serp_status"] = "SKIPPED_NOISE"
            row["decision"] = "EXCLUDE"
            continue
        if row["origin"] == "CURATED_ROOT":
            row["serp_status"] = "SKIPPED_CURATED_ROOT"
            continue
        lookup = "US|en|" + norm(row["keyword"])
        previous = checks.get(lookup) or {}
        age = age_days(previous.get("checked_at"), now)
        cached = previous if (age is not None and 0 <= age <= 3 and
                              len(previous.get("organic") or []) == 10) else None
        if cached is None and row["quality_status"] in ("HIGH_PRIORITY_RESEARCH", "RESEARCH_QUEUE"):
            if not api_key:
                row["serp_status"] = "NOT_CONFIGURED"
            elif calls >= max_calls:
                row["serp_status"] = "QUEUED_BUDGET"
            else:
                calls += 1
                try:
                    results = provider(row["keyword"], api_key)
                    if len(results) == 10:
                        cached = {"checked_at": now_iso, "provider":"SERPER_GOOGLE",
                                  "geo":"US", "language":"en", "organic":results}
                        checks[lookup] = cached
                    else:
                        row["serp_status"] = "PARTIAL_RESULTS"
                        row["serp"] = {"organic_count": len(results), "organic": results}
                except Exception as exc:
                    errors += 1
                    row["serp_status"] = "PROVIDER_ERROR"
                    row["serp"] = {"error": type(exc).__name__ + ": " + str(exc)[:130]}
                    if "429" in str(exc) or "403" in str(exc):
                        api_key = ""  # stop on rate limit
        if cached:
            organic = cached["organic"]
            focused = sum(1 for x in organic if x.get("focused") and x.get("type") in
                          ("GUIDE", "WIKI", "TOOL_TEMPLATE"))
            row["serp_status"] = "VERIFIED_TOP10"
            row["serp_checked_at"] = cached["checked_at"]
            row["serp"] = {"provider": cached["provider"], "organic_count": 10,
                            "focused_specialized_results": focused,
                            "competition_indicator": "FEW_FOCUSED_RESULTS" if focused <= 2 else
                                "MANY_FOCUSED_RESULTS" if focused >= 5 else "MIXED_RESULTS",
                            "organic": organic}
            row["decision"] = ("EDITORIAL_RESEARCH_READY_NOT_DOMAIN_APPROVAL"
                               if row["quality_status"] == "HIGH_PRIORITY_RESEARCH"
                               and row["rising_evidence"] and focused <= 2
                               and row["source_count"] > 0 else
                               "REVIEW_COMPETITION_OR_DEMAND")
    return {"calls":calls, "errors":errors,
            "verified_top10":sum(row["serp_status"]=="VERIFIED_TOP10" for row in rows)}

def build(graph, ledger, *, vertical, now_iso, cache=None, api_key="", max_calls=2,
          provider=serper_search):
    rows = assess(graph, ledger, vertical, now_iso)
    state = cache if cache is not None else {"checks": {}}
    serp = verify_serp(rows, state, now_iso, api_key=api_key,
                       max_calls=max_calls, provider=provider)
    counts = {}
    for row in rows:
        counts[row["quality_status"]] = counts.get(row["quality_status"], 0) + 1
    return {"vertical": vertical, "checked_at": now_iso, "total_nodes": len(rows),
            "quality_counts": counts, "serp_summary": serp,
            "serp_provider_configured": bool(api_key),
            "note": "Relative Google Trends growth != search volume. SERP classification is a heuristic, not proof of low difficulty. No auto domain approval.",
            "rows": rows}, state

def save(root, report, cache):
    root = Path(root)
    reports, data = root / "reports", root / "data"
    reports.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    (reports / "opportunity-latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (data / "serp_cache.json").write_text(
        json.dumps(cache, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    fields = ["keyword","quality_status","score","noise_reason","rising_evidence",
              "highest_rising_growth_pct","breakout_label","source_count",
              "serp_status","serp_checked_at","decision","google_url","trends_url"]
    with (reports / "opportunity-latest.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["rows"])
    lines = ["# 新词机会报告 · " + ("游戏" if report["vertical"]=="game" else "AI 视频"), "",
             "- 检查时间（UTC）：**{}**".format(report["checked_at"]),
             "- 全部候选节点：**{}**".format(report["total_nodes"]),
             "- 高优先级：**{}**".format(report["quality_counts"].get("HIGH_PRIORITY_RESEARCH",0)),
             "- 排除明显噪音：**{}**".format(report["quality_counts"].get("EXCLUDED_NOISE",0)),
             "- 本轮真实 SERP 请求：**{}**".format(report["serp_summary"]["calls"]),
             "- 已核验前十结果：**{}**".format(report["serp_summary"]["verified_top10"]),
             "- SERP 凭证可用：**{}**".format("是" if report["serp_provider_configured"] else "否"), "",
             "> 不编造搜索量、KD 或 SERP。只有真实返回前10条才叫已核验。所有词完整保存于 CSV/JSON。", "",
             "## 值得优先研究（不是已批准建站）", "",
             "| 关键词 | 研究分 | 相关查询涨幅 | SERP | 决策 |",
             "|---|---:|---|---|---|"]
    highlights = [r for r in report["rows"] if r["quality_status"] == "HIGH_PRIORITY_RESEARCH"][:20]
    for r in highlights:
        lines.append("| [{}]({}) | {} | {} | {} | {} |".format(
            r["keyword"].replace("|"," "), r["google_url"], r["score"],
            r["highest_rising_growth_pct"] if r["highest_rising_growth_pct"] is not None else "—",
            r["serp_status"], r["decision"]))
    if not highlights:
        lines.append("| — | — | — | — | 没有满足高优先级条件的候选 |")
    lines += ["", "## 完整分类统计", "| 状态 | 数量 |", "|---|---:|"]
    lines.extend("| {} | {} |".format(k, v) for k,v in sorted(report["quality_counts"].items()))
    lines += ["", "注意：首次观察并不等于关键词刚诞生。仅相关查询暴涨不能证明真实可获得流量。",
              "未配置 SERPER_API_KEY 时自动保留待验证状态及 Google 搜索链接；不调用付费服务。",
              "完整证据和拒绝原因见 opportunity-latest.json / opportunity-latest.csv。"]
    (reports / "opportunity-latest.md").write_text("\n".join(lines)+"\n", encoding="utf-8")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--vertical", choices=["game","ai"], required=True)
    parser.add_argument("--max-serp", type=int, default=2)
    args = parser.parse_args()
    if not 0 <= args.max_serp <= 3:
        parser.error("--max-serp must be 0..3")
    root = Path(args.root)
    graph = read(root / "data" / "trends_graph.json", {"nodes":{}, "edges":[]})
    name = "research_ledger.json" if args.vertical=="game" else "keyword_ledger.json"
    ledger = read(root / "data" / name, {})
    cache = read(root / "data" / "serp_cache.json", {"checks":{}})
    time = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    report, updated = build(graph, ledger, vertical=args.vertical, now_iso=time,
                            cache=cache, api_key=os.getenv("SERPER_API_KEY", ""),
                            max_calls=args.max_serp)
    save(root, report, updated)
    print("opportunity:",report["total_nodes"], report["quality_counts"],
          report["serp_summary"])

if __name__ == "__main__":
    main()
