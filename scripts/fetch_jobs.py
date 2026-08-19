#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_jobs.py
=============
每日抓取 AI for Materials 相关职位（业界 / 教职 / 博后 / 博士）。

数据来源：
  1. RSS/XML feeds (免费，无需认证)
  2. Claude API + web_search (与 fetch_content.py 保持一致)

环境变量:
  ANTHROPIC_API_KEY  必需 (Claude 搜索时)
  ANTHROPIC_MODEL    可选，默认 claude-sonnet-4-5

输出:
  data/jobs_latest.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
TZ = ZoneInfo("America/Toronto")

# ---------------------------------------------------------------------------
# RSS feed sources (free, no auth needed)
# ---------------------------------------------------------------------------
JOB_FEEDS: dict[str, list[str]] = {
    "faculty": [
        "https://www.jobs.ac.uk/feeds/rss/?keywords=machine+learning+materials&type=academic",
        "https://euraxess.ec.europa.eu/jobs/rss",
    ],
    "postdoc": [
        "https://www.jobs.ac.uk/feeds/rss/?keywords=postdoc+machine+learning+materials",
        "https://euraxess.ec.europa.eu/jobs/rss",
    ],
    "phd": [
        "https://www.jobs.ac.uk/feeds/rss/?keywords=phd+machine+learning+materials",
    ],
    "industry": [],  # Claude search only for industry
}

# Keywords to filter RSS entries — must contain at least one
_KEYWORDS = [
    "material", "catalyst", "crystal", "battery", "alloy", "polymer",
    "nanomaterial", "computational", "ML", "machine learning", "deep learning",
    "AI", "artificial intelligence", "perovskite", "electrolyte", "electrode",
    "synthesis", "density functional", "DFT", "force field", "molecular dynamics",
]

# Claude web-search queries per category
_CLAUDE_QUERIES: dict[str, str] = {
    "industry": (
        "AI materials scientist OR machine learning materials engineer 2025 2026 "
        "hiring job opening site:careers.microsoft.com OR site:deepmind.com OR "
        "site:research.google OR site:jobs.lever.co OR site:greenhouse.io"
    ),
    "faculty": (
        "assistant professor AI machine learning materials science 2025 2026 "
        "job opening tenure track"
    ),
    "postdoc": (
        "postdoc postdoctoral AI machine learning materials science 2025 2026 "
        "position opening"
    ),
    "phd": (
        "PhD student position AI machine learning materials science 2025 2026 "
        "funded opening"
    ),
}

MAX_PER_CATEGORY = 8
_USER_AGENT = "Mozilla/5.0 (compatible; AI-Progress-Bot/1.0; +https://github.com/Yang1Bai/ai-progress-site)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contains_keyword(text: str) -> bool:
    lower = text.lower()
    return any(kw.lower() in lower for kw in _KEYWORDS)


def _safe_get(url: str, timeout: int = 10) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"[fetch_jobs] WARNING: could not fetch {url}: {e}", flush=True)
        return None


def _extract_text(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return (elem.text or "").strip()


def _parse_rss_entry(item: ET.Element, ns: dict[str, str]) -> dict | None:
    """Parse a single RSS <item> element into a job dict."""
    title = _extract_text(item.find("title"))
    link = _extract_text(item.find("link"))
    desc = _extract_text(item.find("description"))
    pub_date = _extract_text(item.find("pubDate"))

    # fallback: dc:date
    if not pub_date:
        dc_date = item.find("dc:date", ns)
        if dc_date is not None:
            pub_date = _extract_text(dc_date)

    # author / org: try dc:creator or author
    org = ""
    dc_creator = item.find("dc:creator", ns)
    if dc_creator is not None:
        org = _extract_text(dc_creator)
    if not org:
        author_el = item.find("author")
        org = _extract_text(author_el)

    combined = f"{title} {desc}"
    if not _contains_keyword(combined):
        return None

    # Parse date to iso
    deadline = ""
    if pub_date:
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT",
                    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(pub_date[:31], fmt)
                deadline = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    # Extract tags from title
    tags = []
    for kw in ["machine learning", "AI", "deep learning", "materials", "postdoc",
               "PhD", "faculty", "industry", "computational", "DFT"]:
        if kw.lower() in combined.lower():
            tags.append(kw)
    tags = tags[:4]

    return {
        "title": title or "Untitled",
        "org": org or "—",
        "location": "",
        "url": link or "#",
        "deadline": deadline,
        "tags": tags,
        "source": "rss",
    }


def _fetch_rss_category(category: str) -> list[dict]:
    """Fetch and filter RSS feeds for one category."""
    results: list[dict] = []
    seen_urls: set[str] = set()

    NS = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "atom": "http://www.w3.org/2005/Atom",
    }

    for url in JOB_FEEDS.get(category, []):
        raw = _safe_get(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f"[fetch_jobs] XML parse error for {url}: {e}", flush=True)
            continue

        # Handle both RSS <item> and Atom <entry>
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for item in items:
            try:
                entry = _parse_rss_entry(item, NS)
                if entry is None:
                    continue
                job_url = entry["url"]
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                results.append(entry)
            except Exception as e:
                print(f"[fetch_jobs] entry parse error: {e}", flush=True)

    return results


# ---------------------------------------------------------------------------
# Claude web_search integration
# ---------------------------------------------------------------------------

def _fetch_claude_category(category: str, query: str) -> list[dict]:
    """Use Claude API with web_search to find job listings for one category."""
    try:
        import anthropic  # type: ignore
    except ImportError:
        print("[fetch_jobs] WARNING: anthropic SDK not installed, skipping Claude search", flush=True)
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[fetch_jobs] WARNING: ANTHROPIC_API_KEY not set, skipping Claude search", flush=True)
        return []

    client = anthropic.Anthropic(api_key=api_key)

    prompt = (
        f"Search the web for current {category} job openings in AI for materials science "
        f"(including machine learning for materials, computational materials science, AI-driven materials discovery).\n\n"
        f"Search query: {query}\n\n"
        "Output ONLY a raw JSON array. No markdown, no explanation, no code fences. "
        "Start your response with [ and end with ]. "
        "Each element must follow this exact schema:\n"
        '{"title": "Job Title", "org": "University or Company", "location": "City, Country", '
        '"url": "https://...", "deadline": "YYYY-MM-DD", "tags": ["ML", "materials"]}\n\n'
        "Rules:\n"
        "- Only include real, verifiable openings posted in 2025 or 2026\n"
        "- If deadline is unknown, use \"open\"\n"
        "- If a field is unknown, use empty string \"\"\n"
        "- Return at most 6 items\n"
        "- Escape all quotes inside string values properly"
    )

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        print(f"[fetch_jobs] Claude API error for {category}: {e}", flush=True)
        return []

    # Extract text from response
    full_text = ""
    for block in resp.content:
        if hasattr(block, "text"):
            full_text += block.text

    # Try to parse JSON array from response
    try:
        from json_repair import repair_json  # already installed in workflow
        _json_repair_available = True
    except ImportError:
        _json_repair_available = False

    # 1. Try ```json code block first
    block_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", full_text, re.DOTALL)
    # 2. Fall back to bare array
    array_match = re.search(r"\[[\s\S]*?\]", full_text)

    raw_json = None
    if block_match:
        raw_json = block_match.group(1)
    elif array_match:
        raw_json = array_match.group(0)

    if raw_json:
        try:
            if _json_repair_available:
                raw_json = repair_json(raw_json)
            items = json.loads(raw_json)
            results = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                item["source"] = "claude"
                if "tags" not in item or not isinstance(item["tags"], list):
                    item["tags"] = []
                results.append(item)
            return results
        except (json.JSONDecodeError, Exception) as e:
            print(f"[fetch_jobs] Could not parse Claude response for {category}: {e}", flush=True)

    return []


# ---------------------------------------------------------------------------
# Main fetch function
# ---------------------------------------------------------------------------

def fetch_jobs(today_dt: datetime | None) -> dict:
    """
    Fetch AI-for-materials job listings from RSS feeds + Claude web_search.
    Returns a dict compatible with the jobs_latest.json schema.
    """
    if today_dt is None:
        today_dt = datetime.now(TZ)
    today_iso = today_dt.strftime("%Y-%m-%d")

    jobs: dict[str, list[dict]] = {
        "industry": [],
        "faculty": [],
        "postdoc": [],
        "phd": [],
    }

    category_map = {
        "industry": "industry",
        "faculty": "faculty",
        "postdoc": "postdoc",
        "phd": "phd",
    }

    # 1. Fetch from RSS feeds
    print("[fetch_jobs] Fetching RSS feeds...", flush=True)
    for cat in jobs:
        try:
            rss_results = _fetch_rss_category(cat)
            jobs[cat].extend(rss_results)
            print(f"[fetch_jobs] RSS {cat}: {len(rss_results)} entries", flush=True)
        except Exception as e:
            print(f"[fetch_jobs] WARNING: RSS fetch failed for {cat}: {e}", flush=True)

    # 2. Fetch from Claude web_search
    print("[fetch_jobs] Fetching via Claude web_search...", flush=True)
    for cat, query in _CLAUDE_QUERIES.items():
        try:
            claude_results = _fetch_claude_category(cat, query)
            # Deduplicate by URL
            seen = {j["url"] for j in jobs[cat]}
            for item in claude_results:
                if item.get("url", "#") not in seen:
                    jobs[cat].append(item)
                    seen.add(item["url"])
            print(f"[fetch_jobs] Claude {cat}: {len(claude_results)} entries", flush=True)
        except Exception as e:
            print(f"[fetch_jobs] WARNING: Claude search failed for {cat}: {e}", flush=True)

    # 3. Sort by deadline (most recent first), cap at MAX_PER_CATEGORY
    for cat in jobs:
        def sort_key(j: dict) -> str:
            d = j.get("deadline", "")
            # Put entries with valid ISO dates first (descending), others last
            if d and re.match(r"\d{4}-\d{2}-\d{2}", d):
                return "0_" + d
            return "1_" + d
        jobs[cat] = sorted(jobs[cat], key=sort_key, reverse=True)[:MAX_PER_CATEGORY]

    result = {
        "date": today_iso,
        "jobs": jobs,
    }

    # 4. Save to data/jobs_latest.json
    try:
        DATA_DIR.mkdir(exist_ok=True)
        out_path = DATA_DIR / "jobs_latest.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[fetch_jobs] Saved {out_path}", flush=True)
    except Exception as e:
        print(f"[fetch_jobs] WARNING: could not save jobs_latest.json: {e}", flush=True)

    return result


if __name__ == "__main__":
    data = fetch_jobs(None)
    print(json.dumps(data, ensure_ascii=False, indent=2)[:800])
