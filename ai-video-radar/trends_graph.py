#!/usr/bin/env python3
"""Free, bounded Google Trends Related Queries expansion for existing radar ledgers.

No Web.Cafe, paid API, proxy rotation, or claims of absolute search volume.
Default mode is offline planning. Use --execute for a few real HTTP Explore calls.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

STOP_RATE_LIMIT = ("ratelimiterror", "too many requests", "429", "403")


def norm(value):
    return " ".join(str(value or "").casefold().split())


def moment(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def ingest_seeds(graph, ledger, now):
    items = ledger.get("entities") or ledger.get("keywords") or {}
    nodes = graph.setdefault("nodes", {})
    added = 0
    for item in items.values():
        term = str(item.get("title") or item.get("keyword") or "").strip()
        key = norm(term)
        if not key or len(term) > 90 or len(term.split()) > 12:
            continue
        if key not in nodes:
            nodes[key] = {"keyword": term, "depth": 0, "parents": [],
                          "first_observed_at": item.get("first_observed_at") or
                                               item.get("first_observed_date") or now,
                          "status": "QUEUED", "last_checked_at": None,
                          "next_check_at": None, "rising": [], "top": [],
                          "interest_over_time": []}
            added += 1
    return added


def checkable(item, now, max_depth):
    if item.get("depth", 0) > max_depth:
        return False
    due = moment(item.get("next_check_at"))
    if due and now < due:
        return False
    return item.get("status") in ("QUEUED", "RATE_LIMITED", "FAILED")


def related_rows(result, field):
    related = result.get("related_queries") or {}
    value = related.get(field) if isinstance(related, dict) else []
    return [row for row in value if isinstance(row, dict) and str(row.get("query", "")).strip()]


def evaluate(graph, now_iso, fetcher=None, *, max_queries=3, max_depth=2,
             geo="US", timeframe="now 7-d"):
    now = moment(now_iso)
    if now is None:
        raise ValueError("valid UTC timestamp required")
    nodes = graph.setdefault("nodes", {})
    edges = graph.setdefault("edges", [])
    existing = {(e["parent"], e["child"], e["type"]) for e in edges}
    candidates = [(k, v) for k, v in nodes.items() if checkable(v, now, max_depth)]
    # Explore newly discovered child terms, but prioritize fresh roots before old backlog.
    candidates.sort(key=lambda pair: (pair[1].get("depth", 0),
                                      pair[1].get("first_observed_at", "")), reverse=True)
    attempted = success = new_terms = 0
    limited = False
    if fetcher is None:
        return {"attempted": 0, "success": 0, "new_terms": 0,
                "rate_limited": False, "queued": len(candidates), "mode": "DRY_RUN"}
    for key, node in candidates:
        if attempted >= max_queries:
            break
        attempted += 1
        try:
            result = fetcher(node["keyword"], geo, timeframe)
            if not isinstance(result, dict):
                raise ValueError("Explore provider returned non-dict")
            rising = related_rows(result, "rising")
            top = related_rows(result, "top")
            series = result.get("interest_over_time") or []
            node.update({"status": "CHECKED", "last_checked_at": now_iso,
                         "next_check_at": None, "rising": rising, "top": top,
                         "interest_over_time": series[-100:] if isinstance(series, list) else [],
                         "geo": geo, "timeframe": timeframe})
            success += 1
            if node["depth"] >= max_depth:
                continue
            for category, entries in (("rising", rising), ("top", top)):
                for row in entries:
                    text = str(row["query"]).strip()
                    child = norm(text)
                    if not child or child == key or len(text) > 100:
                        continue
                    if child not in nodes:
                        nodes[child] = {"keyword": text, "depth": node["depth"] + 1,
                                        "parents": [key], "first_observed_at": now_iso,
                                        "status": "QUEUED", "last_checked_at": None,
                                        "next_check_at": None, "rising": [], "top": [],
                                        "interest_over_time": []}
                        new_terms += 1
                    elif key not in nodes[child].get("parents", []):
                        nodes[child].setdefault("parents", []).append(key)
                    edgekey = (key, child, category)
                    if edgekey not in existing:
                        edges.append({"parent": key, "child": child, "type": category,
                                      "observed_at": now_iso,
                                      "formatted_value": row.get("formatted_value"),
                                      "value": row.get("value")})
                        existing.add(edgekey)
        except Exception as exc:
            error = str(exc).lower()
            limited_here = any(marker in error or marker in type(exc).__name__.lower()
                               for marker in STOP_RATE_LIMIT)
            node.update({"status": "RATE_LIMITED" if limited_here else "FAILED",
                         "last_checked_at": now_iso, "error": str(exc)[:200],
                         "next_check_at": (now + dt.timedelta(days=1 if limited_here else 2)).isoformat()})
            if limited_here:
                limited = True
                break  # Never hammer Google after an HTTP 429/403.
    return {"attempted": attempted, "success": success, "new_terms": new_terms,
            "rate_limited": limited,
            "queued": sum(checkable(v, now, max_depth) for v in nodes.values()),
            "mode": "LIVE_HTTP"}


def provider(keyword, geo, timeframe):
    from trendspyg import download_google_trends_explore
    return download_google_trends_explore(keyword, geo=geo, timeframe=timeframe,
                                         engine="http", cache="disk", max_retries=1,
                                         retry_wait=2.0)


def process(root, *, execute=False, max_queries=3):
    root = Path(root)
    data = root / "data"
    ledger_file = data / "research_ledger.json"
    if not ledger_file.exists():
        ledger_file = data / "keyword_ledger.json"
    ledger = json.loads(ledger_file.read_text(encoding="utf-8")) if ledger_file.exists() else {}
    graph_path = data / "trends_graph.json"
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        graph = {"schema_version": 1, "nodes": {}, "edges": []}
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    new_seeds = ingest_seeds(graph, ledger, now_iso)
    stats = evaluate(graph, now_iso, provider if execute else None, max_queries=max_queries)
    graph["last_run"] = {"checked_at": now_iso, "new_seeds": new_seeds, **stats}
    data.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Free Google Trends Related Queries graph", "",
             "Checked: " + now_iso, "",
             "- Mode: " + stats["mode"],
             "- New seed names imported: " + str(new_seeds),
             "- Provider calls attempted: " + str(stats["attempted"]),
             "- Successful requests: " + str(stats["success"]),
             "- New related-query nodes: " + str(stats["new_terms"]),
             "- Pending requests: " + str(stats["queued"]),
             "- Google throttled this run: " + str(stats["rate_limited"]),
             "- Total graph nodes: " + str(len(graph["nodes"])),
             "- Total parent-child edges: " + str(len(graph["edges"])), "",
             "A Google Trends relative-interest value is NOT search volume.",
             "A related search query is NOT itself a verified SEO or build opportunity.",
             "If a provider fails or returns no query, search demand is UNKNOWN, not zero.", "",
             "## Recent discovered related queries (display only)", ""]
    for e in graph["edges"][-20:]:
        lines.append("- {} -> {} ({}, {})".format(e["parent"], e["child"],
                     e["type"], e.get("formatted_value") or "growth not stated"))
    report = root / "reports" / "trends-graph-latest.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Trends graph:", graph["last_run"], "nodes", len(graph["nodes"]))
    return graph


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=Path(__file__).resolve().parent)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--max-queries", type=int, default=3)
    args = p.parse_args()
    if not 0 <= args.max_queries <= 10:
        p.error("--max-queries must be 0..10")
    process(args.root, execute=args.execute, max_queries=args.max_queries)


if __name__ == "__main__":
    main()
