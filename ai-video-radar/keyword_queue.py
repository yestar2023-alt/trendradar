#!/usr/bin/env python3
"""Lossless URL-to-keyword candidate inventory for the AI Video URL Delta Radar.

Page URLs are observations, not publication dates; proposed keywords are NOT
verified Google Trends queries. This module never makes network requests.
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
LEDGER = DATA / "keyword_ledger.json"
RESULT = REPORTS / "keyword-queue-latest.json"
AUDIT = REPORTS / "url-audit-latest.csv"
KEYWORDS = REPORTS / "keyword-queue-latest.csv"
SUMMARY = REPORTS / "keyword-queue-latest.md"
SKIP = {"create", "login", "signup", "pricing", "blog", "templates", "effects",
        "template", "video", "explore", "trending", "viral", "ai-video", "ai"}
STOP_TAILS = [
    ("-with-your-photo", ""), ("-from-your-photo", ""),
    ("-make-it-with-two-photos", ""), ("-prompts-for", "")
]


def read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def canonical(url):
    path = unquote(urlsplit(url).path)
    tail = path.rstrip("/").split("/")[-1].casefold()
    tail = html.unescape(tail).replace("_", "-")
    tail = re.sub(r"[^a-z0-9-]+", "-", tail)
    tail = re.sub(r"-+", "-", tail).strip("-")
    for suffix, replacement in STOP_TAILS:
        if tail.endswith(suffix):
            tail = tail[: -len(suffix)] + replacement
    return " ".join(tail.split("-")).strip()


def classify(row):
    url = row.get("url", "")
    name = canonical(url)
    path = urlsplit(url).path.lower()
    utype = (row.get("url_type") or "").lower()
    if not url or not name or name.replace(" ", "-") in SKIP or "/create/" in path or utype.startswith("create"):
        return "NOT_KEYWORD_CREATE_OR_NAV", name
    words = name.split()
    if len(words) >= 10 or len(name) > 85 or re.fullmatch(r"[0-9 ]+", name):
        return "PENDING_NAME_REVIEW", name
    if not any(token in path for token in ("/templates/", "/template/", "/video-effects/",
            "/ai-video/", "/ai/", "/meme/", "/effects/", "/effect/", "/blog/")):
        return "PENDING_NAME_REVIEW", name
    return "PENDING_TRENDS_VERIFICATION", name


def build(records, previous, observed_date):
    existing = previous.get("keywords") or {}
    keywords = {k: dict(v) for k, v in existing.items()}
    audits = []
    duplicate_urls = set()
    for row in records:
        url = (row.get("url") or "").strip()
        if not url or url in duplicate_urls:
            if url:
                audits.append({"url": url, "source": row.get("source", ""), "keyword": "",
                               "status": "DUPLICATE_URL_IN_BATCH", "observation": "duplicate"})
            continue
        duplicate_urls.add(url)
        status, phrase = classify(row)
        source = row.get("source", "")
        audits.append({"url": url, "source": source, "keyword": phrase,
                       "status": status, "observation": row.get("observation", "")})
        if status == "NOT_KEYWORD_CREATE_OR_NAV":
            continue
        key = phrase
        item = keywords.get(key)
        if item is None:
            item = {"keyword": phrase, "first_observed_date": row.get("first_observed_date") or observed_date,
                    "last_observed_date": observed_date, "review_status": status,
                    "trends_status": "NOT_CHECKED", "serp_status": "NOT_CHECKED",
                    "sources": [], "evidence": []}
            keywords[key] = item
        item["last_observed_date"] = observed_date
        if source and source not in item["sources"]:
            item["sources"].append(source)
        if not any(e["url"] == url for e in item["evidence"]):
            item["evidence"].append({"url": url, "source": source,
                "first_observed_date": row.get("first_observed_date") or observed_date,
                "channel": row.get("channel", "")})
        # Never reset an explicitly reviewed status when another URL appears.
        if item["review_status"] == "PENDING_NAME_REVIEW" and status == "PENDING_TRENDS_VERIFICATION":
            item["review_status"] = status
    items = sorted(keywords.values(), key=lambda x: (
        len(x.get("sources", [])), x.get("last_observed_date", ""), x["keyword"]), reverse=True)
    return {"checked_date": observed_date, "input_url_rows": len(records),
            "unique_urls_in_batch": len(duplicate_urls),
            "audited_url_rows": len(audits), "unique_keywords_in_ledger": len(items),
            "pending_trends": sum(x.get("trends_status") != "VERIFIED" for x in items),
            "keywords": {x["keyword"]: x for x in items},
            "audits": audits,
            "note": "All URLs are classified; only candidate slug phrases, not proven search terms."}


def latest_csv_date():
    files = sorted(REPORTS.glob("????-??-??-all-new-urls.csv"))
    if not files:
        return None, None
    path = files[-1]
    return path, path.name[:10]


def render(result):
    DATA.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    ledger = {k: v for k, v in result.items() if k != "audits"}
    text = json.dumps(ledger, ensure_ascii=False, indent=2) + "\n"
    LEDGER.write_text(text, encoding="utf-8")
    RESULT.write_text(text, encoding="utf-8")
    with AUDIT.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=["url", "source", "keyword", "status", "observation"])
        writer.writeheader()
        writer.writerows(result["audits"])
    with KEYWORDS.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=["keyword", "first_observed_date", "review_status",
            "trends_status", "serp_status", "source_count", "sources", "evidence_urls"])
        writer.writeheader()
        for value in result["keywords"].values():
            writer.writerow({"keyword": value["keyword"],
                "first_observed_date": value["first_observed_date"], "review_status": value["review_status"],
                "trends_status": value["trends_status"], "serp_status": value["serp_status"],
                "source_count": len(value["sources"]), "sources": "|".join(value["sources"]),
                "evidence_urls": "|".join(e["url"] for e in value["evidence"])})
    lines = ["# AI Video complete URL and keyword inventory", "",
             "Report date: **{}**".format(result["checked_date"]), "",
             "- URL rows reviewed: **{}**".format(result["input_url_rows"]),
             "- Distinct URL observations: **{}**".format(result["unique_urls_in_batch"]),
             "- Keyword candidates preserved (including earlier scans): **{}**".format(result["unique_keywords_in_ledger"]),
             "- Keywords without verified Trends evidence: **{}**".format(result["pending_trends"]), "",
             "The short daily Top 30 display is not the full candidate universe.",
             "Full URL coverage: url-audit-latest.csv. Full keyword coverage: keyword-queue-latest.csv.",
             "No Google Trends, SERP, or original website publication dates were inferred.", "",
             "## High priority for next verification (display only)", ""]
    for item in list(result["keywords"].values())[:20]:
        lines.append("- **{}** — {} sources · {} · {}".format(
            item["keyword"], len(item["sources"]), item["review_status"],
            item["evidence"][0]["url"] if item["evidence"] else ""))
    SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    path, day = latest_csv_date()
    if path is None:
        raise SystemExit("No YYYY-MM-DD-all-new-urls.csv exists; run the URL radar first.")
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    previous = read(LEDGER, {})
    # Never mistake an earlier day's raw file for a fresh current-day delta.
    result = build(rows, previous, day)
    render(result)
    print("ai-video keyword queue:", result["unique_urls_in_batch"], "URLs,",
          result["unique_keywords_in_ledger"], "keyword candidates; report date", day)


if __name__ == "__main__":
    main()
