#!/usr/bin/env python3
"""Evidence-first named video-playbook clustering for 24h YouTube shorts.

Input: official-API-backed existing data/state.json (no new API calls).
Specific anchors only; generic AI/cat/dance tags never establish a shared trend.
No AI-made, Shorts, origin, virality, or SEO novelty claims from title strings alone.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import json
import re
import sys
from zoneinfo import ZoneInfo

BJT = ZoneInfo("Asia/Shanghai")
NEWS_OR_TUTORIAL = re.compile(
    r"\b(?:how\s+to|tutorial|guide|news|explained|explain|reaction|reacted|"
    r"fact\s*check|these\s+viral|is\s+it\s+real|actually\s+ai|"
    r"editing\s+tutorial|kaise\s+banaye|review)\b|教程|讲解|如何制作|评测|解说|"
    r"ternyata\s+video\s+ai", re.I)
KNOWN_STOCK = "已有玩法/不算今日新词"
UNVERIFIED = "仅候选/尚未确认新玩法"

# Narrow expressions describe replicable shot/story/effect, not broad content categories.
# For known older formats, the link is evidence of previous existence, not a claimed original.
THEMES = [
    dict(id="cat_clapping", name="Black Cat Clapping / 拍手猫",
         pattern=r"(?:clapp(?:ing)?\s+(?:cat|kitten)|(?:cat|kitten)\s+clapp(?:ing)?)",
         input="一张自有宠物照", outcome="宠物站起并慢拍手",
         known="2026-09-25", url="https://knowyourmeme.com/memes/black-cat-clapping",
         note="9月已出现的存量热门梗，不能把今日二创叫首发", risk="原创素材版权与宠物照片权利"),
    dict(id="cinema_breakout", name="4D Cinema Breakout / 影院破屏",
         pattern=r"(?:4d\s*(?:theat(?:er|re)|cinema|bioskop)|(?:cinema|theat(?:er|re))\s*(?:breakout|out\s+of\s+screen))",
         input="一张本人照片+原创影院场景", outcome="银幕的虚构物体冲向座位",
         known="2026-09-30", url="https://www.makeviral.ai/templates/ai-cinema-breakout-video",
         note="至少9月已有独立模板；新闻/解说视频不代表新AI二创", risk="影视IP与原视频素材授权"),
    dict(id="gangnam_trio", name="Gangnam Style AI Dance / 三人轮流跳舞",
         pattern=r"(?:gangnam\s*style|gamgam\s*style|gangnam\s*trio)",
         input="一至三张成年人授权照片", outcome="三人轮流跟随舞蹈动作",
         known="2026-10-12", url="https://www.makeviral.ai/templates/gangnam-style-ai-dance",
         note="商业生成器已经存在；不能把同歌的不同舞蹈自动合并为单一模板", risk="歌曲音乐版权与原舞蹈素材授权"),
    dict(id="random_photo_mix", name="ChatGPT Mixed 2 Random Photos / 双图混搭",
         pattern=r"(?:mix(?:ed|ing)?\s*(?:two|2)\s*(?:random\s+)?photos?|(?:two|2)\s+random\s+photos?\s+(?:mix|merge))",
         input="两张授权图片", outcome="两张原本无关的图片形成意外混搭画面",
         known=None, url=None,
         note="可能只是单频道系列图片而非视频生成器搜索需求；需要观看内容核验",
         risk="肖像、图片版权及商标"),
    dict(id="living_food", name="Living Food / 食物拟人短剧",
         pattern=r"(?:living\s+food|(?:talking|animated)\s+(?:food|vegetables|fruit)|"
                 r"(?:food|shawarma|pizza|vegetable|fruit|potato)\s+(?:comes?\s+alive|with\s+(?:eyes|mouth)))",
         input="食物照片或文字描述", outcome="食物拟人化并说话/表演",
         known=None, url=None,
         note="标签只是类别线索，需验证是否是具体相同镜头/动作而非食物动画泛类",
         risk="商标包装、音乐、童声和配音"),
    dict(id="food_tree", name="Food Grows on Trees / 食物长在树上",
         pattern=r"(?:aloo\s+tikki\s+grows?|(?:food|pizza|chaat)\s+(?:grows?|growing)\s+on\s+(?:a\s+)?tree|"
                 r"seed\s+to\s+spicy\s+chaat)",
         input="指定食物+植物", outcome="食物像果实一样长在树上",
         known=None, url=None,
         note="同频道系列不能当独立模仿扩散；可能只是老概念变体",
         risk="内容误导与品牌商标"),
    dict(id="robot_girl", name="Robot Girl Dance / 机械人偶跳舞",
         pattern=r"(?:robot\s+girl|(?:ai|barbie|real)\s+robot\s+(?:girl|doll)|mecha[\s-]*doll)",
         input="成年人自有肖像或原创虚构角色", outcome="仿真人偶启动并跳舞",
         known=None, url=None,
         note="同一作者连续发片不代表跨作者爆发，可能是真实拍摄/剪辑",
         risk="肖像、深伪误导与过度性化"),
    dict(id="car_restoration", name="Car Transformation / 废车变超跑",
         pattern=r"(?:car\s+transformation|(?:car|lamborghini)\s+(?:restoration|makeover)|"
                 r"(?:old|scrap)\s+car\s+(?:into|to)\s+(?:lamborghini|supercar))",
         input="一张车辆照片", outcome="车辆从废旧到崭新的视觉变化",
         known=None, url=None,
         note="汽车修复和直接魔法变车可能是不同玩法，必须人工进一步拆分",
         risk="汽车品牌/Logo 商标与真实维修误导"),
    dict(id="celebrity_aging", name="Celebrity Aging / 明星老年化",
         pattern=r"(?:(?:80[- ]year[- ]old|aged|elderly)\s+(?:rappers|celebrities)|(?:rappers|celebrities)\s+aging)",
         input="获得授权的成人肖像", outcome="人脸随年龄变化",
         known=None, url=None,
         note="人物特效大类而非新玩法，避免从单一榜单拼新词",
         risk="明星肖像、真人深伪和角色版权"),
]

def utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)

def bj(iso):
    try:
        return utc(iso).astimezone(BJT).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, AttributeError):
        return "未知"

def clean(s):
    return str(s or "").replace("|", "/").replace("\r", " ").replace("\n", " ")[:165]

def matches_theme(title, theme):
    return bool(re.search(theme["pattern"], title or "", re.I))

def account_key(v):
    # Empty identifiers are not evidence for cross-account copying.
    return v.get("channel_id") or ""

def observed_rate(v):
    samples = v.get("samples") or []
    valid = [x for x in samples if x.get("views") is not None and x.get("at")]
    if len(valid) < 2:
        return None
    try:
        hours = (utc(valid[-1]["at"]) - utc(valid[-2]["at"])).total_seconds() / 3600
        return round((valid[-1]["views"] - valid[-2]["views"]) / hours, 1) if hours > 0 else None
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return None

def classify(video):
    title = video.get("title","")
    # A report about AI is not an AI-generated creative video even when the title mentions AI.
    if NEWS_OR_TUTORIAL.search(title):
        return "解说/教程/资讯", False
    if video.get("ai_metadata_confidence") == "medium":
        return "作者文字/标签自述AI", True
    return "AI制作未核实", False

def build(state, now):
    if not state.get("scans") or not state.get("first_success_at"):
        raise ValueError("Missing successful source snapshot: cannot claim current theme results")
    lastscan = utc(state["scans"][-1]["time"])
    if abs((now - lastscan).total_seconds()) > 36*3600:
        raise ValueError("Stale source snapshot: newer than 36 hours required")
    records = state.get("videos") or {}
    cutoff = now - timedelta(hours=24)
    groups = []
    matched_ids = set()
    for theme in THEMES:
        members = []
        for vid, v in records.items():
            try:
                published = utc(v["published_at"])
                if not cutoff <= published <= now + timedelta(minutes=5):
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            if matches_theme(v.get("title"),theme):
                review, creative = classify(v)
                item = {
                    "video_id": vid, "title": v["title"], "url":v.get("url",""),
                    "channel":v.get("channel",""), "channel_id":account_key(v),
                    "published_at":v.get("published_at"), "first_seen_at":v.get("first_seen_at"),
                    "views":v.get("views"), "observed_growth_per_hour":observed_rate(v),
                    "ai_evidence":review, "creative_claimed":creative,
                }
                members.append(item)
                matched_ids.add(vid)
        if not members:
            continue
        members.sort(key=lambda x:x["views"] or -1,reverse=True)
        creative_members=[x for x in members if x["creative_claimed"]]
        accounts={x["channel_id"] for x in creative_members if x["channel_id"]}
        all_accounts={x["channel_id"] for x in members if x["channel_id"]}
        max_views=max((x["views"] for x in members if x["views"] is not None),default=None)
        status = KNOWN_STOCK if theme["known"] else UNVERIFIED
        # No report automatically assigns "confirmed trend" even with 2 channels.
        if status == KNOWN_STOCK:
            verdict="排除今日新增词；只做历史/现有竞品跟踪"
        elif len(accounts)>=2:
            verdict="有多账号作者文字AI线索；核验是否同一具体玩法后再考虑SEO"
        elif len(creative_members)>=2:
            verdict="只有单账号反复出现或缺渠道ID；不是独立模仿证据"
        else:
            verdict="单个或未核实AI视频；仅观察，不建议立即建站"
        groups.append({
            "theme_id":theme["id"],"name":theme["name"],
            "status":status,"verdict":verdict,
            "concept":theme["outcome"],"input":theme["input"],
            "risk":theme["risk"],"caution":theme["note"],
            "existing_before":theme["known"],"previous_evidence_url":theme["url"],
            "videos":len(members),"channel_count":len(all_accounts),
            "claimed_ai_creations":len(creative_members),
            "independent_claimed_creator_count":len(accounts),
            "max_observed_views":max_views,
            "first_observed_at":min((x["first_seen_at"] for x in members if x.get("first_seen_at")),default=None),
            "examples":members[:8]
        })
    groups.sort(key=lambda g: (
        g["status"]!=KNOWN_STOCK,
        g["independent_claimed_creator_count"],
        g["claimed_ai_creations"],g["max_observed_views"] or 0
    ), reverse=True)
    unmatched = []
    for vid,v in records.items():
        if vid in matched_ids:
            continue
        try:
            if not cutoff <= utc(v["published_at"]) <= now:
                continue
        except (ValueError, KeyError, TypeError):
            continue
        _, creative = classify(v)
        if creative and (v.get("views") or 0)>=8000:
            unmatched.append({
                "title":v.get("title",""),"url":v.get("url",""),
                "views":v.get("views"), "channel":v.get("channel"),
                "first_seen_at":v.get("first_seen_at"),
                "published_at":v.get("published_at"),"observed_growth_per_hour":observed_rate(v)
            })
    unmatched.sort(key=lambda x:(x["observed_growth_per_hour"] if x["observed_growth_per_hour"] is not None else -1,x["views"] or -1), reverse=True)
    return {
        "built_at":now.isoformat(),"source_snapshot_at":state["scans"][-1]["time"],
        "snapshot_video_count":len(records),
        "named_theme_count":len(groups),
        "claimed_multi_creator_themes":sum(x["independent_claimed_creator_count"]>=2 and x["status"]!=KNOWN_STOCK for x in groups),
        "confirmed_new_seo_keywords":0,
        "themes":groups,"unmatched_creative_candidates":unmatched[:20],
    }

def report(result):
    lines = [
        "# AI Shorts 新玩法归组与独立模仿证据（自动候选）","",
        "- 数据时间（北京）："+bj(result["source_snapshot_at"]),
        "- 本次由已有 YouTube Data API 视频快照分组；没有新增 API 查询",
        f'- 24小时视频快照池：{result["snapshot_video_count"]} 条；窄词规则识别主题：{result["named_theme_count"]} 个',
        f'- 有两个及以上独立账号文字自述AI的**候选主题**：{result["claimed_multi_creator_themes"]}（不等于同一玩法的模仿已证实）',
        "- 经核实真正新关键词：**0（自动分类器不能确认新SEO词）**","",
        "> **务必注意：** 此处的“同主题”仅根据明确文字片段聚合，未经视频画面验证。",
        "> 不能把单账号连续上传当作跨账号模仿，也不能把媒体解说当原创AI玩法。",
        "> 只有独立视频截图/动作、跨平台传播、搜索意图及竞品历史都复核后，才可给出真正新词 Top。","",
        "## 窄义玩法候选与历史", ""
    ]
    for i,t in enumerate(result["themes"],1):
        lines += [
            f'### {i}. {t["name"]}',"",
            f'- 自动状态：**{t["status"]}**；建议：{t["verdict"]}',
            f'- 近期匹配视频：{t["videos"]}；不同频道：{t["channel_count"]}；文字自述AI的视频：{t["claimed_ai_creations"]}；其中独立作者频道：{t["independent_claimed_creator_count"]}',
            f'- 最大单条观测播放量：{t["max_observed_views"] if t["max_observed_views"] is not None else "未知"}；首次系统观察：{bj(t["first_observed_at"])}（不等于真实首发）',
            f'- 可复刻概念：{t["concept"]}；输入素材：{t["input"]}',
            f'- 混淆与排除：{t["caution"]}；风险：{t["risk"]}',
        ]
        if t.get("existing_before"):
            lines.append(f'- **不属于今日新发现玩法的历史证据：** {t["existing_before"]} 前已出现页面或内容（具体早期程度待来源确认），[{clean(t["previous_evidence_url"])}]({t["previous_evidence_url"]})')
        lines.extend(["","| 频道 | 原视频 | 原发布日期（北京） | 系统首见（北京） | 单条播放 | AI证据 | 真实采样增速/时 |",
                      "|---|---|---|---|---:|---|---:|"])
        for v in t["examples"]:
            speed = (f'{v["observed_growth_per_hour"]:,.1f}' if v["observed_growth_per_hour"] is not None else "待多次采样")
            lines.append(f'| {clean(v["channel"])} | [{clean(v["title"])}]({v["url"]}) | {bj(v["published_at"])} | {bj(v["first_seen_at"])} | {v["views"] if v["views"] is not None else "未知"} | {v["ai_evidence"]} | {speed} |')
        lines.append("")
    lines += ["## 高热但尚未归入具体玩法的 AI 自述视频（人工核验队列）","",
              "| 原视频 | 频道 | 播放量 | 观测增速/时 |","|---|---|---:|---:|"]
    for item in result["unmatched_creative_candidates"][:20]:
        speed=item["observed_growth_per_hour"]
        lines.append(f'| [{clean(item["title"])}]({item["url"]}) | {clean(item["channel"])} | {item["views"]} | {f"{speed:,.1f}" if speed is not None else "待多次采样"} |')
    if not result["unmatched_creative_candidates"]:
        lines.append("| — | — | — | — |")
    lines += ["","## 当天是否可以建站？","",
              "**自动判定：今日无已确认新增词。** 报告仅提供有原始链接的研究队列，禁止把已有玩法、作者自述或者只出现一次的视频直接变成 SEO Top1–3。"]
    return "\n".join(lines)+"\n"

def run(root, now=None):
    now = now or datetime.now(timezone.utc)
    source = root/"data"/"state.json"
    if not source.exists():
        raise ValueError("Upstream Shorts state.json missing: do not emit invented report")
    state = json.loads(source.read_text(encoding="utf-8"))
    result = build(state, now)
    reports=root/"reports"
    reports.mkdir(parents=True,exist_ok=True)
    content=report(result)
    (reports/"themes-latest.md").write_text(content,encoding="utf-8")
    (reports/"themes-latest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    (reports/(now.astimezone(BJT).strftime("%Y-%m-%d")+"-themes.md")).write_text(content,encoding="utf-8")
    print(json.dumps({"source_video_count":result["snapshot_video_count"],"themes":result["named_theme_count"],
                      "unverified_cross_creator":result["claimed_multi_creator_themes"],
                      "confirmed_new_seo_keywords":0},ensure_ascii=False))
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args()
    try:
        run(args.root)
    except (ValueError,FileNotFoundError) as exc:
        print("主题报告未生成：数据不充分 / "+str(exc),file=sys.stderr)
        sys.exit(2)
