"""Build a source-linked digest without a paid model or API key."""
from datetime import datetime, timezone
from public_sources import collect

NEWS_FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("MIT AI", "https://news.mit.edu/rss/topic/artificial-intelligence2"),
    ("Google Research", "https://research.google/blog/rss/"),
]
PAPER_FEEDS = [
    ("Nature Materials", "https://www.nature.com/nmat.rss"),
    ("Nature Catalysis", "https://www.nature.com/natcatal.rss"),
    ("arXiv materials", "https://rss.arxiv.org/rss/cond-mat.mtrl-sci"),
]


def fetch_public_data(now):
    news, news_status = collect(NEWS_FEEDS, days=7)
    candidates, paper_status = collect(PAPER_FEEDS, days=45)
    keywords = ("machine learning", "neural", "deep learning", "artificial intelligence", "generative", "foundation model")
    papers = []
    for row in candidates:
        if any(k in (row["title"] + " " + row["body"]).lower() for k in keywords):
            papers.append({**row, "venue": row["source"], "venue_type": "conf" if "arXiv" in row["source"] else "nature",
                           "summary": row["body"], "authors": "作者见原文", "is_week_pick": False})
    if not news and not papers:
        raise RuntimeError("No fresh source content; preserving the last published digest")
    return {"date": f"{now.year}年{now.month}月{now.day}日", "news": news[:15], "papers": papers[:12],
            "leaders": [], "models": [], "benchmarks": [], "conferences": [],
            "science": [{"title": p["title"], "body": p["summary"], "url": p["url"]} for p in papers[:6]],
            "content_mode": "public", "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sources": news_status + paper_status}
