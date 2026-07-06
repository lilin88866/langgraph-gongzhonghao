"""Hotness scoring agent."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from math import log10
from typing import Any

from app.agents.constants import PLATFORM_WEIGHTS
from app.schemas.hotspot import Platform
from app.schemas.hotspot import HotnessScore, HotspotState, NormalizedContent


class HotnessScoringAgent:
    """Computes comparable hotness scores across platforms."""

    def invoke(self, state: HotspotState) -> HotspotState:
        relevance_by_id = {item.content_id: item for item in state.get("ai_relevance", [])}
        scores: list[HotnessScore] = []
        for content in state.get("normalized_contents", []):
            if not _is_in_hotness_window(content):
                continue
            relevance = relevance_by_id.get(content.content_id)
            if relevance is None or not relevance.is_ai_related:
                continue
            scores.append(_score_hotness(content, relevance.confidence))
        return {"hotness_scores": sorted(scores, key=lambda item: item.hotness_score, reverse=True)}


def _score_hotness(content: NormalizedContent, confidence: float) -> HotnessScore:
    metrics = content.metrics
    views_or_reads = metrics.views or metrics.reads or 0
    engagement = sum(value or 0 for value in (metrics.likes, metrics.comments, metrics.shares, metrics.saves, metrics.watching))
    velocity = log10(max(views_or_reads, 1)) * 12
    engagement_quality = log10(max(engagement, 1)) * 14
    platform_weight = PLATFORM_WEIGHTS.get(content.platform, 1.0)
    hotness = (velocity * 0.45 + engagement_quality * 0.45 + confidence * 20) * platform_weight
    return HotnessScore(
        content_id=content.content_id,
        hotness_score=round(hotness, 2),
        velocity_score=round(velocity, 2),
        engagement_quality_score=round(engagement_quality, 2),
        platform_weight=platform_weight,
        reason="综合新鲜度代理指标、互动质量、AI 相关性和平台权重。",
    )


def _is_in_hotness_window(content: NormalizedContent) -> bool:
    if content.platform != Platform.WECHAT:
        return True
    if os.getenv("WECHAT_HOTNESS_ONLY_YESTERDAY", "1").lower() in {"0", "false", "no"}:
        return True

    published_at = _parse_datetime(content.published_at)
    if published_at is None:
        return False

    tz = timezone(timedelta(hours=float(os.getenv("WECHAT_HOTNESS_TIMEZONE_OFFSET_HOURS", "8"))))
    now = _hotness_now(tz)
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_published_at = published_at.astimezone(tz)
    return start <= local_published_at < end


def _hotness_now(tz: timezone) -> datetime:
    override = os.getenv("WECHAT_HOTNESS_NOW")
    if override:
        parsed = _parse_datetime(override)
        if parsed is not None:
            return parsed.astimezone(tz)
    return datetime.now(tz)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        parsed = datetime.fromtimestamp(number, tz=timezone.utc)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
