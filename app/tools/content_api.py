"""Content API client interfaces.

Real providers should implement ``ContentApiClient`` and return raw provider
payloads. Agent nodes keep those payloads intact for traceability.
"""

from __future__ import annotations

from hashlib import sha1
from typing import Any, Protocol

from app.schemas.hotspot import ApiDimension, Platform, RawContent, SourcePlan


class ContentApiClient(Protocol):
    source_api: str

    def fetch(self, plan: SourcePlan) -> list[RawContent]:
        """Fetch raw content for a source plan."""


class MockContentApiClient:
    """Deterministic sample client for local workflow development."""

    def __init__(self, platform: Platform, source_api: str = "mock-content-api") -> None:
        self.platform = platform
        self.source_api = source_api

    def fetch(self, plan: SourcePlan) -> list[RawContent]:
        query = plan.query or "AI"
        items: list[RawContent] = []
        for index in range(min(plan.page_size, 3)):
            payload = self._sample_payload(plan, query, index)
            items.append(
                RawContent(
                    platform=plan.platform,
                    dimension=plan.dimension,
                    source_api=self.source_api,
                    raw_payload=payload,
                )
            )
        return items

    def _sample_payload(self, plan: SourcePlan, query: str, index: int) -> dict[str, Any]:
        platform_prefix = plan.platform.value
        dimension = plan.dimension.value
        query_key = sha1(query.encode("utf-8")).hexdigest()[:8]
        return {
            "id": f"{platform_prefix}-{dimension}-{query_key}-{index}",
            "author": f"{platform_prefix}_creator_{index}",
            "title": f"{query} 在 {plan.platform.value} 的 {dimension} 热点观察 {index + 1}",
            "text": f"{query} 在 {plan.platform.value} 的 AI 产品、工具和用户场景讨论正在升温。",
            "media_type": _default_media_type(plan.platform, plan.dimension),
            "published_at": None,
            "url": f"https://example.com/{platform_prefix}/{dimension}/{query_key}/{index}",
            "metrics": {
                "views": 5000 + index * 1500,
                "likes": 300 + index * 60,
                "comments": 40 + index * 10,
                "shares": 25 + index * 8,
                "saves": 80 + index * 20,
                "reads": 6000 + index * 1200,
                "watching": 20 + index * 5,
            },
        }


def _default_media_type(platform: Platform, dimension: ApiDimension) -> str:
    if dimension == ApiDimension.ACCOUNT_INFO:
        return "account"
    if platform == Platform.DOUYIN:
        return "video"
    if platform == Platform.XIAOHONGSHU:
        return "note"
    return "article"
