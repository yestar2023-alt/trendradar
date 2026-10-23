#!/usr/bin/env python3
"""YouTube Data API upstream radar: source-first, snapshot-backed, no fabricated trends.

Public data only; the API key is read from the environment and never written to disk.
The first successful check establishes a baseline and never produces "new" videos.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import sys
from urllib import error, parse, request
from zoneinfo import ZoneInfo

API_ROOT = "https://www.googleapis.com/youtube/v3/"
BJ = ZoneInfo("Asia/Shanghai")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


def beijing(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BJ).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, AttributeError):
        return "未知"


def api_json(resource: str, parameters: dict, key: str) -> dict:
    """GET an official endpoint. Exceptions intentionally omit URLs and credentials."""
    if resource not in {"channels", "playlistItems", "videos"}:
        raise ValueError("unsupported API resource")
    query = parse.urlencode({**parameters, "key": key})
    req = request.Request(API_ROOT + resource + "?" + query,
                          headers={"User-Agent": "AIUpstreamRadar/0.2", "Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=20) as response:
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError("YouTube API response too large")
        return json.loads(data)
    except error.HTTPError as exc:
        reason = "unknown"
        try:
            payload = json.loads(exc.read(5000))
            reason = payload.get("error", {}).get("errors", [{}])[0].get("reason", "unknown")
        except (ValueError, IndexError, TypeError, AttributeError):
            pass
        raise RuntimeError(f"YouTube Data API HTTP {exc.code}; reason={reason}") from None
    except error.URLError:
        raise RuntimeError("YouTube Data API network error") from None


def load_channel_videos(channel_id: str, api_key: str, get=api_json, max_pages: int = 2) -> dict:
    """Resolve uploads playlist -> its newest items -> authoritative video metadata."""
    if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id):
        raise ValueError("Invalid YouTube channel ID")
    channel = get("channels", {"part": "contentDetails", "id": channel_id}, api_key)
    items = channel.get("items", [])
    if len(items) != 1 or items[0].get("id") != channel_id:
        raise ValueError("Channel missing or inaccessible")
    playlist_id = items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not playlist_id:
        raise ValueError("Channel has no accessible uploads playlist")

    ids = []
    token = None
    for _ in range(max_pages):
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
        if token:
            params["pageToken"] = token
        response = get("playlistItems", params, api_key)
        for item in response.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid and ID_PATTERN.fullmatch(vid) and vid not in ids:
                ids.append(vid)
        token = response.get("nextPageToken")
        if not token:
            break
    if not ids:
        raise ValueError("Uploads playlist empty or inaccessible")

    videos = {}
    for offset in range(0, len(ids), 50):
        batch = ids[offset:offset+50]
        response = get("videos", {"part": "snippet,statistics", "id": ",".join(batch)}, api_key)
        for v in response.get("items", []):
            vid = v.get("id", "")
            if vid not in batch:
                continue
            snippet = v.get("snippet", {})
            stats = v.get("statistics", {})
            views = stats.get("viewCount")
            videos[vid] = {
                "title": snippet.get("title") or vid,
                "published": snippet.get("publishedAt") or "",
                "url": "https://www.youtube.com/watch?v=" + vid,
                "views": int(views) if views is not None and str(views).isdigit() else None,
            }
    if not videos:
        raise ValueError("No accessible video metadata")
    return videos


def observe(state: dict, configured: list, api_key: str | None, get=api_json, now: str | None = None,
            max_pages: int = 2):
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    state.setdefault("sources", {})
    state.setdefault("videos", {})
    statuses = []
    new = []
    if not api_key:
        for src in configured:
            statuses.append((src["name"], "未接通：缺少 GitHub Actions Secret YOUTUBE_API_KEY"))
        return statuses, new, now

    for src in configured:
        sid = src["id"]
        try:
            videos = load_channel_videos(src["channel_id"], api_key, get, max_pages)
            before = state["sources"].get(sid)
            previous = set(before["ids"]) if before else None
            if previous is not None:
                for vid in videos:
                    if vid not in previous and vid not in state["videos"]:
                        new.append((src["name"], vid))
            for vid, current in videos.items():
                record = state["videos"].setdefault(
                    vid, {"first_seen": now, "source": sid, "samples": []})
                record.update({k:current[k] for k in ("title", "published", "url")})
                if current["views"] is not None:
                    last = record["samples"][-1] if record["samples"] else None
                    if not last or last["observed_at"] != now:
                        record["samples"].append({"observed_at": now, "views": current["views"]})
                    record["samples"] = record["samples"][-48:]
            state["sources"][sid] = {"ids": sorted(videos), "last_success": now}
            statuses.append((src["name"], f"成功：{len(videos)} 个视频（窗口快照）"
                             + ("；首次建立基线" if previous is None else "")))
        except Exception as exc:
            # Never rewrite the last good source snapshot on API failures.
            statuses.append((src["name"], "抓取失败：" + type(exc).__name__ + ": " + str(exc)[:140]))
    return statuses, new, now


def save_report(root: Path, state: dict, statuses: list, new: list, now: str):
    successful = sum(status.startswith("成功") for _, status in statuses)
    lines = ["# AI 视频上游信号报告（YouTube Data API 试运行）", "",
             f"- 抓取时间（北京时间）：{beijing(now)}",
             f"- 成功频道：{successful}/{len(statuses)}",
             f"- 失败/未配置频道：{len(statuses)-successful}/{len(statuses)}",
             f"- 经成功历史快照对比的首次观察视频：{len(new)}", "",
             "> 这只代表上游新视频，并不是已确认 AI 新玩法。视频发布与首次观察是不同时间。", "",
             "## 数据源状态", ""]
    lines.extend(f"- **{name}**：{status}" for name, status in statuses)
    lines.extend(["", "## 增量视频", "",
                  "| 首次观察（北京） | 原视频发布时间（北京） | 来源 | 链接 | 当前播放量 | 上次采样至今增长 |",
                  "|---|---|---|---|---:|---:|"])
    for name, vid in new:
        v = state["videos"][vid]
        samples = v.get("samples", [])
        growth = ("—" if len(samples) < 2 else
                  str(samples[-1]["views"]-samples[-2]["views"]))
        view = str(samples[-1]["views"]) if samples else "未知"
        title = v["title"].replace("|", "/").replace("[", "").replace("]", "")[:100]
        lines.append(f'| {beijing(v["first_seen"])} | {beijing(v["published"])} | {name} | '
                     f'[{title}]({v["url"]}) | {view} | {growth} |')
    if not new:
        lines.append("| — | — | — | 无已核实增量视频（可能处于首次基线） | — | — |")
    if successful == 0:
        lines.extend(["", "**数据未更新/抓取失败，不能确认今日新增。**"])
    lines.extend(["", "## 审核规则", "",
                  "仅比较同一来源的成功历史快照；失败不更新基线。"
                  "需要另外确认 AI 二创、跨账号传播、搜索意图和竞品，才允许推荐 SEO 词。",
                  "目前监控固定频道，不覆盖全网 Shorts、TikTok 或抖音。"])
    folder = root / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines)+"\n"
    (folder / "latest.md").write_text(content, encoding="utf-8")
    date = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(BJ).date().isoformat()
    (folder / f"{date}.md").write_text(content, encoding="utf-8")
    return successful


def run(root: Path, config: dict, key=None, get=api_json, now=None):
    state_file = root / "data" / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    statuses, new, when = observe(
        state, config["channels"], key if key is not None else os.environ.get("YOUTUBE_API_KEY"),
        get, now, config.get("max_pages", 2))
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(state_file)
    successful = save_report(root, state, statuses, new, when)
    result = {"successful_sources": successful, "total_sources": len(config["channels"]),
              "new_video_urls": len(new), "live_connected": successful > 0}
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    cfg = json.loads((args.root/"config.json").read_text(encoding="utf-8"))
    outcome = run(args.root, cfg)
    if not outcome["live_connected"]:
        sys.exit(2)
