"""WeChat collection agent backed by the external wechat-download-api service."""

from __future__ import annotations

import os

from app.schemas.hotspot import ApiDimension, HotspotState, Platform, RawContent, SourcePlan
from app.tools.wechat_download_api import WechatDownloadApiClient


class WechatDownloadCollectionAgent:
    """Collects WeChat data through the external wechat-download-api service."""

    def __init__(self, client: WechatDownloadApiClient | None = None, *, check_health: bool = True) -> None:
        self.client = client
        self.check_health = check_health

    def invoke(self, state: HotspotState) -> HotspotState:
        client = self.client or WechatDownloadApiClient.from_env()
        quality_flags = list(state.get("quality_flags", []))
        if client is None:
            quality_flags.append("missing_client:wechat_download")
            return {"raw_contents": [], "quality_flags": quality_flags}

        if self.check_health:
            try:
                is_available = client.check_health()
            except RuntimeError as exc:
                quality_flags.append(f"wechat_download_unavailable:{exc}")
                return {"raw_contents": [], "quality_flags": quality_flags}
            if not is_available:
                quality_flags.append("wechat_download_unavailable:health_check_failed")
                return {"raw_contents": [], "quality_flags": quality_flags}

        raw_contents: list[RawContent] = []
        _seed_account_names(client, state)
        for plan in _wechat_plans(state):
            try:
                raw_contents.extend(client.fetch(plan))
            except RuntimeError as exc:
                quality_flags.append(f"fetch_failed:wechat:{plan.dimension.value}:{exc}")

        return {"raw_contents": raw_contents, "quality_flags": quality_flags}


def _wechat_plans(state: HotspotState) -> list[SourcePlan]:
    plans = [plan for plan in state.get("source_plans", []) if plan.platform == Platform.WECHAT]
    planned_fakeids = {
        fakeid
        for plan in plans
        for fakeid in (plan.account_id, plan.metadata.get("fakeid"), plan.metadata.get("fake_id"))
        if fakeid
    }
    task = state.get("task")
    page_size = task.max_items_per_platform if task is not None else 20
    account_plans: list[SourcePlan] = []
    for account in state.get("wechat_accounts", [])[:_discovered_account_limit()]:
        if account.fakeid in planned_fakeids:
            continue
        planned_fakeids.add(account.fakeid)
        account_plans.append(
            SourcePlan(
                platform=Platform.WECHAT,
                dimension=ApiDimension.WORK_LIST,
                query=account.nickname,
                account_id=account.fakeid,
                priority=20,
                page_size=page_size,
                metadata={"fakeid": account.fakeid, "nickname": account.nickname},
            )
        )
    if account_plans and not _include_search_plans():
        return account_plans
    return account_plans + plans


def _seed_account_names(client: WechatDownloadApiClient, state: HotspotState) -> None:
    for account in state.get("wechat_accounts", []):
        if account.fakeid and account.nickname:
            client.account_names_by_fakeid[account.fakeid] = account.nickname


def _discovered_account_limit() -> int:
    return max(0, int(os.getenv("WECHAT_COLLECTION_DISCOVERED_ACCOUNT_LIMIT", "10")))


def _include_search_plans() -> bool:
    return os.getenv("WECHAT_COLLECTION_INCLUDE_SEARCH_PLANS", "0").lower() in {"1", "true", "yes"}
