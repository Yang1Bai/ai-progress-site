#!/usr/bin/env python3
"""
fetch_content.py
================
通过 Claude API + web_search 工具，每日为 ai-progress-site 抓取三段最新内容：
  1. AI 大佬观点 (leaders)
  2. 今日 AI 大事 (news)
  3. AI4Science 进展 (science)

随后将 index.html 中三处 <!-- *:START --> ... <!-- *:END --> 标记内的内容替换为
最新生成的 HTML 片段，并更新页面顶部的 <span id="last-updated"> 日期。

环境变量:
  ANTHROPIC_API_KEY  必需
  ANTHROPIC_MODEL    可选, 默认 claude-sonnet-4-5
  DRY_RUN            可选, 设为 1 时跳过 API 调用，用本地 mock JSON 验证替换逻辑
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
TZ = ZoneInfo("America/Toronto")

# ---------------------------------------------------------------------------
# 1. Prompt 与 Schema
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是 AI 行业资讯编辑。你必须仅输出符合给定 JSON Schema 的结果，不能在 JSON 之外写任何字符。
全部正文使用中文（简体）。重要术语可保留英文原名。"""

USER_PROMPT_TEMPLATE = """今天是 {today}（北美东部时区）。请用 web_search 工具搜索过去 1-3 天的最新 AI 资讯，然后输出包含三个区块的 JSON。

要求：
1. **leaders**：3 位 AI 行业领袖最近 1-2 周的公开观点。优先选 OpenAI / Anthropic / Google DeepMind / Meta / xAI / 微软 / 英伟达 / 阿里 / 字节 / 智谱 等公司高管或知名研究者。每位提供：
   - name: 中文姓名
   - name_en: 英文姓名
   - role: 职位（如 OpenAI 首席执行官）
   - quote: 最具代表性的一句话（中文，不超过 30 字）
   - body: 1-2 句中文背景说明，必须与所引内容直接相关
   - tags: 1-3 个英文/中文短标签，如 "TED 2026" "Anthropic"
   - initials: 英文姓名缩写 2 个字母大写

2. **news**：8-10 条今日（或过去 24-48 小时）AI 相关重要新闻。每条提供：
   - title: 简短标题片段（可省略，留空字符串）
   - body: 一句完整的中文新闻概述（约 30-60 字，可包含 <strong>...</strong> 标签突出关键词，但**只能**使用 <strong> 标签）

3. **science**：5-6 条最近的 AI4Science（AI 用于科学研究）进展。每条提供：
   - title: 短标题（中文，不超过 15 字）
   - body: 1-2 句中文说明（约 40-80 字）

如果搜索结果不足，可以基于近期已知事件合理整理，但**严禁编造具体的论文名/公司名/金额**——若不确定，就用更宽泛的描述。

输出 JSON Schema：
{{
  "date": "YYYY年M月D日",
  "leaders": [
    {{ "name": "...", "name_en": "...", "role": "...", "quote": "...", "body": "...", "tags": ["..."], "initials": "AB" }}
  ],
  "news": [
    {{ "title": "", "body": "..." }}
  ],
  "science": [
    {{ "title": "...", "body": "..." }}
  ]
}}

只输出 JSON，不要 ```json 代码块包裹，不要任何前后说明文字。"""

# ---------------------------------------------------------------------------
# 2. 调用 Claude API
# ---------------------------------------------------------------------------

def call_claude(today: str) -> dict:
    """调用 Claude API 并返回解析后的 JSON。"""
    import anthropic  # 延迟导入，便于 dry-run 不依赖

    client = anthropic.Anthropic()
    user_prompt = USER_PROMPT_TEMPLATE.format(today=today)

    print(f"[claude] model={MODEL}  date={today}", flush=True)

    # 启用服务器侧 web_search 工具，让 Claude 自己抓最新资讯
    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 6,
        }],
    )

    # 收集所有 text block 拼起来
    parts: list[str] = []
    for block in message.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    raw = "".join(parts).strip()

    # 容错：去掉可能的 ```json ... ``` 包裹
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    # 截取第一个 { 到最后一个 } 之间
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError(f"Claude 返回不是 JSON：\n{raw[:500]}")
    payload = json.loads(raw[start : end + 1])
    return payload


# ---------------------------------------------------------------------------
# 3. 渲染 HTML 片段
# ---------------------------------------------------------------------------

# 3.1 leaders
LEADER_AVATAR_VARIANTS = ["em", "sa", "aj"]  # 与 CSS 中已有渐变类对应

def render_leaders(items: list[dict]) -> str:
    cards: list[str] = []
    for i, it in enumerate(items[:3]):
        avatar_cls = LEADER_AVATAR_VARIANTS[i % len(LEADER_AVATAR_VARIANTS)]
        initials = (it.get("initials") or "AI")[:2].upper()
        tags_html = "".join(
            f'<span class="tag">{escape_text(t)}</span>'
            for t in (it.get("tags") or [])[:3]
        )
        card = f'''      <article class="leader-card reveal">
        <div class="leader-head">
          <div class="avatar {avatar_cls}" aria-hidden="true">{escape_text(initials)}</div>
          <div>
            <div class="leader-name">{escape_text(it.get("name", ""))} ({escape_text(it.get("name_en", ""))})</div>
            <div class="leader-role">{escape_text(it.get("role", ""))}</div>
          </div>
        </div>
        <blockquote class="leader-quote">"{escape_text(it.get("quote", ""))}"</blockquote>
        <p class="leader-body">{escape_text(it.get("body", ""))}</p>
        <div class="leader-meta">{tags_html}</div>
      </article>'''
        cards.append(card)
    return "\n".join(cards)


# 3.2 news
NEWS_ICONS = [
    # 麦克风
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>',
    # 图片
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
    # 立方体
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>',
    # 书本
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
    # 闪电
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    # 芯片
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="2" x2="9" y2="4"/><line x1="15" y1="2" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="22"/><line x1="15" y1="20" x2="15" y2="22"/><line x1="20" y1="9" x2="22" y2="9"/><line x1="20" y1="14" x2="22" y2="14"/><line x1="2" y1="9" x2="4" y2="9"/><line x1="2" y1="14" x2="4" y2="14"/></svg>',
    # 对话框
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    # 齿轮
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    # 学院
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>',
    # 钱袋
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
]

def render_news(items: list[dict]) -> str:
    rows: list[str] = []
    for i, it in enumerate(items[:10]):
        icon = NEWS_ICONS[i % len(NEWS_ICONS)]
        body = sanitize_strong(it.get("body", ""))
        row = f'''      <div class="news-item reveal">
        <div class="news-icon" aria-hidden="true">
          {icon}
        </div>
        <div class="news-content">{body}</div>
      </div>'''
        rows.append(row)
    return "\n".join(rows)


# 3.3 science
SCIENCE_ICONS = [
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 2v7.31"/><path d="M14 9.3V1.99"/><path d="M8.5 2h7"/><path d="M14 9.3a6.5 6.5 0 1 1-4 0"/></svg>',
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11H1l8-8 8 8h-8v8l-8-8"/></svg>',
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>',
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/></svg>',
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
]

def render_science(items: list[dict]) -> str:
    cards: list[str] = []
    for i, it in enumerate(items[:6]):
        icon = SCIENCE_ICONS[i % len(SCIENCE_ICONS)]
        card = f'''      <article class="sci-card reveal">
        <div class="sci-icon">
          {icon}
        </div>
        <h4>{escape_text(it.get("title", ""))}</h4>
        <p>{escape_text(it.get("body", ""))}</p>
      </article>'''
        cards.append(card)
    return "\n".join(cards)


# ---------------------------------------------------------------------------
# 4. 工具函数
# ---------------------------------------------------------------------------

def escape_text(s: str) -> str:
    """简单 HTML 转义（不允许任何标签）。"""
    if s is None:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def sanitize_strong(s: str) -> str:
    """允许 <strong> 标签，其他全部转义。"""
    if not s:
        return ""
    # 先全部转义
    safe = escape_text(s)
    # 把 &lt;strong&gt; 还原
    safe = safe.replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")
    return safe


def replace_block(html: str, start_marker: str, end_marker: str, new_inner: str) -> str:
    """把 <!-- start --> ... <!-- end --> 之间内容替换为 new_inner。"""
    pattern = re.compile(
        re.escape(start_marker) + r".*?" + re.escape(end_marker),
        re.DOTALL,
    )
    replacement = f"{start_marker}\n{new_inner}\n      {end_marker}"
    if not pattern.search(html):
        raise RuntimeError(f"未在 index.html 中找到标记：{start_marker}")
    return pattern.sub(replacement, html, count=1)


def update_date(html: str, date_str: str) -> str:
    return re.sub(
        r'<span id="last-updated">[^<]*</span>',
        f'<span id="last-updated">{escape_text(date_str)}</span>',
        html,
        count=1,
    )


# ---------------------------------------------------------------------------
# 5. 主流程
# ---------------------------------------------------------------------------

def load_mock() -> dict:
    """DRY_RUN 时使用的本地模拟 JSON。"""
    return {
        "date": "2026年4月27日",
        "leaders": [
            {
                "name": "示例·一号", "name_en": "Sample One",
                "role": "示例公司 CEO",
                "quote": "AI 将重塑下一个十年。",
                "body": "在最近的访谈中，他表示生成式 AI 已进入企业大规模部署阶段。",
                "tags": ["2026-04", "Enterprise"], "initials": "S1",
            },
            {
                "name": "示例·二号", "name_en": "Sample Two",
                "role": "Anthropic 首席研究员",
                "quote": "可解释性是 AGI 安全的关键。",
                "body": "他强调下一代模型必须把可解释性研究放在与能力同等重要的位置。",
                "tags": ["Anthropic", "Safety"], "initials": "S2",
            },
            {
                "name": "示例·三号", "name_en": "Sample Three",
                "role": "DeepMind VP",
                "quote": "AI4Science 进入加速期。",
                "body": "他列举了过去 6 个月在材料发现与蛋白质设计上的多项突破。",
                "tags": ["DeepMind", "AI4Science"], "initials": "S3",
            },
        ],
        "news": [
            {"title": "", "body": "<strong>示例新闻 A</strong>：这是一条用于本地 dry-run 的占位新闻。"},
            {"title": "", "body": "<strong>示例新闻 B</strong>：再来一条占位新闻。"},
        ],
        "science": [
            {"title": "示例进展 α", "body": "AI 在某科学问题上取得突破（占位）。"},
            {"title": "示例进展 β", "body": "AI 在另一科学问题上取得突破（占位）。"},
        ],
    }


def main() -> int:
    today = datetime.now(TZ).strftime("%Y年%-m月%-d日")

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
            print(f"ERROR: Claude 调用失败：{e}", file=sys.stderr)
            return 3

    # 渲染并替换
    html = INDEX.read_text(encoding="utf-8")
    html = replace_block(html, "<!-- LEADERS:START -->", "<!-- LEADERS:END -->", render_leaders(data.get("leaders", [])))
    html = replace_block(html, "<!-- NEWS:START -->", "<!-- NEWS:END -->", render_news(data.get("news", [])))
    html = replace_block(html, "<!-- SCIENCE:START -->", "<!-- SCIENCE:END -->", render_science(data.get("science", [])))
    html = update_date(html, data.get("date", today))

    INDEX.write_text(html, encoding="utf-8")
    print(f"[ok] 已更新 {INDEX.relative_to(ROOT)}（日期 {data.get('date', today)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
