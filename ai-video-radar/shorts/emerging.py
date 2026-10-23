#!/usr/bin/env python3
"""Automatically mine new named AI-video playbook *leads* from YouTube metadata.

No extra API calls, LLM key or dependency. Proof = dated original URLs in a
persisted YouTube Data API snapshot. Text similarity is NOT proof of imitation,
a true Shorts classification, AI generation, or SEO search demand.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

from themes import NEWS_OR_TUTORIAL, THEMES, bj, matches_theme, observed_rate, utc

# Excluding commodity words is deliberate: "AI cat dance" is not a new named trend.
STOP = set("""
a an the this that is are was were be been for of on in at to from by with into vs or
and but not what which who why how when our your you we i it its their his her
video videos short shorts shortvideo shortsfeed youtube youtubeshorts ytshorts
trend trends trending viral new latest original ai ia aigenerated aivideo aianimation
aishorts aiart aistory aigirl aigeneratedvideo aiimages artificialintelligence machinelearning genai
generated generating made create created maker edit editing editor generator
animation animated anime cartoon cartoons 3d render vfx
funny fun humor comedy cute amazing unbelievable incredible insane wow omg
best top ranking reaction reacts news tutorial explanation guide
dance dancing dancers challenge challenges meme memes effect effects transform
transformation transitions transition filter filters image photo photos
watch subscribe follow like likes share now today real life
girl boy man woman person baby babies kids children cat cats kitten
dog dogs puppy animal animals pet pets
story stories content scene scenes part episode ep pov
viralvideo shortsviral fyp fypshorts reel reels
instagram tiktok capcut openai chatgpt seedance
videoia videosia viralshorts funnyshorts
un una unos unas el la las los de del en con por para como que
es esta este estes estas sobre tu mi su ai generado generada generados
vídeo vídeos feito feita efeitos dança danca dancing desafio
hindi english malayalam tamil japanese chinese language official
""".split())
# No exact pair of these alone should be considered a distinct reproducible format.
SUBJECT_ONLY = set("""
lamine yamal pedri ronaldo messi trump netanyahu biden putin elon musk
mrbeast disney marvel league legends minecraft roblox naruto sonic michael jackson terminator
christmas halloween bangladesh india pakistan brazil spain football soccer
""".split())
COMMON_HASH = set("""
trendingshorts shortstrending satisfying funnysatisfying foodshorts artificialintelligence genai
cooking relatable digitalcreator hindicomedy funnyanimals catlovers
minecraft aicooking cutebaby funnysnake bhojpuri 3danimation terminator beforeandafter entertainment deepfake
catsoftiktok catcartoon recipe pizzarecipe ghiblistyle
funnycats dancingcats catshorts cartoonshorts aishort aiimages aiimage aiart
aitransformation aidance aitool aiimages aiimage aistorytelling
danceshorts girlshorts musicshorts animememes aiartist
ai ia aivideo aigenerated aianimation aishorts shorts short shortvideo
shortsfeed youtubeshorts youtubeshort ytshorts viral trend trending
reels tiktok fyp funny animation dance dancing meme memes funnycat
cats cat dogs dog pet cute aiart aiimages aiartwork
explore newtrend shortsviral viralshorts videoai viralvideo
""".split())
# Tags built entirely from generic social-media words are not named effects.
# This prevents #TrendingShorts, #AIDance, #FunnyCats, #AITransformation,
# and concatenated variants from becoming falsely high-priority trends.
GENERIC_HASH_PARTS = sorted(set("""
ai ia video videos short shorts shortsvideo youtube yt shortsfeed
created generated generating generator
cooking cook relatable digital creator hindi animals animal
lovers lover baby babies snake 3d mine craft recipe
viral trending trend fyp instagram tiktok reel reels
funny comedy cute cat cats kitten dog dogs pet pets
animation animated cartoon cartoons satisfying effect effects
transformation transform transition dance dancing challenge
meme memes art artist content original official news
photo photos image images story stories vlog vlogs
usashorts india usa funnyvideo funnyvideos shortsviral
""".split()),key=len,reverse=True)


def is_generic_hashtag(value: str) -> bool:
    key = value.casefold().lstrip("#").replace("_","").replace("-","")
    if key in STOP or key in COMMON_HASH:
        return True
    memo={}
    def segmented(i):
        if i==len(key):
            return True
        if i in memo:
            return memo[i]
        memo[i]=any(key.startswith(part,i) and segmented(i+len(part))
                    for part in GENERIC_HASH_PARTS)
        return memo[i]
    return segmented(0)


# A shared *action* makes a same-named-video topic more interesting, but still
# needs watching: metadata alone cannot establish identical choreography/effect.
ACTION_ROOTS = {
    "clap": r"clap(?:s|ping|ped)?", "kiss": r"kiss(?:es|ing|ed)?",
    "hug": r"hug(?:s|ging|ged)?", "swap": r"swap(?:s|ping|ped)?",
    "age": r"ag(?:e|ing|ed)", "sing": r"sing(?:s|ing|er)?",
    "dance": r"danc(?:e|es|ed|ing)", "jump": r"jump(?:s|ing|ed)?",
    "fly": r"fly|flying|flies|flew", "throw": r"throw(?:s|ing)?|threw",
    "grow": r"grow(?:s|ing|n)?", "transform": r"transform(?:s|ing|ed|ation)?",
    "turn": r"turn(?:s|ing|ed)?", "morph": r"morph(?:s|ing|ed)?",
    "cook": r"cook(?:s|ing|ed)?", "eat": r"eat(?:s|ing|en)?",
    "talk": r"talk(?:s|ing|ed)?", "open": r"open(?:s|ing|ed)?",
    "dance_cn": r"跳舞|起舞|舞蹈", "transform_cn": r"变身|變身|变化|變化",
}
ACTION_RE = {key: re.compile(r"\b(?:" + pattern + r")\b" if key[-3:]!="_cn" else pattern, re.I)
             for key,pattern in ACTION_ROOTS.items()}
WORD = re.compile(r"[^\W_]+", re.UNICODE)
HASHTAG = re.compile(r"(?<!\w)#([\w-]{3,50})", re.UNICODE)
DAY = timedelta(hours=24)


def terms(s: str) -> list[str]:
    norm = unicodedata.normalize("NFKC", s or "").casefold()
    norm = norm.replace("k/da", "kda")
    tokens = WORD.findall(norm)
    return [t for t in tokens if len(t) >= 2 and t not in STOP and
            not t.isdigit() and not (len(t)==2 and t in ("de","la","le","da"))]


def title_text(video: dict) -> str:
    title = video.get("title") or ""
    # Hashtags and appended platform metadata are excluded from the main phrase.
    first = title.split("#", 1)[0]
    first = re.split(r"\s+[|｜]\s+|\s+/\s+", first, maxsplit=1)[0]
    return first.strip()


def title_terms(video: dict) -> list[str]:
    return terms(title_text(video))[:12]


def named_hashtags(video: dict) -> set[str]:
    t = video.get("title") or ""
    # Metadata tags are supplied by videos.list.snippet.tags, when present.
    tags = video.get("source_tags") or []
    alltags = HASHTAG.findall(t)
    alltags.extend(str(t).lstrip("#") for t in tags[:30] if t)
    out = set()
    for raw in alltags:
        key = unicodedata.normalize("NFKC", str(raw)).casefold().replace("_", "")
        key = key.strip("-#")
        if (re.fullmatch(r"[\w-]{7,50}", key, re.UNICODE) and not is_generic_hashtag(key) and not key.startswith("shorts") and
            not key.startswith("aigenerated") and not key.startswith("viral") and
            not key.isdigit()):
            out.add(key)
    return out


def actions(video: dict) -> set[str]:
    text = title_text(video)
    return {k for k,rx in ACTION_RE.items() if rx.search(text)}


def phrases(video: dict) -> set[tuple[str, str]]:
    """Named multiword fragments and uncommon hashtags; no generic 1-word trends."""
    words = title_terms(video)
    result = set()
    if len(words) >= 2:
        for width in (2, 3, 4):
            for start in range(len(words)-width+1):
                chunk = words[start:start+width]
                if not any(len(w) >= 5 or any(c.isdigit() for c in w) for w in chunk):
                    continue
                if all(w in SUBJECT_ONLY for w in chunk):
                    continue
                # Very long phrases are likely one-off descriptions, but can
                # become useful when genuinely repeated across different creators.
                result.add(("phrase"," ".join(chunk)))
    for tag in named_hashtags(video):
        result.add(("tag","#"+tag))
    return result


def role(video: dict) -> str:
    title = video.get("title") or ""
    if NEWS_OR_TUTORIAL.search(title):
        return "教程/新闻解说"
    if (video.get("ai_metadata_confidence") or "").lower() == "medium":
        return "作者文字自述AI"
    return "AI制作未验证"


def eligible(video, now):
    try:
        published = utc(video["published_at"])
        return (now-DAY <= published <= now+timedelta(minutes=5)
                and bool(video.get("channel_id")) and bool(video.get("url"))
                and not NEWS_OR_TUTORIAL.search(video.get("title") or ""))
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def source_is_fresh(state, now):
    scans = state.get("scans") or []
    if not scans or not state.get("first_success_at"):
        raise ValueError("No verified first-success history snapshot")
    recent = scans[-1]
    if not recent.get("successful_queries"):
        raise ValueError("Latest source snapshot has no successful queries")
    observed = utc(recent["time"])
    if not (timedelta(0) <= now-observed <= timedelta(hours=24)):
        raise ValueError("Source snapshot is stale or in the future")
    return recent["time"]


def old_known(video):
    return next((t["name"] for t in THEMES if t["known"] and matches_theme(video.get("title"),t)),None)


def main_caption_signature(video: dict) -> str:
    """Same uninformative pasted title on many channels is not fresh imitation."""
    t = unicodedata.normalize("NFKC", title_text(video)).casefold().replace("k/da", "kda")
    return " ".join(WORD.findall(t))


def candidate_excerpts(rows, limit=4):
    rows = sorted(rows,key=lambda x:(x.get("views") or 0),reverse=True)
    result=[]
    for v in rows[:limit]:
        result.append({
            "title":v.get("title"), "channel":v.get("channel"), "channel_id":v.get("channel_id"),
            "url":v["url"], "published_at":v["published_at"], "first_seen_at":v.get("first_seen_at"),
            "views":v.get("views"), "observed_growth_per_hour":observed_rate(v),
            "ai_evidence":role(v), "actions":sorted(actions(v))
        })
    return result


def compress_group(key, group, older_seen):
    channels = {v["channel_id"] for v in group}
    claimed = {v["channel_id"] for v in group if role(v)=="作者文字自述AI"}
    motion_sets = [actions(v) for v in group]
    common_action=set.intersection(*motion_sets) if motion_sets else set()
    known = sorted({old_known(v) for v in group if old_known(v)})
    signatures=Counter(main_caption_signature(v) for v in group)
    leading_caption_fraction=(max(signatures.values()) / len(group)) if group else 0
    likely_copied_caption=(len(group)>=2 and leading_caption_fraction>=0.95)

    # Repeated named actor/event is not evidence of one reusable *effect*.
    kind = ("known" if known else
            "possible_reuploads" if likely_copied_caption else
            "potential_same_action" if common_action and len(claimed)>=2 else
            "shared_phrase_only")
    # This is a human review *priority*, never a probability or SEO potential.
    peak = max((v.get("views") or 0 for v in group), default=0)
    positive_growth = max((max(0, observed_rate(v) or 0) for v in group),default=0)
    score = (min(32,16*len(channels))+
             min(28,14*len(claimed))+
             min(16,4*math.log10(max(peak,1)))+
             min(12,4*math.log10(max(positive_growth,1)))+
             (12 if kind=="potential_same_action" else 0))
    if kind=="known": score=0
    if kind=="shared_phrase_only": score=min(score,35)
    if kind=="possible_reuploads": score=min(score,12)
    return {
        "anchor":key[1], "anchor_type":key[0],
        "unique_channels":len(channels),
        "ai_claimed_channels":len(claimed),
        "video_count":len(group),
        "title_actions_shared":sorted(common_action),
        "classification":kind,
        "near_duplicate_caption_fraction":round(leading_caption_fraction,2),
        "previously_observed_older_video":bool(older_seen),
        "priority_points_not_seo_score":round(min(score,100),1),
        "examples":candidate_excerpts(group)
    }


def build(state, now):
    observed_at=source_is_fresh(state,now)
    pool=state.get("videos") or {}
    eligible_rows=[v for v in pool.values() if eligible(v,now)]
    by_phrase=defaultdict(dict)
    prior=defaultdict(set)
    for v in pool.values():
        if not v.get("channel_id") or not v.get("published_at"):
            continue
        try:
            is_old=utc(v["published_at"]) < now-DAY
        except (ValueError,TypeError):
            continue
        if is_old:
            for key in phrases(v):
                prior[key].add(v["channel_id"])
    for v in eligible_rows:
        for key in phrases(v):
            by_phrase[key][v["url"]]=v
    groups=[]
    for key,mapping in by_phrase.items():
        rows=list(mapping.values())
        creators={v["channel_id"] for v in rows}
        if len(creators) < 2:
            continue
        # Creator claims are not proof of an AI-generated video, but a
        # cross-creator lead requires at least two *independent* such claims.
        if len({v["channel_id"] for v in rows if role(v)=="作者文字自述AI"}) < 2:
            continue
        # One generic entity appearing in many unrelated titles should not be
        # called the same action. Keep it as shared-title evidence only.
        groups.append(compress_group(key,rows,prior.get(key,set())))
    groups.sort(key=lambda g: (
        3 if g["classification"]=="potential_same_action" else
        2 if g["classification"]=="shared_phrase_only" else
        1 if g["classification"]=="possible_reuploads" else 0,
        g["ai_claimed_channels"],g["unique_channels"],
        len(g["anchor"].split()),g["priority_points_not_seo_score"]),reverse=True)

    # Suppress overlapping n-grams with nearly identical evidence videos;
    # retain the longer, more specific anchor when it explains the same set.
    reduced=[]
    for candidate in groups:
        vids={v["url"] for v in candidate["examples"]}
        is_duplicate=any(
            c["classification"]==candidate["classification"] and
            len(vids.intersection({x["url"] for x in c["examples"]}))>=2 and
            (vids=={x["url"] for x in c["examples"]} or
             vids.issubset({x["url"] for x in c["examples"]}))
            for c in reduced)
        if not is_duplicate:
            reduced.append(candidate)
        if len(reduced)>=25:
            break

    singles=[]
    seen_channels=set()
    # Current inventory already includes a separate fixed dictionary of old
    # named formats; here we focus on as-yet-unmapped high-velocity originals.
    ordered=sorted(eligible_rows,key=lambda v:(
        max(0,observed_rate(v) or 0),(v.get("views") or 0)),reverse=True)
    for v in ordered:
        if role(v)!="作者文字自述AI":
            continue
        if old_known(v):
            continue
        if not len(title_terms(v))>=2:
            continue
        if (v.get("views") or 0)<4000:
            continue
        if v["channel_id"] in seen_channels:
            continue
        named=sorted(phrases(v),key=lambda k:(k[0]=="phrase",len(k[1].split()),len(k[1])),reverse=True)
        if not named:
            continue
        seen_channels.add(v["channel_id"])
        singles.append({
            **candidate_excerpts([v],1)[0],
            "suggested_search_phrase_unverified":named[0][1],
            "confidence":"单作者、作者自述AI；需核验画面和模仿",
            "historically_known_named_format":False,
        })
        if len(singles)>=12:
            break

    # Keep only the source-backed timestamps. No hypothesis about publication
    # before our first observation can be claimed from this database.
    return {
        "generated_at":now.isoformat(),
        "source_snapshot_at":observed_at,
        "source_video_count":len(pool),
        "published_last_24h_with_channel":len(eligible_rows),
        "shared_name_groups":len(reduced),
        "independent_claimed_and_same_action_candidates":sum(
            g["classification"]=="potential_same_action" for g in reduced),
        "confirmed_new_seo_keywords":0,
        "cross_creator_groups":reduced[:15],
        "high_velocity_single_creator_watchlist":singles,
    }


def clean(value):
    text = str(value if value is not None else "").replace("\n"," ").replace("\r"," ")
    for a,b in [("|","/"),("[","("),("]",")"),("<","‹"),(">","›")]:
        text=text.replace(a,b)
    return text[:155]


def report(info):
    rows=[
        "# AI Shorts 自动新玩法挖掘（动态提名，非已验证爆款）","",
        "- 最新成功快照（北京）："+bj(info["source_snapshot_at"]),
        f'- 数据库视频：{info["source_video_count"]}；24小时内且有频道ID的非教程候选：{info["published_last_24h_with_channel"]}',
        f'- 自动发现跨账号同名/同词线索：{info["shared_name_groups"]}',
        f'- 其中“同名+共同动作词+至少2个AI自述账号”：{info["independent_claimed_and_same_action_candidates"]}',
        "- 已独立核实的新 SEO 关键词：**0（需核验画面、模仿和 SERP）**","",
        "> **证据边界：** 自动挖掘的是“共同标题片段/标签”，不是视频画面或视觉内容的相似度。",
        "> 跨账号同名不等于同一特效或模仿；没有跨账号不能声称流行玩法扩散。",
        "> 作者标注 AI、播放量增长和 Shorts 时长均不单独证明 AI 生成或 SEO 需求。",
        "> 所有关键词均为待搜索表达，不能声称搜索量、首发时间或竞争程度。","",
        "## 自动发现的跨作者同名候选（最多15组）",""
    ]
    if not info["cross_creator_groups"]:
        rows.append("本轮没有足够具体且由两个独立作者共同使用的名字或标签。")
    for n,group in enumerate(info["cross_creator_groups"],1):
        verdict={"potential_same_action":"同名且有共同动作描述——优先人工比对镜头",
                 "shared_phrase_only":"仅同名/同题材——未确认同一效果",
                 "possible_reuploads":"多账号粘贴近似相同标题——疑似批量转发，未证实独立创作",
                 "known":"历史已有玩法——排除“今日首发”"}.get(group["classification"],"未核实")
        rows.extend([
            f'### {n}. {clean(group["anchor"])}',"",
            f'- 初判：{verdict}；历史快照里是否发现更早视频：{"是" if group["previously_observed_older_video"] else "未观察到（不等于新）"}',
            f'- 独立频道：{group["unique_channels"]}；其中AI文字自述频道：{group["ai_claimed_channels"]}；视频：{group["video_count"]}',
            f'- 相同动作词：{", ".join(group["title_actions_shared"]) or "无"}；主文案复用比例：{group["near_duplicate_caption_fraction"]:.0%}；人工复核优先级分：{group["priority_points_not_seo_score"]}/100（并非SEO评分）',
            "", "| 作者频道 | 原视频 | 发布时间（北京） | 本系统首见（北京） | 播放量 | 采样增速/小时 | AI证据 |",
            "|---|---|---|---|---:|---:|---|",
        ])
        for x in group["examples"]:
            growth=x["observed_growth_per_hour"]
            rows.append(
                f'| {clean(x["channel"])} | [{clean(x["title"])}]({x["url"]})'
                f' | {bj(x["published_at"])} | {bj(x["first_seen_at"])}'
                f' | {x["views"] if x["views"] is not None else "未知"}'
                f' | {f"{growth:,.1f}" if growth is not None else "待多次采样"}'
                f' | {x["ai_evidence"]} |'
            )
        rows.append("")
    rows+=["## 单作者高增长候选：下一步应该找独立模仿证据","",
           "| 作者 | 具体视频（原链接） | 原发布（北京） | 首见（北京） | 观看量 | 真实采样增速/时 |",
           "|---|---|---|---|---:|---:|"]
    for x in info["high_velocity_single_creator_watchlist"]:
        g=x["observed_growth_per_hour"]
        rows.append(f'| {clean(x["channel"])} | [{clean(x["title"])}]({x["url"]})'
                    f' | {bj(x["published_at"])} | {bj(x["first_seen_at"])} | {x["views"]}'
                    f' | {f"{g:,.1f}" if g is not None else "待二次采样"} |')
    if not info["high_velocity_single_creator_watchlist"]:
        rows.append("| — | 本轮没有达到基础条件的单作者候选 | — | — | — | — |")
    rows+=["","## 人工核验清单","",
           "从上表选择有具体可复制行为的候选，先**实际打开视频**：",
           "1. 是否真由 AI 生成？是否属于正式 Shorts？效果的动作/镜头能否从自有素材重现？",
           "2. 搜索同款名称和动作，找出**不同作者**发布的独立视频及其发布时间。",
           "3. 对比 Google 搜索、现有模板生成器及社媒标签，区分旧梗、老词变体和真正的机会。",
           "4. 核实授权、音乐、角色及人物肖像风险，才决定独立站/内页/观察/不做。","",
           "**自动结论：本轮没有经过人工视觉和 SERP 复核的“已确认新增 SEO 词”。**"]
    return "\n".join(rows)+"\n"


def run(root, now=None):
    now=now or datetime.now(timezone.utc)
    state_path=root/"data/state.json"
    if not state_path.exists():
        raise ValueError("No shorts successful state.json")
    state=json.loads(state_path.read_text(encoding="utf-8"))
    result=build(state,now)
    folder=root/"reports"
    folder.mkdir(parents=True,exist_ok=True)
    markdown=report(result)
    (folder/"emerging-latest.md").write_text(markdown,encoding="utf-8")
    (folder/"emerging-latest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    stamp=now.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    (folder/(stamp+"-emerging.md")).write_text(markdown,encoding="utf-8")
    summary={
        "cross_creator_named":result["shared_name_groups"],
        "common_action_and_ai_claim":result["independent_claimed_and_same_action_candidates"],
        "high_velocity_singles":len(result["high_velocity_single_creator_watchlist"]),
        "confirmed_new_seo_keywords":0
    }
    print(json.dumps(summary,ensure_ascii=False))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args()
    try:
        run(args.root)
    except (ValueError,FileNotFoundError) as exc:
        print("动态玩法报告未生成："+str(exc),file=sys.stderr)
        sys.exit(2)
