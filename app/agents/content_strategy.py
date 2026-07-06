"""Content strategy agent."""

from __future__ import annotations

from app.schemas.hotspot import ContentStrategy, HotspotState, Platform


class ContentStrategyAgent:
    """Creates platform-specific topic angles from validated trends."""

    def invoke(self, state: HotspotState) -> HotspotState:
        strategies: list[ContentStrategy] = []
        for trend in state.get("trends", []):
            for platform in trend.platforms:
                strategies.append(
                    ContentStrategy(
                        trend_id=trend.trend_id,
                        platform=platform,
                        title_direction=_title_direction(platform, trend.name),
                        core_argument=f"{trend.name} 不只是热点，更反映了用户对 AI 场景落地的真实需求。",
                        format_suggestion=_format_suggestion(platform),
                        supporting_content_ids=trend.evidence,
                    )
                )
        return {"content_strategies": strategies}


def _title_direction(platform: Platform, trend_name: str) -> str:
    if platform == Platform.DOUYIN:
        return f"3 分钟看懂：为什么大家都在讨论{trend_name}"
    if platform == Platform.XIAOHONGSHU:
        return f"我用{trend_name}解决了一个真实效率问题"
    if platform == Platform.WECHAT:
        return f"{trend_name}背后的产品机会与用户需求"
    return f"{trend_name}最新趋势复盘"


def _format_suggestion(platform: Platform) -> str:
    return {
        Platform.DOUYIN: "短视频脚本：冲突开场、案例展示、行动建议",
        Platform.XIAOHONGSHU: "图文笔记：问题场景、工具体验、避坑清单",
        Platform.WECHAT: "深度文章：趋势背景、证据链、产品判断",
        Platform.TOUTIAO: "热点解读：事实摘要、争议点、延伸阅读",
    }[platform]
