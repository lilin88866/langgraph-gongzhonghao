"""Quality control agent."""

from __future__ import annotations

from app.schemas.hotspot import HotspotState, NormalizedContent


class QualityControlAgent:
    """Adds review flags for low-confidence or structurally risky output."""

    def invoke(self, state: HotspotState) -> HotspotState:
        flags = list(state.get("quality_flags", []))
        info = list(state.get("quality_info", []))
        review_flags = list(state.get("review_flags", []))
        relevance = state.get("ai_relevance", [])
        if any(item.confidence < 0.45 for item in relevance):
            flags.append("low_ai_relevance_confidence")
        if not state.get("trends"):
            flags.append("no_trend_detected")
        duplicate_titles = _duplicate_titles(state.get("normalized_contents", []))
        flags.extend(f"duplicate_title:{title}" for title in duplicate_titles)
        review_flags.extend(_review_flags_for(flags))
        review_flags.extend(_article_review_flags(state.get("article_compliance")))
        return {
            "quality_flags": sorted(set(flags)),
            "quality_info": sorted(set(info)),
            "review_flags": sorted(set(review_flags)),
            "human_review_required": bool(review_flags),
        }


def _duplicate_titles(contents: list[NormalizedContent]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for content in contents:
        title = content.title.strip()
        if not title:
            continue
        if title in seen:
            duplicates.add(title)
        seen.add(title)
    return sorted(duplicates)


def _review_flags_for(flags: list[str]) -> list[str]:
    review_prefixes = (
        "missing_client:",
        "fetch_failed:",
        "wechat_download_unavailable:",
        "wechat_account_discovery_failed:",
        "wechat_account_subscribe_failed:",
        "low_ai_relevance_confidence",
        "no_trend_detected",
        "duplicate_title:",
    )
    info_prefixes = ("wechat_accounts_discovered:",)
    return [
        flag
        for flag in flags
        if flag.startswith(review_prefixes) and not flag.startswith(info_prefixes)
    ]


def _article_review_flags(article_compliance: object) -> list[str]:
    if not isinstance(article_compliance, dict):
        return []
    if article_compliance.get("compliant") is False:
        similarity = article_compliance.get("similarity")
        max_similarity = article_compliance.get("max_similarity") or article_compliance.get("threshold")
        if isinstance(similarity, (int, float)) and isinstance(max_similarity, (int, float)) and similarity > max_similarity:
            return [f"article_similarity_too_high:{similarity}%"]
    return []
