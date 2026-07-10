"""Quality control agent."""

from __future__ import annotations

import re

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
        flags.extend(_rewrite_length_flags(state))
        flags.extend(_inline_image_suggestion_flags(state))
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
        "article_rewrite_too_short:",
        "article_rewrite_too_long:",
        "missing_inline_image_suggestions",
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
        min_similarity = article_compliance.get("min_similarity")
        max_similarity = article_compliance.get("max_similarity") or article_compliance.get("threshold")
        if isinstance(similarity, (int, float)) and isinstance(min_similarity, (int, float)) and similarity < min_similarity:
            return [f"article_similarity_too_low:{similarity}%"]
        if isinstance(similarity, (int, float)) and isinstance(max_similarity, (int, float)) and similarity > max_similarity:
            return [f"article_similarity_too_high:{similarity}%"]
    return []


def _rewrite_length_flags(state: HotspotState) -> list[str]:
    article = state.get("generated_article")
    body_markdown = getattr(article, "body_markdown", "") if article is not None else ""
    rewrite_length = _plain_text_length(body_markdown)
    source_length = max((len((content.text or "").strip()) for content in state.get("normalized_contents", [])), default=0)
    if source_length <= 0 or rewrite_length <= 0:
        return []
    ratio = rewrite_length / source_length
    if ratio < 0.5:
        return [f"article_rewrite_too_short:{rewrite_length}/{source_length}:{ratio:.0%}"]
    if ratio > 0.9:
        return [f"article_rewrite_too_long:{rewrite_length}/{source_length}:{ratio:.0%}"]
    return []


def _inline_image_suggestion_flags(state: HotspotState) -> list[str]:
    article = state.get("generated_article")
    body_markdown = getattr(article, "body_markdown", "") if article is not None else ""
    if not body_markdown.strip():
        return []
    body_section = _published_body_section(body_markdown)
    if not body_section.strip():
        return []
    if "配图建议" not in body_section:
        return ["missing_inline_image_suggestions"]
    return []


def _published_body_section(body_markdown: str) -> str:
    match = re.search(r"###\s*公众号改写正文\s*(.+?)(?:\n###\s*(?:来源与复核提醒|配图建议|发布风险自查|Tags|内部改写依据|wechat-rewrite 任务 Prompt|合规检测)\b|$)", body_markdown, flags=re.DOTALL)
    if match:
        return match.group(1)
    return re.split(r"\n###\s*(?:来源与复核提醒|配图建议|发布风险自查|Tags|内部改写依据|wechat-rewrite 任务 Prompt|合规检测)\b", body_markdown, maxsplit=1)[0]


def _plain_text_length(text: str) -> int:
    without_code = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    without_html = re.sub(r"<[^>]+>", " ", without_code)
    without_markdown = re.sub(r"#+\s*", " ", without_html)
    return len(re.sub(r"\s+", "", without_markdown))
