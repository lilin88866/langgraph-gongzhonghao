import os
import unittest
from unittest.mock import patch

from app.agents.hotness_scoring import HotnessScoringAgent
from app.schemas.hotspot import AIRelevanceResult, EngagementMetrics, MediaType, NormalizedContent, Platform


class HotnessScoringAgentTest(unittest.TestCase):
    def test_wechat_hotness_only_scores_yesterday_articles_by_default(self) -> None:
        state = {
            "normalized_contents": [
                _content("yesterday", "2026-06-24T10:00:00+08:00"),
                _content("today", "2026-06-25T09:00:00+08:00"),
                _content("older", "2026-06-23T23:59:59+08:00"),
                _content("missing", None),
            ],
            "ai_relevance": [
                _relevance("yesterday"),
                _relevance("today"),
                _relevance("older"),
                _relevance("missing"),
            ],
        }

        with patch.dict(
            os.environ,
            {"WECHAT_HOTNESS_NOW": "2026-06-25T12:00:00+08:00", "WECHAT_HOTNESS_TIMEZONE_OFFSET_HOURS": "8"},
            clear=True,
        ):
            update = HotnessScoringAgent().invoke(state)

        self.assertEqual([score.content_id for score in update["hotness_scores"]], ["yesterday"])

    def test_wechat_hotness_window_can_be_disabled(self) -> None:
        state = {
            "normalized_contents": [_content("missing", None)],
            "ai_relevance": [_relevance("missing")],
        }

        with patch.dict(os.environ, {"WECHAT_HOTNESS_ONLY_YESTERDAY": "0"}, clear=True):
            update = HotnessScoringAgent().invoke(state)

        self.assertEqual([score.content_id for score in update["hotness_scores"]], ["missing"])


def _content(content_id: str, published_at: str | None) -> NormalizedContent:
    return NormalizedContent(
        platform=Platform.WECHAT,
        content_id=content_id,
        author="AI 公众号",
        title=f"{content_id} article",
        text="AI Agent 正在进入工作流。",
        media_type=MediaType.ARTICLE,
        published_at=published_at,
        metrics=EngagementMetrics(reads=1000, likes=30),
        url="https://mp.weixin.qq.com/s/demo",
        source_api="wechat-download-api",
        raw_payload={},
    )


def _relevance(content_id: str) -> AIRelevanceResult:
    return AIRelevanceResult(
        content_id=content_id,
        is_ai_related=True,
        confidence=0.9,
        categories=["agent"],
        keywords=["AI"],
        reason="测试",
    )


if __name__ == "__main__":
    unittest.main()
