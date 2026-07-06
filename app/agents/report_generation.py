"""Report generation agent."""

from __future__ import annotations

from datetime import datetime

from app.schemas.hotspot import HotspotReport, HotspotState


class ReportGenerationAgent:
    """Builds a traceable report from prior structured outputs."""

    def invoke(self, state: HotspotState) -> HotspotState:
        task = state["task"]
        scores = state.get("hotness_scores", [])[:10]
        trends = state.get("trends", [])
        insights = state.get("product_insights", [])
        summary = f"围绕“{task.objective}”共识别 {len(trends)} 个趋势和 {len(insights)} 条产品洞察。"
        report = HotspotReport(
            title=f"AI 热点数据分析报告 - {datetime.now().strftime('%Y-%m-%d')}",
            summary=summary,
            top_content_ids=[item.content_id for item in scores],
            trend_ids=[item.trend_id for item in trends],
            insight_ids=[item.trend_id for item in insights],
            strategy_count=len(state.get("content_strategies", [])),
        )
        return {"report": report}
