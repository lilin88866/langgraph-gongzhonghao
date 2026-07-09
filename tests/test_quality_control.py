import unittest

from app.agents.quality_control import QualityControlAgent
from app.schemas.hotspot import EngagementMetrics, GeneratedArticle, MediaType, NormalizedContent, Platform, TrendCluster


class QualityControlAgentTest(unittest.TestCase):
    def test_flags_rewrite_that_is_too_short_for_source(self) -> None:
        source_text = "原文关键解释。" * 300
        article = GeneratedArticle(
            title="短改写",
            subtitle="测试",
            body_markdown="### 公众号改写正文\n\n<section><p>短稿。配图建议：正文卡片。</p></section>",
            source_trend_id="trend-1",
            source_content_ids=["content-1"],
            recommended_tags=[],
        )
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="content-1",
                    author="AI 公众号",
                    title="长文原文",
                    text=source_text,
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(),
                    url="https://mp.weixin.qq.com/s/source",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "trends": [
                TrendCluster(
                    trend_id="trend-1",
                    name="长文原文",
                    summary="测试",
                    content_ids=["content-1"],
                    platforms=[Platform.WECHAT],
                    hotness_score=80.0,
                    lifecycle="rising",
                    evidence=["content-1"],
                )
            ],
            "generated_article": article,
        }

        update = QualityControlAgent().invoke(state)

        self.assertTrue(any(flag.startswith("article_rewrite_too_short:") for flag in update["quality_flags"]))
        self.assertTrue(any(flag.startswith("article_rewrite_too_short:") for flag in update["review_flags"]))
        self.assertTrue(update["human_review_required"])

    def test_information_flags_do_not_require_human_review(self) -> None:
        update = QualityControlAgent().invoke(
            {
                "trends": [object()],
                "quality_info": ["wechat_accounts_discovered:3"],
                "quality_flags": [],
            }
        )

        self.assertEqual(update["quality_info"], ["wechat_accounts_discovered:3"])
        self.assertEqual(update["review_flags"], [])
        self.assertFalse(update["human_review_required"])

    def test_fetch_failures_and_article_similarity_require_review(self) -> None:
        update = QualityControlAgent().invoke(
            {
                "trends": [object()],
                "quality_flags": ["fetch_failed:wechat:work_list:captcha"],
                "article_compliance": {"similarity": 62, "threshold": 40, "compliant": False},
            }
        )

        self.assertIn("fetch_failed:wechat:work_list:captcha", update["review_flags"])
        self.assertIn("article_similarity_too_high:62%", update["review_flags"])
        self.assertTrue(update["human_review_required"])

    def test_flags_missing_inline_image_suggestions(self) -> None:
        article = GeneratedArticle(
            title="只有文末配图",
            subtitle="测试",
            body_markdown=(
                "### 公众号改写正文\n\n"
                "<section><p>正文讲方法，但没有正文配图卡片。</p></section>\n\n"
                "### 配图建议\n\n"
                "1. 正文配图：流程图。"
            ),
            source_trend_id="trend-1",
            source_content_ids=["content-1"],
            recommended_tags=[],
        )

        update = QualityControlAgent().invoke({"trends": [object()], "generated_article": article})

        self.assertIn("missing_inline_image_suggestions", update["quality_flags"])
        self.assertIn("missing_inline_image_suggestions", update["review_flags"])
        self.assertTrue(update["human_review_required"])

    def test_accepts_inline_image_suggestions_in_body(self) -> None:
        article = GeneratedArticle(
            title="正文已有配图",
            subtitle="测试",
            body_markdown=(
                "### 公众号改写正文\n\n"
                "<section><p>正文段落。</p><section><p>配图建议：流程图</p></section></section>\n\n"
                "### 配图建议\n\n"
                "1. 正文配图复核：流程图。"
            ),
            source_trend_id="trend-1",
            source_content_ids=["content-1"],
            recommended_tags=[],
        )

        update = QualityControlAgent().invoke({"trends": [object()], "generated_article": article})

        self.assertNotIn("missing_inline_image_suggestions", update["quality_flags"])


if __name__ == "__main__":
    unittest.main()
