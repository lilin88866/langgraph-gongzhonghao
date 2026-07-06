"""Trend analysis agent."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha1

from app.schemas.hotspot import HotspotState, TrendCluster


class TrendAnalysisAgent:
    """Clusters related content into trend candidates."""

    def invoke(self, state: HotspotState) -> HotspotState:
        content_by_id = {item.content_id: item for item in state.get("normalized_contents", [])}
        score_by_id = {item.content_id: item for item in state.get("hotness_scores", [])}
        relevance_by_id = {item.content_id: item for item in state.get("ai_relevance", [])}
        grouped: dict[str, list[str]] = defaultdict(list)

        for content_id, relevance in relevance_by_id.items():
            if content_id not in score_by_id or not relevance.is_ai_related:
                continue
            category = relevance.categories[0] if relevance.categories else "ai_general"
            grouped[category].append(content_id)

        trends: list[TrendCluster] = []
        for category, content_ids in grouped.items():
            scores = [score_by_id[content_id].hotness_score for content_id in content_ids]
            platforms = sorted({content_by_id[content_id].platform for content_id in content_ids}, key=str)
            trend_id = _stable_id("trend", category, ",".join(content_ids))
            top_evidence = sorted(content_ids, key=lambda item: score_by_id[item].hotness_score, reverse=True)[:3]
            average_score = round(sum(scores) / max(len(scores), 1), 2)
            trends.append(
                TrendCluster(
                    trend_id=trend_id,
                    name=_trend_name(category),
                    summary=f"{category} 在 {len(platforms)} 个平台形成讨论，共覆盖 {len(content_ids)} 条内容。",
                    content_ids=content_ids,
                    platforms=platforms,
                    hotness_score=average_score,
                    lifecycle=_lifecycle(average_score, len(platforms)),
                    evidence=top_evidence,
                )
            )

        return {"trends": sorted(trends, key=lambda item: item.hotness_score, reverse=True)}


def _trend_name(category: str) -> str:
    names = {
        "large_model": "大模型产品更新",
        "ai_product": "AI 产品与智能体工作流",
        "ai_content": "AI 内容生成",
        "ai_coding": "AI 编程工具",
        "ai_business": "AI 商业化与创业",
        "ai_policy": "AI 政策与合规",
        "ai_general": "AI 综合热点",
    }
    return names.get(category, category)


def _lifecycle(score: float, platform_count: int) -> str:
    if score >= 70 and platform_count >= 2:
        return "peaking"
    if score >= 55:
        return "rising"
    if score >= 35:
        return "emerging"
    return "cooling"


def _stable_id(*parts: str) -> str:
    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
