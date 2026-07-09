import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from app.schemas.hotspot import EngagementMetrics, HotnessScore, MediaType, NormalizedContent, Platform

try:
    from app.server import (
        _markdown_line_to_html,
        _image_negative_prompt,
        _image_prompt_from_text,
        _image_urls_from_output,
        _rewrite_candidates,
        _wechat_10w_hot_candidates,
        _enrich_content_detail_with_status,
        _rewrite_selected_article,
        _video_workspace_html,
        _rewrite_workspace_html,
        _allow_stale_candidate_rewrite,
        _augment_content_with_image_text,
        _delete_previous_wechat_download_cache,
        _save_workflow_state_cache,
        _should_auto_start_ollama,
        _should_auto_start_wechat_download_api,
        _source_image_urls,
        _state_from_candidate_snapshot,
        _summarize_state,
        _WORKFLOW_CACHE,
        WORKFLOW_CACHE_FILE,
        _is_reference_image_too_small_error,
        _without_reference_image_args,
        _textbook_original_question_from_basis,
        _textbook_solution_from_basis,
        _title_from_instruction,
        _textbook_query_words,
        _textbook_required_topic_terms,
        _textbook_topic_matches,
        _textbook_hit_text_is_usable,
        _has_complete_textbook_solution_block,
        _textbook_glob,
        _subject_from_instruction,
        _ensure_china_textbook_pdf,
        _video_agent_source_html,
        workflow_rewrite_candidates,
        workflow_rewrite_image,
        workflow_video_agent_run,
        workflow_video_render,
        _workflow_graph_html,
    )
except ImportError:  # pragma: no cover - optional server extra may be absent locally.
    _markdown_line_to_html = None
    _image_negative_prompt = None
    _image_prompt_from_text = None
    _image_urls_from_output = None
    _rewrite_candidates = None
    _wechat_10w_hot_candidates = None
    _enrich_content_detail_with_status = None
    _rewrite_selected_article = None
    _video_workspace_html = None
    _rewrite_workspace_html = None
    _allow_stale_candidate_rewrite = None
    _augment_content_with_image_text = None
    _delete_previous_wechat_download_cache = None
    _save_workflow_state_cache = None
    _should_auto_start_ollama = None
    _should_auto_start_wechat_download_api = None
    _source_image_urls = None
    _state_from_candidate_snapshot = None
    _summarize_state = None
    _WORKFLOW_CACHE = None
    WORKFLOW_CACHE_FILE = None
    _is_reference_image_too_small_error = None
    _without_reference_image_args = None
    _textbook_original_question_from_basis = None
    _textbook_solution_from_basis = None
    _title_from_instruction = None
    _textbook_query_words = None
    _textbook_required_topic_terms = None
    _textbook_topic_matches = None
    _textbook_hit_text_is_usable = None
    _has_complete_textbook_solution_block = None
    _textbook_glob = None
    _subject_from_instruction = None
    _ensure_china_textbook_pdf = None
    _video_agent_source_html = None
    workflow_rewrite_candidates = None
    workflow_rewrite_image = None
    workflow_video_agent_run = None
    workflow_video_render = None
    _workflow_graph_html = None


@unittest.skipIf(_summarize_state is None, "server extra is not installed")
class ServerTest(unittest.TestCase):
    def test_summarize_state_counts_workflow_outputs(self) -> None:
        summary = _summarize_state(
            {
                "raw_contents": [object(), object()],
                "normalized_contents": [object()],
                "trends": [],
                "product_insights": [object()],
                "content_strategies": [object(), object(), object()],
                "quality_flags": ["no_trend_detected"],
                "quality_info": ["wechat_accounts_discovered:2"],
                "review_flags": ["no_trend_detected"],
                "human_review_required": True,
            }
        )

        self.assertEqual(summary["raw_content_count"], 2)
        self.assertEqual(summary["normalized_content_count"], 1)
        self.assertEqual(summary["trend_count"], 0)
        self.assertEqual(summary["insight_count"], 1)
        self.assertEqual(summary["strategy_count"], 3)
        self.assertEqual(summary["quality_flags"], ["no_trend_detected"])
        self.assertEqual(summary["quality_info"], ["wechat_accounts_discovered:2"])
        self.assertEqual(summary["review_flags"], ["no_trend_detected"])
        self.assertTrue(summary["human_review_required"])

    def test_article_html_keeps_skill_html_lines(self) -> None:
        self.assertEqual(_markdown_line_to_html("### 公众号改写正文"), "<h3>公众号改写正文</h3>")
        self.assertEqual(
            _markdown_line_to_html('<section style="font-size:16px;">'),
            '<section style="font-size:16px;">',
        )
        self.assertEqual(
            _markdown_line_to_html('<h2 style="font-size:20px;">简要回答</h2>'),
            '<h2 style="font-size:20px;">简要回答</h2>',
        )

    def test_rewrite_candidates_add_light_status(self) -> None:
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="content-1",
                    author="AI 公众号",
                    title="AI 工作流文章",
                    text="",
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=12000, likes=300),
                    url="https://mp.weixin.qq.com/s/demo",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="content-1",
                    hotness_score=91.0,
                    velocity_score=40.0,
                    engagement_quality_score=30.0,
                    platform_weight=1.0,
                    reason="测试",
                )
            ],
        }

        [candidate] = _rewrite_candidates(state)

        self.assertEqual(candidate["light"], "green")
        self.assertEqual(candidate["title"], "AI 工作流文章")
        self.assertEqual(candidate["reads"], 12000)
        self.assertIn("ai_hot_score", candidate)
        self.assertIn("ai", candidate["matched_keywords"])
        self.assertEqual(candidate["readiness"], "missing")

    def test_rewrite_candidates_prioritize_ai_knowledge_hot_articles(self) -> None:
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="general-hot",
                    author="科技号",
                    title="普通科技新闻",
                    text="这是一篇普通科技新闻。" * 80,
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=95000, likes=100),
                    url="https://mp.weixin.qq.com/s/general",
                    source_api="wechat-download-api",
                    raw_payload={},
                ),
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="ai-knowledge",
                    author="AI 知识号",
                    title="AI Agent 架构实践指南",
                    text="本文拆解大模型 Agent 工具调用、RAG 流程和实践方法。" * 80,
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=60000, likes=300),
                    url="https://mp.weixin.qq.com/s/ai",
                    source_api="wechat-download-api",
                    raw_payload={"image_urls": ["https://mmbiz.qpic.cn/demo.jpg"]},
                ),
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="general-hot",
                    hotness_score=92.0,
                    velocity_score=40.0,
                    engagement_quality_score=30.0,
                    platform_weight=1.0,
                    reason="普通高热",
                ),
                HotnessScore(
                    content_id="ai-knowledge",
                    hotness_score=80.0,
                    velocity_score=35.0,
                    engagement_quality_score=25.0,
                    platform_weight=1.0,
                    reason="AI 知识",
                ),
            ],
        }

        candidates = _rewrite_candidates(state)

        self.assertEqual(candidates[0]["content_id"], "ai-knowledge")
        self.assertGreater(candidates[0]["ai_hot_score"], candidates[1]["ai_hot_score"])
        self.assertEqual(candidates[0]["readiness"], "ready")
        self.assertEqual(candidates[0]["image_count"], 1)

    def test_image_text_evidence_is_appended_to_selected_content(self) -> None:
        content = NormalizedContent(
            platform=Platform.WECHAT,
            content_id="content-1",
            author="AI 公众号",
            title="AI 图片文章",
            text="正文已有文本。",
            media_type=MediaType.ARTICLE,
            published_at=None,
            metrics=EngagementMetrics(reads=1000),
            url="https://mp.weixin.qq.com/s/demo",
            source_api="wechat-download-api",
            raw_payload={"image_urls": ["https://mmbiz.qpic.cn/demo.jpg"]},
        )

        with (
            patch("app.server._image_ocr_enabled", return_value=True),
            patch("app.server._extract_image_text_with_qwen", return_value=("图片里的关键流程：检索、生成、校验。", None)),
        ):
            augmented, evidence = _augment_content_with_image_text(content)

        self.assertIn("【图片文字 OCR 补充证据】", augmented.text)
        self.assertIn("检索、生成、校验", augmented.text)
        self.assertEqual(evidence["status"], "extracted")
        self.assertEqual(evidence["processed_image_count"], 1)

    def test_rewrite_candidates_skip_wechat_account_results(self) -> None:
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="account-1",
                    author="AI",
                    title="AI",
                    text="",
                    media_type=MediaType.ACCOUNT,
                    published_at=None,
                    metrics=EngagementMetrics(),
                    url=None,
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="account-1",
                    hotness_score=12.1,
                    velocity_score=10.0,
                    engagement_quality_score=2.0,
                    platform_weight=1.0,
                    reason="账号搜索结果",
                )
            ],
        }

        self.assertEqual(_rewrite_candidates(state), [])

    def test_rewrite_candidates_keep_missing_reads_unknown(self) -> None:
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="content-1",
                    author="AI 公众号",
                    title="没有统计字段的文章",
                    text="AI Agent 实践指南。" * 80,
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(),
                    url="https://mp.weixin.qq.com/s/no-metrics",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="content-1",
                    hotness_score=22.0,
                    velocity_score=0.0,
                    engagement_quality_score=0.0,
                    platform_weight=1.0,
                    reason="无统计字段",
                )
            ],
        }

        [candidate] = _rewrite_candidates(state)

        self.assertIsNone(candidate["reads"])
        self.assertIsNone(candidate["likes"])
        self.assertIsNone(candidate["comments"])

    def test_wechat_10w_hot_candidates_rank_reads_then_ai_heat(self) -> None:
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="known-reads",
                    author="AI 公众号",
                    title="阅读量明确的 AI 文章",
                    text="AI Agent 实践指南。" * 80,
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=12000, likes=20),
                    url="https://mp.weixin.qq.com/s/known",
                    source_api="wechat-download-api",
                    raw_payload={},
                ),
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="unknown-reads",
                    author="AI 公众号",
                    title="AI Agent 架构实践指南",
                    text="本文拆解大模型 Agent 工具调用、RAG 流程和实践方法。" * 80,
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(),
                    url="https://mp.weixin.qq.com/s/unknown",
                    source_api="wechat-download-api",
                    raw_payload={},
                ),
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="known-reads",
                    hotness_score=40.0,
                    velocity_score=0.0,
                    engagement_quality_score=0.0,
                    platform_weight=1.0,
                    reason="有阅读量",
                ),
                HotnessScore(
                    content_id="unknown-reads",
                    hotness_score=90.0,
                    velocity_score=0.0,
                    engagement_quality_score=0.0,
                    platform_weight=1.0,
                    reason="无阅读量但 AI 热度高",
                ),
            ],
        }

        candidates = _wechat_10w_hot_candidates(state, limit=2)

        self.assertEqual(candidates[0]["content_id"], "known-reads")
        self.assertEqual(candidates[0]["source"], "wechat-10w-hot")
        self.assertIn("阅读量 12000", candidates[0]["hot_reason"])
        self.assertIn("未返回阅读量", candidates[1]["hot_reason"])

    def test_rewrite_selected_article_uses_selected_content(self) -> None:
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="content-1",
                    author="AI 公众号",
                    title="AI 工作流文章",
                    text="AI 正在进入具体工作流。",
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=12000, likes=300, comments=20),
                    url="https://mp.weixin.qq.com/s/demo",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="content-1",
                    hotness_score=91.0,
                    velocity_score=40.0,
                    engagement_quality_score=30.0,
                    platform_weight=1.0,
                    reason="测试",
                )
            ],
        }

        with (
            patch("app.server.WechatDownloadApiClient.from_env", return_value=None),
            patch.dict(os.environ, {"QWEN_API_KEY": "", "DASHSCOPE_API_KEY": ""}),
        ):
            article, source = _rewrite_selected_article(state, "content-1")

        self.assertIsNotNone(article)
        assert article is not None
        self.assertIn("AI 工作流文章", article.body_markdown)
        self.assertIn("### 公众号改写正文", article.body_markdown)
        self.assertEqual(source["content_id"], "content-1")
        self.assertEqual(source["title"], "AI 工作流文章")
        self.assertIn("article_compliance", source)
        self.assertFalse(source["human_review_required"])
        self.assertEqual(source["review_flags"], [])

    def test_enrich_content_detail_reports_short_fetch_failure(self) -> None:
        content = NormalizedContent(
            platform=Platform.WECHAT,
            content_id="content-1",
            author="AI 公众号",
            title="短正文文章",
            text="只有十二字",
            media_type=MediaType.ARTICLE,
            published_at=None,
            metrics=EngagementMetrics(),
            url="https://mp.weixin.qq.com/s/demo",
            source_api="wechat-download-api",
            raw_payload={},
        )

        with patch("app.server.WechatDownloadApiClient.from_env", return_value=None):
            enriched, status = _enrich_content_detail_with_status(content)

        self.assertEqual(enriched.text, "只有十二字")
        self.assertEqual(status["status"], "missing_client")
        self.assertEqual(status["final_text_length"], 5)
        self.assertIn("未配置", status["message"])

    def test_rewrite_workspace_contains_flow_ui(self) -> None:
        html = _rewrite_workspace_html()

        self.assertIn("微信热点改写工作台", html)
        self.assertIn("拉取和发布前先完成微信登录", html)
        self.assertIn("http://localhost:5000/login.html", html)
        self.assertIn("https://mp.weixin.qq.com/", html)
        self.assertIn("微信公众号后台发布入口", html)
        self.assertNotIn("触发验证码，请稍后重试", html)
        self.assertNotIn("WECHAT_REFRESH_BATCH_SIZE", html)
        self.assertIn("绿灯", html)
        self.assertIn("/workflow/rewrite/candidates", html)
        self.assertIn("/workflow/rewrite/selected", html)
        self.assertIn("/workflow/rewrite/selected/stream", html)
        self.assertIn("/workflow/rewrite/subscriptions/refresh/stream", html)
        self.assertIn("手动更新订阅号文章", html)
        self.assertIn("wechat-10w-hot 高热榜", html)
        self.assertIn("/workflow/rewrite/hot-candidates", html)
        self.assertIn("loadHotCandidates", html)
        self.assertIn("currentCandidateMode", html)
        self.assertIn("hot_badge", html)
        self.assertIn("hot_reason", html)
        self.assertIn("manualRefreshSubscriptions", html)
        self.assertIn("refresh-progress", html)
        self.assertIn("activeRefreshTimerId", html)
        self.assertIn("updateRefreshElapsedProgress", html)
        self.assertIn("stopRefreshElapsedProgress", html)
        self.assertIn("rewrite-progress", html)
        self.assertIn("activeRewriteTimerId", html)
        self.assertIn("updateRewriteElapsedProgress", html)
        self.assertIn("stopRewriteElapsedProgress", html)
        self.assertIn("formatStreamError", html)
        self.assertIn("改写流连接中断", html)
        self.assertIn("handleRewriteStreamEvent", html)
        self.assertIn("appendRewriteProgress", html)
        self.assertIn("原文 ${sourceTextLength} 字", html)
        self.assertIn("改写稿 ${rewriteTextLength} 字", html)
        self.assertIn("总耗时 ${formatSeconds", html)
        self.assertIn("已耗时", html)
        self.assertIn("candidatesById", html)
        self.assertIn("localStorage", html)
        self.assertIn("AI 知识型高热公众号文章", html)
        self.assertIn("图文 OCR 证据增强", html)
        self.assertIn("状态/图片", html)
        self.assertIn("formatSignals", html)
        self.assertIn("formatMetric", html)
        self.assertIn("未知", html)
        self.assertIn("image-ocr", html)
        self.assertIn("langgraph-study:rewrite:candidates:v4", html)
        self.assertIn("activeRewriteRequestId", html)
        self.assertIn("当前改写来源", html)
        self.assertIn("cache_only=${refresh ? \"false\" : \"true\"}", html)
        self.assertIn("candidate: candidatesById.get(contentId)", html)
        self.assertIn("图片生成图标", html)
        self.assertIn("🖼", html)
        self.assertIn("buildSuggestionText", html)
        self.assertIn("collectSuggestionGroup", html)
        self.assertIn("insertImageAction", html)
        self.assertIn("isInlineImageSuggestionCard", html)
        self.assertIn("closestInlineImageSuggestionCard", html)
        self.assertIn("block.anchor", html)
        self.assertIn("inline-image-prompt", html)
        self.assertIn("inline-reference-images", html)
        self.assertIn("reference_image", html)
        self.assertIn("currentSourceImages", html)
        self.assertIn("临时出图 prompt 模板", html)
        self.assertIn("buildTemporaryPromptTemplate", html)
        self.assertIn("只能使用清晰、可读、语义正确的简体中文", html)
        self.assertIn("不要英文单词", html)
        self.assertIn("不要繁体字", html)
        self.assertIn("不要伪中文", html)
        self.assertIn("不要乱码字母", html)
        self.assertIn("suggestion, reference_image", html)
        self.assertIn("enhanceImageSuggestions", html)
        self.assertIn("findImageSuggestionBlocks", html)
        self.assertIn("已继续显示浏览器本地缓存", html)
        self.assertIn("/workflow/rewrite/image", html)

    def test_delete_previous_wechat_download_cache_keeps_today_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "wechat_article_lists"
            detail_cache_dir = Path(temp_dir) / "wechat_article_details"
            cache_dir.mkdir()
            detail_cache_dir.mkdir()
            yesterday_cache = cache_dir / "old.json"
            today_cache = cache_dir / "today.json"
            yesterday_detail_cache = detail_cache_dir / "old-detail.json"
            today_detail_cache = detail_cache_dir / "today-detail.json"
            workflow_cache = Path(temp_dir) / "workflow_rewrite_state.json"
            yesterday_cache.write_text(
                json.dumps({"cached_at": "2026-07-07T10:00:00+00:00", "payload": {}}),
                encoding="utf-8",
            )
            today_cache.write_text(
                json.dumps({"cached_at": "2026-07-08T01:00:00+00:00", "payload": {}}),
                encoding="utf-8",
            )
            yesterday_detail_cache.write_text(
                json.dumps({"cached_at": "2026-07-07T10:00:00+00:00", "payload": {}}),
                encoding="utf-8",
            )
            today_detail_cache.write_text(
                json.dumps({"cached_at": "2026-07-08T01:00:00+00:00", "payload": {}}),
                encoding="utf-8",
            )
            workflow_cache.write_text(
                json.dumps({"cached_at": "2026-07-07T10:00:00+00:00", "state": {}}),
                encoding="utf-8",
            )

            with (
                patch("app.server.ARTICLE_LIST_CACHE_DIR", cache_dir),
                patch("app.server.ARTICLE_DETAIL_CACHE_DIR", detail_cache_dir),
                patch("app.server.WORKFLOW_CACHE_FILE", workflow_cache),
            ):
                result = _delete_previous_wechat_download_cache(
                    now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
                )

            self.assertEqual(result["article_list_cache_deleted"], 1)
            self.assertEqual(result["article_detail_cache_deleted"], 1)
            self.assertEqual(result["workflow_cache_deleted"], 1)
            self.assertFalse(yesterday_cache.exists())
            self.assertTrue(today_cache.exists())
            self.assertFalse(yesterday_detail_cache.exists())
            self.assertTrue(today_detail_cache.exists())
            self.assertFalse(workflow_cache.exists())

    def test_video_workspace_redirects_to_agent(self) -> None:
        html = _video_workspace_html()

        self.assertIn("/workflow/video/agent", html)
        self.assertNotIn("/workflow/video/script", html)
        self.assertNotIn("生成视频号脚本", html)

    def test_textbook_example_keeps_original_question_and_solution(self) -> None:
        basis = (
            "化学反应速率通常用单位时间内反应物浓度的减小或生成物浓度的增大来表示（取正值）。"
            "例如，某反应的反应物浓度在 5 min 内由 6 mol/L 变成了 2 mol/L，则以该反应物浓度"
            "的变化表示的该反应在这段时间内的平均反应速率为 0.8 mol/(L·min)。"
        )

        question = _textbook_original_question_from_basis("化学反应速率", basis)
        solution = _textbook_solution_from_basis("化学反应速率", basis, question)

        self.assertIn("教材原文例句", question)
        self.assertIn("5 min", question)
        self.assertIn("6 mol/L", question)
        self.assertNotIn("根据教材中关于", question)
        self.assertTrue(any("Δc = 6 mol/L - 2 mol/L = 4 mol/L" in step for step in solution))
        self.assertTrue(any("0.8 mol/(L·min)" in step for step in solution))

    def test_textbook_question_extracts_real_example_block(self) -> None:
        basis = (
            "如图6.3-3所示，在长为l的细绳下端拴一个质量为 m的小球，捏住绳子的上端，"
            "使小球在水平面内做圆周运动，细绳就沿圆锥面旋转，这样就成了一个圆锥摆。"
            "当绳子跟竖直方向的夹角为θ 时，小球运动的向心加速度an 的大小为多少？"
            "通过计算说明：要增大夹角θ，应该增大小球运动的角速度ω。"
            "分析 由于小球在水平面内做圆周运动，向心加速度的方向始终指向圆心。"
            "【例题】图 6.3-3 解 根据对小球的受力分析，可得小球的向心力 Fn ＝ mgtan θ"
        )

        question = _textbook_original_question_from_basis("圆锥摆", basis)

        self.assertIn("一个质量为 m的小球", question)
        self.assertIn("向心加速度", question)
        self.assertIn("角速度ω", question)
        self.assertIn("【例题】", question)
        self.assertIn("分析", question)
        self.assertIn("向心加速度的方向始终指向圆心", question)
        self.assertNotIn("解 根据", question)

    def test_textbook_question_does_not_use_example_discussion_as_question(self) -> None:
        basis = (
            "上述例题中，M、N 是两块平行金属板，两板间的电场是匀强电场。"
            "如果 M、N 是其他形状，中间的电场不再均匀，例题中的三个问题还有确定答案吗？为什么？"
        )

        question = _textbook_original_question_from_basis("电场", basis)

        self.assertNotIn("上述例题中", question)
        self.assertIn("其他形状", question)
        self.assertIn("确定答案吗", question)
        self.assertNotIn("未从当前教材页提取到完整原始题目", question)

    def test_textbook_question_fallback_always_returns_page_content(self) -> None:
        basis = "思考与讨论\n空气是不导电的。但是如果空气中的电场很强，空气就会被击穿。"

        question = _textbook_original_question_from_basis("电场强度", basis)

        self.assertIn("空气", question)
        self.assertNotIn("未从当前教材页提取到完整原始题目", question)

    def test_textbook_example_keeps_full_question_and_solution_block(self) -> None:
        basis = (
            "【例题】如图所示，一个不带电的验电器靠近带正电的带电体时，"
            "验电器金属箔片张开。请说明金属箔片为什么会张开，并判断验电器近端和远端电荷分布情况。\n"
            "分析与解答 静电感应使导体中的自由电子重新分布。靠近带正电体的一端感应出负电荷，"
            "远端因缺少电子而带正电。金属箔片同种电荷相互排斥，所以会张开。\n"
            "答案：近端带负电，远端带正电，箔片张开的原因是同种电荷相互排斥。\n"
            "练习与应用\n1. 下列说法正确的是……"
        )

        question = _textbook_original_question_from_basis("静电感应", basis)
        solution = _textbook_solution_from_basis("静电感应", basis, question)

        self.assertIn("验电器金属箔片张开", question)
        self.assertIn("判断验电器近端和远端电荷分布情况", question)
        self.assertNotIn("分析与解答", question)
        self.assertNotIn("自由电子重新分布", question)
        self.assertNotIn("答案", question)
        self.assertTrue(any("自由电子重新分布" in step for step in solution))
        self.assertTrue(any("近端带负电" in step for step in solution))
        self.assertFalse(any("练习与应用" in step for step in solution))
        self.assertTrue(_has_complete_textbook_solution_block(basis, solution))

    def test_textbook_question_stops_before_solution_on_same_line(self) -> None:
        basis = (
            "【例题】当带正电的带电体靠近验电器导体棒时，说明近端和远端电荷分布，"
            "并解释金属箔片为什么张开。分析与解答 静电感应使导体中的自由电子向近端移动。"
            "答案：近端带负电，远端带正电。"
        )

        question = _textbook_original_question_from_basis("静电感应", basis)
        solution = _textbook_solution_from_basis("静电感应", basis, question)

        self.assertIn("解释金属箔片为什么张开", question)
        self.assertNotIn("静电感应使导体", question)
        self.assertNotIn("近端带负电", question)
        self.assertTrue(any("自由电子向近端移动" in step for step in solution))
        self.assertTrue(any("近端带负电" in step for step in solution))

    def test_textbook_question_keeps_standalone_analysis_before_solution(self) -> None:
        basis = (
            "【例题 2】真空中有三个带正电的点电荷，它们固定在边长为 50 cm 的等边三角形的三个顶点上，"
            "每个点电荷的电荷量都是 2.0×10-6 C，求它们各自所受的静电力。"
            "分析 根据题意作图（图 9.2-2）。每个点电荷都受到其他两个点电荷的斥力，"
            "因此，只要求出一个点电荷（例如 q3）所受的力即可。"
            "解 根据库仑定律，点电荷 q3 共受到 F1 和 F2 两个力的作用。"
            "答案：每个点电荷所受静电力大小均为 0.25 N。"
        )

        question = _textbook_original_question_from_basis("静电力", basis)
        solution = _textbook_solution_from_basis("静电力", basis, question)

        self.assertIn("【例题 2】", question)
        self.assertIn("求它们各自所受的静电力", question)
        self.assertIn("分析 根据题意作图", question)
        self.assertIn("只要求出一个点电荷", question)
        self.assertNotIn("解 根据库仑定律", question)
        self.assertNotIn("答案", question)
        self.assertTrue(any("根据库仑定律" in step for step in solution))
        self.assertTrue(any("0.25 N" in step for step in solution))

    def test_textbook_example_rejects_concept_paragraph_without_solution(self) -> None:
        basis = (
            "观察：当带电体靠近导体棒的上端时，金属箔片是否张开？"
            "当一个带电体靠近导体时，导体中的自由电荷会重新分布。"
            "这种现象叫作静电感应。"
        )

        solution = _textbook_solution_from_basis("静电感应", basis, "观察金属箔片是否张开？")

        self.assertEqual(solution, [])
        self.assertFalse(_has_complete_textbook_solution_block(basis, solution))

    def test_generic_textbook_example_instruction_uses_searchable_title(self) -> None:
        instruction = "生成一个高中物理课本上的例题做成3d 视频"

        title = _title_from_instruction(instruction)
        query_words = _textbook_query_words(title, "物理", instruction)

        self.assertEqual(title, "高中物理教材例题")
        self.assertEqual(query_words, ["例题"])
        self.assertNotIn("生成一个高中物理课本上的例题做成3d 视频", query_words)

    def test_electromagnetic_textbook_task_requires_matching_topic(self) -> None:
        instruction = "在高中物理教材上找一个电磁场的例题，获取教材内容，生成一个1到2分钟的3D动画视频。"

        title = _title_from_instruction(instruction)
        query_words = _textbook_query_words(title, "物理", instruction)
        required_terms = _textbook_required_topic_terms(title, instruction)

        self.assertEqual(title, "高中物理电磁场教材例题")
        self.assertIn("电磁场", query_words)
        self.assertIn("电场", required_terms)
        self.assertTrue(_textbook_topic_matches("带电粒子在匀强磁场中运动，受到洛伦兹力。", required_terms))
        self.assertFalse(
            _textbook_topic_matches(
                "一个小孩坐在游乐场的旋转木马上，绕中心轴在水平面内做匀速圆周运动。",
                required_terms,
            )
        )

    def test_electromagnetic_textbook_task_stops_when_topic_source_missing(self) -> None:
        instruction = "在高中物理教材上找一个电磁场的例题，获取教材内容，生成一个1到2分钟的3D动画视频。"

        with patch("app.server._video_textbook_example", return_value=None):
            result = workflow_video_agent_run({"instruction": instruction})

        self.assertFalse(result["ok"])
        self.assertIn("避免编造教材来源", result["error"])
        self.assertIn("电磁场", result["error"])

    def test_static_induction_textbook_task_is_physics_and_rejects_garbled_math(self) -> None:
        instruction = "在高中教材上找一个例题，解释清楚静电感应"
        garbled_math = "２ ．（１）在△犃 犅 犆中，已知犪＝２，犮＝槡２３３，犃＝１２０°，求犫和犆；"

        title = _title_from_instruction(instruction)
        subject = _subject_from_instruction(instruction)
        query_words = _textbook_query_words(title, subject, instruction)
        required_terms = _textbook_required_topic_terms(title, instruction)

        self.assertEqual(subject, "物理")
        self.assertEqual(title, "高中物理静电感应教材例题")
        self.assertEqual(_textbook_glob(subject, "高中", instruction), "高中/物理/人教版*/*.pdf")
        self.assertIn("静电感应", query_words)
        self.assertIn("导体", required_terms)
        self.assertTrue(_textbook_topic_matches("导体接近带电体时，自由电子重新分布，这就是静电感应现象。", required_terms))
        self.assertFalse(_textbook_topic_matches(garbled_math, required_terms))
        self.assertFalse(_textbook_hit_text_is_usable(garbled_math))

    def test_textbook_glob_keeps_k12_broad(self) -> None:
        self.assertEqual(_textbook_glob("物理", "K12", "找一个教材例题"), "**/物理/人教版*/*.pdf")

    def test_video_agent_source_html_uses_required_textbook_format(self) -> None:
        html = _video_agent_source_html(
            {
                "repository": "https://github.com/TapXWorld/ChinaTextbook",
                "pdf": "高中/物理/人教版-人民教育出版社/普通高中教科书·物理必修 第二册.pdf",
                "pages": "PDF 第 32-33 页，教材页码第 27-28 页",
                "basis": "第六章“向心力”用空中飞椅说明：飞椅与人做圆周运动时，绳子斜向上方的拉力和重力的合力提供向心力。",
                "subject": "物理",
            }
        )

        self.assertIn("仓库：", html)
        self.assertIn("PDF：", html)
        self.assertIn("页码：", html)
        self.assertIn("依据：", html)
        self.assertIn("PDF 第 32-33 页，教材页码第 27-28 页", html)
        self.assertNotIn("学科", html)
        self.assertLess(html.index("仓库："), html.index("PDF："))
        self.assertLess(html.index("PDF："), html.index("页码："))
        self.assertLess(html.index("页码："), html.index("依据："))

    def test_conical_textbook_task_routes_to_conical_3d_video(self) -> None:
        with patch("app.server.subprocess.run", return_value=Mock(returncode=0)):
            result = workflow_video_agent_run(
                {
                    "instruction": "在高中物理教材上找圆锥摆运动的例题，获取教材内容，生成一个1到2分钟的3D动画视频。"
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "conical_pendulum")
        self.assertEqual(result["page_url"], "/workflow/video/conical-pendulum")
        self.assertEqual(result["video_url"], "/workflow/out/conical-pendulum-narrated.mp4")

    def test_ensure_china_textbook_pdf_checks_out_matching_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "ChinaTextbook"
            tracked_pdf = root / "高中" / "物理" / "人教版-人民教育出版社" / "普通高中教科书·物理必修 第二册.pdf"
            git_dir = root / ".git"
            git_dir.mkdir(parents=True)

            def fake_run(command, **kwargs):
                if command[3:5] == ["ls-files", "-z"]:
                    return Mock(stdout=str(tracked_pdf.relative_to(root)).encode("utf-8") + b"\0")
                if command[3:6] == ["checkout", "HEAD", "--"]:
                    tracked_pdf.parent.mkdir(parents=True, exist_ok=True)
                    tracked_pdf.write_bytes(b"%PDF-1.4\n")
                    return Mock(stdout=b"")
                raise AssertionError(f"unexpected command: {command}")

            with patch("app.server.subprocess.run", side_effect=fake_run) as run:
                ok = _ensure_china_textbook_pdf(
                    root,
                    "高中/物理/人教版*/*.pdf",
                    "高中物理教材例题",
                    "物理",
                    "找一个高中物理人教版必修第二册教材例题",
                )

        self.assertTrue(ok)
        self.assertTrue(any(call.args[0][3:6] == ["checkout", "HEAD", "--"] for call in run.call_args_list))

    def test_workflow_video_render_returns_preview_assets(self) -> None:
        render_result = Mock(
            video_path=Path("/tmp/video_abc/video.mp4"),
            audio_path=Path("/tmp/video_abc/voice.mp3"),
            subtitles_path=Path("/tmp/video_abc/subtitles.srt"),
            frame_paths=[Path("/tmp/video_abc/frame_001.png")],
            warnings=["已跳过 TTS，使用静音音轨。"],
            duration_seconds=60.0,
        )
        with patch("app.server.render_video_draft", return_value=render_result):
            result = workflow_video_render(
                {
                    "script": {
                        "title": "为什么分数除法要乘倒数？一分钟讲透",
                        "cover_text": "分数除法为何乘倒数",
                        "hook": "死记硬背可不行！",
                        "voiceover": "分数除法的本质，是求一个数里面包含多少个这样的分数单位。",
                        "storyboard_markdown": "| 时间 | 画面 | 口播 | 屏幕字幕 |\n|---|---|---|---|\n| 0-3s | 苹果切开 | 先看一个苹果 | 分数除法 |",
                        "cover_prompt": "竖屏封面图，简体中文。",
                        "publish_copy": "",
                        "hashtags": ["#小学数学"],
                        "source_review": [],
                        "risk_flags": [],
                    }
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["video_url"], "/workflow/generated/videos/video_abc/video.mp4")
        self.assertEqual(result["subtitles_url"], "/workflow/generated/videos/video_abc/subtitles.srt")
        self.assertTrue(result["human_review_required"])
        self.assertIn("人工复核", result["review_note"])

    def test_image_prompt_extracts_aigc_prompt_or_image_suggestion(self) -> None:
        prompt = _image_prompt_from_text("### 配图建议\n\n1. AIGC 提示词：公众号封面图，AI 工作流，科技蓝。")
        self.assertIn("临时图片生成 skill", prompt)
        self.assertIn("公众号封面图，AI 工作流，科技蓝", prompt)
        self.assertIn(
            "模型迁移工作流",
            _image_prompt_from_text("<p>配图建议：模型迁移工作流，流程图，重新绘制。</p>"),
        )
        focused_prompt = "微信公众号配图，严格按这条建议生成原创图片：模型迁移工作流，科技蓝。"
        self.assertIn("模型迁移工作流，科技蓝", _image_prompt_from_text(focused_prompt))
        grouped_prompt = _image_prompt_from_text(
            "配图建议：智能体终端核心工作流\n"
            "位置：放在核心工作流解析段落后。\n"
            "画面：意图理解 -> 任务拆解 -> 工具调用 -> 结果整合 -> 交付用户。\n"
            "用途：帮助读者理解 Agent 在设备后台的运行逻辑。"
        )
        self.assertIn("智能体终端核心工作流", grouped_prompt)
        self.assertIn("工具调用", grouped_prompt)
        self.assertIn("语义正确的简体中文", grouped_prompt)
        self.assertIn("翻译成简体中文标签", grouped_prompt)
        self.assertIn("不要英文单词", grouped_prompt)
        self.assertIn("不要繁体字", grouped_prompt)
        self.assertNotIn("简体中文或英文", grouped_prompt)
        self.assertIn("不要伪中文", grouped_prompt)

    def test_image_negative_prompt_blocks_garbled_text(self) -> None:
        negative_prompt = _image_negative_prompt()

        self.assertIn("伪中文", negative_prompt)
        self.assertIn("英文单词", negative_prompt)
        self.assertIn("繁体字", negative_prompt)
        self.assertIn("English words", negative_prompt)
        self.assertIn("gibberish letters", negative_prompt)
        self.assertIn("unreadable text", negative_prompt)

    def test_source_image_urls_extracts_nested_wechat_images(self) -> None:
        urls = _source_image_urls(
            {
                "cover": "https://mmbiz.qpic.cn/cover.jpg",
                "url": "https://mp.weixin.qq.com/s/article",
                "detail": {
                    "image_urls": ["//mmbiz.qpic.cn/a.jpg", "https://mmbiz.qpic.cn/cover.jpg"],
                    "provider_payload": {"thumb_url": "https://mmbiz.qpic.cn/thumb.jpg"},
                },
            }
        )

        self.assertEqual(
            urls,
            [
                "https://mmbiz.qpic.cn/cover.jpg",
                "https://mmbiz.qpic.cn/a.jpg",
                "https://mmbiz.qpic.cn/thumb.jpg",
            ],
        )

    def test_image_urls_from_output_maps_saved_files_to_routes(self) -> None:
        output = "/tmp/generated/wechat_rewrite_1.png\nnot an image\n/tmp/generated/wechat_rewrite_2.webp\n"

        self.assertEqual(
            _image_urls_from_output(output),
            ["/workflow/generated/images/wechat_rewrite_1.png", "/workflow/generated/images/wechat_rewrite_2.webp"],
        )

    def test_reference_image_too_small_falls_back_to_text_to_image(self) -> None:
        error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["imagegen"],
            stderr='[imagegen] error: DashScope API 错误 HTTP 400: {"message":"resolution must be at least 240x240, got 200x200"}',
        )
        success = Mock(stdout="/tmp/generated/wechat_rewrite_1.png\n")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("app.server.GENERATED_IMAGE_DIR", Path(temp_dir)),
            patch("app.server.subprocess.run", side_effect=[error, success]) as run,
        ):
            result = workflow_rewrite_image(
                {
                    "suggestion": "配图建议：模型迁移工作流，流程图，科技蓝，重新绘制。",
                    "reference_image": "https://mmbiz.qpic.cn/small.jpg",
                }
            )

        self.assertTrue(result["ok"])
        self.assertIn("参考图分辨率低于 240x240", result["warning"])
        self.assertEqual(result["images"], ["/workflow/generated/images/wechat_rewrite_1.png"])
        first_command = run.call_args_list[0].args[0]
        second_command = run.call_args_list[1].args[0]
        self.assertIn("--reference-image", first_command)
        self.assertIn("--negative-prompt", first_command)
        self.assertNotIn("--reference-image", second_command)
        self.assertIn("--negative-prompt", second_command)

    def test_reference_image_helpers_detect_and_remove_small_image_args(self) -> None:
        self.assertTrue(_is_reference_image_too_small_error("resolution must be at least 240x240, got 200x200"))
        self.assertEqual(
            _without_reference_image_args(["python", "imagegen.py", "prompt", "--reference-image", "https://example.com/a.jpg"]),
            ["python", "imagegen.py", "prompt"],
        )

    def test_state_from_candidate_snapshot_recovers_stale_selection(self) -> None:
        state = _state_from_candidate_snapshot(
            {
                "content_id": "2247663830_2",
                "title": "旧候选文章",
                "author": "AI 公众号",
                "url": "https://mp.weixin.qq.com/s/demo",
                "reads": "100",
                "likes": 5,
                "comments": "",
                "hotness_score": 66.5,
            }
        )

        self.assertIsNotNone(state)
        assert state is not None
        [content] = state["normalized_contents"]
        [score] = state["hotness_scores"]
        self.assertEqual(content.content_id, "2247663830_2")
        self.assertEqual(content.media_type, MediaType.ARTICLE)
        self.assertEqual(content.metrics.reads, 100)
        self.assertIsNone(content.metrics.comments)
        self.assertEqual(score.hotness_score, 66.5)

    def test_stale_candidate_rewrite_is_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(_allow_stale_candidate_rewrite())

        with patch.dict(os.environ, {"WECHAT_REWRITE_ALLOW_STALE_CANDIDATE": "1"}, clear=True):
            self.assertTrue(_allow_stale_candidate_rewrite())

    def test_rewrite_candidates_cache_only_returns_fast_without_cache(self) -> None:
        _WORKFLOW_CACHE["state"] = None
        _WORKFLOW_CACHE["expires_at"] = None

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("app.server.WORKFLOW_CACHE_FILE", Path(temp_dir) / "missing.json"),
            patch("app.server.build_hotspot_workflow") as build_workflow,
        ):
            result = workflow_rewrite_candidates(refresh=False, cache_only=True)

        self.assertEqual(result["items"], [])
        self.assertFalse(result["cached"])
        build_workflow.assert_not_called()

    def test_rewrite_candidates_refresh_uses_candidate_workflow_without_article_generation(self) -> None:
        _WORKFLOW_CACHE["state"] = None
        _WORKFLOW_CACHE["expires_at"] = None
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="content-1",
                    author="AI 公众号",
                    title="候选刷新文章",
                    text="候选正文",
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=1000, likes=20),
                    url="https://mp.weixin.qq.com/s/candidate",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="content-1",
                    hotness_score=80.0,
                    velocity_score=30.0,
                    engagement_quality_score=20.0,
                    platform_weight=1.0,
                    reason="候选测试",
                )
            ],
            "quality_info": ["wechat_accounts_discovered:1"],
            "review_flags": [],
            "human_review_required": False,
        }

        class FakeCandidateWorkflow:
            def invoke(self, _payload):
                return state

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("app.server.WORKFLOW_CACHE_FILE", Path(temp_dir) / "workflow_cache.json"),
            patch("app.server.build_rewrite_candidate_workflow", return_value=FakeCandidateWorkflow()) as build_candidate,
            patch("app.server.build_hotspot_workflow") as build_full,
        ):
            result = workflow_rewrite_candidates(refresh=True, cache_only=False)

        self.assertEqual(result["items"][0]["title"], "候选刷新文章")
        self.assertIn("wechat_accounts_discovered:1", result["summary"]["quality_info"])
        build_candidate.assert_called_once()
        build_full.assert_not_called()

    def test_rewrite_candidates_cache_only_reads_server_file_cache(self) -> None:
        _WORKFLOW_CACHE["state"] = None
        _WORKFLOW_CACHE["expires_at"] = None
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="content-1",
                    author="AI 公众号",
                    title="服务端缓存文章",
                    text="缓存正文",
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=1000, likes=20),
                    url="https://mp.weixin.qq.com/s/cache",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="content-1",
                    hotness_score=80.0,
                    velocity_score=30.0,
                    engagement_quality_score=20.0,
                    platform_weight=1.0,
                    reason="缓存测试",
                )
            ],
        }

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("app.server.WORKFLOW_CACHE_FILE", Path(temp_dir) / "workflow_cache.json"),
            patch("app.server.build_hotspot_workflow") as build_workflow,
        ):
            _save_workflow_state_cache(state, expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
            _WORKFLOW_CACHE["state"] = None
            _WORKFLOW_CACHE["expires_at"] = None
            result = workflow_rewrite_candidates(refresh=False, cache_only=True)

        self.assertTrue(result["cached"])
        self.assertEqual(result["items"][0]["title"], "服务端缓存文章")
        build_workflow.assert_not_called()

    def test_rewrite_candidates_cache_only_reads_expired_server_file_cache(self) -> None:
        _WORKFLOW_CACHE["state"] = None
        _WORKFLOW_CACHE["expires_at"] = None
        state = {
            "normalized_contents": [
                NormalizedContent(
                    platform=Platform.WECHAT,
                    content_id="content-1",
                    author="AI 公众号",
                    title="过期服务端缓存文章",
                    text="缓存正文",
                    media_type=MediaType.ARTICLE,
                    published_at=None,
                    metrics=EngagementMetrics(reads=1000, likes=20),
                    url="https://mp.weixin.qq.com/s/stale-cache",
                    source_api="wechat-download-api",
                    raw_payload={},
                )
            ],
            "hotness_scores": [
                HotnessScore(
                    content_id="content-1",
                    hotness_score=80.0,
                    velocity_score=30.0,
                    engagement_quality_score=20.0,
                    platform_weight=1.0,
                    reason="缓存测试",
                )
            ],
        }

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("app.server.WORKFLOW_CACHE_FILE", Path(temp_dir) / "workflow_cache.json"),
            patch("app.server.build_hotspot_workflow") as build_workflow,
        ):
            _save_workflow_state_cache(state, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
            _WORKFLOW_CACHE["state"] = None
            _WORKFLOW_CACHE["expires_at"] = None
            result = workflow_rewrite_candidates(refresh=False, cache_only=True)

        self.assertTrue(result["cached"])
        self.assertEqual(result["items"][0]["title"], "过期服务端缓存文章")
        build_workflow.assert_not_called()

    def test_rewrite_candidates_cache_migrates_old_discovery_flag_to_info(self) -> None:
        _WORKFLOW_CACHE["state"] = None
        _WORKFLOW_CACHE["expires_at"] = None
        cache_payload = {
            "version": 1,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "state": {
                "normalized_contents": [],
                "hotness_scores": [],
                "quality_flags": ["wechat_accounts_discovered:5"],
                "human_review_required": True,
            },
        }

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("app.server.WORKFLOW_CACHE_FILE", Path(temp_dir) / "workflow_cache.json") as cache_file,
        ):
            cache_file.write_text(json.dumps(cache_payload), encoding="utf-8")
            result = workflow_rewrite_candidates(refresh=False, cache_only=True)

        self.assertIn("wechat_accounts_discovered:5", result["summary"]["quality_info"])
        self.assertEqual(result["summary"]["quality_flags"], [])
        self.assertEqual(result["summary"]["review_flags"], [])
        self.assertFalse(result["summary"]["human_review_required"])

    def test_workflow_graph_contains_agent_flow(self) -> None:
        html = _workflow_graph_html()

        self.assertIn("LangGraph Agent 流程图", html)
        self.assertIn("task_router", html)
        self.assertIn("wechat_account_discovery", html)
        self.assertIn("wechat_article_writing", html)
        self.assertIn("report_generation", html)
        self.assertIn("compact-flow", html)
        self.assertIn("flow-node", html)
        self.assertIn("flow-io", html)
        self.assertIn("入：", html)
        self.assertIn("出：", html)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(92px, 1fr))", html)
        self.assertIn("紧凑总览", html)
        self.assertIn("人工 Review", html)
        self.assertIn("flow-node review", html)
        self.assertIn("发布前需要", html)
        self.assertIn("human_review_required / review_flags / quality_flags", html)

    def test_should_auto_start_wechat_download_api_only_for_local_service(self) -> None:
        with patch.dict(
            os.environ,
            {
                "WECHAT_PROVIDER": "wechat_download",
                "WECHAT_DOWNLOAD_API_BASE_URL": "http://localhost:5000",
                "WECHAT_DOWNLOAD_API_AUTO_START": "1",
            },
            clear=True,
        ):
            self.assertTrue(_should_auto_start_wechat_download_api())

        with patch.dict(
            os.environ,
            {
                "WECHAT_PROVIDER": "wechat_download",
                "WECHAT_DOWNLOAD_API_BASE_URL": "https://provider.example.com",
                "WECHAT_DOWNLOAD_API_AUTO_START": "1",
            },
            clear=True,
        ):
            self.assertFalse(_should_auto_start_wechat_download_api())

    def test_should_auto_start_ollama_only_for_local_fallback(self) -> None:
        with patch.dict(
            os.environ,
            {
                "QWEN_FALLBACK_BASE_URL": "http://localhost:11434/v1",
                "QWEN_FALLBACK_AUTO_START": "1",
            },
            clear=True,
        ):
            self.assertTrue(_should_auto_start_ollama())

        with patch.dict(
            os.environ,
            {
                "QWEN_FALLBACK_BASE_URL": "https://provider.example.com/v1",
                "QWEN_FALLBACK_AUTO_START": "1",
            },
            clear=True,
        ):
            self.assertFalse(_should_auto_start_ollama())

        with patch.dict(
            os.environ,
            {
                "QWEN_FALLBACK_BASE_URL": "http://localhost:11434/v1",
                "QWEN_FALLBACK_AUTO_START": "0",
            },
            clear=True,
        ):
            self.assertFalse(_should_auto_start_ollama())

        with patch.dict(
            os.environ,
            {
                "WECHAT_PROVIDER": "wechat_download",
                "WECHAT_DOWNLOAD_API_BASE_URL": "http://localhost:5000",
                "WECHAT_DOWNLOAD_API_AUTO_START": "0",
            },
            clear=True,
        ):
            self.assertFalse(_should_auto_start_wechat_download_api())


if __name__ == "__main__":
    unittest.main()
