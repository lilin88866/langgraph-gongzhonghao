"""Product insight agent."""

from __future__ import annotations

from app.schemas.hotspot import FollowUpDecision, HotspotState, ProductInsight


class ProductInsightAgent:
    """Translates trend signals into product-manager-friendly insights."""

    def invoke(self, state: HotspotState) -> HotspotState:
        insights: list[ProductInsight] = []
        for trend in state.get("trends", []):
            decision = FollowUpDecision.VALIDATE if trend.hotness_score >= 55 else FollowUpDecision.WATCH
            if trend.hotness_score < 30:
                decision = FollowUpDecision.SKIP
            insights.append(
                ProductInsight(
                    trend_id=trend.trend_id,
                    decision=decision,
                    user_pain=f"用户正在围绕“{trend.name}”寻找更省时、更低门槛的解决方式。",
                    product_opportunity=f"将“{trend.name}”包装为可验证的 AI 产品场景或内容专题。",
                    validation_hypothesis=f"如果该趋势连续跨平台升温，则优先验证 {trend.name} 的付费意愿和留存场景。",
                    target_users=["AI 产品经理", "内容创作者", "效率工具用户"],
                )
            )
        return {"product_insights": insights}
