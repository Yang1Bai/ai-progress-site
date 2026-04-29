#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_content.py
================
通过 Claude API + web_search，每日为 ai-progress-site 抓取四段最新内容：
  1. AI 大佬观点 (leaders)
  2. 今日 AI 大事 (news)  ← 每条带原文链接
  3. AI4Science 进展 (science)
  4. AI4Material 论文 (papers)  ← 严格材料领域过滤
  5. 本周模型动态 (models)  ← 新增

同时：
  - 保存原始 JSON 到 data/YYYY-MM-DD.json + data/latest.json
  - 更新 data/index.json（归档日期列表）
  - 生成 feed.xml（RSS/Atom 订阅）
  - 保存今日快照到 archive/YYYY-MM-DD.html
  - 重建 archive/index.html（归档目录页）

环境变量:
  ANTHROPIC_API_KEY  必需
  ANTHROPIC_MODEL    可选, 默认 claude-sonnet-4-5
  DRY_RUN            可选, 设为 1 跳过 API 调用，用本地 mock 验证替换逻辑
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from icons import NEWS_ICONS, SCIENCE_ICONS, LINK_SVG  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
DATA_DIR = ROOT / "data"
ARCHIVE_DIR = ROOT / "archive"
FEED = ROOT / "feed.xml"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
TZ = ZoneInfo("America/Toronto")

# ---------------------------------------------------------------------------
# 1. Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "你是 AI 行业资讯编辑。你必须仅输出符合给定 JSON Schema 的结果，"
    "不能在 JSON 之外写任何字符。全部正文使用中文（简体）。"
    "重要术语可保留英文原名。"
)

USER_PROMPT_TEMPLATE = """今天是 {today}（北美东部时区）。请用 web_search 工具搜索过去 1-7 天的最新 AI 资讯与论文，然后输出包含五个区块的 JSON。

要求：
1. **leaders**：3 位 AI 行业领袖最近 1-2 周的公开观点。优先 OpenAI / Anthropic / Google DeepMind / Meta / xAI / 微软 / 英伟达 / 阿里 / 字节 / 智谱 等公司高管或知名研究者。每位提供：
   - name (中文姓名), name_en (英文姓名), role (职位)
   - quote (代表性中文一句话, <30 字)
   - body (1-2 句中文背景说明)
   - tags (1-3 个短标签), initials (英文姓名缩写 2 字母大写)
   - quote_date (言论发表日期，格式 "M月D日"，如 "4月26日"；如不确定则写 "近期")

2. **news**：8-10 条今日（或过去 24-48 小时）AI 重要新闻。每条提供：
   - title (可省略, 留空字符串)
   - body (一句完整中文新闻概述, 30-60 字, 可包含 <strong>...</strong> 标签突出关键词，但只能使用 <strong>)
   - url (该新闻的原文链接，必须是真实存在的 https:// URL；如实在无法确认链接则留空字符串 "")
   - importance ("breaking" | "major" | "normal"): breaking=突破性头条(每次最多1条), major=重磅消息, normal=普通资讯
   - tags (1-2 个话题标签列表，从以下选择: ["#LLM", "#多模态", "#机器人", "#安全", "#芯片", "#材料", "#生物", "#政策", "#开源", "#Agent"])

3. **science**：5-6 条最近 AI4Science 进展。每条提供：
   - title (短标题, 中文 <15 字)
   - body (1-2 句中文说明, 40-80 字)

5. **benchmarks**：当前 5-7 个最顶级 AI 大模型的主要基准分数（基于 web_search 最新数据）。每个：
   - model (模型名), org (机构简称), mmlu (MMLU 百分比, 如 "91.2"), math (MATH 百分比), humaneval (HumanEval 百分比), notes (1句亮点说明)
   - 如某项无公开数据，填 "N/A"

6. **conferences**：未来 3 个月内 AI/ML 顶级会议的重要截止日期（论文提交或通知截止）。每个：
   - name (会议名, 如 "NeurIPS 2026"), event_type ("submission"|"notification"|"camera_ready"), deadline ("YYYY-MM-DD"), url (官网), days_left (距今天 {today} 的天数, 整数)
   - 只列真实的、已公布的截止日期，不要猜测

4. **papers**：6-8 篇过去 7 天的 AI4Material（AI 用于材料科学/化学/能源/催化）相关论文，必须真实存在。
   严格定义：论文核心必须是 AI/ML 方法用于以下任一方向：
   ① 材料发现、合成预测、性质预测（晶体、合金、聚合物、多孔材料等）
   ② 催化剂设计与优化
   ③ 电池材料、能源存储材料
   ④ 药物分子/蛋白质设计（与材料交叉的）
   ⑤ 腐蚀、缺陷、界面分析
   排除：纯 NLP/CV/LLM 优化（如量化、压缩、RAG）、机器人运动控制、通用代码生成——这些不是 AI4Material。

   来源覆盖：
   - Nature 正刊和大子刊（Nature / Nature Materials / Nature Chemistry / Nature Energy / Nature Catalysis / Nature Nanotechnology / Nature Synthesis / Nature Machine Intelligence / Nature Communications / Nature Computational Science 等）
   - Science 正刊和子刊（Science / Science Advances 等）
   - 计算机/机器学习顶会论文（NeurIPS / ICML / ICLR / KDD / AAAI / IJCAI 等的最新公开论文，含 OpenReview / arXiv）

   每篇提供：
   - venue_type ("nature" | "science" | "conf"), venue (期刊或会议短名)
   - title (论文英文原标题)
   - authors ("Smith J. et al." 格式)
   - summary (1-2 句中文要点, 40-80 字, 重点说明 AI 方法 + 材料应用)
   - date ("YYYY-MM-DD"), url (DOI / 会议 / arXiv 链接)
   - is_week_pick (true | false): 每次只能有 1 篇为 true，选出本周最重要的材料 AI 论文

5. **models**：本周发布或更新的 top AI 模型，4-6 个条目。每个提供：
   - name (模型名称), org (机构全名), org_short (机构缩写 2-4 字母大写)
   - release_date ("YYYY-MM-DD"), highlight (一句中文亮点 <20 字)
   - tier ("S" | "A" | "B"): S=顶级旗舰, A=强力, B=实用

关键约束：
- 必须基于 web_search 结果，不要编造不存在的论文或链接
- 数量不够时宁可减少条目（papers 最少 2 篇也可以），不要强行凑数
- 可放宽到过去两周，实在没有某类内容则返回空数组 []
- 新闻 url 不确定则留空字符串
- **无论如何都必须输出完整 JSON，绝对不允许输出解释文字或拒绝消息**

输出 JSON Schema：
{{
  "date": "YYYY年M月D日",
  "leaders": [{{ "name": "...", "name_en": "...", "role": "...", "quote": "...", "body": "...", "tags": ["..."], "initials": "AB", "quote_date": "M月D日" }}],
  "news": [{{ "title": "", "body": "...", "url": "https://...", "importance": "normal", "tags": ["#LLM"] }}],
  "science": [{{ "title": "...", "body": "..." }}],
  "papers": [{{ "venue_type": "nature", "venue": "...", "title": "...", "authors": "...", "summary": "...", "date": "YYYY-MM-DD", "url": "https://...", "is_week_pick": false }}],
  "models": [{{ "name": "...", "org": "...", "org_short": "OAI", "release_date": "YYYY-MM-DD", "highlight": "...", "tier": "A" }}],
  "benchmarks": [{{ "model": "...", "org": "...", "mmlu": "91.2", "math": "88.3", "humaneval": "91.2", "notes": "..." }}],
  "conferences": [{{ "name": "...", "event_type": "submission", "deadline": "YYYY-MM-DD", "url": "https://...", "days_left": 18 }}]
}}

只输出 JSON，不要 ```json 代码块包裹，不要任何前后说明文字。"""


# ---------------------------------------------------------------------------
# 2. 调用 Claude API
# ---------------------------------------------------------------------------

def call_claude(today: str) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    user_prompt = USER_PROMPT_TEMPLATE.format(today=today)
    print(f"[claude] model={MODEL}  date={today}", flush=True)

    msg = client.messages.create(
        model=MODEL,
        max_tokens=6000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 12,
        }],
    )

    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    raw = "".join(parts).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    s = raw.find("{")
    e = raw.rfind("}")
    if s == -1 or e == -1:
        raise RuntimeError(f"Claude 未返回 JSON: {raw[:500]}")
    candidate = raw[s : e + 1]
    # 先尝试直接解析
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # 兜底：用 json-repair 修复常见问题（未转义引号、多余逗号等）
    try:
        from json_repair import repair_json
        repaired = repair_json(candidate)
        return json.loads(repaired)
    except Exception:
        pass
    # 最后兜底：去掉控制字符后再试
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', candidate)
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# 3. 渲染
# ---------------------------------------------------------------------------

LEADER_VARIANTS = ["em", "sa", "aj"]


def escape_text(s: str) -> str:
    if s is None:
        return ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def sanitize_strong(s: str) -> str:
    if not s:
        return ""
    safe = escape_text(s)
    return (safe.replace("&lt;strong&gt;", "<strong>")
                .replace("&lt;/strong&gt;", "</strong>"))


# Source credibility inference
_OFFICIAL_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "meta.com", "microsoft.com",
    "nvidia.com", "blogs.nvidia.com", "ai.google", "blog.google", "research.google",
    "mistral.ai", "cohere.com", "ai.sony", "ai.meta.com",
}
_PAPER_DOMAINS = {
    "nature.com", "science.org", "cell.com", "acs.org", "wiley.com", "springer.com",
    "pubs.acs.org", "onlinelibrary.wiley.com", "advanced.onlinelibrary.wiley.com",
    "pnas.org", "sciencemag.org", "rsc.org", "iopscience.iop.org",
}
_PREPRINT_DOMAINS = {"arxiv.org", "biorxiv.org", "chemrxiv.org", "openreview.net"}
_MEDIA_DOMAINS = {
    "bloomberg.com", "reuters.com", "techcrunch.com", "wired.com", "theverge.com",
    "wsj.com", "nytimes.com", "bbc.com", "cnn.com", "ft.com", "economist.com",
    "arstechnica.com", "euronews.com", "technologyreview.com",
}
_BLOG_DOMAINS = {"substack.com", "medium.com", "huggingface.co", "marketingprofs.com", "sciencedaily.com"}


def infer_source_type(url: str) -> str:
    """Infer the source credibility type from a URL."""
    if not url or not url.startswith("http"):
        return "Unknown"
    try:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return "Unknown"
    # Check "blog" in URL path/host
    if "blog" in url.lower():
        return "Blog"
    for domain in _OFFICIAL_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return "Official"
    for domain in _PAPER_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return "Paper"
    for domain in _PREPRINT_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return "Preprint"
    for domain in _MEDIA_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return "Major media"
    for domain in _BLOG_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return "Blog"
    return "Unknown"


def render_leaders(items):
    out = []
    for i, it in enumerate(items[:3]):
        cls = LEADER_VARIANTS[i % 3]
        ini = (it.get("initials") or "AI")[:2].upper()
        tags_html = "".join(
            f'<span class="tag">{escape_text(t)}</span>'
            for t in (it.get("tags") or [])[:3]
        )
        quote_date = it.get("quote_date", "")
        date_badge = f'<span class="tag tag-date">{escape_text(quote_date)}</span>' if quote_date else ""
        out.append(f'''      <article class="leader-card reveal">
        <div class="leader-head">
          <div class="avatar {cls}" aria-hidden="true">{escape_text(ini)}</div>
          <div>
            <div class="leader-name">{escape_text(it.get("name", ""))} ({escape_text(it.get("name_en", ""))})</div>
            <div class="leader-role">{escape_text(it.get("role", ""))}</div>
          </div>
        </div>
        <blockquote class="leader-quote">"{escape_text(it.get("quote", ""))}"</blockquote>
        <p class="leader-body">{escape_text(it.get("body", ""))}</p>
        <div class="leader-meta">{tags_html}{date_badge}</div>
      </article>''')
    return "\n".join(out)



# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def fetch_og_image(url: str, timeout: int = 5):
    """Fetch og:image from a URL. Returns image URL or None."""
    if not url or not url.startswith('http'):
        return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read(32768).decode('utf-8', errors='ignore')
        # Try og:image
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']( https?://[^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if m:
            v = m.group(1).strip()
            if v.startswith('http'):
                return v
        # Try og:image with reversed attribute order
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I)
        if m:
            v = m.group(1).strip()
            if v.startswith('http'):
                return v
        # Try twitter:image
        m = re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if m:
            v = m.group(1).strip()
            if v.startswith('http'):
                return v
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']', html, re.I)
        if m:
            v = m.group(1).strip()
            if v.startswith('http'):
                return v
        return None
    except Exception:
        return None


# Keyword map for Unsplash: Chinese/English terms → English Unsplash search terms
_UNSPLASH_KW_MAP = [
    ("OpenAI", "OpenAI artificial intelligence"),
    ("Anthropic", "Anthropic artificial intelligence"),
    ("Google", "Google technology research"),
    ("DeepSeek", "deep learning neural network"),
    ("Meta", "Meta artificial intelligence"),
    ("xAI", "artificial intelligence technology"),
    ("Grok", "artificial intelligence technology"),
    ("Gemini", "Google AI research"),
    ("GPT", "OpenAI language model"),
    ("Claude", "Anthropic AI model"),
    ("NASA", "NASA space technology robot"),
    ("\u706b\u661f", "Mars space robot"),          # 火星
    ("\u673a\u5668\u4eba", "robot automation"),     # 机器人
    ("\u82af\u7247", "semiconductor chip technology"),  # 芯片
    ("\u7535\u529b", "power energy data center"),   # 电力
    ("\u6838\u7535", "nuclear power energy"),        # 核电
    ("\u5b89\u5168", "AI safety security"),           # 安全
    ("\u76d1\u7ba1", "AI regulation policy"),         # 监管
    ("\u6cd5\u89c4", "AI regulation policy"),         # 法规
    ("\u79d1\u5b66", "science research laboratory"),  # 科学
    ("\u6750\u6599", "materials science laboratory"), # 材料
    ("\u751f\u7269", "biology research laboratory"),  # 生物
    ("\u533b\u7597", "medical healthcare AI"),        # 医疗
    ("\u6295\u8d44", "investment finance technology"), # 投资
    ("\u521b\u4e1a", "startup technology innovation"), # 创业
]
_DEFAULT_UNSPLASH_KW = "artificial intelligence technology"


def _extract_unsplash_keywords(text: str) -> str:
    """Extract Unsplash-friendly English keywords from a news body/title string."""
    for trigger, keywords in _UNSPLASH_KW_MAP:
        if trigger.lower() in text.lower():
            return keywords
    return _DEFAULT_UNSPLASH_KW


def search_news_image(query: str, timeout: int = 5) -> str:
    """Return a source.unsplash.com URL for relevant stock photo. No API key needed."""
    try:
        keywords = _extract_unsplash_keywords(query)
        encoded = urllib.parse.quote(keywords)
        return f"https://source.unsplash.com/800x450/?{encoded}"
    except Exception:
        return "https://source.unsplash.com/800x450/?artificial+intelligence"


def get_card_image_url(url: str, fallback_text: str) -> str:
    """Try og:image first, then Unsplash fallback. Never returns None."""
    img = fetch_og_image(url)
    if img:
        return img
    return search_news_image(fallback_text)


# Topic emoji mapping for headline card image placeholder
TOPIC_ICONS = [
    ("OpenAI", "\U0001f916", "OpenAI"),
    ("Google", "\U0001f50d", "Google"),
    ("Anthropic", "\U0001f9e0", "Anthropic"),
    ("release", "\u26a1", "Release"),
    ("launch", "\u26a1", "Launch"),
    ("\u53d1\u5e03", "\u26a1", "Release"),
    ("safety", "\U0001f6e1\ufe0f", "Safety"),
    ("\u5b89\u5168", "\U0001f6e1\ufe0f", "Safety"),
    ("research", "\U0001f52c", "Research"),
    ("\u7814\u7a76", "\U0001f52c", "Research"),
    ("regulation", "\u2696\ufe0f", "Policy"),
    ("\u76d1\u7ba1", "\u2696\ufe0f", "Policy"),
    ("\u6cd5\u89c4", "\u2696\ufe0f", "Policy"),
]
DEFAULT_TOPIC_ICON = ("\U0001f4e1", "AI News")


def get_topic_icon(text: str):
    """Return (emoji, label) based on text content."""
    t = text.lower()
    for keyword, emoji, label in TOPIC_ICONS:
        if keyword.lower() in t:
            return emoji, label
    return DEFAULT_TOPIC_ICON


def get_badge_class(title: str, body: str) -> str:
    """Determine badge class from title+body text."""
    combined = (title or "") + " " + (body or "")
    breaking_kws = ["\u7a81\u7834", "\u9996\u6b21", "\u53d1\u5e03", "launch", "release"]
    major_kws = ["\u8b66\u544a", "\u76d1\u7ba1", "\u6cd5\u89c4"]
    for kw in breaking_kws:
        if kw in combined:
            return "breaking"
    for kw in major_kws:
        if kw in combined:
            return "major"
    return "update"


def render_news(items):
    out = []
    # Find first breaking item or use index 0 as headline
    headline_idx = 0
    for i, it in enumerate(items[:10]):
        if it.get("importance") == "breaking":
            headline_idx = i
            break

    for i, it in enumerate(items[:10]):
        body = sanitize_strong(it.get("body", ""))
        url = (it.get("url") or "").strip()
        tags = it.get("tags") or []
        tags_str = escape_text(",".join(tags))
        # Stable bookmark id from body text
        bm_id = escape_text(re.sub(r'[^\w]', '', (it.get('body') or ''))[:24])
        bookmark_btn = '<button class="bookmark-btn" onclick="toggleBookmark(this)" title="\u6536\u85cf">\u2606</button>'
        source_link = ""
        src_type = infer_source_type(url)
        src_cls = src_type.lower().replace(" ", "-")
        src_badge = f'<span class="src-badge src-{src_cls}">{escape_text(src_type)}</span>'
        if url.startswith(("http://", "https://")):
            source_link = f'{src_badge}<a class="card-source-link" href="{escape_text(url)}" target="_blank" rel="noopener">\u539f\u6587 \u2197</a>'
        else:
            source_link = src_badge

        # Determine badge
        importance = it.get("importance", "normal")
        raw_title = it.get("title") or ""
        badge_cls = get_badge_class(raw_title, it.get("body", ""))
        if importance == "breaking":
            badge_cls = "breaking"
        elif importance == "major" and badge_cls == "update":
            badge_cls = "major"
        badge_label = {"breaking": "BREAKING", "major": "MAJOR", "update": "UPDATE"}.get(badge_cls, "UPDATE")
        badge_html = f'<span class="card-badge {badge_cls}">{badge_label}</span>'

        card_tags_html = ""
        if tags:
            tag_items = "".join(
                f'<span class="card-tag" onclick="filterNews(\'{escape_text(t)}\')">{escape_text(t)}</span>'
                for t in tags[:2]
            )
            card_tags_html = f'<div class="card-tags">{tag_items}</div>'

        # Derive a short title from body if title is empty
        display_title = raw_title
        if not display_title:
            plain = re.sub(r"<[^>]+>", "", it.get("body", ""))
            display_title = plain[:30].rstrip() + ("\u2026" if len(plain) > 30 else "")
        display_title = escape_text(display_title)

        if i == headline_idx:
            # Full-width headline card — real og:image, else Unsplash fallback
            fallback_text = it.get("body", "") + " " + (it.get("title") or "")
            img_url = get_card_image_url(url, fallback_text)
            img_safe = escape_text(img_url)
            # Build fallback emoji for onerror
            topic_icon_text = fallback_text
            icon_emoji, icon_label = get_topic_icon(topic_icon_text)
            fallback_unsplash = escape_text(search_news_image(fallback_text))
            out.append(f'''      <div class="news-card-headline reveal" data-tags="{tags_str}" data-bookmark-id="{bm_id}">
        <div class="card-image">
          <img src="{img_safe}" alt="{escape_text(display_title)}" style="width:100%;height:100%;object-fit:cover;" loading="lazy" onerror="this.src='{fallback_unsplash}'">
        </div>
        <div class="card-body">
          {badge_html}
          <h3 class="card-title">{display_title}</h3>
          <p class="card-summary">{body}</p>
          <div class="card-footer">
            {source_link}
            {card_tags_html}
            {bookmark_btn}
          </div>
        </div>
      </div>''')
        elif i == (headline_idx + 1) % len(items[:10]):
            # Second card — medium (spans 2 cols) with image strip
            fallback_text2 = it.get("body", "") + " " + (it.get("title") or "")
            img_url2 = get_card_image_url(url, fallback_text2)
            img_safe2 = escape_text(img_url2)
            fallback_unsplash2 = escape_text(search_news_image(fallback_text2))
            out.append(f'''      <div class="news-card medium reveal" data-tags="{tags_str}" data-bookmark-id="{bm_id}">
        <img class="card-img-top" src="{img_safe2}" alt="{escape_text(display_title)}" loading="lazy" onerror="this.src='{fallback_unsplash2}'">
        {badge_html}
        <h3 class="card-title">{display_title}</h3>
        <p class="card-summary">{body}</p>
        <div class="card-footer">
          {source_link}
          {card_tags_html}
          {bookmark_btn}
        </div>
      </div>''')
        else:
            # Standard card (1 col)
            out.append(f'''      <div class="news-card reveal" data-tags="{tags_str}" data-bookmark-id="{bm_id}">
        {badge_html}
        <h3 class="card-title">{display_title}</h3>
        <p class="card-summary">{body}</p>
        <div class="card-footer">
          {source_link}
          {card_tags_html}
          {bookmark_btn}
        </div>
      </div>''')
    return "\n".join(out)


def render_top3(news_items, papers_items):
    """Select top 3 items from news + papers by importance heuristic."""
    candidates = []
    # Add breaking news first
    for it in (news_items or []):
        score = 0
        if it.get("importance") == "breaking": score += 100
        elif it.get("importance") == "major": score += 50
        tags = it.get("tags", [])
        if any(t in ["#\u6750\u6599", "#AI4Science", "#\u673a\u5668\u4eba"] for t in tags): score += 20
        candidates.append({"type": "news", "score": score, "data": it})
    # Add week pick papers
    for it in (papers_items or []):
        score = 0
        if it.get("is_week_pick"): score += 80
        if it.get("venue_type") == "nature": score += 30
        candidates.append({"type": "paper", "score": score, "data": it})
    candidates.sort(key=lambda x: -x["score"])
    top3 = candidates[:3]

    rank_labels = ["01", "02", "03"]
    out = []
    for idx, c in enumerate(top3):
        rank = rank_labels[idx]
        d = c["data"]
        if c["type"] == "news":
            body = sanitize_strong(d.get("body", ""))
            plain_title = re.sub(r"<[^>]+>", "", d.get("body", ""))[:40].rstrip()
            display_title = escape_text(plain_title + ("\u2026" if len(re.sub(r"<[^>]+>", "", d.get("body", ""))) > 40 else ""))
            url = (d.get("url") or "").strip()
            tags = d.get("tags", [])
            tags_str = escape_text(",".join(tags))
            src_type = infer_source_type(url)
            src_cls = src_type.lower().replace(" ", "-")
            src_badge = f'<span class="src-badge src-{src_cls}">{escape_text(src_type)}</span>'
            link_html = f'<a class="card-source-link" href="{escape_text(url)}" target="_blank" rel="noopener">\u539f\u6587 \u2197</a>' if url.startswith("http") else ""
            tag_items = "".join(f'<span class="card-tag">{escape_text(t)}</span>' for t in tags[:2])
            imp = d.get("importance", "normal")
            why_map = {
                "breaking": "\u4eca\u65e5\u5934\u6761\u2014\u2014\u7a81\u7834\u6027\u8fdb\u5c55\uff0c\u5024\u5f97\u7b2c\u4e00\u65f6\u95f4\u5173\u6ce8",
                "major": "\u91cd\u78c5\u6d88\u606f\u2014\u2014\u5bf9 AI \u683c\u5c40\u6709\u663e\u8457\u5f71\u54cd",
                "normal": "\u5024\u5f97\u5173\u6ce8\u7684\u884c\u4e1a\u52a8\u6001",
            }
            why = why_map.get(imp, "\u5024\u5f97\u5173\u6ce8\u7684\u91cd\u8981\u8fdb\u5c55")
            out.append(f'''    <div class="top3-card reveal" data-tags="{tags_str}">
      <div class="top3-rank">{rank}</div>
      {src_badge}
      <h3 class="top3-title">{display_title}</h3>
      <p class="top3-summary">{body}</p>
      <div class="top3-why"><strong>\u4e3a\u4f55\u91cd\u8981</strong>\u3000{escape_text(why)}</div>
      <div class="top3-footer">
        {link_html}
        <div class="card-tags">{tag_items}</div>
      </div>
    </div>''')
        else:  # paper
            title = escape_text(d.get("title", ""))
            summary = escape_text(d.get("summary", ""))
            venue = escape_text(d.get("venue", ""))
            url = (d.get("url") or "").strip()
            link_html = f'<a class="card-source-link" href="{escape_text(url)}" target="_blank" rel="noopener">\u9605\u8bfb \u2197</a>' if url.startswith("http") else ""
            src_badge = '<span class="src-badge src-paper">Paper</span>'
            why = f"\u53d1\u8868\u4e8e {d.get('venue', '')}\uff0c\u662f\u672c\u671f AI4Materials \u7cbe\u9009\u8bba\u6587"
            out.append(f'''    <div class="top3-card reveal" data-tags="#\u6750\u6599,#AI4Science">
      <div class="top3-rank">{rank}</div>
      {src_badge}
      <span class="paper-venue">{venue}</span>
      <h3 class="top3-title">{title}</h3>
      <p class="top3-summary">{summary}</p>
      <div class="top3-why"><strong>\u4e3a\u4f55\u91cd\u8981</strong>\u3000{escape_text(why)}</div>
      <div class="top3-footer">
        {link_html}
        <div class="card-tags"><span class="card-tag">#AI4Science</span><span class="card-tag">#\u6750\u6599</span></div>
      </div>
    </div>''')
    return "\n".join(out)


def render_science(items):
    out = []
    for i, it in enumerate(items[:6]):
        icon = SCIENCE_ICONS[i % len(SCIENCE_ICONS)]
        out.append(f'''      <article class="sci-card reveal">
        <div class="sci-icon">
          {icon}
        </div>
        <h4>{escape_text(it.get("title", ""))}</h4>
        <p>{escape_text(it.get("body", ""))}</p>
      </article>''')
    return "\n".join(out)


def render_papers(items):
    # 把 week pick 排最前
    sorted_items = sorted(items[:8], key=lambda x: 0 if x.get("is_week_pick") else 1)
    out = []
    for it in sorted_items:
        vt = (it.get("venue_type") or "conf").lower()
        if vt not in ("nature", "science", "conf"):
            vt = "conf"
        url = (it.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            url = "#"
        pick = it.get("is_week_pick", False)
        pick_banner = '<div class="pick-banner">\U0001f52c Yang\'s Pick</div>' if pick else ""
        pick_class = " paper-card-pick" if pick else ""
        yang_comment = it.get("yang_comment") or ""
        yangs_pick_block = ""
        if pick:
            why_text = yang_comment if yang_comment else "精选理由：该论文对 AI 驱动材料发现具有重要方法论意义，值得优先阅读。"
            yangs_pick_block = f'''        <div class="yangs-pick-why">
          <span class="yangs-pick-label">\U0001f52c Yang's Pick</span>{escape_text(why_text)}
        </div>'''
        out.append(f'''      <article class="paper-card {vt}{pick_class} reveal">
        {pick_banner}
        <span class="paper-venue">{escape_text(it.get("venue", ""))}</span>
        <h4 class="paper-title">{escape_text(it.get("title", ""))}</h4>
        <p class="paper-authors">{escape_text(it.get("authors", ""))}</p>
        <p class="paper-summary">{escape_text(it.get("summary", ""))}</p>
{yangs_pick_block}
        <div class="paper-meta">
          <span class="paper-date">{escape_text(it.get("date", ""))}</span>
          <a class="paper-link" href="{escape_text(url)}" target="_blank" rel="noopener">阅读 {LINK_SVG}</a>
        </div>
      </article>''')
    return "\n".join(out)


def render_models(items):
    out = []
    for it in (items or [])[:8]:
        tier = (it.get("tier") or "B").upper()
        if tier not in ("S", "A", "B"):
            tier = "B"
        out.append(f'''      <div class="model-chip tier-{tier}">
        <span class="model-org">{escape_text(it.get("org_short", ""))}</span>
        <span class="model-name">{escape_text(it.get("name", ""))}</span>
        <span class="model-tier">{tier}</span>
      </div>''')
    return "\n".join(out)


def render_benchmarks(items):
    if not items:
        return '      <tr><td colspan="6" style="text-align:center;color:#3d4d6a;padding:24px;">暂无数据</td></tr>'
    rows = []
    for it in items[:8]:
        def score_cell(v):
            v = str(v or "N/A")
            if v == "N/A":
                return f'<td class="score" style="color:#3d4d6a">{v}</td>'
            try:
                f = float(v)
                color = "#00ff88" if f >= 90 else "#00e5ff" if f >= 80 else "#ffaa00" if f >= 70 else "#ff2d78"
                return f'<td class="score" style="color:{color}">{v}</td>'
            except Exception:
                return f'<td class="score">{escape_text(v)}</td>'
        rows.append(f'''        <tr>
          <td class="model-cell">{escape_text(it.get("model",""))}</td>
          <td class="org-cell">{escape_text(it.get("org",""))}</td>
          {score_cell(it.get("mmlu"))}
          {score_cell(it.get("math"))}
          {score_cell(it.get("humaneval"))}
          <td class="note">{escape_text(it.get("notes",""))}</td>
        </tr>''')
    return "\n".join(rows)


def render_conferences(items):
    if not items:
        return '      <div class="conf-card"><div class="conf-name" style="color:#3d4d6a;">暂无近期截止</div></div>'
    out = []
    # Sort: upcoming (days_left >= 0) first sorted by days_left, past last
    sorted_items = sorted(
        items,
        key=lambda x: (0 if (x.get("days_left", 0) or 0) >= 0 else 1,
                       x.get("days_left", 999) if (x.get("days_left", 0) or 0) >= 0 else 0)
    )
    for it in sorted_items[:8]:
        days = it.get("days_left", 0)
        if isinstance(days, (int, float)):
            if days < 0:
                day_cls = "past"
                day_txt = "已结束"
            elif days == 0:
                day_cls = "urgent"
                day_txt = "今天截止"
            elif days <= 14:
                day_cls = "urgent"
                day_txt = f"还有 {days} 天"
            elif days <= 30:
                day_cls = "soon"
                day_txt = f"还有 {days} 天"
            else:
                day_cls = "normal"
                day_txt = f"还有 {days} 天"
        else:
            day_cls = "normal"
            day_txt = str(days)
        url = it.get("url", "#")
        event_map = {"submission": "投稿截止", "notification": "录取通知", "camera_ready": "终稿截止"}
        etype = event_map.get(it.get("event_type", ""), it.get("event_type", ""))
        out.append(f'''      <a class="conf-card reveal" href="{escape_text(url)}" target="_blank" rel="noopener" style="text-decoration:none;color:inherit;display:block;">
        <div class="conf-name">{escape_text(it.get("name",""))}</div>
        <div class="conf-deadline">{escape_text(etype)} · {escape_text(it.get("deadline",""))}</div>
        <div class="conf-days {day_cls}">{day_txt}</div>
      </a>''')
    return "\n".join(out)


def render_stats(data):
    stats = data.get("stats", {})
    nc = stats.get("news_count", 0)
    pc = stats.get("paper_count", 0)
    lc = stats.get("leader_count", 3)
    sc = stats.get("science_count", 0)
    date_str = escape_text(data.get("date", ""))
    return f'''  <div class="stats-row">
    <div class="stat-block">
      <span class="stat-num mono" data-target="{nc}">{nc}</span>
      <span class="stat-label">条资讯</span>
    </div>
    <div class="stat-divider"></div>
    <div class="stat-block">
      <span class="stat-num mono" data-target="{pc}">{pc}</span>
      <span class="stat-label">篇论文</span>
    </div>
    <div class="stat-divider"></div>
    <div class="stat-block">
      <span class="stat-num mono" data-target="{lc}">{lc}</span>
      <span class="stat-label">位领袖</span>
    </div>
    <div class="stat-divider"></div>
    <div class="stat-block">
      <span class="stat-num mono" data-target="{sc}">{sc}</span>
      <span class="stat-label">项进展</span>
    </div>
    <div class="stat-divider"></div>
    <div class="stat-block" id="visitor-stat">
      <span class="stat-num mono" id="visitor-count">…</span>
      <span class="stat-label">历史访客</span>
    </div>
  </div>
  <div class="hero-update-badge">
    <span class="badge-dot"></span>
    <span class="mono" style="font-size:.72rem;color:var(--text-mute);">LAST UPDATE</span>
    <span class="mono" style="font-size:.72rem;color:var(--cyan);" id="last-updated">{date_str}</span>
  </div>'''


# ---------------------------------------------------------------------------
# 4. HTML 替换
# ---------------------------------------------------------------------------

def replace_block(html, start, end, inner):
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    repl = f"{start}\n{inner}\n      {end}"
    if not pat.search(html):
        raise RuntimeError(f"未找到标记: {start}")
    return pat.sub(repl, html, count=1)


def update_date(html, date_str):
    return re.sub(
        r'<span id="last-updated">[^<]*</span>',
        f'<span id="last-updated">{escape_text(date_str)}</span>',
        html, count=1,
    )


# ---------------------------------------------------------------------------
# 5. 归档 & RSS
# ---------------------------------------------------------------------------

def save_data(data: dict, today_iso: str):
    """保存原始 JSON 到 data/YYYY-MM-DD.json 和 data/latest.json，更新 data/index.json"""
    DATA_DIR.mkdir(exist_ok=True)

    dated = DATA_DIR / f"{today_iso}.json"
    dated.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    latest = DATA_DIR / "latest.json"
    latest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 更新 index.json（按日期降序排列的列表）
    index_file = DATA_DIR / "index.json"
    existing = []
    if index_file.exists():
        try:
            existing = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    if today_iso not in existing:
        existing.insert(0, today_iso)
    existing.sort(reverse=True)
    index_file.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

    print(f"[ok] 数据已保存到 data/{today_iso}.json", flush=True)


def save_archive_snapshot(today_iso: str):
    """把当日 index.html 复制到 archive/YYYY-MM-DD.html"""
    ARCHIVE_DIR.mkdir(exist_ok=True)
    dest = ARCHIVE_DIR / f"{today_iso}.html"
    shutil.copy2(INDEX, dest)
    print(f"[ok] 快照已保存到 archive/{today_iso}.html", flush=True)


def rebuild_archive_index():
    """重建 archive/index.html 归档目录页"""
    ARCHIVE_DIR.mkdir(exist_ok=True)
    index_file = DATA_DIR / "index.json"
    dates: list[str] = []
    if index_file.exists():
        try:
            dates = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            dates = []

    items_html = "\n".join(
        f'      <li><a href="{d}.html">{d}</a></li>'
        for d in dates
        if (ARCHIVE_DIR / f"{d}.html").exists()
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>历史归档 · AI Progress Hub</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=Noto+Sans+SC:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: #060814; --surface: rgba(255,255,255,.05); --border: rgba(255,255,255,.10); --text: #e6ebff; --text-dim: #9aa3c7; --accent: #6366f1; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: "Inter","Noto Sans SC",system-ui,sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 60px 24px; }}
  h1 {{ font-size: 2rem; font-weight: 800; margin: 0 0 8px; }}
  .sub {{ color: var(--text-dim); margin: 0 0 40px; }}
  ul {{ list-style: none; padding: 0; margin: 0; width: 100%; max-width: 480px; display: flex; flex-direction: column; gap: 10px; }}
  li a {{ display: block; padding: 14px 20px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; color: var(--text); text-decoration: none; font-weight: 600; font-size: 1rem; transition: border-color .2s, background .2s; }}
  li a:hover {{ border-color: var(--accent); background: rgba(99,102,241,.08); }}
  .back {{ margin-top: 40px; color: var(--text-dim); font-size: .9rem; }}
  .back a {{ color: var(--accent); text-decoration: none; }}
</style>
</head>
<body>
<h1>历史归档</h1>
<p class="sub">每日 AI 进展快照，共 {len(dates)} 期</p>
<ul>
{items_html}
</ul>
<p class="back"><a href="../">← 返回今日</a></p>
</body>
</html>"""
    (ARCHIVE_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"[ok] archive/index.html 已重建（{len(dates)} 期）", flush=True)


def generate_rss(data: dict, today_iso: str):
    """生成 Atom/RSS feed.xml"""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_label = data.get("date", today_iso)
    base_url = "https://yang1bai.github.io/ai-progress-site"

    def xml_escape(s: str) -> str:
        return (str(s)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))

    entries = []
    for it in (data.get("news") or [])[:10]:
        body = re.sub(r"<[^>]+>", "", it.get("body", ""))
        url = it.get("url", "").strip()
        if not url.startswith(("http://", "https://")):
            url = f"{base_url}/#daily"
        entries.append(f"""  <entry>
    <title>{xml_escape(body[:80])}…</title>
    <link href="{xml_escape(url)}"/>
    <id>{xml_escape(url)}</id>
    <updated>{now_utc}</updated>
    <summary>{xml_escape(body)}</summary>
  </entry>""")

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>AI Progress Hub · 每日 AI 资讯</title>
  <subtitle>领袖观点 · 今日大事 · AI4Science · AI4Material 论文</subtitle>
  <link href="{base_url}/feed.xml" rel="self"/>
  <link href="{base_url}/"/>
  <id>{base_url}/</id>
  <updated>{now_utc}</updated>
  <author><name>AI Progress Hub</name></author>
  <entry>
    <title>每日汇总 {xml_escape(date_label)}</title>
    <link href="{base_url}/archive/{today_iso}.html"/>
    <id>{base_url}/archive/{today_iso}.html</id>
    <updated>{now_utc}</updated>
    <summary>今日 AI 大事 · 领袖观点 · AI4Science · AI4Material 论文完整汇总。</summary>
  </entry>
{chr(10).join(entries)}
</feed>"""
    FEED.write_text(feed, encoding="utf-8")
    print(f"[ok] feed.xml 已更新（{len(entries)} 条新闻）", flush=True)


# ---------------------------------------------------------------------------
# 6. Mock & main
# ---------------------------------------------------------------------------

def load_mock():
    return {
        "leaders": [
            {"name": "示例·一号", "name_en": "Sample One", "role": "示例公司 CEO",
             "quote": "AI 将重塑下一个十年。", "body": "占位（dry-run）。",
             "tags": ["2026-04"], "initials": "S1", "quote_date": "4月27日"},
            {"name": "示例·二号", "name_en": "Sample Two", "role": "Anthropic 研究员",
             "quote": "可解释性是 AGI 安全的关键。", "body": "占位（dry-run）。",
             "tags": ["Anthropic"], "initials": "S2", "quote_date": "近期"},
            {"name": "示例·三号", "name_en": "Sample Three", "role": "DeepMind VP",
             "quote": "AI4Science 进入加速期。", "body": "占位（dry-run）。",
             "tags": ["DeepMind"], "initials": "S3", "quote_date": "4月25日"},
        ],
        "news": [
            {"title": "", "body": "<strong>示例 A</strong>：占位新闻。", "url": "https://example.com/a",
             "importance": "breaking", "tags": ["#LLM"]},
            {"title": "", "body": "<strong>示例 B</strong>：占位新闻。", "url": "",
             "importance": "major", "tags": ["#Agent", "#开源"]},
            {"title": "", "body": "<strong>示例 C</strong>：占位新闻。", "url": "https://example.com/c",
             "importance": "normal", "tags": ["#芯片"]},
        ],
        "science": [
            {"title": "示例进展 alpha", "body": "AI 在某科学问题上突破（占位）。"},
            {"title": "示例进展 beta", "body": "AI 在另一问题上突破（占位）。"},
        ],
        "papers": [
            {"venue_type": "nature", "venue": "Nature Materials",
             "title": "Mock paper for dry-run rendering",
             "authors": "Doe J. et al.",
             "summary": "Mock 验证论文卡片渲染。",
             "date": "2026-04-25", "url": "https://example.com/p1",
             "is_week_pick": True},
            {"venue_type": "science", "venue": "Science",
             "title": "Mock paper on AI-driven catalysis",
             "authors": "Roe A. et al.",
             "summary": "AI 引导的催化剂设计示例。",
             "date": "2026-04-23", "url": "https://example.com/p2",
             "is_week_pick": False},
            {"venue_type": "conf", "venue": "NeurIPS 2025",
             "title": "Mock GNN paper for crystals",
             "authors": "Kim S. et al.",
             "summary": "图神经网络预测晶体性质示例。",
             "date": "2026-04-22", "url": "https://example.com/p3",
             "is_week_pick": False},
        ],
        "models": [
            {"name": "Claude Sonnet 4", "org": "Anthropic", "org_short": "ANT", "release_date": "2026-04-25", "highlight": "最新旗舰推理模型", "tier": "S"},
            {"name": "GPT-5.5", "org": "OpenAI", "org_short": "OAI", "release_date": "2026-04-24", "highlight": "统一超级应用", "tier": "S"},
            {"name": "DeepSeek V4", "org": "DeepSeek", "org_short": "DS", "release_date": "2026-04-23", "highlight": "开源最强，100K ctx", "tier": "A"},
        ],
        "benchmarks": [
            {"model": "Claude Sonnet 4", "org": "Anthropic", "mmlu": "91.5", "math": "87.2", "humaneval": "90.1", "notes": "最新旗舰，强推理"},
            {"model": "GPT-5.5", "org": "OpenAI", "mmlu": "92.1", "math": "88.3", "humaneval": "91.2", "notes": "统一超级应用"},
            {"model": "Gemini 2.5 Pro", "org": "Google", "mmlu": "90.8", "math": "91.0", "humaneval": "88.5", "notes": "数学最强"},
            {"model": "DeepSeek V4", "org": "DeepSeek", "mmlu": "88.5", "math": "85.1", "humaneval": "87.3", "notes": "开源最强"},
        ],
        "conferences": [
            {"name": "ICML 2026", "event_type": "notification", "deadline": "2026-05-15", "url": "https://icml.cc", "days_left": 18},
            {"name": "NeurIPS 2026", "event_type": "submission", "deadline": "2026-05-30", "url": "https://neurips.cc", "days_left": 33},
            {"name": "ICLR 2027", "event_type": "submission", "deadline": "2026-09-27", "url": "https://iclr.cc", "days_left": 153},
        ],
    }


def main():
    now = datetime.now(TZ)
    today = now.strftime("%Y年%-m月%-d日")
    today_iso = now.strftime("%Y-%m-%d")

    if os.environ.get("DRY_RUN") == "1":
        print("[dry-run] 跳过 Claude API，使用 mock JSON")
        data = load_mock()
        data["date"] = today
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ERROR: 未设置 ANTHROPIC_API_KEY", file=sys.stderr)
            return 2
        last_err = None
        data = None
        for attempt in range(3):
            try:
                data = call_claude(today)
                break
            except Exception as e:
                last_err = e
                print(f"WARN: 第 {attempt+1} 次尝试失败: {e}", file=sys.stderr)
        if data is None:
            print(f"ERROR: Claude 调用失败（3次尝试）: {last_err}", file=sys.stderr)
            return 3

    # 自动计算 stats
    data["stats"] = {
        "news_count": len(data.get("news", [])),
        "paper_count": len(data.get("papers", [])),
        "leader_count": len(data.get("leaders", [])),
        "science_count": len(data.get("science", [])),
    }

    # 更新 index.html
    html = INDEX.read_text(encoding="utf-8")
    html = replace_block(html, "<!-- LEADERS:START -->", "<!-- LEADERS:END -->",
                         render_leaders(data.get("leaders", [])))
    html = replace_block(html, "<!-- NEWS:START -->", "<!-- NEWS:END -->",
                         render_news(data.get("news", [])))
    html = replace_block(html, "<!-- SCIENCE:START -->", "<!-- SCIENCE:END -->",
                         render_science(data.get("science", [])))
    html = replace_block(html, "<!-- MATERIAL:START -->", "<!-- MATERIAL:END -->",
                         render_papers(data.get("papers", [])))
    html = replace_block(html, "<!-- MODELS:START -->", "<!-- MODELS:END -->",
                         render_models(data.get("models", [])))
    html = replace_block(html, "<!-- STATS:START -->", "<!-- STATS:END -->",
                         render_stats(data))
    html = replace_block(html, "<!-- BENCHMARKS:START -->", "<!-- BENCHMARKS:END -->",
                         render_benchmarks(data.get("benchmarks", [])))
    html = replace_block(html, "<!-- CONFERENCES:START -->", "<!-- CONFERENCES:END -->",
                         render_conferences(data.get("conferences", [])))
    html = replace_block(html, "<!-- TOP3:START -->", "<!-- TOP3:END -->",
                         render_top3(data.get("news", []), data.get("papers", [])))
    # update_date as fallback (id="last-updated" is now inside STATS block)
    html = update_date(html, data.get("date", today))
    INDEX.write_text(html, encoding="utf-8")
    print(f"[ok] 已更新 index.html（日期 {data.get('date', today)}）")

    # 归档 & RSS
    save_data(data, today_iso)
    save_archive_snapshot(today_iso)
    rebuild_archive_index()
    generate_rss(data, today_iso)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
