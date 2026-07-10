import os
import unittest
from unittest.mock import Mock, patch

from app.agents.wechat_article_writing import (
    REWRITE_SIMILARITY_MAX,
    WechatArticleWritingAgent,
    _compliance_report,
    _execute_rewrite_prompt,
)
from app.schemas.hotspot import (
    EngagementMetrics,
    FollowUpDecision,
    HotnessScore,
    MediaType,
    NormalizedContent,
    Platform,
    ProductInsight,
    TrendCluster,
)
from app.tools.qwen_rewrite_client import QwenRewriteResult


class WechatArticleWritingAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = patch.dict(os.environ, {"QWEN_API_KEY": "", "DASHSCOPE_API_KEY": ""})
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.env_patcher.stop()

    def test_agent_generates_article_from_selected_trend_evidence(self) -> None:
        progress_events: list[dict[str, str]] = []
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="content-1",
                    author="AI 公众号",
                    title='<em class="highlight">智能体</em>工作流开始落地',
                    text="智能体正在把资料整理和内容生成串成稳定流程。",
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=100),
                    url="https://mp.weixin.qq.com/s/demo",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "trends": [
                TrendCluster(
                    trend_id="trend-1",
                    name="AI 产品与智能体工作流",
                    summary="测试趋势",
                    content_ids=["content-1"],
                    platforms=[Platform.WECHAT],
                    hotness_score=88.0,
                    lifecycle="rising",
                    evidence=["content-1"],
                )
            ],
            "product_insights": [
                ProductInsight(
                    trend_id="trend-1",
                    decision=FollowUpDecision.VALIDATE,
                    user_pain="用户需要稳定的自动化流程。",
                    product_opportunity="把智能体包装成可执行工作流。",
                    validation_hypothesis="如果连续升温，则验证付费意愿。",
                    target_users=["AI 产品经理"],
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="content-1",
                    hotness_score=66.0,
                    velocity_score=24.0,
                    engagement_quality_score=18.0,
                    platform_weight=1.0,
                    reason="测试",
                )
            ],
            "progress_callback": progress_events.append,
        }

        update = WechatArticleWritingAgent().invoke(state)

        article = update["generated_article"]
        self.assertIn("article_compliance", update)
        self.assertIn("similarity", update["article_compliance"])
        self.assertEqual(update["article_compliance"]["threshold"], REWRITE_SIMILARITY_MAX)
        self.assertIsNone(article.llm_usage)
        self.assertLessEqual(len(article.title), 20)
        self.assertIn("### 改写标题", article.body_markdown)
        self.assertIn("### 改写状态", article.body_markdown)
        self.assertIn("### 公众号改写正文", article.body_markdown)
        self.assertIn("<section", article.body_markdown)
        self.assertIn("智能体工作流开始落地", article.body_markdown)
        self.assertIn("AI 知识型订阅号文章", article.body_markdown)
        self.assertIn("这个 AI 话题到底解决什么问题", article.body_markdown)
        self.assertIn("常见误区", article.body_markdown)
        self.assertIn("阅读 100", article.body_markdown)
        self.assertIn("热度 66.0", article.body_markdown)
        self.assertIn("### Tags", article.body_markdown)
        self.assertIn("#AI", article.body_markdown)
        self.assertIn("### 合规检测", article.body_markdown)
        self.assertIn("与原文相似度：", article.body_markdown)
        self.assertIn("合规判断：", article.body_markdown)
        self.assertIn("### wechat-rewrite 任务 Prompt", article.body_markdown)
        self.assertIn("配图建议：", article.body_markdown)
        self.assertIn("核心结构图", article.body_markdown)
        self.assertIn("实践路径图", article.body_markdown)
        self.assertIn("智能体正在把资料整理和内容生成串成稳定流程。", article.rewrite_prompt)
        self.assertIn("确定性原文骨架", article.rewrite_prompt)
        self.assertNotIn("<em", article.body_markdown)
        self.assertIn("用户需要稳定的自动化流程。", article.body_markdown)
        self.assertEqual(article.source_content_ids, ["content-1"])
        phases = [event["phase"] for event in progress_events]
        self.assertIn("rewrite-outline", phases)
        self.assertIn("rewrite-draft", phases)
        self.assertIn("rewrite-length-check", phases)
        self.assertIn("rewrite-similarity-check", phases)

    def test_agent_ranks_article_evidence_by_hotness_votes(self) -> None:
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="low",
                    author="账号一",
                    title="低互动文章",
                    text="",
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=100, likes=1),
                    url=None,
                    source_api="wechat-download-api",
                    raw_payload={},
                ),
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="high",
                    author="账号二",
                    title="高投票文章",
                    text="",
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=12000, likes=300, comments=20),
                    url=None,
                    source_api="wechat-download-api",
                    raw_payload={},
                ),
            ],
            "trends": [
                TrendCluster(
                    trend_id="trend-1",
                    name="AI 产品与智能体工作流",
                    summary="测试趋势",
                    content_ids=["low", "high"],
                    platforms=[Platform.WECHAT],
                    hotness_score=88.0,
                    lifecycle="rising",
                    evidence=["low"],
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="low",
                    hotness_score=20.0,
                    velocity_score=10.0,
                    engagement_quality_score=5.0,
                    platform_weight=1.0,
                    reason="测试",
                ),
                HotnessScore(
                    content_id="high",
                    hotness_score=91.0,
                    velocity_score=40.0,
                    engagement_quality_score=30.0,
                    platform_weight=1.0,
                    reason="测试",
                ),
            ],
        }

        update = WechatArticleWritingAgent().invoke(state)

        article = update["generated_article"]
        self.assertEqual(article.source_content_ids[:2], ["high", "low"])
        self.assertIn("阅读 1.2万，点赞 300，评论 20，热度 91.0", article.body_markdown)
        self.assertIn("最高热度 91.0", article.subtitle)

    def test_agent_builds_article_level_rewrite_for_claude_codex_source(self) -> None:
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="claude",
                    author="爱AI的大刘",
                    title="Claude / Codex 可以直接复制的 CLAUDE.md / AGENTS.md，实测效果惊艳",
                    text="一份可以直接抄的 Claude.md / Agents.md / Soul.md，让 AI 编程工具更懂项目规则。",
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=0),
                    url="https://mp.weixin.qq.com/s/a_1x_Bj9cypObx5hDJj6MA",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "trends": [
                TrendCluster(
                    trend_id="selected-claude",
                    name="Claude / Code…",
                    summary="测试趋势",
                    content_ids=["claude"],
                    platforms=[Platform.WECHAT],
                    hotness_score=16.5,
                    lifecycle="rising",
                    evidence=["claude"],
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="claude",
                    hotness_score=16.5,
                    velocity_score=10.0,
                    engagement_quality_score=5.0,
                    platform_weight=1.0,
                    reason="测试",
                )
            ],
        }

        article = WechatArticleWritingAgent().invoke(state)["generated_article"]

        self.assertEqual(article.title, "AI编程提示词指南")
        self.assertIn("CLAUDE.md", article.body_markdown)
        self.assertIn("AGENTS.md", article.body_markdown)
        self.assertIn("先写清项目背景", article.body_markdown)
        self.assertIn("不要直接复制别人的模板不改", article.body_markdown)
        self.assertIn("你是 `langgraph-study` 的微信公众号改写 Agent", article.rewrite_prompt)
        self.assertIn("### 发布风险自查", article.rewrite_prompt)

    def test_agent_prompt_sets_minimum_length_for_long_source(self) -> None:
        long_text = "\n\n".join(
            f"第{index}段：Agent 范式在工程实践中需要解释清楚目标、流程、成本、延迟和维护边界。"
            for index in range(1, 80)
        )
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="long",
                    author="AI 知识号",
                    title="Agent 范式长文解析",
                    text=long_text,
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=1000),
                    url="https://mp.weixin.qq.com/s/long",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "trends": [
                TrendCluster(
                    trend_id="selected-long",
                    name="Agent 范式",
                    summary="测试趋势",
                    content_ids=["long"],
                    platforms=[Platform.WECHAT],
                    hotness_score=80.0,
                    lifecycle="rising",
                    evidence=["long"],
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="long",
                    hotness_score=80.0,
                    velocity_score=30.0,
                    engagement_quality_score=20.0,
                    platform_weight=1.0,
                    reason="长文",
                )
            ],
        }

        article = WechatArticleWritingAgent().invoke(state)["generated_article"]

        self.assertIn("原文正文长度约", article.rewrite_prompt)
        self.assertIn("应控制在", article.rewrite_prompt)
        self.assertIn("约为原文 50%-90%", article.rewrite_prompt)
        self.assertIn("禁止超过原文长度", article.rewrite_prompt)
        self.assertIn("原文关键信息展开", article.body_markdown)
        self.assertIn("原文要点 1", article.body_markdown)
        self.assertIn("第1段", article.body_markdown)
        self.assertIn("配图建议：Agent 范式长文解析核心结构图", article.body_markdown)
        self.assertIn("配图建议：Agent 范式长文解析实践路径图", article.body_markdown)

    def test_agent_adds_missing_outline_blocks_when_llm_rewrite_is_too_short(self) -> None:
        long_text = "Agent 工程实践需要解释目标、流程、工具配置、上下文管理、复核方式和风险边界。" * 120
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="long",
                    author="AI 知识号",
                    title="Agent 长文实践",
                    text=long_text,
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=1000),
                    url="https://mp.weixin.qq.com/s/long",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "trends": [
                TrendCluster(
                    trend_id="selected-long",
                    name="Agent 长文实践",
                    summary="测试趋势",
                    content_ids=["long"],
                    platforms=[Platform.WECHAT],
                    hotness_score=80.0,
                    lifecycle="rising",
                    evidence=["long"],
                )
            ],
        }

        with patch(
            "app.agents.wechat_article_writing._execute_rewrite_prompt",
            return_value=("### 公众号改写正文\n\n<section><p>短稿。</p></section>\n\n### 来源与复核提醒\n\n1. 待复核", {"provider": "fallback", "total_tokens": 100}),
        ) as execute:
            article = WechatArticleWritingAgent().invoke(state)["generated_article"]

        self.assertEqual(execute.call_count, 1)
        self.assertIn("先看这篇文章在讲什么", article.body_markdown)
        self.assertIn("Agent 工程实践要讲清目标", article.body_markdown)
        self.assertNotIn("原文段落 1", article.body_markdown)
        self.assertNotIn("信息块", article.body_markdown)
        self.assertNotIn("原文核对信息", article.body_markdown)
        assert article.llm_usage is not None
        self.assertTrue(article.llm_usage["length_retry"]["accepted"])
        self.assertTrue(article.llm_usage["length_retry"]["deterministic_supplement"])
        self.assertGreaterEqual(article.llm_usage["similarity_retry"]["similarity"], 25)
        self.assertLessEqual(article.llm_usage["similarity_retry"]["similarity"], 35)

    def test_agent_switches_to_source_outline_when_llm_rewrite_is_too_different(self) -> None:
        source_text = "Claude Loops 的核心是先写清目标，再让模型执行、检查、修正，并通过低 Token 的上下文管理降低成本。"
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="loops",
                    author="AI 知识号",
                    title="如何写高质量、低Token消耗的Loops",
                    text=source_text,
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=1000),
                    url="https://mp.weixin.qq.com/s/loops",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "trends": [
                TrendCluster(
                    trend_id="selected-loops",
                    name="Claude Loops",
                    summary="测试趋势",
                    content_ids=["loops"],
                    platforms=[Platform.WECHAT],
                    hotness_score=80.0,
                    lifecycle="rising",
                    evidence=["loops"],
                )
            ],
        }

        with patch(
            "app.agents.wechat_article_writing._execute_rewrite_prompt",
            return_value=("### 公众号改写正文\n\n<section><p>今天聊一个完全不同的 AI 产品商业化故事。</p></section>", {"provider": "fallback", "total_tokens": 100}),
        ) as execute:
            article = WechatArticleWritingAgent().invoke(state)["generated_article"]

        self.assertEqual(execute.call_count, 1)
        self.assertIn("Claude Loops 的核心", article.body_markdown)
        assert article.llm_usage is not None
        self.assertFalse(article.llm_usage["similarity_retry"]["accepted"])
        self.assertTrue(article.llm_usage["similarity_retry"]["deterministic_fallback"])
        self.assertTrue(article.llm_usage["similarity_retry"]["forced_source_preserving_fallback"])
        self.assertGreaterEqual(article.llm_usage["similarity_retry"]["similarity"], 25)

    def test_agent_uses_source_preserving_fallback_when_similarity_repair_fails(self) -> None:
        source_text = "Claude Loops 的核心是先写清目标，再让模型执行、检查、修正，并通过低 Token 的上下文管理降低成本。" * 12
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="loops",
                    author="AI 知识号",
                    title="如何写高质量、低Token消耗的Loops",
                    text=source_text,
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=1000),
                    url="https://mp.weixin.qq.com/s/loops",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "trends": [
                TrendCluster(
                    trend_id="selected-loops",
                    name="Claude Loops",
                    summary="测试趋势",
                    content_ids=["loops"],
                    platforms=[Platform.WECHAT],
                    hotness_score=80.0,
                    lifecycle="rising",
                    evidence=["loops"],
                )
            ],
        }

        with patch(
            "app.agents.wechat_article_writing._execute_rewrite_prompt",
            return_value=("### 公众号改写正文\n\n<section><p>这是一篇完全不同的创业故事。</p></section>", {"provider": "fallback", "total_tokens": 100}),
        ) as execute:
            article = WechatArticleWritingAgent().invoke(state)["generated_article"]

        self.assertEqual(execute.call_count, 1)
        self.assertIn("先看这篇文章在讲什么", article.body_markdown)
        self.assertIn("关键做法：沿着原文逻辑拆开看", article.body_markdown)
        self.assertIn("Claude Loops 的核心", article.body_markdown)
        self.assertNotIn("上一次模型改写", article.body_markdown)
        self.assertNotIn("信息块", article.body_markdown)
        self.assertNotIn("原文核对信息", article.body_markdown)
        self.assertNotIn("原文骨架", article.body_markdown)
        self.assertNotIn("继续讲另一个产品增长故事", article.body_markdown)
        assert article.llm_usage is not None
        self.assertTrue(article.llm_usage["similarity_retry"]["forced_source_preserving_fallback"])
        self.assertGreaterEqual(article.llm_usage["similarity_retry"]["similarity"], 25)

    def test_compliance_report_flags_high_similarity(self) -> None:
        source = NormalizedContent(
            platform=Platform.WECHAT,
            content_id="source",
            author="AI 公众号",
            title="AI 工作流",
            text="智能体正在把资料整理和内容生成串成稳定流程。",
            media_type=MediaType.ARTICLE,
            published_at=None,
            metrics=EngagementMetrics(),
            url=None,
            source_api="wechat-download-api",
            raw_payload={},
        )

        report = _compliance_report("智能体正在把资料整理和内容生成串成稳定流程。", source)

        self.assertIn("与原文相似度：", report)
        self.assertIn("合规判断：需人工复核", report)
        self.assertIn("目标相似度为 25%-35%", report)

    def test_execute_rewrite_prompt_falls_back_to_ollama_on_quota_error(self) -> None:
        primary = Mock()
        primary.model = "qwen-primary"
        primary.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/"
        primary.rewrite_with_usage.side_effect = RuntimeError("Qwen rewrite HTTP 429: Free allocated quota exceeded")
        fallback = Mock()
        fallback.model = "qwen2.5:7b"
        fallback.base_url = "http://localhost:11434/v1/"
        fallback.rewrite_with_usage.return_value = QwenRewriteResult(
            content="本地 Ollama 改写结果",
            usage={"model": "qwen2.5:7b", "prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
        )

        with (
            patch.dict(os.environ, {"QWEN_REWRITE_PREFER_LOCAL": "0"}),
            patch("app.agents.wechat_article_writing.QwenRewriteClient.from_env", return_value=primary),
            patch("app.agents.wechat_article_writing.QwenRewriteClient.fallback_from_env", return_value=fallback),
        ):
            result, usage = _execute_rewrite_prompt("rewrite prompt")

        self.assertEqual(result, "本地 Ollama 改写结果")
        assert usage is not None
        self.assertEqual(usage["provider"], "fallback")
        self.assertEqual(usage["total_tokens"], 46)
        primary.rewrite_with_usage.assert_called_once_with("rewrite prompt")
        fallback.rewrite_with_usage.assert_called_once_with("rewrite prompt")

    def test_execute_rewrite_prompt_falls_back_to_ollama_on_timeout(self) -> None:
        primary = Mock()
        primary.model = "qwen-primary"
        primary.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/"
        primary.rewrite_with_usage.side_effect = RuntimeError("Qwen rewrite request failed: The read operation timed out")
        fallback = Mock()
        fallback.model = "qwen2.5:7b"
        fallback.base_url = "http://localhost:11434/v1/"
        fallback.rewrite_with_usage.return_value = QwenRewriteResult(
            content="本地 Ollama 改写结果",
            usage={"model": "qwen2.5:7b", "prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )

        with (
            patch.dict(os.environ, {"QWEN_REWRITE_PREFER_LOCAL": "0"}),
            patch("app.agents.wechat_article_writing.QwenRewriteClient.from_env", return_value=primary),
            patch("app.agents.wechat_article_writing.QwenRewriteClient.fallback_from_env", return_value=fallback),
        ):
            result, usage = _execute_rewrite_prompt("rewrite prompt")

        self.assertEqual(result, "本地 Ollama 改写结果")
        assert usage is not None
        self.assertEqual(usage["total_tokens"], 3)
        primary.rewrite_with_usage.assert_called_once_with("rewrite prompt")
        fallback.rewrite_with_usage.assert_called_once_with("rewrite prompt")

    def test_execute_rewrite_prompt_prefers_local_fallback_by_default(self) -> None:
        primary = Mock()
        primary.model = "qwen-primary"
        primary.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/"
        fallback = Mock()
        fallback.model = "qwen2.5:7b"
        fallback.base_url = "http://localhost:11434/v1/"
        fallback.rewrite_with_usage.return_value = QwenRewriteResult(
            content="本地优先改写结果",
            usage={"model": "qwen2.5:7b", "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("app.agents.wechat_article_writing.QwenRewriteClient.from_env", return_value=primary),
            patch("app.agents.wechat_article_writing.QwenRewriteClient.fallback_from_env", return_value=fallback),
        ):
            result, usage = _execute_rewrite_prompt("rewrite prompt")

        self.assertEqual(result, "本地优先改写结果")
        assert usage is not None
        self.assertEqual(usage["provider"], "fallback")
        self.assertEqual(usage["base_url"], "http://localhost:11434/v1/")
        fallback.rewrite_with_usage.assert_called_once_with("rewrite prompt")
        primary.rewrite_with_usage.assert_not_called()

    def test_execute_rewrite_prompt_does_not_fallback_on_non_quota_error(self) -> None:
        primary = Mock()
        primary.model = "qwen-primary"
        primary.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/"
        primary.rewrite_with_usage.side_effect = RuntimeError("Qwen rewrite request failed: connection refused")

        with (
            patch.dict(os.environ, {"QWEN_REWRITE_PREFER_LOCAL": "0"}),
            patch("app.agents.wechat_article_writing.QwenRewriteClient.from_env", return_value=primary),
            patch("app.agents.wechat_article_writing.QwenRewriteClient.fallback_from_env") as fallback_from_env,
        ):
            result, usage = _execute_rewrite_prompt("rewrite prompt")

        assert result is not None
        assert usage is not None
        self.assertIn("Qwen 改写调用失败", result)
        self.assertIn("connection refused", result)
        self.assertIsNone(usage["total_tokens"])
        self.assertIn("connection refused", usage["error"])
        fallback_from_env.assert_called_once()
        fallback_from_env.return_value.rewrite_with_usage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
