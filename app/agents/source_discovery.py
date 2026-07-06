"""Data source discovery agent."""

from __future__ import annotations

from app.schemas.hotspot import ApiDimension, HotspotState, Platform, SourcePlan


class SourceDiscoveryAgent:
    """Turns a product research task into concrete platform API plans."""

    def invoke(self, state: HotspotState) -> HotspotState:
        task = state["task"]
        plans: list[SourcePlan] = []
        for platform in task.platforms:
            for dimension in task.dimensions:
                keywords = task.keywords if dimension == ApiDimension.SEARCH_QUERY else [task.keywords[0]]
                for keyword in keywords:
                    plans.append(
                        SourcePlan(
                            platform=platform,
                            dimension=dimension,
                            query=keyword,
                            priority=_priority_for(platform, dimension),
                            page_size=task.max_items_per_platform,
                            metadata={"objective": task.objective, "time_window_hours": task.time_window_hours},
                        )
                    )
        return {"source_plans": sorted(plans, key=lambda item: item.priority, reverse=True)}


def _priority_for(platform: Platform, dimension: ApiDimension) -> int:
    base = {
        ApiDimension.SEARCH_QUERY: 100,
        ApiDimension.WORK_LIST: 80,
        ApiDimension.ARTICLE_DETAIL: 70,
        ApiDimension.ACCOUNT_INFO: 60,
    }[dimension]
    if platform == Platform.TOUTIAO:
        base -= 5
    return base
