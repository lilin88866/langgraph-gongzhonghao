"""Xiaohongshu real content API client."""

from __future__ import annotations

from app.schemas.hotspot import Platform
from app.tools.platform_http_api import PlatformHttpApiClient


class XiaohongshuApiClient(PlatformHttpApiClient):
    """HTTP client for Xiaohongshu account, note, work, and search data."""

    def __init__(self, *, base_url: str, api_key: str | None = None) -> None:
        super().__init__(
            platform=Platform.XIAOHONGSHU,
            env_prefix="XIAOHONGSHU",
            base_url=base_url,
            api_key=api_key,
            source_api="xiaohongshu-content-api",
        )

    @classmethod
    def from_env(cls) -> "XiaohongshuApiClient | None":
        client = PlatformHttpApiClient.from_env(
            platform=Platform.XIAOHONGSHU,
            env_prefix="XIAOHONGSHU",
            source_api="xiaohongshu-content-api",
        )
        if client is None:
            return None
        return cls(base_url=client.base_url, api_key=client.api_key)
