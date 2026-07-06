"""Normalization agent."""

from __future__ import annotations

from hashlib import sha1
from typing import Any

from app.schemas.hotspot import EngagementMetrics, HotspotState, MediaType, NormalizedContent, RawContent


class NormalizationAgent:
    """Maps platform payloads into a provider-neutral content shape."""

    def invoke(self, state: HotspotState) -> HotspotState:
        normalized = [_normalize(raw) for raw in state.get("raw_contents", [])]
        return {"normalized_contents": normalized}


def _normalize(raw: RawContent) -> NormalizedContent:
    payload = raw.raw_payload
    metrics = payload.get("metrics", {})
    return NormalizedContent(
        platform=raw.platform,
        content_id=str(payload.get("id") or _stable_id(raw.platform.value, str(payload))),
        author=payload.get("author"),
        title=str(payload.get("title") or ""),
        text=str(payload.get("text") or payload.get("summary") or ""),
        media_type=_media_type(payload.get("media_type")),
        published_at=payload.get("published_at"),
        metrics=EngagementMetrics(
            views=_int_or_none(metrics.get("views")),
            likes=_int_or_none(metrics.get("likes")),
            comments=_int_or_none(metrics.get("comments")),
            shares=_int_or_none(metrics.get("shares")),
            saves=_int_or_none(metrics.get("saves")),
            reads=_int_or_none(metrics.get("reads")),
            watching=_int_or_none(metrics.get("watching")),
        ),
        url=payload.get("url"),
        source_api=raw.source_api,
        raw_payload=payload,
    )


def _media_type(value: Any) -> MediaType:
    try:
        return MediaType(str(value))
    except ValueError:
        return MediaType.UNKNOWN


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stable_id(*parts: str) -> str:
    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
