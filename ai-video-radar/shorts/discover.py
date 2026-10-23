#!/usr/bin/env python3
"""24-hour AI short-video discovery via official YouTube Data API.

Search is discovery (never exhaustive); videos.list verifies age, duration and counters.
'AI-made' and 'Shorts' are *candidates*, not independently authenticated classifications.
No AI-model hallucinated views, growth or publication dates.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import sys
from urllib import error, parse, request
from zoneinfo import ZoneInfo
import os

API_ROOT = "https://www.googleapis.com/youtube/v3/"
BJ = ZoneInfo("Asia/Shanghai")
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
DURATION = re.compile(r"^P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", re.I)
AI_TOKEN = re.compile(r"(?<![a-z])ai(?![a-z])|aigenerated|aivideo|aianimation|人工智能|人工知能|生成ai|ai生成|vídeo\s+ia|video\s+ia", re.I)
STRONG_AI = re.compile(
    r"ai[\s_-]*(?:generated|made|created|video|animation|shorts?|dance|edit|meme|cat|dog|animal|transformation)"
    r"|(?:generated|made|created)[\s_-]*(?:by|with|using)[\s_-]*ai"
    r"|#(?:aigenerated|aivideo|aianimation|aishorts)|人工智能生成|ai生成", re.I)
NON_MADE = re.compile(
    r"\b(?:tutorial|review|guide|explained|how[\s-]*to|course|lesson|news|workflow|prompt\s*tips|comparison|"
    r"best\s+ai\s+tools|software\s+update)\b|教程|评测|教你|使用教程", re.I)
KINDS = [
    ("dance", re.compile(r"danc|choreo|跳舞|댄스|ダンス|baile", re.I)),
    ("animals", re.compile(r"cat|dog|pet|animal|kitten|puppy|猫|狗|gato|perro", re.I)),
    ("transformation", re.compile(r"transform|morph|before\s*and\s*after|effect|transition|变身|変身", re.I)),
    ("animation", re.compile(r"animat|cartoon|anime|3d|动画|アニメ|animación", re.I)),
    ("meme", re.compile(r"meme|funny|humor|brainrot|梗|搞笑", re.I)),
]


def parsed_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def utc_iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def to_bj(value):
    try:
        return parsed_time(value).astimezone(BJ).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, AttributeError):
        return "未知"


def duration_seconds(value):
    m = DURATION.fullmatch(value or "")
    if not m:
        return None
    return int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0)


def api_json(resource, params, key):
    if resource not in ("search", "videos"):
        raise ValueError("Unsupported API resource")
    url = API_ROOT + resource + "?" + parse.urlencode({**params, "key": key})
    req = request.Request(url, headers={"User-Agent": "AIShortsDiscovery/0.1",
                                        "Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=25) as resp:
            payload = resp.read(2_000_001)
            if len(payload) > 2_000_000:
                raise RuntimeError("API result exceeds 2 MB")
            return json.loads(payload)
    except error.HTTPError as ex:
        code = ex.code
        reason = "unknown"
        try:
            errors = json.loads(ex.read(4096)).get("error", {}).get("errors", [])
            if errors:
                reason = str(errors[0].get("reason", "unknown"))[:60]
        except (ValueError, IndexError, TypeError, AttributeError):
            pass
        # Avoid including ex.url, which contains the API key.
        raise RuntimeError(f"YouTube API {resource} HTTP {code}; reason={reason}") from None
    except error.URLError:
        raise RuntimeError(f"YouTube API {resource} network unavailable") from None


def classify_metadata(title, description, tags, synthetic_flag):
    title = title or ""
    desc = description or ""
    tagtext = " ".join(tags or [])
    combined = " ".join([title, desc[:500], tagtext])
    topic = next((name for name, rx in KINDS if rx.search(title + " " + tagtext)), "other")
    is_education = bool(NON_MADE.search(title))
    strongly_claimed = bool(STRONG_AI.search(title + " " + tagtext))
    any_claim = bool(AI_TOKEN.search(combined))
    if is_education:
        confidence = "low"
        reason = "标题为教学、评测或资讯内容，不可直接当作 AI 生成作品"
    elif strongly_claimed:
        confidence = "medium"
        reason = "标题/标签自述 AI 制作（未经画面核验）"
    elif any_claim or synthetic_flag is True:
        confidence = "low"
        reason = "仅文字/合成媒体声明相关（不等于 AI 视频已确认）"
    else:
        confidence = "unknown"
        reason = "搜索命中但元数据缺乏 AI 制作证据"
    shorts_hint = bool(re.search(r"#shorts?\b|\byoutube shorts?\b", combined, re.I))
    return confidence, reason, topic, shorts_hint


def search_recent(queries, key, now, get=api_json):
    after = utc_iso(now - timedelta(hours=24))
    before = utc_iso(now)
    ids = {}
    status = []
    for item in queries:
        q = item["q"]
        ordering = item.get("order", "viewCount")
        try:
            found = get("search", {"part": "snippet", "type": "video", "q": q,
                                    "order": ordering, "videoDuration": "short",
                                    "maxResults": 50, "publishedAfter": after,
                                    "publishedBefore": before, "safeSearch": "moderate"}, key)
            count = 0
            for result in found.get("items", []):
                video = result.get("id", {})
                vid = video.get("videoId") if isinstance(video, dict) and video.get("kind") == "youtube#video" else None
                if vid and VIDEO_ID.fullmatch(vid):
                    ids.setdefault(vid, set()).add(q)
                    count += 1
            status.append({"query": q, "order": ordering, "status": "success", "found": count})
        except Exception as exc:
            status.append({"query": q, "order": ordering, "status": "failed", "detail": str(exc)[:160]})
    return ids, status


def fetch_video_details(ids, key, get=api_json):
    videos = {}
    failures = []
    idlist = sorted(ids)
    for start in range(0, len(idlist), 50):
        batch = idlist[start:start+50]
        try:
            result = get("videos", {"part": "snippet,statistics,contentDetails,status", "id": ",".join(batch)}, key)
            for row in result.get("items", []):
                vid = row.get("id")
                if vid in batch:
                    videos[vid] = row
        except Exception as exc:
            failures.append(str(exc)[:160])
    return videos, failures


def normalized_video(vid, obj, matches, now):
    snippet = obj.get("snippet", {})
    content = obj.get("contentDetails", {})
    stats = obj.get("statistics", {})
    status = obj.get("status", {})
    published = snippet.get("publishedAt", "")
    try:
        parsed_time(published)
    except (ValueError, TypeError, AttributeError):
        return None
    secs = duration_seconds(content.get("duration", ""))
    if secs is None or not 1 <= secs <= 180:
        return None
    title = snippet.get("title", "")
    description = snippet.get("description", "")
    confidence, reason, topic, shorts_hint = classify_metadata(
        title, description, snippet.get("tags", []), status.get("containsSyntheticMedia"))
    def number(value):
        return int(value) if str(value).isdigit() else None
    return {
        "video_id": vid,
        "url": "https://www.youtube.com/watch?v=" + vid,
        "published_at": published,
        "title": title,
        "channel": snippet.get("channelTitle", ""),
        "channel_id": snippet.get("channelId", ""),
        "duration_seconds": secs,
        "views": number(stats.get("viewCount")),
        "likes": number(stats.get("likeCount")),
        "comments": number(stats.get("commentCount")),
        "ai_metadata_confidence": confidence,
        "ai_metadata_reason": reason,
        "category": topic,
        "shorts_hint": shorts_hint,
        "shorts_verified": False,
        "synthetic_media_disclosed": status.get("containsSyntheticMedia", None),
        "queries": sorted(matches),
        "last_seen_at": utc_iso(now),
    }


def recent_score(video, now):
    try:
        hours = max((now - parsed_time(video["published_at"])).total_seconds() / 3600, 1)
    except (ValueError, TypeError, KeyError):
        hours = 24
    count = video.get("views")
    return round(count / hours, 1) if count is not None else None


def observed_growth(samples):
    if len(samples) < 2:
        return None
    first, last = samples[0], samples[-1]
    interval = (parsed_time(last["at"]) - parsed_time(first["at"])).total_seconds() / 3600
    if interval <= 0:
        return None
    if first.get("views") is None or last.get("views") is None:
        return None
    return round((last["views"] - first["views"]) / interval, 1)


def discover(state, config, key, now, get=api_json):
    state.setdefault("videos", {})
    state.setdefault("scans", [])
    state.setdefault("first_success_at", None)
    queries = config["queries"][:config.get("max_searches_per_scan", 8)]
    matched, query_status = search_recent(queries, key, now, get)
    usable = sum(s["status"] == "success" for s in query_status)
    if not usable:
        return [], {"statuses": query_status, "lookup_failures": [], "successful_queries": 0,
                    "eligible": 0, "baseline": False, "new_since_prior": 0}, False

    # Preserve old 48-hour candidates so a second sample can measure genuine changes.
    active_ids = set()
    for vid, record in state["videos"].items():
        try:
            if (now - parsed_time(record["published_at"])).total_seconds() <= 48 * 3600:
                active_ids.add(vid)
        except (ValueError, KeyError, TypeError):
            pass
    all_ids = set(matched) | active_ids
    # A cap limits total detail requests; current discoveries take priority.
    max_ids = config.get("max_detail_ids", 700)
    priorities = sorted(matched) + sorted(active_ids - set(matched))
    all_ids = priorities[:max_ids]
    details, fail = fetch_video_details(all_ids, key, get)
    initial = state["first_success_at"] is None
    accepted_now = []
    new_since_prior = 0
    for vid, obj in details.items():
        meta = normalized_video(vid, obj, matched.get(vid, []), now)
        if meta is None:
            continue
        if parsed_time(meta["published_at"]) > now + timedelta(minutes=5):
            continue
        prior = state["videos"].get(vid)
        if prior is None:
            state["videos"][vid] = {**meta, "first_seen_at": utc_iso(now), "samples": []}
            if not initial and vid in matched:
                new_since_prior += 1
        else:
            prior.update({k: v for k, v in meta.items() if k not in ("queries",)})
            prior["queries"] = sorted(set(prior.get("queries", [])) | set(meta["queries"]))
        video = state["videos"][vid]
        if video["views"] is not None:
            samples = video["samples"]
            sample = {"at": utc_iso(now), "views": video["views"],
                      "likes": video["likes"], "comments": video["comments"]}
            if not samples or samples[-1]["at"] != sample["at"]:
                samples.append(sample)
            video["samples"] = samples[-18:]
        if vid in matched and timedelta(0) <= (now - parsed_time(meta["published_at"])) <= timedelta(hours=24):
            accepted_now.append(video)

    # Keep data for a week; no indefinite retention of API metadata.
    keep = now - timedelta(days=7)
    state["videos"] = {
        vid: v for vid, v in state["videos"].items()
        if "published_at" in v and parsed_time(v["published_at"]) >= keep
    }
    state["scans"].append({"time": utc_iso(now), "successful_queries": usable,
                           "failed_queries": len(queries)-usable,
                           "valid_short_candidates": len(accepted_now),
                           "first_observed_since_prior": new_since_prior})
    state["scans"] = state["scans"][-42:]
    if state["first_success_at"] is None:
        state["first_success_at"] = utc_iso(now)
    accepted_now.sort(key=lambda v: (
        observed_growth(v.get("samples", [])) or -1,
        recent_score(v, now) or -1,
        v.get("views") or -1), reverse=True)
    return accepted_now, {
        "statuses": query_status, "lookup_failures": fail, "successful_queries": usable,
        "eligible": len(accepted_now), "baseline": initial,
        "new_since_prior": new_since_prior,
    }, True


def text_cell(value):
    return str(value if value is not None else "未知").replace("|", "/").replace("\n", " ").replace("\r", " ")[:170]


def write_reports(root, now, config, items, metadata):
    folder = root/"reports"
    folder.mkdir(parents=True, exist_ok=True)
    successful = metadata["successful_queries"]
    statuses = metadata["statuses"]
    cutoff = now - timedelta(hours=24)
    hot = [
        x for x in items if x["ai_metadata_confidence"] == "medium"
        and x.get("views") is not None
        and x["views"] >= config.get("min_views", 1000)
        and (recent_score(x, now) or 0) >= config.get("min_avg_views_per_hour", 150)
    ]
    hot.sort(key=lambda v: (observed_growth(v["samples"]) or -1,
                            recent_score(v, now) or -1,
                            v["views"] or 0), reverse=True)
    lines = [
        "# 24 小时 AI 视频 Shorts 发现雷达（候选，非最终确认）", "",
        f"- 北京时间：{now.astimezone(BJ):%Y-%m-%d %H:%M}",
        f"- 发布窗口：{to_bj(utc_iso(cutoff))} — {to_bj(utc_iso(now))}（北京时间）",
        f"- 查询成功率：{successful}/{len(statuses)}；失败：{len(statuses)-successful}",
        f"- 符合最近 24 小时且视频不超过 180 秒的候选：{len(items)}",
        f"- 作者元数据声称 AI 制作、达到参考热度门槛：{len(hot)}",
        f"- 相对于历史观察首次发现：{metadata['new_since_prior']}（首次成功采集只建基线）",
        f"- 采集方式：YouTube Data API search.list + videos.list，非九站关键词差分", "",
        "> **重要**：YouTube API 的 videoDuration=short 意味着少于 4 分钟，并非严格的 Shorts 标识。",
        "> 本程序进一步筛选 ≤180 秒，但无法通过公开 Data API 判断宽高比；因此这里只称 Shorts 候选。",
        "> 「AI 制作」仅根据作者公开文字/标签判断，尚未观看视频确认。观看量是累计播放量，",
        "> 「发布以来平均每小时播放」不是实际逐小时增长；只有多次采样才能计算观测增长。", "",
        "## 有热度的 AI 短视频候选（最多 20 条）", "",
        "| 视频（原始链接） | 类别 | 发布（北京） | 播放量 | 发布以来均速/时 | 两次采样实际增速/时 | AI 证据 |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for v in hot[:20]:
        speed = observed_growth(v.get("samples", []))
        lines.append(
            f'| [{text_cell(v["title"])}]({v["url"]}) | {v["category"]} | {to_bj(v["published_at"])}'
            f' | {v["views"]:,} | {recent_score(v, now):,.1f}'
            f' | {speed if speed is not None else "待第二次采样"} | {v["ai_metadata_reason"]} |'
        )
    if not hot:
        lines.append("| — | — | — | — | — | — | 本轮无达到门槛且具备 AI 元数据声明的候选 |")
    lines += ["", "## 其他刚发布的短视频线索（最多 15 条，待进一步识别）", "",
              "| 标题 | 发布时间（北京） | 观看量 | AI 可信度 | 匹配搜索词 |",
              "|---|---|---:|---|---|"]
    extra = [x for x in items if x not in hot]
    extra.sort(key=lambda x: x.get("views") or 0, reverse=True)
    for v in extra[:15]:
        lines.append(f'| [{text_cell(v["title"])}]({v["url"]}) | {to_bj(v["published_at"])}'
                     f' | {v["views"] if v["views"] is not None else "未知"}'
                     f' | {v["ai_metadata_confidence"]} | {text_cell(", ".join(v.get("queries",[])))} |')
    if not extra:
        lines.append("| — | — | — | — | — |")
    lines += ["", "## 搜索覆盖和失败项", "",
              "| 本轮查询 | 排序 | 状态 | 返回视频条数 |",
              "|---|---|---|---:|"]
    for item in statuses:
        rows = (str(item.get("found", 0)) if item["status"] == "success"
                else "失败：" + item.get("detail", "未知")[:120])
        lines.append(f'| {text_cell(item["query"])} | {item["order"]} | {item["status"]} | {rows} |')
    if metadata.get("lookup_failures"):
        lines += ["", "**部分视频详情请求失败：**" + "; ".join(metadata["lookup_failures"][:3])]
    if not successful:
        lines += ["", "**数据未更新/抓取失败，不能确认今日新增。**"]
    if metadata["baseline"]:
        lines += ["", "**本轮为第一份有效搜索基线。** 可以看到最近 24 小时发布的视频，但无法断言它们相对历史系统今天才新增。"]
    lines += ["", "## SEO 研究规则", "",
              "视频播放量不是搜索量；视频热度不等于新关键词。需要核实原始玩法、独立二创数量、",
              "不同账号传播、Google 搜索意图、生成器竞品与 IP/音乐/肖像风险，才进入建站 Top。"]
    content = "\n".join(lines)+"\n"
    (folder/"latest.md").write_text(content, encoding="utf-8")
    (folder/f'{now.astimezone(BJ):%Y-%m-%d}.md').write_text(content, encoding="utf-8")
    csvcols = ["video_id","title","url","channel","published_at","first_seen_at","last_seen_at",
               "views","likes","comments","duration_seconds","category","ai_metadata_confidence",
               "ai_metadata_reason","shorts_hint","shorts_verified","queries",
               "published_avg_views_per_hour","observed_growth_views_per_hour"]
    with (folder/"latest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=csvcols)
        writer.writeheader()
        for x in items:
            data = {field: x.get(field) for field in csvcols}
            data["queries"] = " | ".join(x.get("queries", []))
            data["published_avg_views_per_hour"] = recent_score(x, now)
            data["observed_growth_views_per_hour"] = observed_growth(x.get("samples", []))
            writer.writerow(data)
    return hot


def run(root, config, key=None, get=api_json, now=None):
    key = key if key is not None else os.environ.get("YOUTUBE_API_KEY", "")
    now = now or datetime.now(timezone.utc)
    state_path = root/"data/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    if not key:
        statuses = [{"query": item["q"], "order": item.get("order","viewCount"),
                     "status": "failed", "detail": "YOUTUBE_API_KEY 未配置"}
                    for item in config["queries"][:config.get("max_searches_per_scan",8)]]
        items = []
        meta = {"statuses": statuses, "lookup_failures": [],
                "successful_queries": 0, "eligible": 0, "baseline": False,
                "new_since_prior": 0}
        connected = False
    else:
        items, meta, connected = discover(state, config, key, now, get)
    # Retain last good state if the entire search batch failed.
    if connected:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",",":")),
                       encoding="utf-8")
        tmp.replace(state_path)
    hot = write_reports(root, now, config, items, meta)
    response = {
        "connected": connected,
        "queries_succeeded": meta["successful_queries"],
        "queries_total": len(meta["statuses"]),
        "recent_24h_short_candidates": len(items),
        "metadata_ai_hot_candidates": len(hot),
        "first_observed_after_baseline": meta["new_since_prior"],
    }
    print(json.dumps(response, ensure_ascii=False))
    return response


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    config = json.loads((args.root/"config.json").read_text(encoding="utf-8"))
    outcome = run(args.root, config)
    if not outcome["connected"]:
        sys.exit(2)
