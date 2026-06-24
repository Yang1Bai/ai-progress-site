#!/usr/bin/env python3
"""Build the semi-monthly AI keyword trend dataset from local archive JSON."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "trending_terms.json"
KEEP_PERIODS = 6


GENERAL_AI_TERMS = [
    {
        "id": "agent",
        "label": "Agent",
        "label_cn": "Agent / 智能体",
        "aliases": ["agent", "agents", "agentic", "智能体", "代理", "computer use", "tool use"],
    },
    {
        "id": "reasoning",
        "label": "Reasoning model",
        "label_cn": "推理模型",
        "aliases": ["reasoning", "推理", "深度思考", "chain-of-thought", "o3", "r1"],
    },
    {
        "id": "long_context",
        "label": "Long context",
        "label_cn": "长上下文",
        "aliases": ["long context", "context window", "token 上下文", "上下文窗口", "百万 token", "100 万 token"],
    },
    {
        "id": "multimodal",
        "label": "Multimodal",
        "label_cn": "多模态",
        "aliases": ["multimodal", "omni", "多模态", "图像", "视频", "音频", "vision-language"],
    },
    {
        "id": "ai_coding",
        "label": "AI coding",
        "label_cn": "AI 编程",
        "aliases": ["coding", "code", "SWE-bench", "HumanEval", "编程", "代码", "coding agent"],
    },
    {
        "id": "open_source",
        "label": "Open source",
        "label_cn": "开源模型",
        "aliases": ["open source", "open-source", "开源", "llama", "qwen", "deepseek"],
    },
    {
        "id": "ai_safety",
        "label": "AI safety",
        "label_cn": "AI 安全",
        "aliases": ["safety", "alignment", "安全", "治理", "risk", "风险", "评测", "red team"],
    },
    {
        "id": "inference_efficiency",
        "label": "Inference efficiency",
        "label_cn": "推理效率",
        "aliases": ["inference", "KV cache", "quant", "推理", "量化", "能耗", "memory"],
    },
    {
        "id": "synthetic_data",
        "label": "Synthetic data",
        "label_cn": "合成数据",
        "aliases": ["synthetic data", "合成数据", "self-play", "distillation", "蒸馏"],
    },
    {
        "id": "ai_infrastructure",
        "label": "AI infrastructure",
        "label_cn": "AI 基础设施",
        "aliases": ["infrastructure", "data center", "GPU", "芯片", "算力", "基础设施", "HBM"],
    },
]


MATERIAL_AI_TERMS = [
    {
        "id": "materials_discovery",
        "label": "Materials discovery",
        "label_cn": "材料发现",
        "aliases": ["materials discovery", "material discovery", "材料发现", "新材料", "materials design"],
    },
    {
        "id": "catalyst_inverse_design",
        "label": "Catalyst inverse design",
        "label_cn": "催化剂逆向设计",
        "aliases": ["catalyst", "catalysts", "catalyst inverse design", "催化剂", "催化", "逆向设计"],
    },
    {
        "id": "ml_potential",
        "label": "ML potential",
        "label_cn": "机器学习势",
        "aliases": ["machine learning potential", "ML potential", "neural potential", "势能", "机器学习势"],
    },
    {
        "id": "generative_materials",
        "label": "Generative materials",
        "label_cn": "生成式材料设计",
        "aliases": ["generative", "生成模型", "生成式", "diffusion", "扩散模型", "VAE", "GAN"],
    },
    {
        "id": "crystal_structure",
        "label": "Crystal structure",
        "label_cn": "晶体结构生成",
        "aliases": ["crystal", "crystal structure", "晶体", "晶体结构", "无机晶体", "structure prediction"],
    },
    {
        "id": "battery_materials",
        "label": "Battery materials",
        "label_cn": "电池材料",
        "aliases": ["battery", "batteries", "电池", "锂", "钠", "cathode", "anode", "solid-state"],
    },
    {
        "id": "self_driving_lab",
        "label": "Self-driving lab",
        "label_cn": "自驱动实验室",
        "aliases": ["self-driving lab", "autonomous lab", "自动化实验", "自驱动实验", "robot scientist"],
    },
    {
        "id": "atomistic_language_model",
        "label": "Atomistic language model",
        "label_cn": "原子语言模型",
        "aliases": ["atomistic language model", "atomistic", "ALM", "原子语言模型", "原子结构"],
    },
    {
        "id": "graph_neural_network",
        "label": "Graph neural network",
        "label_cn": "图神经网络",
        "aliases": ["graph neural network", "GNN", "图神经网络", "graph network"],
    },
    {
        "id": "active_learning",
        "label": "Active learning",
        "label_cn": "主动学习",
        "aliases": ["active learning", "主动学习", "Bayesian optimization", "贝叶斯优化"],
    },
]


CATEGORIES = [
    {
        "id": "general_ai",
        "label": "For general AI",
        "label_cn": "For general AI",
        "description": "Terms extracted from news, leader views, model releases, and benchmark notes.",
        "description_cn": "从今日资讯、领袖观点、模型动态和基准说明中统计。",
        "sections": ["news", "leaders", "models", "benchmarks"],
        "terms": GENERAL_AI_TERMS,
    },
    {
        "id": "ai_for_materials",
        "label": "AI for Materials",
        "label_cn": "AI for Material",
        "description": "Terms extracted from AI4Science items and AI4Materials papers.",
        "description_cn": "从 AI4Science 进展与 AI4Material 论文中统计。",
        "sections": ["science", "papers"],
        "terms": MATERIAL_AI_TERMS,
    },
]


def parse_data_date(path: Path) -> date | None:
    try:
        return datetime.strptime(path.stem, "%Y-%m-%d").date()
    except ValueError:
        return None


def period_id(d: date) -> str:
    half = "H1" if d.day <= 15 else "H2"
    return f"{d.year:04d}-{d.month:02d}-{half}"


def period_bounds(pid: str) -> tuple[date, date]:
    year = int(pid[0:4])
    month = int(pid[5:7])
    if pid.endswith("H1"):
        return date(year, month, 1), date(year, month, 15)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return date(year, month, 16), end


def period_label(pid: str) -> str:
    start, end = period_bounds(pid)
    return f"{start.month}/{start.day}-{end.month}/{end.day}"


def period_label_en(pid: str) -> str:
    start, end = period_bounds(pid)
    if start.month == end.month:
        return f"{start.strftime('%b')} {start.day}-{end.day}"
    return f"{start.strftime('%b')} {start.day}-{end.strftime('%b')} {end.day}"


def next_update_after(d: date) -> date:
    if d.day < 15:
        return date(d.year, d.month, 15)
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(flatten_strings(item))
        return parts
    if isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(flatten_strings(item))
        return parts
    return []


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def count_aliases(text: str, aliases: list[str]) -> int:
    total = 0
    normalized = normalize(text)
    for alias in aliases:
        needle = normalize(alias)
        if not needle:
            continue
        if re.search(r"[a-z0-9]", needle):
            total += len(re.findall(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", normalized))
        else:
            total += normalized.count(needle)
    return total


def load_snapshots() -> list[tuple[date, dict[str, Any]]]:
    snapshots: list[tuple[date, dict[str, Any]]] = []
    for path in sorted(DATA_DIR.glob("????-??-??.json")):
        d = parse_data_date(path)
        if not d:
            continue
        try:
            snapshots.append((d, json.loads(path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError as exc:
            print(f"[warn] skip invalid JSON {path.name}: {exc}", flush=True)
    return snapshots


def collect_category_text(payload: dict[str, Any], sections: list[str]) -> str:
    parts: list[str] = []
    for section in sections:
        parts.extend(flatten_strings(payload.get(section, [])))
    return "\n".join(parts)


def build() -> dict[str, Any]:
    snapshots = load_snapshots()
    if not snapshots:
        raise SystemExit("No dated JSON snapshots found in data/")

    latest_data_date = max(d for d, _ in snapshots)
    all_periods = sorted({period_id(d) for d, _ in snapshots})
    selected_periods = all_periods[-KEEP_PERIODS:]
    latest_period = selected_periods[-1]

    periods_payload = [
        {
            "id": pid,
            "label": period_label(pid),
            "label_en": period_label_en(pid),
        }
        for pid in selected_periods
    ]

    categories_payload = []
    for category in CATEGORIES:
        counts: dict[str, dict[str, int]] = {
            term["id"]: defaultdict(int) for term in category["terms"]
        }

        for snapshot_date, payload in snapshots:
            pid = period_id(snapshot_date)
            if pid not in selected_periods:
                continue
            text = collect_category_text(payload, category["sections"])
            for term in category["terms"]:
                counts[term["id"]][pid] += count_aliases(text, term["aliases"])

        max_count = max(
            [counts[term["id"]][pid] for term in category["terms"] for pid in selected_periods] or [1]
        )
        if max_count <= 0:
            max_count = 1

        term_payload = []
        for term in category["terms"]:
            series = []
            first_seen = None
            total_count = 0
            for pid in selected_periods:
                count = int(counts[term["id"]][pid])
                total_count += count
                if count > 0 and not first_seen:
                    first_seen = pid
                series.append(
                    {
                        "period": pid,
                        "label": period_label(pid),
                        "label_en": period_label_en(pid),
                        "count": count,
                        "score": round((count / max_count) * 100),
                    }
                )
            if total_count == 0:
                continue
            latest_count = series[-1]["count"]
            previous_count = series[-2]["count"] if len(series) > 1 else 0
            term_payload.append(
                {
                    "id": term["id"],
                    "label": term["label"],
                    "label_cn": term["label_cn"],
                    "latest_count": latest_count,
                    "delta": latest_count - previous_count,
                    "total_count": total_count,
                    "first_seen_period": first_seen,
                    "is_new": first_seen == latest_period and latest_count > 0,
                    "series": series,
                }
            )

        term_payload.sort(
            key=lambda item: (
                item["latest_count"],
                item["delta"],
                item["total_count"],
                item["label"],
            ),
            reverse=True,
        )
        top_terms = term_payload[:8]
        new_terms = [term for term in term_payload if term["is_new"]][:5]

        categories_payload.append(
            {
                "id": category["id"],
                "label": category["label"],
                "label_cn": category["label_cn"],
                "description": category["description"],
                "description_cn": category["description_cn"],
                "terms": top_terms,
                "new_terms": new_terms,
            }
        )

    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "updated_at": generated,
        "data_through": latest_data_date.isoformat(),
        "next_update": next_update_after(latest_data_date).isoformat(),
        "update_cadence": "semi-monthly",
        "update_cadence_cn": "每月 1 日 / 15 日自动刷新",
        "source": "AI Progress Hub archive JSON",
        "method": "Keyword and tag counts across dated site snapshots; scores are relative within each category.",
        "method_cn": "基于本站 data/YYYY-MM-DD.json 历史快照做关键词与标签词频统计；热度分数只代表本站记录中的相对热度。",
        "periods": periods_payload,
        "categories": categories_payload,
    }


def main() -> None:
    payload = build()
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
