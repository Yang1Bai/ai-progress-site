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

USER_PROMPT_TEMPLATE = """今天是 {today}（北美东部时区）。请用 web_search 工具搜索过去 1-7 天的最新 AI 资讯与论文，然后输出包含四个区块的 JSON。

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

3. **science**：5-6 条最近 AI4Science 进展。每条提供：
   - title (短标题, 中文 <15 字)
   - body (1-2 句中文说明, 40-80 字)

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

关键约束：必须基于 web_search 结果，严禁编造不存在的论文或链接。如某来源近一周确实没有合适论文，宁可减少数量也不要造假。如果完全找不到，可放宽到过去两周。新闻 url 也必须是真实可访问链接，不确定则留空。

输出 JSON Schema：
{{
  "date": "YYYY年M月D日",
  "leaders": [{{ "name": "...", "name_en": "...", "role": "...", "quote": "...", "body": "...", "tags": ["..."], "initials": "AB", "quote_date": "M月D日" }}],
  "news": [{{ "title": "", "body": "...", "url": "https://..." }}],
  "science": [{{ "title": "...", "body": "..." }}],
  "papers": [{{ "venue_type": "nature", "venue": "...", "title": "...", "authors": "...", "summary": "...", "date": "YYYY-MM-DD", "url": "https://..." }}]
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
    return json.loads(raw[s : e + 1])


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


def render_news(items):
    out = []
    for i, it in enumerate(items[:10]):
        icon = NEWS_ICONS[i % len(NEWS_ICONS)]
        body = sanitize_strong(it.get("body", ""))
        url = (it.get("url") or "").strip()
        source_btn = ""
        if url.startswith(("http://", "https://")):
            source_btn = f'<a class="news-source-link" href="{escape_text(url)}" target="_blank" rel="noopener">原文 {LINK_SVG}</a>'
        out.append(f'''      <div class="news-item reveal">
        <div class="news-icon" aria-hidden="true">
          {icon}
        </div>
        <div class="news-content">
          <p class="news-body">{body}</p>
          {source_btn}
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
    out = []
    for it in items[:8]:
        vt = (it.get("venue_type") or "conf").lower()
        if vt not in ("nature", "science", "conf"):
            vt = "conf"
        url = (it.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            url = "#"
        out.append(f'''      <article class="paper-card {vt} reveal">
        <span class="paper-venue">{escape_text(it.get("venue", ""))}</span>
        <h4 class="paper-title">{escape_text(it.get("title", ""))}</h4>
        <p class="paper-authors">{escape_text(it.get("authors", ""))}</p>
        <p class="paper-summary">{escape_text(it.get("summary", ""))}</p>
        <div class="paper-meta">
          <span class="paper-date">{escape_text(it.get("date", ""))}</span>
          <a class="paper-link" href="{escape_text(url)}" target="_blank" rel="noopener">阅读 {LINK_SVG}</a>
        </div>
      </article>''')
    return "\n".join(out)


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
            {"title": "", "body": "<strong>示例 A</strong>：占位新闻。", "url": "https://example.com/a"},
            {"title": "", "body": "<strong>示例 B</strong>：占位新闻。", "url": ""},
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
             "date": "2026-04-25", "url": "https://example.com/p1"},
            {"venue_type": "science", "venue": "Science",
             "title": "Mock paper on AI-driven catalysis",
             "authors": "Roe A. et al.",
             "summary": "AI 引导的催化剂设计示例。",
             "date": "2026-04-23", "url": "https://example.com/p2"},
            {"venue_type": "conf", "venue": "NeurIPS 2025",
             "title": "Mock GNN paper for crystals",
             "authors": "Kim S. et al.",
             "summary": "图神经网络预测晶体性质示例。",
             "date": "2026-04-22", "url": "https://example.com/p3"},
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
        try:
            data = call_claude(today)
        except Exception as e:
            print(f"ERROR: Claude 调用失败: {e}", file=sys.stderr)
            return 3

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
