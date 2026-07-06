"""Task routing agent."""

from __future__ import annotations

from app.schemas.hotspot import ApiDimension, HotspotState, HotspotTask, Platform


class TaskRouterAgent:
    """Creates a conservative task when callers provide only an objective."""

    def invoke(self, state: HotspotState) -> HotspotState:
        if "task" in state:
            return {}
        task = HotspotTask(
            objective="发现今天中文内容平台上的 AI 产品与应用热点",
            keywords=["AI", "大模型", "智能体", "AI 产品"],
            platforms=[Platform.DOUYIN, Platform.XIAOHONGSHU, Platform.WECHAT],
            dimensions=[
                ApiDimension.SEARCH_QUERY,
                ApiDimension.ARTICLE_DETAIL,
                ApiDimension.WORK_LIST,
                ApiDimension.ACCOUNT_INFO,
            ],
        )
        return {"task": task}
