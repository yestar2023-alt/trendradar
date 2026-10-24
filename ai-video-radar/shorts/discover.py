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
    elif synthetic_flag is True:
        # YouTube status.containsSyntheticMedia: creator's *own* altered/synthetic
        # declaration, not a guarantee of fully AI-generated footage.
        confidence = "medium"
        reason = "YouTube API：作者主动声明含合成/修改内容（未经画面核验）"
    elif strongly_claimed:
        confidence = "medium"
        reason = "标题/标签自述 AI 制作（未经画面核验）"
    elif any_claim:
        confidence = "low"
        reason = "仅笼统文字提及 AI（无法确认视频由 AI 制作）"
    else:
        confidence = "unknown"
        reason = "搜索命中但元数据缺乏 AI 制作证据"
    shorts_hint = bool(re.search(r"#shorts?\b|\byoutube shorts?\b", combined, re.I))
    return confidence, reason, topic, shorts_hint


def query_label(item):
    """Stable provenance label. No-query regional discovery is not an AI search."""
    if item.get("source") == "broad_region":
        return "broad_no_keyword:" + str(item["regionCode"])
    return item["q"]


def search_recent(queries, key, now, get=api_json):
    after = utc_iso(now - timedelta(hours=24))
    before = utc_iso(now)
    ids = {}
    status = []
    for item in queries:
        source = item.get("source", "ai_keyword")
        label = query_label(item)
        ordering = item.get("order", "viewCount")
        params = {"part": "snippet", "type": "video",
                  "order": ordering, "videoDuration": "short",
                  "maxResults": 50, "publishedAfter": after,
                  "publishedBefore": before, "safeSearch": "moderate"}
        if source == "broad_region":
            # q is intentionally OMITTED, not set to an empty string or "AI".
            # This samples high-view recently published short videos in a
            # rotating content region, NOT the deprecated global trending list.
            params["regionCode"] = item["regionCode"]
        else:
            params["q"] = item["q"]
        try:
            found = get("search", params, key)
            count = 0
            for result in found.get("items", []):
                video = result.get("id", {})
                vid = video.get("videoId") if isinstance(video, dict) and video.get("kind") == "youtube#video" else None
                if vid and VIDEO_ID.fullmatch(vid):
                    ids.setdefault(vid, set()).add(label)
                    count += 1
            status.append({"query": label, "source": source, "order": ordering,
                           "status": "success", "found": count})
        except Exception as exc:
            status.append({"query": label, "source": source, "order": ordering,
                           "status": "failed", "detail": str(exc)[:160]})
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
        "source_tags": [str(t)[:80] for t in (snippet.get("tags") or [])[:30] if t],
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


def choose_queries(config, now):
    """Rotate 2 AI queries + 1 regional no-keyword sample within the SAME cap.

    A source without q is a broad sample (not an exhaustive trending feed).
    Without broad config, existing AI-only installations keep prior behavior.
    """
    source = config.get("queries", [])
    limit = max(1, int(config.get("max_searches_per_scan", 3)))
    broad = config.get("broad_discovery", {})
    regions = broad.get("region_codes", [])
    use_broad = bool(broad.get("enabled") and regions and limit >= 2)
    ai_slots = min(len(source), limit - int(use_broad))
    # 6 four-hour UTC slots daily. Deterministic even if a scheduled run fails.
    ordinal = int(now.timestamp() // (4 * 3600))
    selected = []
    if ai_slots:
        start = (ordinal * ai_slots) % len(source)
        selected = [source[(start + offset) % len(source)]
                    for offset in range(ai_slots)]
    if use_broad:
        region = str(regions[ordinal % len(regions)]).upper()
        if not re.fullmatch(r"[A-Z]{2}", region):
            raise ValueError("Invalid broad-discovery ISO country code")
        selected.append({"q": "", "order": "viewCount",
                         "regionCode": region, "source": "broad_region"})
    return selected


def discover(state, config, key, now, get=api_json):
    state.setdefault("videos", {})
    state.setdefault("scans", [])
    state.setdefault("first_success_at", None)
    # Rotate a small query subset across scheduled scans to reduce rate limiting.
    # The rotation is derived from Beijing four-hour slots, so failed runs do not
    # stall the query cycle; fixed-time reruns are deterministic.
    queries = choose_queries(config, now)
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
    # Keep previously discovered million-view candidates across rotating query slots.
    # Every reported metric must still come from a fresh videos.list response.
    max_ids = config.get("max_detail_ids", 700)
    priorities = sorted(matched) + sorted(
        active_ids - set(matched),
        key=lambda vid: (state["videos"].get(vid, {}).get("views") or 0),
        reverse=True)
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
        if timedelta(0) <= (now - parsed_time(meta["published_at"])) <= timedelta(hours=24):
            # Also include past discovery matches whose stats were refreshed today.
            accepted_now.append(video)

    # Report this scan's no-keyword source evidence separately from historical
    # provenance. A creator disclosure is not a verified AI-generated effect.
    broad_ids = {vid for vid, labels in matched.items()
                 if any(label.startswith("broad_no_keyword:") for label in labels)}
    broad_items = [v for v in accepted_now if v["video_id"] in broad_ids]
    broad_disclosed_million_without_ai_words = [
        v for v in broad_items
        if v.get("synthetic_media_disclosed") is True
        and isinstance(v.get("views"), int) and v["views"] >= 1_000_000
        and not AI_TOKEN.search(
            v.get("title", "") + " " + " ".join(v.get("source_tags", [])))
        and classify_viral_tier(v, config) == "million_view_candidate"
    ]

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
        "broad_short_candidates": len(broad_items),
        "broad_disclosed_million_without_ai_words":
            len(broad_disclosed_million_without_ai_words),
    }, True


def text_cell(value):
    return str(value if value is not None else "未知").replace("|", "/").replace("\n", " ").replace("\r", " ")[:170]


def classify_viral_tier(video, config):
    """One individual video >= 1M views is a candidate viral hit, never a sum."""
    views = video.get("views")
    if video.get("ai_metadata_confidence") != "medium" or not isinstance(views, int):
        return "unverified_or_unrelated"
    if views >= config.get("viral_min_views", 1_000_000):
        return "million_view_candidate"
    if views >= config.get("early_watch_min_views", 100_000):
        return "early_watch_not_viral"
    return "below_review_threshold"


def write_reports(root, now, config, items, metadata):
    folder = root/"reports"
    folder.mkdir(parents=True, exist_ok=True)
    successful = metadata["successful_queries"]
    statuses = metadata["statuses"]
    cutoff = now-timedelta(hours=24)
    broad_statuses = [s for s in statuses if s.get("source") == "broad_region"]
    broad_success = sum(s["status"] == "success" for s in broad_statuses)
    threshold = config.get("viral_min_views", 1_000_000)
    if threshold < 1_000_000:
        raise ValueError("Million-view viral floor cannot be lowered below 1,000,000")
    all_million = [v for v in items if (v.get("views") or 0) >= threshold]
    viral = [v for v in items if classify_viral_tier(v, config) == "million_view_candidate"]
    early = [v for v in items if classify_viral_tier(v, config) == "early_watch_not_viral"]
    viral.sort(key=lambda v: (v["views"] or -1, observed_growth(v.get("samples", [])) or -1), reverse=True)
    early.sort(key=lambda v: (observed_growth(v.get("samples", [])) or -1, v["views"] or -1), reverse=True)
    lines = [
        "# 最近24小时 AI 短视频：百万爆款候选（未核验画面）", "",
        f"- 北京时间：{now.astimezone(BJ):%Y-%m-%d %H:%M}",
        f"- 视频发布时间窗口：{to_bj(utc_iso(cutoff))} — {to_bj(utc_iso(now))}（北京时间）",
        f"- 本轮搜索成功率：{successful}/{len(statuses)}；失败：{len(statuses)-successful}",
        f"- 无AI关键词的跨地区热门短视频抽样：{broad_success}/{len(broad_statuses)}次成功；本轮命中24小时短视频：{metadata.get('broad_short_candidates', 0)}条",
        f"- 其中只靠作者合成内容声明（标题/标签无AI词）检出的百万候选：{metadata.get('broad_disclosed_million_without_ai_words', 0)}条",
        f"- 最近24小时发布、时长≤180秒、已在本轮更新真实观看数据的视频候选：{len(items)}",
        f"- 全部候选中单条观看量≥{threshold:,}的视频：{len(all_million)}（含非AI/未验证AI内容）",
        f"- **百万爆款 AI/合成媒体候选：{len(viral)}**（单条≥{threshold:,}，且作者标题/标签自述AI，或YouTube API明确返回作者合成媒体声明）",
        f"- **早期观察，非爆款：{len(early)}**（单条≥{config.get('early_watch_min_views',100_000):,}但未满百万）",
        f"- 历史快照后首次观察到的原视频：{metadata['new_since_prior']}",
        f"- 搜索方式：关键词轮换+先前视频重新采样；不依赖九站模板监控", "",
        "> **严格定义**：爆款门槛是最近24小时内发布的单条视频，当前累计≥100万次观看。",
        "> YouTube API 的 status.containsSyntheticMedia=true 是作者主动声明**写实合成/修改内容**，不是完整 AI 视频鉴定；字段缺失不是 false，更不等于非AI。",
        "> 标题/标签自述AI也未得到画面核验。官方平台自动添加的 Made with AI 标记（如C2PA、YouTube工具）可能不出现在这个API字段里。",
        "> YouTube Data API的短时长筛选与后续≤180秒判断，不能证实正式Shorts的宽高比或分类。",
        "> 单次累计播放量不是增速；真实观测增速需要两次以上有时间戳的采样。",
        "> 关键词搜索与各国无关键词查询都是**抽样**，并非全站所有Shorts；regionCode不是精确来源国筛选。本轮没有百万候选不等于YouTube没有百万视频。",
        "> 无关键词查询每轮轮换一个国家/地区，且沿用搜索接口的最近24小时+短时长筛选；不是 YouTube 的 mostPopular 榜单。", "",
        "## 百万爆款候选（单条≥100万，最多20条）", "",
        "| 原视频链接 | 频道 | 官方发布时间（北京） | 本次累计播放量 | 真实观测增速/小时 | AI证据 |",
        "|---|---|---|---:|---:|---|",
    ]
    for v in viral[:20]:
        g = observed_growth(v.get("samples", []))
        lines.append(
            f'| [{text_cell(v["title"])}]({v["url"]}) | {text_cell(v["channel"])}'
            f' | {to_bj(v["published_at"])} | {v["views"]:,}'
            f' | {f"{g:,.1f}" if g is not None else "待第二次采样"}'
            f' | {v["ai_metadata_reason"]} |'
        )
    if not viral:
        lines.append("| — | — | — | — | — | 本轮无合格百万AI候选，禁止用低播放视频凑数 |")
    lines.extend(["", "## 早期潜力观察（10万–99.9万；明确不是爆款，最多5条）", "",
                  "| 原视频链接 | 官方发布时间（北京） | 累计播放量 | 真实观测增速/小时 |",
                  "|---|---|---:|---:|"])
    for v in early[:5]:
        g = observed_growth(v.get("samples", []))
        lines.append(f'| [{text_cell(v["title"])}]({v["url"]}) | {to_bj(v["published_at"])}'
                     f' | {v["views"]:,} | {f"{g:,.1f}" if g is not None else "待第二次采样"} |')
    if not early:
        lines.append("| — | — | — | — |")
    lines.extend(["", "## 搜索覆盖和失败项", "",
                  "| 本轮查询 | 排序 | 状态 | 返回视频条数 |",
                  "|---|---|---|---:|"])
    for item in statuses:
        row = (str(item.get("found", 0)) if item["status"]=="success"
               else "失败：" + item.get("detail","未知")[:120])
        lines.append(f'| {text_cell(item["query"])} | {item["order"]} | {item["status"]} | {row} |')
    if metadata.get("lookup_failures"):
        lines.append("**部分视频详情失败：**" + "; ".join(metadata["lookup_failures"][:3]))
    if not successful:
        lines.append("**数据未更新/抓取失败，不能确认本轮新增。**")
    if broad_statuses and not broad_success:
        lines.append("**无关键词地区发现本轮失败；即使AI关键词成功，也不能声称覆盖无AI标题作品。**")
    if metadata["baseline"]:
        lines.append("本轮是首次历史基线；系统首次观察时间不等于原视频官方发布时间。")
    lines.extend(["", "## 进一步SEO判断", "",
                  "完整候选清单见 latest.csv；低播放量视频只用于历史研究，不进入爆款榜。",
                  "百万播放并不等于SEO新词或具体AI玩法已确认。还需要视频画面、独立模仿、",
                  "Google搜索需求、竞品时间线及版权/肖像核验。"])
    content = "\n".join(lines)+"\n"
    (folder/"latest.md").write_text(content, encoding="utf-8")
    (folder/f'{now.astimezone(BJ):%Y-%m-%d}.md').write_text(content, encoding="utf-8")
    csvcols = ["video_id","title","url","channel","published_at","first_seen_at","last_seen_at",
               "views","likes","comments","duration_seconds","category","ai_metadata_confidence",
               "ai_metadata_reason","synthetic_media_disclosed","shorts_hint","shorts_verified","queries",
               "published_avg_views_per_hour","observed_growth_views_per_hour","viral_tier"]
    with (folder/"latest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=csvcols)
        writer.writeheader()
        for x in sorted(items,key=lambda v:v.get("views") or -1,reverse=True):
            data = {field:x.get(field) for field in csvcols}
            # Preserve tri-state; blank/omitted API data is NOT an explicit No.
            flag = x.get("synthetic_media_disclosed")
            data["synthetic_media_disclosed"] = ("true" if flag is True
                                                  else "false" if flag is False
                                                  else "not_returned")
            data["queries"] = " | ".join(x.get("queries", []))
            data["published_avg_views_per_hour"] = recent_score(x, now)
            data["observed_growth_views_per_hour"] = observed_growth(x.get("samples", []))
            data["viral_tier"] = classify_viral_tier(x, config)
            writer.writerow(data)
    return viral, early


def run(root, config, key=None, get=api_json, now=None):
    key = key if key is not None else os.environ.get("YOUTUBE_API_KEY", "")
    now = now or datetime.now(timezone.utc)
    state_path = root/"data/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    if not key:
        statuses = [{"query": query_label(item), "source": item.get("source", "ai_keyword"),
                     "order": item.get("order","viewCount"),
                     "status": "failed", "detail": "YOUTUBE_API_KEY 未配置"}
                    for item in choose_queries(config, now)]
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
    viral, early = write_reports(root, now, config, items, meta)
    response = {
        "connected": connected,
        "queries_succeeded": meta["successful_queries"],
        "queries_total": len(meta["statuses"]),
        "recent_24h_short_candidates": len(items),
        "million_view_ai_candidates": len(viral),
        "early_watch_not_viral": len(early),
        "broad_queries_succeeded": sum(
            s.get("source") == "broad_region" and s["status"] == "success"
            for s in meta["statuses"]),
        "broad_short_candidates": meta.get("broad_short_candidates", 0),
        "broad_disclosed_million_without_ai_words":
            meta.get("broad_disclosed_million_without_ai_words", 0),
        "metadata_ai_hot_candidates": len(viral),  # compatibility: now >= 1M only
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
