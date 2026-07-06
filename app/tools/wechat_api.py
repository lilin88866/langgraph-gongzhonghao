"""WeChat Official Accounts real content API client."""

from __future__ import annotations

from app.schemas.hotspot import Platform
from app.tools.platform_http_api import PlatformHttpApiClient


class WechatApiClient(PlatformHttpApiClient):
    """HTTP client for WeChat account, article, and search data."""

    def __init__(self, *, base_url: str, api_key: str | None = None) -> None:
        super().__init__(
            platform=Platform.WECHAT,
            env_prefix="WECHAT",
            base_url=base_url,
            api_key=api_key,
            source_api="wechat-content-api",
        )

    @classmethod
    def from_env(cls) -> "WechatApiClient | None":
        client = PlatformHttpApiClient.from_env(
            platform=Platform.WECHAT,
            env_prefix="WECHAT",
            source_api="wechat-content-api",
        )
        if client is None:
            return None
        return cls(base_url=client.base_url, api_key=client.api_key)
