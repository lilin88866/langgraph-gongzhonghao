"""Platform collection agent."""

from __future__ import annotations

import os

from app.schemas.hotspot import HotspotState, Platform, RawContent
from app.tools.client_factory import build_content_clients
from app.tools.content_api import ContentApiClient
from app.agents.wechat_download_collection import WechatDownloadCollectionAgent


class PlatformCollectionAgent:
    """Collects raw payloads using platform-specific content API clients."""

    def __init__(
        self,
        clients: dict[Platform, ContentApiClient] | None = None,
        wechat_agent: WechatDownloadCollectionAgent | None = None,
    ) -> None:
        self.clients = clients
        self.wechat_agent = wechat_agent

    def invoke(self, state: HotspotState) -> HotspotState:
        task = state["task"]
        clients = self.clients or build_content_clients(task.platforms)
        raw_contents: list[RawContent] = []
        quality_flags = list(state.get("quality_flags", []))

        handled_by_wechat_agent = _uses_wechat_download_agent()
        if handled_by_wechat_agent:
            wechat_update = (self.wechat_agent or WechatDownloadCollectionAgent()).invoke(state)
            raw_contents.extend(wechat_update.get("raw_contents", []))
            quality_flags = list(wechat_update.get("quality_flags", quality_flags))

        for plan in state.get("source_plans", []):
            if handled_by_wechat_agent and plan.platform == Platform.WECHAT:
                continue
            client = clients.get(plan.platform)
            if client is None:
                quality_flags.append(f"missing_client:{plan.platform.value}")
                continue
            try:
                raw_contents.extend(client.fetch(plan))
            except RuntimeError as exc:
                quality_flags.append(f"fetch_failed:{plan.platform.value}:{plan.dimension.value}:{exc}")

        return {"raw_contents": raw_contents, "quality_flags": quality_flags}


def _uses_wechat_download_agent() -> bool:
    return os.getenv("WECHAT_PROVIDER", "").lower() == "wechat_download"
