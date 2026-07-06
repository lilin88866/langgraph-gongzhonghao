"""AI relevance agent."""

from __future__ import annotations

from app.agents.constants import AI_CATEGORY_KEYWORDS
from app.schemas.hotspot import AIRelevanceResult, HotspotState, NormalizedContent


class AIRelevanceAgent:
    """Filters and labels content that is actually about AI."""

    def invoke(self, state: HotspotState) -> HotspotState:
        results = [_classify_ai_relevance(content) for content in state.get("normalized_contents", [])]
        return {"ai_relevance": results}


def _classify_ai_relevance(content: NormalizedContent) -> AIRelevanceResult:
    searchable = f"{content.title} {content.text}".lower()
    categories: list[str] = []
    matched_keywords: list[str] = []
    for category, keywords in AI_CATEGORY_KEYWORDS.items():
        matched = [keyword for keyword in keywords if keyword.lower() in searchable]
        if matched:
            categories.append(category)
            matched_keywords.extend(matched)
    generic_ai_hit = "ai" in searchable or "人工智能" in searchable
    is_related = bool(categories or generic_ai_hit)
    confidence = min(0.95, 0.35 + len(categories) * 0.2 + (0.2 if generic_ai_hit else 0))
    return AIRelevanceResult(
        content_id=content.content_id,
        is_ai_related=is_related,
        confidence=round(confidence if is_related else 0.15, 2),
        categories=categories or (["ai_general"] if generic_ai_hit else []),
        keywords=sorted(set(matched_keywords or (["AI"] if generic_ai_hit else []))),
        reason="命中 AI 主题关键词和场景描述。" if is_related else "未发现明确 AI 主题证据。",
    )
