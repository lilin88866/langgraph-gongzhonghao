import unittest

from app.graphs.ai_hotspot_graph import format_hotspot_report, format_hotspot_report_html
from app.schemas.hotspot import (
    AIRelevanceResult,
    EngagementMetrics,
    FollowUpDecision,
    GeneratedArticle,
    HotnessScore,
    HotspotReport,
    MediaType,
    NormalizedContent,
    Platform,
    ProductInsight,
    TrendCluster,
    WechatAccountCandidate,
)


class ReportFormattingTest(unittest.TestCase):
    def test_report_formats_hotspots_as_tables_grouped_by_category(self) -> None:
        state = _sample_report_state()

        report = format_hotspot_report(state)

        self.assertIn("## 分类内容明细", report)
        self.assertIn("| 排名 | 分类 | 平台 | 公众号/作者 | 标题 | 热度 | 阅读 | 点赞 | 评论 | 链接 |", report)
        self.assertIn("### AI 产品与智能体工作流", report)
        self.assertIn("## 自动发现公众号", report)
        self.assertIn("## Agent 生成公众号文章", report)
        self.assertIn("Claude AI 前沿", report)
        self.assertIn("作者", report)
        self.assertIn("新一代AI智能体应用", report)
        self.assertNotIn("<em", report)

    def test_report_formats_browser_friendly_html_tables(self) -> None:
        html = format_hotspot_report_html(_sample_report_state())

        self.assertIn("<table>", html)
        self.assertIn("tbody tr:nth-child(even)", html)
        self.assertIn("category-card", html)
        self.assertIn("自动发现公众号", html)
        self.assertIn("Agent 生成公众号文章", html)
        self.assertIn("Claude AI 前沿", html)
        self.assertIn("公众号/作者", html)
        self.assertIn("作者", html)
        self.assertIn("新一代AI智能体应用", html)
        self.assertIn('target="_blank"', html)
        self.assertNotIn("<em", html)


def _sample_report_state() -> dict:
    return {
        "normalized_contents": [
            NormalizedContent(
                platform=Platform.WECHAT,
                content_id="content-1",
                author="作者",
                title='新一代<em class="highlight">AI</em>智能体应用',
                text="AI 智能体工作流",
                media_type=MediaType.ARTICLE,
                published_at=None,
                metrics=EngagementMetrics(reads=100, likes=20, comments=3),
                url="https://mp.weixin.qq.com/s/demo",
                source_api="wechat-download-api",
                raw_payload={},
            )
        ],
        "ai_relevance": [
            AIRelevanceResult(
                content_id="content-1",
                is_ai_related=True,
                confidence=0.95,
                categories=["ai_product"],
                keywords=["AI", "智能体"],
                reason="命中 AI 主题关键词。",
            )
        ],
        "hotness_scores": [
            HotnessScore(
                content_id="content-1",
                hotness_score=42.0,
                velocity_score=20.0,
                engagement_quality_score=10.0,
                platform_weight=1.0,
                reason="测试",
            )
        ],
        "trends": [
            TrendCluster(
                trend_id="trend-1",
                name="AI 产品与智能体工作流",
                summary="测试趋势",
                content_ids=["content-1"],
                platforms=[Platform.WECHAT],
                hotness_score=42.0,
                lifecycle="emerging",
                evidence=["content-1"],
            )
        ],
        "product_insights": [
            ProductInsight(
                trend_id="trend-1",
                decision=FollowUpDecision.VALIDATE,
                user_pain="测试痛点",
                product_opportunity="测试机会",
                validation_hypothesis="测试假设",
                target_users=["AI 产品经理"],
            )
        ],
        "content_strategies": [],
        "wechat_accounts": [
            WechatAccountCandidate(
                fakeid="fake_ai",
                nickname="Claude AI 前沿",
                alias="claude-ai",
                relevance_score=0.8,
                matched_keywords=["AI", "Claude"],
                subscribed=True,
                reason="账号名称或简介命中：AI、Claude",
            )
        ],
        "generated_article": GeneratedArticle(
            title="AI 产品与智能体工作流正在变成真实机会",
            subtitle="基于热点生成",
            body_markdown="## 开头\n\n这是一篇由 Agent 生成的文章。",
            source_trend_id="trend-1",
            source_content_ids=["content-1"],
            recommended_tags=["AI", "智能体"],
        ),
        "report": HotspotReport(
            title="测试报告",
            summary="测试摘要",
            top_content_ids=["content-1"],
            trend_ids=["trend-1"],
            insight_ids=["trend-1"],
            strategy_count=0,
        ),
    }


if __name__ == "__main__":
    unittest.main()
