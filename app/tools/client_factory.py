"""Client factory for real platform APIs with mock fallback."""

from __future__ import annotations

import os

from app.schemas.hotspot import Platform
from app.tools.content_api import ContentApiClient, MockContentApiClient
from app.tools.douyin_api import DouyinApiClient
from app.tools.forgerss_xiaohongshu_api import ForgeRSSXiaohongshuClient
from app.tools.tianapi_wechat_api import TianapiWechatClient
from app.tools.toutiao_api import ToutiaoApiClient
from app.tools.wechat_api import WechatApiClient
from app.tools.wechat_download_api import WechatDownloadApiClient
from app.tools.xiaohongshu_api import XiaohongshuApiClient


REAL_CLIENTS = {
    Platform.DOUYIN: DouyinApiClient,
    Platform.XIAOHONGSHU: XiaohongshuApiClient,
    Platform.WECHAT: WechatApiClient,
    Platform.TOUTIAO: ToutiaoApiClient,
}


def build_content_clients(platforms: list[Platform]) -> dict[Platform, ContentApiClient]:
    """Build real clients when configured, otherwise use deterministic mocks.

    Set ``CONTENT_API_REQUIRE_REAL=1`` to disable mock fallback and surface a
    ``missing_client:<platform>`` quality flag from the collection agent.
    """

    require_real = os.getenv("CONTENT_API_REQUIRE_REAL", "").lower() in {"1", "true", "yes"}
    clients: dict[Platform, ContentApiClient] = {}
    for platform in platforms:
        if platform == Platform.WECHAT:
            wechat_client = _build_wechat_client()
            if wechat_client is not None:
                clients[platform] = wechat_client
                continue
        if platform == Platform.XIAOHONGSHU:
            xiaohongshu_client = _build_xiaohongshu_client()
            if xiaohongshu_client is not None:
                clients[platform] = xiaohongshu_client
                continue

        client_class = REAL_CLIENTS.get(platform)
        real_client = client_class.from_env() if client_class is not None else None
        if real_client is not None:
            clients[platform] = real_client
        elif not require_real:
            clients[platform] = MockContentApiClient(platform)
    return clients


def _build_wechat_client() -> ContentApiClient | None:
    provider = os.getenv("WECHAT_PROVIDER", "").lower()
    if provider == "wechat_download":
        return WechatDownloadApiClient.from_env()
    if provider == "tianapi":
        return TianapiWechatClient.from_env()
    return WechatApiClient.from_env()


def _build_xiaohongshu_client() -> ContentApiClient | None:
    provider = os.getenv("XIAOHONGSHU_PROVIDER", "").lower()
    if provider == "forgerss":
        return ForgeRSSXiaohongshuClient.from_env()
    return None
