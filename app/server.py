"""FastAPI server for running the AI hotspot workflow in development."""

from __future__ import annotations

import os
import json
import re
import subprocess
import sys
import threading
import time
from queue import Empty, Queue
from datetime import datetime, timedelta, timezone
from html import escape
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from fastapi import FastAPI, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from app.agents.ai_relevance import AIRelevanceAgent
from app.agents.hotness_scoring import HotnessScoringAgent
from app.agents.video_channel_knowledge import EducationKnowledgeSourceAgent, VideoComplianceCheckAgent
from app.agents.normalization import NormalizationAgent
from app.agents.quality_control import QualityControlAgent
from app.agents.trend_analysis import TrendAnalysisAgent
from app.agents.wechat_account_discovery import DEFAULT_ACCOUNT_KEYWORDS
from app.agents.wechat_article_writing import WechatArticleWritingAgent
from app.config.env import load_dotenv
from app.graphs.ai_hotspot_graph import (
    NODE_ORDER,
    build_hotspot_workflow,
    build_rewrite_candidate_workflow,
    format_hotspot_report,
    format_hotspot_report_html,
)
from app.schemas.hotspot import (
    ApiDimension,
    EngagementMetrics,
    EducationKnowledgePoint,
    GeneratedArticle,
    HotnessScore,
    HotspotState,
    MediaType,
    NormalizedContent,
    Platform,
    SourcePlan,
    TrendCluster,
    VideoChannelScript,
)
from app.tools.video_render import StoryboardClip, render_remotion_timeline_draft, render_video_draft
from app.tools.wechat_download_api import (
    ARTICLE_DETAIL_CACHE_DIR,
    ARTICLE_LIST_CACHE_DIR,
    WechatDownloadApiClient,
    _is_excluded_account_name,
    _looks_like_wechat_fakeid,
)

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]
GENERATED_IMAGE_DIR = ROOT_DIR / "generated" / "images"
GENERATED_VIDEO_DIR = ROOT_DIR / "generated" / "videos"
OUT_DIR = ROOT_DIR / "out"
WORKFLOW_CACHE_FILE = ROOT_DIR / ".cache" / "workflow_rewrite_state.json"

app = FastAPI(title="LangGraph Study Server")
_WORKFLOW_CACHE: dict[str, Any] = {"state": None, "expires_at": None}
_WORKFLOW_CACHE_TTL = timedelta(seconds=int(os.getenv("WORKFLOW_CACHE_TTL_SECONDS", os.getenv("WECHAT_REFRESH_INTERVAL_SECONDS", "14400"))))

AI_KNOWLEDGE_KEYWORDS = (
    "ai",
    "ai agent",
    "agentic ai",
    "ai coding",
    "ai engineer",
    "vibe coding",
    "人工智能",
    "大模型",
    "llm",
    "slm",
    "moe",
    "智能体",
    "多智能体",
    "agentic",
    "multi-agent",
    "工作流",
    "gpt",
    "openai",
    "deepseek",
    "qwen",
    "通义",
    "豆包",
    "kimi",
    "claude",
    "claude code",
    "gemini",
    "grok",
    "llama",
    "mistral",
    "glm",
    "智谱",
    "minimax",
    "阶跃星辰",
    "moonshot",
    "prompt",
    "提示词",
    "上下文工程",
    "context engineering",
    "mcp",
    "model context protocol",
    "function calling",
    "tool calling",
    "tool use",
    "工具调用",
    "rag",
    "agentic rag",
    "graph rag",
    "graphrag",
    "向量",
    "向量数据库",
    "embedding",
    "嵌入",
    "知识图谱",
    "多模态",
    "multimodal",
    "推理模型",
    "reasoning model",
    "思维链",
    "模型",
    "算力",
    "机器学习",
    "深度学习",
    "生成式",
    "aigc",
    "cursor",
    "codex",
    "copilot",
    "harness",
    "langgraph",
    "langflow",
    "langchain",
    "langchain-ai",
    "crewai",
    "autogen",
    "dify",
    "coze",
    "n8n",
    "manus",
    "ollama",
    "vllm",
    "本地大模型",
    "端侧 ai",
    "模型路由",
    "prompt caching",
    "微调",
    "fine-tuning",
    "蒸馏",
    "量化",
)
KNOWLEDGE_SIGNAL_KEYWORDS = (
    "原理",
    "教程",
    "指南",
    "方法",
    "方法论",
    "实践",
    "实战",
    "案例",
    "拆解",
    "复盘",
    "入门",
    "进阶",
    "框架",
    "范式",
    "流程",
    "工具",
    "开源",
    "技术",
    "架构",
    "对比",
    "区别",
    "选型",
    "报告",
    "详解",
    "图解",
    "一文读懂",
    "讲透",
    "核心逻辑",
    "底层",
    "面试题",
    "总结",
)
KNOWLEDGE_STRUCTURE_KEYWORDS = (
    "什么是",
    "为什么",
    "怎么做",
    "如何",
    "一文",
    "讲清楚",
    "讲明白",
    "核心区别",
    "核心逻辑",
    "实际项目",
    "工程实践",
    "选型指南",
    "常见误区",
    "面试总结",
)
KNOWLEDGE_MARKETING_KEYWORDS = (
    "直播",
    "训练营",
    "公开课",
    "报名",
    "扫码",
    "领取",
    "福利",
    "限时",
    "课程",
    "私域",
    "副业",
    "赚钱",
    "变现",
    "招商",
    "加群",
    "进群",
)
CANDIDATE_PLACEHOLDER_TITLES = (
    "无标题",
    "未命名",
    "未命名文章",
    "打开原文",
    "原文",
)
HOLLOW_ARTICLE_KEYWORDS = (
    "重磅",
    "震撼",
    "颠覆",
    "爆火",
    "刷屏",
    "炸裂",
    "风口",
    "红利",
    "机会来了",
    "抓住机会",
    "时代变了",
    "未来已来",
    "彻底变了",
    "全面爆发",
    "普通人必须",
    "一定要看",
    "不可错过",
    "改变命运",
    "降维打击",
)


@app.on_event("startup")
def start_local_services() -> None:
    _auto_start_ollama()
    _auto_start_wechat_download_api()


def _auto_start_ollama() -> None:
    if not _should_auto_start_ollama():
        return

    command = [sys.executable, str(ROOT_DIR / "scripts" / "start_ollama_docker.py")]
    model = os.getenv("QWEN_FALLBACK_MODEL")
    if model:
        command.extend(["--model", model])
    if os.getenv("QWEN_FALLBACK_AUTO_PULL", "1").lower() in {"0", "false", "no"}:
        command.append("--skip-pull")

    try:
        subprocess.run(command, cwd=ROOT_DIR, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Failed to auto-start Ollama fallback: {exc}", flush=True)


def _should_auto_start_ollama() -> bool:
    if os.getenv("QWEN_FALLBACK_AUTO_START", "1").lower() in {"0", "false", "no"}:
        return False

    base_url = os.getenv("QWEN_FALLBACK_BASE_URL", "")
    parsed = urlparse(base_url)
    return (parsed.hostname or "").lower() in {"localhost", "127.0.0.1"} and parsed.port == 11434


def _auto_start_wechat_download_api() -> None:
    if not _should_auto_start_wechat_download_api():
        return

    try:
        subprocess.run(
            [sys.executable, str(ROOT_DIR / "scripts" / "start_wechat_download_api.py")],
            cwd=ROOT_DIR,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Failed to auto-start wechat-download-api: {exc}", flush=True)


def _should_auto_start_wechat_download_api() -> bool:
    if os.getenv("WECHAT_DOWNLOAD_API_AUTO_START", "1").lower() in {"0", "false", "no"}:
        return False
    if os.getenv("WECHAT_PROVIDER", "").lower() != "wechat_download":
        return False

    base_url = os.getenv("WECHAT_DOWNLOAD_API_BASE_URL", "")
    parsed = urlparse(base_url)
    return (parsed.hostname or "").lower() in {"localhost", "127.0.0.1"}


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "langgraph-study",
        "status": "ok",
        "endpoints": {
            "health": "/health",
            "wechat_health": "/external/wechat/health",
            "run_workflow": "GET or POST /workflow/run",
            "workflow_report": "/workflow/report",
            "workflow_report_html": "/workflow/report/html",
            "generated_article": "/workflow/article",
            "generated_article_html": "/workflow/article/html",
            "wechat_rewrite_workspace": "/workflow/rewrite",
            "wechat_knowledge_candidates": "/workflow/rewrite/knowledge-candidates",
            "wechat_article_feed": "/workflow/wechat/articles",
            "video_channel_workspace": "/workflow/video",
            "video_agent_workspace": "/workflow/video/agent",
            "workflow_graph": "/workflow/graph",
            "docs": "/docs",
        },
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "langgraph-study"}


@app.get("/external/wechat/health")
def wechat_health_check() -> dict[str, Any]:
    client = WechatDownloadApiClient.from_env()
    if client is None:
        return {
            "status": "missing_client",
            "detail": "Set WECHAT_PROVIDER=wechat_download and WECHAT_DOWNLOAD_API_BASE_URL.",
        }

    try:
        healthy = client.check_health()
    except RuntimeError as exc:
        return {"status": "unavailable", "detail": str(exc)}

    return {"status": "ok" if healthy else "unhealthy", "base_url": client.base_url}


@app.post("/workflow/run")
def run_workflow(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _run_workflow(payload)


@app.get("/workflow/run")
def run_workflow_from_browser() -> dict[str, Any]:
    return _run_workflow()


@app.get("/workflow/report")
def workflow_report() -> Response:
    result = build_hotspot_workflow(prefer_langgraph=False).invoke({})
    return Response(format_hotspot_report(result), media_type="text/plain; charset=utf-8")


@app.get("/workflow/report/html")
def workflow_report_html() -> Response:
    result = build_hotspot_workflow(prefer_langgraph=False).invoke({})
    return Response(format_hotspot_report_html(result), media_type="text/html; charset=utf-8")


@app.get("/workflow/article")
def workflow_article() -> Response:
    result = build_hotspot_workflow(prefer_langgraph=False).invoke({})
    article = result.get("generated_article")
    if article is None:
        return Response("暂无生成文章。", media_type="text/plain; charset=utf-8")
    if result.get("human_review_required"):
        return Response(_review_gate_text(result), status_code=409, media_type="text/plain; charset=utf-8")
    return Response(article.body_markdown, media_type="text/plain; charset=utf-8")


@app.get("/workflow/article/html")
def workflow_article_html() -> Response:
    result = build_hotspot_workflow(prefer_langgraph=False).invoke({})
    article = result.get("generated_article")
    if article is None:
        return Response("<p>暂无生成文章。</p>", media_type="text/html; charset=utf-8")
    if result.get("human_review_required"):
        return Response(_review_gate_html(result), status_code=409, media_type="text/html; charset=utf-8")
    return Response(_article_html(article.title, article.subtitle, article.body_markdown), media_type="text/html; charset=utf-8")


@app.get("/workflow/rewrite")
def workflow_rewrite_workspace() -> Response:
    return Response(_rewrite_workspace_html(), media_type="text/html; charset=utf-8")


@app.get("/workflow/video")
def workflow_video_workspace() -> RedirectResponse:
    return RedirectResponse("/workflow/video/agent", status_code=307)


@app.get("/workflow/video/agent")
def workflow_video_agent_workspace() -> Response:
    return Response(_video_agent_workspace_html(), media_type="text/html; charset=utf-8")


@app.get("/workflow/video/agent/run/stream")
def workflow_video_agent_run_stream_page() -> Response:
    return Response(_video_agent_stream_page_html(), media_type="text/html; charset=utf-8")


@app.post("/workflow/video/agent/run")
def workflow_video_agent_run(payload: dict[str, Any]) -> dict[str, Any]:
    instruction = str(payload.get("instruction") or payload.get("task") or "").strip()
    if not instruction:
        return {"ok": False, "error": "请输入你希望 Agent 完成的视频任务。"}
    if _is_reference_only_video_instruction(instruction):
        return {
            "ok": False,
            "error": (
                "当前输入只有“参考圆锥摆展示页模式”的要求，没有实际视频主题。"
                "请补充要讲的知识点或例题，例如：在高中物理教材上找圆锥摆运动的例题，获取教材内容，生成一个1到2分钟的3D动画视频。"
            ),
        }
    if bool(payload.get("use_conical_demo")) or _is_real_conical_pendulum_request(instruction):
        return _run_conical_pendulum_agent_task(instruction)
    return _run_general_video_agent_task(instruction, payload)


@app.post("/workflow/video/agent/run/stream")
def workflow_video_agent_run_stream(payload: dict[str, Any]) -> StreamingResponse:
    return StreamingResponse(
        _stream_video_agent_run(payload),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/workflow/video/conical-pendulum")
def workflow_conical_pendulum_page() -> Response:
    return Response(_conical_pendulum_page_html(), media_type="text/html; charset=utf-8")


@app.get("/workflow/video/agent/result/{job}")
def workflow_video_agent_result_page(job: str) -> Response:
    safe_job = Path(job).name
    data_path = OUT_DIR / "video-agent-results" / f"{safe_job}.json"
    if not data_path.exists():
        return Response("<p>视频 Agent 结果不存在或已被清理。</p>", status_code=404, media_type="text/html; charset=utf-8")
    try:
        result = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Response("<p>视频 Agent 结果读取失败。</p>", status_code=500, media_type="text/html; charset=utf-8")
    return Response(_video_agent_result_page_html(result), media_type="text/html; charset=utf-8")


@app.post("/workflow/video/render")
def workflow_video_render(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        script = _video_script_from_payload(payload.get("script") or payload)
        result = render_video_draft(script, GENERATED_VIDEO_DIR)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "video_url": _generated_video_url(result.video_path),
        "audio_url": _generated_video_url(result.audio_path),
        "subtitles_url": _generated_video_url(result.subtitles_path),
        "frame_urls": [_generated_video_url(path) for path in result.frame_paths],
        "warnings": [],
        "duration_seconds": result.duration_seconds,
        "human_review_required": True,
        "review_note": "视频草稿仅用于预览，发布前必须人工复核教材来源、概念定义、字幕文字和图片版权。",
    }


@app.get("/workflow/graph")
def workflow_graph() -> Response:
    return Response(_workflow_graph_html(), media_type="text/html; charset=utf-8")


@app.get("/workflow/rewrite/candidates")
def workflow_rewrite_candidates(refresh: bool = False, cache_only: bool = False) -> dict[str, Any]:
    try:
        state = _cached_workflow_state(refresh=refresh, cache_only=cache_only)
    except Exception as exc:
        return {
            "items": [],
            "summary": {"error": _clean_subprocess_error(exc)},
            "cached": False,
            "error": _clean_subprocess_error(exc),
        }
    if state is None:
        return {"items": [], "summary": {}, "cached": False, "cache": _workflow_cache_status()}
    rows = _rewrite_candidates(state)
    return {"items": rows, "summary": _summarize_state(state), "cached": not refresh, "cache": _workflow_cache_status()}


@app.get("/workflow/rewrite/hot-candidates")
def workflow_rewrite_hot_candidates(refresh: bool = False, cache_only: bool = False, limit: int = 20) -> dict[str, Any]:
    try:
        state = _cached_workflow_state(refresh=refresh, cache_only=cache_only)
    except Exception as exc:
        return {
            "items": [],
            "summary": {"error": _clean_subprocess_error(exc)},
            "cached": False,
            "source": "wechat-10w-hot",
            "error": _clean_subprocess_error(exc),
        }
    if state is None:
        return {"items": [], "summary": {}, "cached": False, "source": "wechat-10w-hot", "cache": _workflow_cache_status()}
    rows = _wechat_10w_hot_candidates(state, limit=limit)
    summary = _summarize_state(state)
    summary["hot_rank_source"] = "wechat-10w-hot"
    summary["hot_rank_note"] = (
        "优先按真实阅读量排序；当前数据源未返回阅读量时，自动退回按 AI 热度和本地热度排序。"
    )
    return {"items": rows, "summary": summary, "cached": not refresh, "source": "wechat-10w-hot", "cache": _workflow_cache_status()}


@app.get("/workflow/rewrite/knowledge-candidates")
def workflow_rewrite_knowledge_candidates(refresh: bool = False, cache_only: bool = False, limit: int = 20) -> dict[str, Any]:
    try:
        state = _cached_workflow_state(refresh=refresh, cache_only=cache_only)
    except Exception as exc:
        return {
            "items": [],
            "summary": {"error": _clean_subprocess_error(exc)},
            "cached": False,
            "source": "knowledge-first",
            "error": _clean_subprocess_error(exc),
            "cache": _workflow_cache_status(),
        }
    if state is None:
        return {"items": [], "summary": {}, "cached": False, "source": "knowledge-first", "cache": _workflow_cache_status()}
    rows = _knowledge_first_candidates(state, limit=limit)
    summary = _summarize_state(state)
    summary["knowledge_rank_source"] = "knowledge-first"
    summary["knowledge_rank_note"] = "优先选择教程、原理、对比、面试题、案例复盘等知识解释型公众号文章，并降低营销转化内容权重。"
    return {"items": rows, "summary": summary, "cached": not refresh, "source": "knowledge-first", "cache": _workflow_cache_status()}


@app.get("/workflow/wechat/articles")
def workflow_wechat_articles(refresh: bool = False, cache_only: bool = False, limit: int = 50) -> dict[str, Any]:
    try:
        state = _cached_workflow_state(refresh=refresh, cache_only=cache_only)
    except Exception as exc:
        return {
            "items": [],
            "summary": {"error": _clean_subprocess_error(exc)},
            "cached": False,
            "source": "wechat-subscription-feed",
            "error": _clean_subprocess_error(exc),
            "cache": _workflow_cache_status(),
        }
    if state is None:
        return {
            "items": [],
            "summary": {},
            "cached": False,
            "source": "wechat-subscription-feed",
            "cache": _workflow_cache_status(),
        }
    rows = _wechat_article_feed(state, limit=limit)
    return {
        "items": rows,
        "summary": _summarize_state(state),
        "cached": not refresh,
        "source": "wechat-subscription-feed",
        "cache": _workflow_cache_status(),
    }


@app.get("/workflow/wechat/articles/{content_id}")
def workflow_wechat_article_detail(content_id: str, fetch_detail: bool = True) -> dict[str, Any]:
    state = _cached_workflow_state(refresh=False, cache_only=True)
    if state is None:
        state = _cached_workflow_state(refresh=False)
    detail = _wechat_article_detail_payload(state, content_id, fetch_detail=fetch_detail) if state is not None else None
    if detail is None:
        return {"ok": False, "error": f"content not found: {content_id}", "cache": _workflow_cache_status()}
    return {"ok": True, **detail, "cache": _workflow_cache_status()}


@app.post("/workflow/rewrite/subscriptions/refresh/stream")
def workflow_rewrite_subscription_refresh_stream() -> StreamingResponse:
    return StreamingResponse(
        _stream_rewrite_subscription_refresh(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _stream_rewrite_subscription_refresh():
    def emit(event: str, **data: Any) -> str:
        payload = {"event": event, **data}
        message = payload.get("message")
        if message:
            print(f"[rewrite-subscription-refresh] {message}", flush=True)
        return json.dumps(payload, ensure_ascii=False) + "\n"

    started_at = time.monotonic()
    yield emit("progress", message="开始手动更新订阅号文章...")

    cleanup_started_at = time.monotonic()
    cleanup = _delete_previous_wechat_download_cache()
    yield emit(
        "progress",
        message=(
            f"已清理前一天及更早的下载缓存，用时 {_format_elapsed(time.monotonic() - cleanup_started_at)}："
            f"删除文章列表缓存 {cleanup['article_list_cache_deleted']} 个，"
            f"删除文章详情缓存 {cleanup['article_detail_cache_deleted']} 个，"
            f"删除候选缓存 {cleanup['workflow_cache_deleted']} 个。"
        ),
        cleanup=cleanup,
    )

    result_queue: Queue[tuple[str, Any]] = Queue()

    def refresh() -> None:
        try:
            result_queue.put(("ok", _cached_workflow_state(refresh=True)))
        except Exception as exc:  # pragma: no cover - exercised through stream output.
            result_queue.put(("error", exc))

    refresh_started_at = time.monotonic()
    thread = threading.Thread(target=refresh, name="rewrite-subscription-refresh", daemon=True)
    thread.start()
    yield emit("progress", message="正在拉取订阅号文章并重建候选列表...", phase="fetching", elapsed_seconds=0)
    while True:
        try:
            status, value = result_queue.get(timeout=1.0)
            break
        except Empty:
            elapsed_seconds = time.monotonic() - refresh_started_at
            yield emit(
                "progress",
                message=f"订阅号文章仍在拉取中，已耗时 {_format_elapsed(elapsed_seconds)}。",
                phase="fetching",
                elapsed_seconds=round(elapsed_seconds, 3),
            )

    refresh_elapsed = time.monotonic() - refresh_started_at
    if status == "error":
        yield emit("error", message=f"订阅号文章拉取失败，用时 {_format_elapsed(refresh_elapsed)}：{_clean_subprocess_error(value)}")
        return

    state = value
    rows = _rewrite_candidates(state) if state is not None else []
    total_elapsed = time.monotonic() - started_at
    yield emit(
        "done",
        message=f"订阅号文章更新完成：候选 {len(rows)} 篇，拉取用时 {_format_elapsed(refresh_elapsed)}，总耗时 {_format_elapsed(total_elapsed)}。",
        result={
            "items": rows,
            "summary": _summarize_state(state or {}),
            "cached": False,
            "elapsed_seconds": round(total_elapsed, 3),
            "fetch_elapsed_seconds": round(refresh_elapsed, 3),
            "cleanup": cleanup,
        },
    )


def _stream_rewrite_selected(payload: dict[str, Any]):
    def emit(event: str, **data: Any) -> str:
        payload = {"event": event, **data}
        message = payload.get("message")
        if message:
            print(f"[rewrite-selected] {message}", flush=True)
        return json.dumps(payload, ensure_ascii=False) + "\n"

    started_at = time.monotonic()
    content_id = str(payload.get("content_id") or "")
    if not content_id:
        yield emit("error", message="missing content_id")
        return

    yield emit("progress", message="正在读取候选文章缓存...")
    state = _cached_workflow_state(refresh=False)
    states: list[tuple[HotspotState | None, str]] = [(state, "服务端候选缓存")]
    if _allow_stale_candidate_rewrite():
        states.append((_state_from_candidate_snapshot(payload.get("candidate")), "页面候选快照"))

    for selected_state, state_label in states:
        if selected_state is None:
            continue
        contents = {content.content_id: content for content in selected_state.get("normalized_contents", [])}
        content = contents.get(content_id)
        if content is None:
            continue

        title = content.title or "未命名文章"
        initial_text_length = len(content.text or "")
        yield emit(
            "progress",
            message=f"已命中{state_label}：准备改写《{title}》，当前候选摘要 {initial_text_length} 字，接下来会补拉完整正文。",
            article_title=title,
            source_text_length=initial_text_length,
        )

        try:
            detail_started_at = time.monotonic()
            content, detail_status = yield from _run_with_stream_progress(
                lambda: _enrich_content_detail_with_status(content),
                emit=emit,
                waiting_message=lambda elapsed: f"正在校验或补拉《{title}》全文，已耗时 {elapsed}。",
                progress_phase="rewrite-detail",
            )
            detail_elapsed = time.monotonic() - detail_started_at
            source_text_length = len(content.text or "")
            source_images = _source_image_urls(content.raw_payload)
            if source_text_length < 200:
                yield emit(
                    "error",
                    message=(
                        f"全文未就绪：《{title}》当前正文只有 {source_text_length} 字，"
                        f"补拉状态：{detail_status.get('message', '未知原因')}。"
                        "请稍后重试，或检查 wechat-download-api 登录状态和文章详情接口。"
                    ),
                    article_title=title,
                    source_text_length=source_text_length,
                    detail_status=detail_status,
                    elapsed_seconds=round(detail_elapsed, 3),
                )
                return
            yield emit(
                "progress",
                message=(
                    f"全文准备完成：《{content.title}》，正文 {source_text_length} 字，"
                    f"原文图片 {len(source_images)} 张，用时 {_format_elapsed(detail_elapsed)}。"
                ),
                article_title=content.title,
                source_text_length=source_text_length,
                source_image_count=len(source_images),
                elapsed_seconds=round(detail_elapsed, 3),
            )

            ocr_started_at = time.monotonic()
            if source_images:
                yield emit(
                    "progress",
                    message=f"正在用 pdf-image-text-extractor 图文解析能力提取《{content.title}》图片文字...",
                    phase="image-ocr",
                    elapsed_seconds=0,
                )
            content, image_text_evidence = yield from _run_with_stream_progress(
                lambda: _augment_content_with_image_text(content),
                emit=emit,
                waiting_message=lambda elapsed: f"正在提取《{content.title}》图片文字，已耗时 {elapsed}。",
                progress_phase="image-ocr" if source_images else None,
            )
            ocr_elapsed = time.monotonic() - ocr_started_at
            source_text_length = len(content.text or "")
            if source_images:
                yield emit(
                    "progress",
                    message=f"图片文字处理完成：{image_text_evidence.get('message')} 用时 {_format_elapsed(ocr_elapsed)}。",
                    article_title=content.title,
                    source_text_length=source_text_length,
                    image_text_evidence=image_text_evidence,
                    elapsed_seconds=round(ocr_elapsed, 3),
                )

            trend = TrendCluster(
                trend_id=f"selected-{content.content_id}",
                name=_selected_topic(content.title),
                summary=f"用户选择的公众号热度文章：{content.title}",
                content_ids=[content.content_id],
                platforms=[content.platform],
                hotness_score=_score_for_content(selected_state, content.content_id),
                lifecycle="rising",
                evidence=[content.content_id],
            )
            rewrite_state: HotspotState = {
                "normalized_contents": [content],
                "hotness_scores": [
                    score for score in selected_state.get("hotness_scores", []) if score.content_id == content_id
                ],
                "trends": [trend],
                "product_insights": [],
            }

            rewrite_started_at = time.monotonic()
            rewrite_stage_events: Queue[dict[str, Any]] = Queue()
            rewrite_state["progress_callback"] = rewrite_stage_events.put
            yield emit("progress", message=f"正在调用 wechat-rewrite Agent 改写《{content.title}》...")
            rewrite_update = yield from _run_with_stream_progress(
                lambda: WechatArticleWritingAgent().invoke(rewrite_state),
                emit=emit,
                waiting_message=lambda elapsed: f"正在改写《{content.title}》，已耗时 {elapsed}。",
                progress_phase="rewriting",
                progress_events=rewrite_stage_events,
            )
            rewrite_elapsed = time.monotonic() - rewrite_started_at
            article = rewrite_update.get("generated_article")
            if article is None:
                yield emit("error", message="改写 Agent 未返回文章。")
                return
            yield emit("progress", message=f"改写正文生成完成，用时 {_format_elapsed(rewrite_elapsed)}，正在做质量检查...")

            review_started_at = time.monotonic()
            review_state: HotspotState = {**rewrite_state, **rewrite_update}
            review_update = QualityControlAgent().invoke(review_state)
            review_elapsed = time.monotonic() - review_started_at
            total_elapsed = time.monotonic() - started_at
            rewrite_text_length = _plain_text_length(article.body_markdown)
            source = {
                "content_id": content.content_id,
                "title": content.title,
                "author": content.author,
                "url": content.url,
                "source_text_length": source_text_length,
                "rewrite_text_length": rewrite_text_length,
                "image_text_evidence": image_text_evidence,
                "article_compliance": rewrite_update.get("article_compliance"),
                "quality_flags": review_update.get("quality_flags", []),
                "quality_info": review_update.get("quality_info", []),
                "review_flags": review_update.get("review_flags", []),
                "human_review_required": bool(review_update.get("human_review_required")),
                "stage_timings": {
                    "full_text_seconds": round(detail_elapsed, 3),
                    "image_ocr_seconds": round(ocr_elapsed, 3),
                    "rewrite_seconds": round(rewrite_elapsed, 3),
                    "quality_check_seconds": round(review_elapsed, 3),
                    "total_seconds": round(total_elapsed, 3),
                },
            }
            result = {
                "ok": True,
                "content_id": content_id,
                "article": jsonable_encoder(article),
                "article_html": _article_html(article.title, article.subtitle, article.body_markdown),
                "source_images": source_images,
                "source": source,
                "human_review_required": bool(source.get("human_review_required")),
                "review_flags": source.get("review_flags", []),
                "quality_info": source.get("quality_info", []),
            }
            yield emit(
                "done",
                message=(
                    f"改写完成：《{article.title}》，原文 {source_text_length} 字，"
                    f"改写稿 {rewrite_text_length} 字，"
                    f"全文 {_format_elapsed(detail_elapsed)}，改写 {_format_elapsed(rewrite_elapsed)}，"
                    f"质检 {_format_elapsed(review_elapsed)}，总耗时 {_format_elapsed(total_elapsed)}。"
                ),
                result=result,
            )
            return
        except Exception as exc:
            yield emit("error", message=f"改写失败：{_clean_subprocess_error(exc)}")
            return

    yield emit("error", message=f"content not found: {content_id}. 请点击“重新拉取”刷新候选列表后再选择。")


def _run_with_stream_progress(
    operation: Callable[[], Any],
    *,
    emit: Callable[..., str],
    waiting_message: Callable[[str], str],
    progress_phase: str | None = None,
    progress_events: Queue[dict[str, Any]] | None = None,
) -> Any:
    result_queue: Queue[tuple[str, Any]] = Queue()

    def run() -> None:
        try:
            result_queue.put(("ok", operation()))
        except Exception as exc:
            result_queue.put(("error", exc))

    started_at = time.monotonic()
    threading.Thread(target=run, daemon=True).start()
    while True:
        if progress_events is not None:
            while True:
                try:
                    event = progress_events.get_nowait()
                except Empty:
                    break
                elapsed_seconds = time.monotonic() - started_at
                payload = {
                    "message": str(event.get("message") or waiting_message(_format_elapsed(elapsed_seconds))),
                    "elapsed_seconds": round(elapsed_seconds, 3),
                }
                if event.get("phase"):
                    payload["phase"] = str(event["phase"])
                elif progress_phase:
                    payload["phase"] = progress_phase
                yield emit("progress", **payload)
        try:
            status, value = result_queue.get(timeout=1.0)
            break
        except Empty:
            elapsed_seconds = time.monotonic() - started_at
            payload: dict[str, Any] = {
                "message": waiting_message(_format_elapsed(elapsed_seconds)),
                "elapsed_seconds": round(elapsed_seconds, 3),
            }
            if progress_phase:
                payload["phase"] = progress_phase
            yield emit("progress", **payload)
    if progress_events is not None:
        while True:
            try:
                event = progress_events.get_nowait()
            except Empty:
                break
            elapsed_seconds = time.monotonic() - started_at
            payload = {
                "message": str(event.get("message") or waiting_message(_format_elapsed(elapsed_seconds))),
                "elapsed_seconds": round(elapsed_seconds, 3),
            }
            if event.get("phase"):
                payload["phase"] = str(event["phase"])
            elif progress_phase:
                payload["phase"] = progress_phase
            yield emit("progress", **payload)
    if status == "error":
        raise value
    return value


def _plain_text_length(text: str) -> int:
    return len(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", text or "")))


@app.post("/workflow/rewrite/selected")
def workflow_rewrite_selected(payload: dict[str, Any]) -> dict[str, Any]:
    content_id = str(payload.get("content_id") or "")
    if not content_id:
        return {"ok": False, "error": "missing content_id"}

    state = _cached_workflow_state(refresh=False)
    article, source = _rewrite_selected_article(state, content_id)
    if article is None and _allow_stale_candidate_rewrite():
        fallback_state = _state_from_candidate_snapshot(payload.get("candidate"))
        if fallback_state is not None:
            article, source = _rewrite_selected_article(fallback_state, content_id)
    if article is None:
        return {"ok": False, "error": f"content not found: {content_id}. 请点击“重新拉取”刷新候选列表后再选择。"}
    return {
        "ok": True,
        "content_id": content_id,
        "article": jsonable_encoder(article),
        "article_html": _article_html(article.title, article.subtitle, article.body_markdown),
        "source_images": _source_image_urls_for_selection(state, content_id),
        "source": source,
        "human_review_required": bool(source.get("human_review_required")),
        "review_flags": source.get("review_flags", []),
        "quality_info": source.get("quality_info", []),
    }


@app.post("/workflow/rewrite/selected/stream")
def workflow_rewrite_selected_stream(payload: dict[str, Any]) -> StreamingResponse:
    return StreamingResponse(
        _stream_rewrite_selected(payload),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/workflow/rewrite/image")
def workflow_rewrite_image(payload: dict[str, Any]) -> dict[str, Any]:
    prompt_source = str(
        payload.get("suggestion")
        or payload.get("prompt")
        or payload.get("article_markdown")
        or payload.get("article_html")
        or ""
    )
    prompt = _image_prompt_from_text(prompt_source)
    if not prompt:
        return {"ok": False, "error": "missing image prompt"}

    size = str(payload.get("size") or "1024x1024")
    count = int(payload.get("count") or 1)
    GENERATED_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(ROOT_DIR / "skills" / "image-caption-prompt" / "imagegen.py"),
        prompt,
        "--size",
        size,
        "--count",
        str(max(1, min(count, 2))),
        "--output-dir",
        str(GENERATED_IMAGE_DIR),
        "--prefix",
        "wechat_rewrite",
        "--negative-prompt",
        _image_negative_prompt(),
    ]
    reference_image = str(payload.get("reference_image") or payload.get("image_url") or "").strip()
    if reference_image:
        command.extend(["--reference-image", reference_image])
    try:
        result = subprocess.run(command, cwd=ROOT_DIR, check=True, text=True, capture_output=True, timeout=240)
        warning = ""
    except subprocess.CalledProcessError as exc:
        if reference_image and _is_reference_image_too_small_error(_clean_subprocess_error(exc)):
            fallback_command = _without_reference_image_args(command)
            try:
                result = subprocess.run(fallback_command, cwd=ROOT_DIR, check=True, text=True, capture_output=True, timeout=240)
                warning = "参考图分辨率低于 240x240，已自动改用文字配图建议重新生成。"
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as fallback_exc:
                return {
                    "ok": False,
                    "error": f"image generation failed after skipping small reference image: {_clean_subprocess_error(fallback_exc)}",
                    "prompt": prompt,
                }
        else:
            return {"ok": False, "error": f"image generation failed: {_clean_subprocess_error(exc)}", "prompt": prompt}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"image generation failed: {_clean_subprocess_error(exc)}", "prompt": prompt}

    image_urls = _image_urls_from_output(result.stdout)
    return {"ok": bool(image_urls), "prompt": prompt, "images": image_urls, "stdout": result.stdout[-1000:], "warning": warning}


@app.get("/workflow/generated/images/{filename}")
def workflow_generated_image(filename: str):
    safe_name = Path(filename).name
    path = GENERATED_IMAGE_DIR / safe_name
    if not path.exists() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return Response("image not found", status_code=404, media_type="text/plain; charset=utf-8")
    return FileResponse(path)


@app.get("/workflow/generated/videos/{job}/{filename}")
def workflow_generated_video(job: str, filename: str):
    safe_job = Path(job).name
    safe_name = Path(filename).name
    path = GENERATED_VIDEO_DIR / safe_job / safe_name
    if not path.exists() or path.suffix.lower() not in {".mp4", ".mp3", ".m4a", ".srt", ".png"}:
        return Response("video asset not found", status_code=404, media_type="text/plain; charset=utf-8")
    return FileResponse(path)


@app.get("/workflow/out/{filename}")
def workflow_out_asset(filename: str):
    safe_name = Path(filename).name
    path = OUT_DIR / safe_name
    if not path.exists() or path.suffix.lower() not in {".mp4", ".mp3", ".m4a", ".srt", ".png", ".json"}:
        return Response("asset not found", status_code=404, media_type="text/plain; charset=utf-8")
    return FileResponse(path)


def _run_workflow(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    workflow = build_hotspot_workflow(prefer_langgraph=False)
    initial_state: HotspotState = dict(payload or {})
    result = workflow.invoke(initial_state)
    report_markdown = format_hotspot_report(result)
    return {
        "report_markdown": report_markdown,
        "generated_article": jsonable_encoder(result.get("generated_article")),
        "summary": _summarize_state(result),
        "state": jsonable_encoder(result),
    }


def _conical_pendulum_page_html() -> str:
    example = _conical_pendulum_example_payload()
    source = example["source"]
    video_info = example.get("video") if isinstance(example.get("video"), dict) else {}
    solution_items = "".join(f"<li>{escape(item)}</li>" for item in example["solution"])
    render_engine = str(video_info.get("render_engine") or "unknown")
    remotion_skill = str(video_info.get("remotion_skill") or "skills/video-remotion/SKILL.md")
    warnings = video_info.get("warnings") if isinstance(video_info.get("warnings"), list) else []
    warning_items = "".join(f"<li>{escape(str(item))}</li>" for item in warnings) or "<li>暂无渲染警告。</li>"
    video_url = "/workflow/out/conical-pendulum-narrated.mp4"
    silent_url = "/workflow/out/conical-pendulum.mp4"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>圆锥摆运动例题</title>
  <style>
    body {{
      margin: 0;
      background: #f8fafc;
      color: #0f172a;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 34px;
    }}
    .subtitle {{
      margin: 0 0 24px;
      color: #475569;
      line-height: 1.7;
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(280px, 420px) 1fr;
      gap: 22px;
      align-items: start;
    }}
    section, .video-card {{
      background: white;
      border: 1px solid #e2e8f0;
      border-radius: 22px;
      box-shadow: 0 18px 42px rgba(15, 23, 42, 0.06);
      padding: 22px;
    }}
    video {{
      width: 100%;
      border-radius: 18px;
      background: #020617;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 22px;
    }}
    p, li {{
      font-size: 16px;
      line-height: 1.8;
    }}
    .source-list {{
      display: grid;
      gap: 8px;
      color: #334155;
      line-height: 1.7;
    }}
    .tag {{
      display: inline-flex;
      border-radius: 999px;
      background: #dbeafe;
      color: #1d4ed8;
      padding: 5px 11px;
      font-weight: 700;
      font-size: 13px;
    }}
    .stack {{
      display: grid;
      gap: 18px;
    }}
    code {{
      background: #f1f5f9;
      padding: 2px 5px;
      border-radius: 6px;
    }}
    @media (max-width: 860px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <span class="tag">教材来源 + 3D 动画讲解</span>
    <h1>圆锥摆运动例题</h1>
    <p class="subtitle">基于人教版高中物理必修第二册“向心力”中的空中飞椅情境，整理成圆锥摆模型例题，并生成带解说音的视频草稿。</p>
    <div class="grid">
      <div class="video-card">
        <video controls src="{video_url}"></video>
        <p>带解说音视频：<code>out/conical-pendulum-narrated.mp4</code></p>
        <p>无声动画草稿：<a href="{silent_url}">out/conical-pendulum.mp4</a></p>
      </div>
      <div class="stack">
        <section>
          <h2>例题来源</h2>
          <div class="source-list">
            <div><strong>仓库：</strong><a href="{escape(source["repository"])}">{escape(source["repository"])}</a></div>
            <div><strong>PDF：</strong>{escape(source["pdf"])}</div>
            <div><strong>页码：</strong>{escape(source["pages"])}</div>
            <div><strong>依据：</strong>{escape(source["basis"])}</div>
          </div>
        </section>
        <section>
          <h2>完整题目</h2>
          <p>{escape(example["question"])}</p>
        </section>
        <section>
          <h2>解答过程</h2>
          <ol>{solution_items}</ol>
        </section>
        <section>
          <h2>视频渲染</h2>
          <div class="source-list">
            <div><strong>渲染引擎：</strong>{escape(render_engine)}</div>
            <div><strong>使用 skill：</strong>{escape(remotion_skill)}</div>
            <div><strong>Composition：</strong>ConicalPendulumVideo</div>
          </div>
          <ol>{warning_items}</ol>
        </section>
      </div>
    </div>
  </main>
</body>
</html>"""


def _conical_pendulum_example_payload() -> dict[str, Any]:
    data_path = OUT_DIR / "conical-pendulum-example.json"
    if data_path.exists():
        try:
            return json.loads(data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "source": {
            "repository": "https://github.com/TapXWorld/ChinaTextbook",
            "pdf": "高中/物理/人教版-人民教育出版社/普通高中教科书·物理必修 第二册.pdf",
            "pages": "PDF 第 32-33 页，教材页码第 27-28 页",
            "basis": "第六章“向心力”用空中飞椅说明绳子斜向上方的拉力和重力的合力提供向心力。",
        },
        "question": "一小球用长为 L 的轻绳悬挂，绕竖直轴做匀速圆周运动，轻绳与竖直方向夹角为 θ。求绳中拉力、半径和线速度。",
        "solution": [
            "竖直方向：T cosθ = mg，所以 T = mg / cosθ。",
            "圆周半径：r = L sinθ。",
            "水平方向：T sinθ = m v² / r。",
            "代入并化简：v = √(g L sinθ tanθ)。",
        ],
    }


def _video_agent_result_page_html(result: dict[str, Any]) -> str:
    title = str(result.get("title") or result.get("question") or result.get("instruction") or "视频 Agent 结果")[:80]
    video_url = str(result.get("video_url") or "")
    source_html = _video_agent_source_html(result.get("source"))
    question = str(result.get("question") or result.get("instruction") or "")
    solution = result.get("solution") if isinstance(result.get("solution"), list) else []
    solution_html = "".join(f"<li>{escape(str(item))}</li>" for item in solution)
    video_tag = f'<video controls src="{escape(video_url)}"></video>' if video_url else "<p>暂无视频文件。</p>"
    solution_section = f"<section><h2>解答过程</h2><ol>{solution_html}</ol></section>" if solution_html else ""
    links = []
    if video_url:
        links.append(f'<a href="{escape(video_url)}" target="_blank">打开 MP4</a>')
    if result.get("audio_url"):
        links.append(f'<a href="{escape(str(result["audio_url"]))}" target="_blank">打开音频</a>')
    if result.get("subtitles_url"):
        links.append(f'<a href="{escape(str(result["subtitles_url"]))}" target="_blank">下载字幕</a>')
    link_html = " · ".join(links)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    body {{
      margin: 0;
      background: #f8fafc;
      color: #0f172a;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 34px;
    }}
    .subtitle {{
      margin: 0 0 24px;
      color: #475569;
      line-height: 1.7;
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(280px, 420px) 1fr;
      gap: 22px;
      align-items: start;
    }}
    section, .video-card {{
      background: white;
      border: 1px solid #e2e8f0;
      border-radius: 22px;
      box-shadow: 0 18px 42px rgba(15, 23, 42, 0.06);
      padding: 22px;
    }}
    video {{
      width: 100%;
      border-radius: 18px;
      background: #020617;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 22px;
    }}
    h3 {{
      margin-top: 22px;
      color: #111827;
    }}
    p, li {{
      font-size: 16px;
      line-height: 1.8;
    }}
    .source-list {{
      display: grid;
      gap: 8px;
      color: #334155;
      line-height: 1.7;
    }}
    .tag {{
      display: inline-flex;
      border-radius: 999px;
      background: #dbeafe;
      color: #1d4ed8;
      padding: 5px 11px;
      font-weight: 700;
      font-size: 13px;
    }}
    .stack {{
      display: grid;
      gap: 18px;
    }}
    .script {{
      max-height: 720px;
      overflow: auto;
    }}
    .script table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 680px;
    }}
    .script th, .script td {{
      border: 1px solid #e2e8f0;
      padding: 8px;
      vertical-align: top;
    }}
    .links a {{
      display: inline-block;
      margin-right: 12px;
      color: #2563eb;
      font-weight: 700;
    }}
    code {{
      background: #f1f5f9;
      padding: 2px 5px;
      border-radius: 6px;
    }}
    @media (max-width: 860px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <span class="tag">Agent 任务结果 + 视频预览</span>
    <h1>{escape(title)}</h1>
    <p class="subtitle">这里展示教材例题来源、完整原始题目、解答过程和视频预览；发布前请人工复核页码、题目原文、讲解、字幕和画面。</p>
    <p class="links"><a href="/workflow/video/agent">返回视频 Agent 任务入口</a><a href="/workflow/graph" target="_blank">查看 LangGraph 流程图</a></p>
    <div class="grid">
      <div class="video-card">
        {video_tag}
        <p>{link_html}</p>
      </div>
      <div class="stack">
        <section>
          <h2>例题来源</h2>
          <div class="source-list">{source_html}</div>
        </section>
        <section>
          <h2>完整原始题目</h2>
          <p>{escape(question)}</p>
        </section>
        {solution_section}
      </div>
    </div>
  </main>
</body>
</html>"""


def _video_agent_source_html(source: Any) -> str:
    if isinstance(source, dict):
        rows = []
        for key, label in (("repository", "仓库"), ("pdf", "PDF"), ("pages", "页码"), ("basis", "依据")):
            value = source.get(key)
            if value in (None, "", []):
                value = "未提供来源，需要人工补充或复核" if key == "repository" else "未提供"
            text = escape(str(value))
            if key == "repository" and str(value).startswith(("http://", "https://")):
                text = f'<a href="{text}" target="_blank">{text}</a>'
            rows.append(f"<div><strong>{label}：</strong>{text}</div>")
        return "".join(rows) or "<div>未提供来源，需要人工补充。</div>"
    if source:
        return f"<div>{escape(str(source))}</div>"
    return "<div>未提供来源，需要人工补充。</div>"


def _save_video_agent_result(result: dict[str, Any]) -> str:
    result_dir = OUT_DIR / "video-agent-results"
    result_dir.mkdir(parents=True, exist_ok=True)
    base = str(result.get("title") or result.get("question") or result.get("instruction") or "video-agent")
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", base).strip("-")[:32] or "video-agent"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    job = f"{stamp}-{slug}"
    (result_dir / f"{job}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return job


def _video_agent_workspace_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>视频 Agent 任务入口</title>
  <style>
    :root { --blue:#2563eb; --line:#d9e2ef; --muted:#667085; --bg:#f6f8fb; --card:#fff; }
    body { margin:0; background:var(--bg); color:#172033; font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
    main { max-width:1180px; margin:0 auto; padding:32px 18px 60px; }
    h1 { margin:0 0 8px; }
    .muted { color:var(--muted); }
    .workspace-links { display:flex; gap:10px; flex-wrap:wrap; margin:8px 0 18px; }
    .workspace-links a { display:inline-flex; align-items:center; text-decoration:none; border-radius:999px; border:1px solid var(--line); background:#fff; color:#2563eb; padding:7px 12px; font-weight:800; }
    .layout { display:grid; grid-template-columns:0.9fr 1.1fr; gap:18px; align-items:start; }
    .panel { background:var(--card); border:1px solid var(--line); border-radius:16px; box-shadow:0 10px 28px rgba(15,23,42,.06); padding:20px; }
    textarea { width:100%; min-height:260px; box-sizing:border-box; border:1px solid var(--line); border-radius:12px; padding:14px; font:inherit; resize:vertical; }
    button { border:0; border-radius:11px; background:var(--blue); color:white; padding:10px 16px; font-weight:800; cursor:pointer; }
    button.secondary { background:#475467; }
    .button-link { display:inline-flex; align-items:center; text-decoration:none; border-radius:11px; background:#0f766e; color:white; padding:10px 16px; font-weight:800; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .actions { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:14px; }
    .result { min-height:520px; border:1px solid var(--line); border-radius:14px; background:white; padding:18px; overflow:auto; }
    pre { white-space:pre-wrap; word-break:break-word; background:#f8fafc; border:1px solid var(--line); border-radius:10px; padding:12px; }
    video { max-width:380px; width:100%; border-radius:14px; background:#000; border:1px solid var(--line); }
    .links a { display:inline-block; margin-right:12px; }
    @media (max-width:900px) { .layout { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <main>
    <h1>视频 Agent 任务入口</h1>
    <div class="workspace-links">
      <a href="/workflow/rewrite">公众号改写工作台</a>
      <a href="/workflow/video/agent/run/stream" target="_blank">视频流式处理页</a>
      <a href="/workflow/graph" target="_blank">LangGraph 流程图</a>
    </div>
    <div class="layout">
      <section class="panel">
        <h2>给 Agent 的任务</h2>
        <textarea id="instruction" placeholder="例如：去 ChinaTextbook 找人教版高中物理必修/选择性必修里找一个知识点或例题，必须使用 Remotion best practices skill 生成 3D 解析动画视频，用动画表现条件提取、建模、推导和结果，不要只是文字卡片旋转，并配上解说音。"></textarea>
        <div class="actions">
          <button id="run-button" onclick="runAgentTask()">让 Agent 生成视频</button>
          <button class="secondary" onclick="fillConicalDemo()">填入参考格式示例</button>
          <button class="secondary" onclick="fillGenericDemo()">填入通用示例</button>
          <a class="button-link" href="/workflow/video/agent/run/stream" target="_blank">打开流式页面</a>
        </div>
        <p id="status" class="muted">等待任务。</p>
      </section>
      <section class="panel">
        <h2>结果</h2>
        <div id="result" class="result"><p class="muted">生成后会显示视频、脚本、来源和复核提示。</p></div>
      </section>
    </div>
  </main>
  <script>
    async function runAgentTask() {
      const button = document.getElementById("run-button");
      const instruction = document.getElementById("instruction").value.trim();
      if (!instruction) {
        setStatus("请先输入任务。");
        return;
      }
      button.disabled = true;
      setStatus("Agent 正在处理任务，下面会实时显示进度。");
      document.getElementById("result").innerHTML = "<h3>处理进度</h3><ol id='progress-list'></ol>";
      try {
        const response = await fetch("/workflow/video/agent/run/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instruction })
        });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(`流式接口 HTTP ${response.status}：${text.slice(0, 300)}`);
        }
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("application/x-ndjson")) {
          const text = await response.text();
          throw new Error(`流式接口返回了非 JSON 流：${text.slice(0, 300)}`);
        }
        if (!response.body) {
          throw new Error("当前浏览器不支持流式读取响应");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        let finalData = null;
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (!line.trim()) continue;
            const event = parseStreamEvent(line);
            if (event.event === "progress") {
              appendProgress(event.message || "处理中...");
              setStatus(event.message || "处理中...");
            }
            if (event.event === "done") {
              finalData = event;
            }
          }
        }
        if (buffer.trim()) {
          const event = parseStreamEvent(buffer);
          if (event.event === "done") finalData = event;
        }
        if (!finalData) {
          throw new Error("流式响应结束但没有返回最终结果");
        }
        if (!finalData.ok) {
          setStatus(finalData.error || "生成失败");
          document.getElementById("result").innerHTML += `<pre>${escapeHtml(JSON.stringify(finalData, null, 2))}</pre>`;
          return;
        }
        appendProgress("处理完成，正在展示结果。");
        setStatus(finalData.message || "已生成视频。发布前请人工复核。");
        document.getElementById("result").innerHTML = renderResult(finalData);
      } catch (error) {
        const errorText = String(error);
        if (errorText.includes("Error in input stream")) {
          appendProgress("流式连接被开发服务器热重载中断，正在改用普通接口重试一次。");
          setStatus("流式连接中断，正在改用普通接口重试...");
          try {
            const fallback = await fetch("/workflow/video/agent/run", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ instruction })
            });
            const data = await fallback.json();
            if (!data.ok) {
              setStatus(data.error || "生成失败");
              document.getElementById("result").innerHTML += `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
              return;
            }
            setStatus(data.message || "已生成视频。发布前请人工复核。");
            document.getElementById("result").innerHTML = renderResult(data);
            return;
          } catch (fallbackError) {
            setStatus(`普通接口重试也失败：${fallbackError}`);
            return;
          }
        }
        setStatus(`生成失败：${error}`);
      } finally {
        button.disabled = false;
      }
    }

    function renderResult(data) {
      if (data.page_url) {
        return `
          <p class="links"><a href="${data.page_url}" target="_blank">打开展示页</a>${data.video_url ? ` · <a href="${data.video_url}" target="_blank">打开 MP4</a>` : ""}</p>
          <iframe src="${data.page_url}" style="width:100%; min-height:760px; border:1px solid #d9e2ef; border-radius:14px; background:white;"></iframe>
        `;
      }
      const video = data.video_url ? `<video controls src="${data.video_url}"></video>` : "";
      const links = `<p class="links">${data.video_url ? `<a href="${data.video_url}" target="_blank">打开 MP4</a>` : ""}</p>`;
      const source = data.source ? `<h3>来源</h3><pre>${escapeHtml(JSON.stringify(data.source, null, 2))}</pre>` : "";
      const question = data.question ? `<h3>完整题目</h3><p>${escapeHtml(data.question)}</p>` : "";
      const solution = data.solution ? `<h3>解答过程</h3><ol>${data.solution.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ol>` : "";
      const review = data.review_flags ? `<h3>复核提示</h3><pre>${escapeHtml((data.review_flags || []).join("\\n") || "发布前人工复核教材来源、概念定义、字幕和画面。")}</pre>` : "";
      return `${video}${links}${source}${question}${solution}${review}`;
    }

    function fillConicalDemo() {
      document.getElementById("instruction").value = "在高中物理教材上找圆锥摆运动的例题，获取教材内容，必须使用 Remotion best practices skill 生成一个1到2分钟的3D解析动画视频，用动画表现条件提取、建模、推导和结果，不要只是文字卡片旋转。";
    }

    function fillGenericDemo() {
      document.getElementById("instruction").value = "在高中教材上找一个例题，必须使用 PDF Skill 获取教材内容，必须使用 Remotion best practices skill 生成一个 3D 解析动画视频，用动画表现条件提取、建模、推导和结果，不要只是文字卡片旋转，并使用 voice-tts skill 调用火山引擎文字转语音 API 给视频配解说音。";
    }

    function setStatus(text) {
      document.getElementById("status").textContent = text;
    }

    function appendProgress(text) {
      const list = document.getElementById("progress-list");
      if (!list) return;
      const item = document.createElement("li");
      item.textContent = text;
      list.appendChild(item);
    }

    function parseStreamEvent(line) {
      const text = String(line || "").trim();
      try {
        return JSON.parse(text.startsWith("data:") ? text.slice(5).trim() : text);
      } catch (error) {
        throw new Error(`流式接口返回了无法解析的内容：${text.slice(0, 300)}`);
      }
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      })[char]);
    }
  </script>
</body>
</html>"""


def _video_agent_stream_page_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>视频 Agent 流式处理页</title>
  <style>
    :root { --blue:#2563eb; --line:#d9e2ef; --muted:#667085; --bg:#f6f8fb; --card:#fff; }
    body { margin:0; background:var(--bg); color:#172033; font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
    main { max-width:980px; margin:0 auto; padding:32px 18px 60px; }
    .panel { background:var(--card); border:1px solid var(--line); border-radius:16px; box-shadow:0 10px 28px rgba(15,23,42,.06); padding:20px; margin-top:18px; }
    textarea { width:100%; min-height:160px; box-sizing:border-box; border:1px solid var(--line); border-radius:12px; padding:14px; font:inherit; resize:vertical; }
    button { border:0; border-radius:11px; background:var(--blue); color:white; padding:10px 16px; font-weight:800; cursor:pointer; }
    button.secondary { background:#475467; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .actions { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:14px; }
    .muted { color:var(--muted); }
    pre, .log { white-space:pre-wrap; word-break:break-word; background:#f8fafc; border:1px solid var(--line); border-radius:10px; padding:12px; }
    .links a { display:inline-block; margin-right:12px; }
  </style>
</head>
<body>
  <main>
    <h1>视频 Agent 流式处理页</h1>
    <p class="links"><a href="/workflow/video/agent">返回视频 Agent 任务入口</a><a href="/workflow/graph" target="_blank">查看 LangGraph 流程图</a></p>
    <section class="panel">
      <h2>任务</h2>
      <textarea id="instruction">在高中物理教材上找圆锥摆运动的例题，获取教材内容，生成一个1到2分钟的3D动画视频。</textarea>
      <div class="actions">
        <button id="run-button" onclick="runStream()">开始流式生成</button>
        <button class="secondary" onclick="fillDemo()">填入圆锥摆例题任务</button>
      </div>
      <p id="status" class="muted">等待任务。</p>
    </section>
    <section class="panel">
      <h2>实时进度</h2>
      <ol id="progress-list"></ol>
      <div id="final-result"></div>
    </section>
  </main>
  <script>
    async function runStream() {
      const button = document.getElementById("run-button");
      const instruction = document.getElementById("instruction").value.trim();
      if (!instruction) {
        setStatus("请先输入任务。");
        return;
      }
      button.disabled = true;
      document.getElementById("progress-list").innerHTML = "";
      document.getElementById("final-result").innerHTML = "";
      setStatus("正在连接流式接口...");
      try {
        const response = await fetch("/workflow/video/agent/run/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instruction })
        });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(`流式接口 HTTP ${response.status}：${text.slice(0, 300)}`);
        }
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("application/x-ndjson")) {
          const text = await response.text();
          throw new Error(`流式接口返回了非 JSON 流：${text.slice(0, 300)}`);
        }
        if (!response.body) throw new Error("当前浏览器不支持流式读取响应");
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (line.trim()) handleEvent(parseStreamEvent(line));
          }
        }
        if (buffer.trim()) handleEvent(parseStreamEvent(buffer));
      } catch (error) {
        const errorText = String(error);
        if (errorText.includes("Error in input stream")) {
          appendProgress("流式连接被开发服务器热重载中断，正在改用普通接口重试一次。");
          setStatus("流式连接中断，正在改用普通接口重试...");
          try {
            const fallback = await fetch("/workflow/video/agent/run", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ instruction })
            });
            const data = await fallback.json();
            if (!data.ok) {
              setStatus(data.error || "生成失败");
              document.getElementById("final-result").innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
              return;
            }
            setStatus(data.message || "已生成视频。");
            document.getElementById("final-result").innerHTML = renderResult(data);
            return;
          } catch (fallbackError) {
            setStatus(`普通接口重试也失败：${fallbackError}`);
            return;
          }
        }
        setStatus(`流式生成失败：${error}`);
      } finally {
        button.disabled = false;
      }
    }

    function handleEvent(event) {
      if (event.event === "progress") {
        appendProgress(event.message || "处理中...");
        setStatus(event.message || "处理中...");
        return;
      }
      if (event.event === "done") {
        if (!event.ok) {
          setStatus(event.error || "生成失败");
          document.getElementById("final-result").innerHTML = `<pre>${escapeHtml(JSON.stringify(event, null, 2))}</pre>`;
          return;
        }
        setStatus(event.message || "已生成视频。");
        document.getElementById("final-result").innerHTML = renderResult(event);
      }
    }

    function renderResult(data) {
      const pageLink = data.page_url ? `<a href="${data.page_url}" target="_blank">打开展示页</a>` : "";
      const videoLink = data.video_url ? `<a href="${data.video_url}" target="_blank">打开 MP4</a>` : "";
      return `<p class="links">${pageLink} ${videoLink}</p><pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
    }

    function fillDemo() {
      document.getElementById("instruction").value = "在高中物理教材上找圆锥摆运动的例题，获取教材内容，生成一个1到2分钟的3D动画视频。";
    }

    function appendProgress(text) {
      const item = document.createElement("li");
      item.textContent = text;
      document.getElementById("progress-list").appendChild(item);
    }

    function setStatus(text) {
      document.getElementById("status").textContent = text;
    }

    function parseStreamEvent(line) {
      const text = String(line || "").trim();
      try {
        return JSON.parse(text.startsWith("data:") ? text.slice(5).trim() : text);
      } catch (error) {
        throw new Error(`流式接口返回了无法解析的内容：${text.slice(0, 300)}`);
      }
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      })[char]);
    }
  </script>
</body>
</html>"""


def _is_conical_pendulum_task(instruction: str) -> bool:
    if _mentions_conical_as_reference(instruction):
        return False
    if any(keyword in instruction for keyword in ("圆锥摆", "空中飞椅")):
        return True
    return "向心力" in instruction and any(keyword in instruction for keyword in ("教材", "例题", "ChinaTextbook", "人教版"))


def _mentions_conical_as_reference(instruction: str) -> bool:
    return "圆锥摆" in instruction and any(keyword in instruction for keyword in ("参考", "示例", "模式", "不要固定", "不是就要"))


def _is_real_conical_pendulum_request(instruction: str) -> bool:
    if _mentions_conical_as_reference(instruction):
        return False
    return any(keyword in instruction for keyword in ("圆锥摆", "空中飞椅"))


def _is_reference_only_video_instruction(instruction: str) -> bool:
    if not any(keyword in instruction for keyword in ("参考", "展示页", "模式", "格式示例")):
        return False
    if any(pattern in instruction for pattern in ("什么是", "为什么", "知识点：", "知识点:", "主题：", "主题:", "例题：", "例题:")):
        return False
    meta_markers = ("请参考", "圆锥摆展示页", "先给出", "最后生成", "主题请按", "不要固定")
    return any(marker in instruction for marker in meta_markers)


def _conical_pendulum_material_text(example: dict[str, Any]) -> str:
    source = example["source"]
    solution = "\n".join(f"{index}. {item}" for index, item in enumerate(example["solution"], start=1))
    return f"""资料来源：
仓库：{source["repository"]}
PDF：{source["pdf"]}
页码：{source["pages"]}
依据：{source["basis"]}

完整题目：
{example["question"]}

解答过程：
{solution}

讲解边界：
圆锥摆不是简谐振动。这个例题只讲水平圆周运动、受力分解和向心力来源。"""

 
def _stream_video_agent_run(payload: dict[str, Any]):
    def emit(event: str, **data: Any) -> str:
        return json.dumps({"event": event, **data}, ensure_ascii=False) + "\n"

    instruction = str(payload.get("instruction") or payload.get("task") or "").strip()
    if not instruction:
        yield emit("done", ok=False, error="请输入你希望 Agent 完成的视频任务。")
        return
    if _is_reference_only_video_instruction(instruction):
        yield emit(
            "done",
            ok=False,
            error=(
                "当前输入只有“参考圆锥摆展示页模式”的要求，没有实际视频主题。"
                "请补充要讲的知识点或例题，例如：在高中物理教材上找圆锥摆运动的例题，获取教材内容，生成一个1到2分钟的3D动画视频。"
            ),
        )
        return

    yield emit("progress", message="收到任务，开始解析视频生成要求。")
    events: Queue[dict[str, Any]] = Queue()

    def progress(message: str) -> None:
        events.put({"event": "progress", "message": message})

    def worker() -> None:
        try:
            if bool(payload.get("use_conical_demo")) or _is_real_conical_pendulum_request(instruction):
                result = _run_conical_pendulum_agent_task(instruction, progress=progress)
            else:
                result = _run_general_video_agent_task(instruction, payload, progress=progress)
        except Exception as exc:
            events.put({"event": "progress", "message": "生成过程中出现异常，正在返回错误信息。"})
            events.put({"event": "done", "ok": False, "error": f"视频生成失败：{_clean_text(str(exc))}"})
            return
        events.put({"event": "done", **result})

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while True:
        try:
            event = events.get(timeout=15)
        except Empty:
            yield emit("progress", message="仍在处理中：视频生成、TTS 或 Remotion 渲染可能需要较长时间。")
            continue
        yield json.dumps(event, ensure_ascii=False) + "\n"
        if event.get("event") == "done":
            break


def _run_conical_pendulum_agent_task(instruction: str, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    progress = progress or (lambda _message: None)
    progress("使用内置圆锥摆教材例题准备 3D 动画任务。")
    command = [sys.executable, str(ROOT_DIR / "scripts" / "render_conical_pendulum_video.py")]
    try:
        progress("调用 Remotion 圆锥摆渲染脚本，生成动画、字幕和解说音。")
        subprocess.run(command, cwd=ROOT_DIR, check=True, capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"圆锥摆视频生成失败：{_clean_subprocess_error(exc)}"}

    example = _conical_pendulum_example_payload()
    progress("圆锥摆视频已生成，正在组织展示页数据。")
    return {
        "ok": True,
        "kind": "conical_pendulum",
        "message": "已根据教材来源生成圆锥摆 3D 动画视频和展示页。",
        "instruction": instruction,
        "video_url": "/workflow/out/conical-pendulum-narrated.mp4",
        "silent_video_url": "/workflow/out/conical-pendulum.mp4",
        "page_url": "/workflow/video/conical-pendulum",
        "source": example.get("source"),
        "question": example.get("question"),
        "solution": example.get("solution"),
        "review_flags": ["发布前人工复核教材页码、题目改编准确性、字幕文字和讲解语音。"],
    }


def _run_general_video_agent_task(
    instruction: str,
    payload: dict[str, Any],
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    progress = progress or (lambda _message: None)
    progress("解析用户任务，识别学段、学科、知识点和教材检索条件。")
    source_payload = _video_source_from_instruction(instruction, payload)
    progress("使用 PDF Skill 检查本地/远程教材 PDF，并尝试解析教材例题。")
    textbook_example = _video_textbook_example(source_payload, instruction)
    if textbook_example is not None:
        progress("已从教材页提取例题来源、完整原始题目和解答依据。")
        source_payload = {
            **source_payload,
            "source_url": textbook_example["source"].get("repository") or source_payload.get("source_url") or "",
            "raw_text": _textbook_example_material_text(textbook_example),
            "examples": [textbook_example["question"]],
            "key_points": _textbook_example_key_points(source_payload, textbook_example),
            "common_misunderstandings": _textbook_example_misunderstandings(source_payload, textbook_example),
        }
    else:
        required_terms = _textbook_required_topic_terms(str(source_payload.get("title") or ""), instruction)
        if required_terms and any(keyword in instruction for keyword in ("教材", "课本", "教科书", "ChinaTextbook", "TapXWorld")):
            return {
                "ok": False,
                "error": (
                    "未在教材 PDF 中命中与任务主题匹配的例题，已停止生成，避免编造教材来源。"
                    f" 当前强制主题关键词：{'、'.join(required_terms[:6])}。"
                    "请指定教材册次/章节，或先补充包含该主题的 PDF。"
                ),
            }
        progress("未命中标准教材例题，使用任务输入和可用来源构建待复核题目。")
    result_source = textbook_example["source"] if textbook_example is not None else _video_result_source(source_payload, instruction)
    state: HotspotState = {"video_source": source_payload}
    progress("调用 EducationKnowledgeSourceAgent 整理知识点、题目和常见误区。")
    state.update(EducationKnowledgeSourceAgent().invoke(state))
    knowledge = state.get("education_knowledge")
    if knowledge is None:
        return {"ok": False, "error": "Agent 未能解析视频任务，请补充知识点、学段、学科或教材来源。"}
    question = textbook_example["question"] if textbook_example is not None else _video_full_question(instruction, result_source)
    solution = textbook_example["solution"] if textbook_example is not None else _structured_solution_from_source_payload(source_payload, question)
    progress("根据结构化题目和解答过程构建 Remotion best practices 3D 动画脚本。")
    script = _remotion_script_from_result(
        title=str(source_payload.get("title") or knowledge.title),
        question=question,
        solution=solution,
        knowledge=knowledge,
    )
    progress("按 Remotion best practices 生成 3D 解析动画时间线、字幕和逐段解说文本。")
    timeline_clips = _remotion_timeline_from_solution(script.title, question, solution)
    state["video_channel_script"] = script
    progress("调用 VideoComplianceCheckAgent 增加发布前人工复核提示。")
    state.update(VideoComplianceCheckAgent().invoke(state))
    try:
        progress("调用 voice-tts skill 生成解说音，并按 Remotion best practices 渲染 3D 动画视频。")
        result = render_remotion_timeline_draft(script, timeline_clips, GENERATED_VIDEO_DIR, require_remotion=True)
    except RuntimeError as exc:
        return {
            "ok": False,
            "error": (
                f"{exc} 当前任务要求使用 Remotion skill。请确认 video-renderer 依赖已安装、Docker 可用，"
                "并且 VIDEO_RENDER_REMOTION_DOCKER_IMAGE 使用带 Chrome 运行依赖的镜像，例如 "
                "mcr.microsoft.com/playwright:v1.49.1-jammy。"
            ),
            "required_skill": "skills/video-remotion/SKILL.md",
        }
    progress("视频、音频和字幕已生成，正在保存展示页结果。")
    response = {
        "ok": True,
        "kind": "general_video",
        "message": "已根据 Agent 任务使用 Remotion best practices skill 生成 3D 动画视频和展示页。",
        "instruction": instruction,
        "title": script.title,
        "question": question,
        "solution": solution,
        "source": result_source,
        "video_url": _generated_video_url(result.video_path),
        "audio_url": _generated_video_url(result.audio_path),
        "subtitles_url": _generated_video_url(result.subtitles_path),
        "duration_seconds": result.duration_seconds,
        "render_engine": "remotion",
        "required_skill": "skills/video-remotion/SKILL.md",
        "required_remotion_practices": "skills/video-remotion/SKILL.md#rendering-rules",
        "warnings": [],
        "review_flags": state.get("review_flags", []),
        "human_review_required": True,
    }
    job = _save_video_agent_result(response)
    response["page_url"] = f"/workflow/video/agent/result/{job}"
    return response


def _video_source_from_instruction(instruction: str, payload: dict[str, Any]) -> dict[str, Any]:
    if _is_real_conical_pendulum_request(instruction):
        example = _conical_pendulum_example_payload()
        return {
            "title": "圆锥摆运动例题",
            "subject": "物理",
            "grade_or_level": "高中",
            "source_url": example["source"]["repository"],
            "raw_text": _conical_pendulum_material_text(example),
            "key_points": [
                "圆锥摆小球做水平面内的匀速圆周运动",
                "竖直方向拉力分量平衡重力",
                "水平方向拉力分量提供向心力",
            ],
            "examples": [example["question"]],
            "common_misunderstandings": [
                "把圆锥摆说成简谐振动",
                "把向心力当成额外多出来的一种性质力",
                "忽略半径 r = L sinθ",
            ],
        }
    title = str(payload.get("title") or _title_from_instruction(instruction))
    return {
        "title": title,
        "subject": payload.get("subject") or _subject_from_instruction(instruction),
        "grade_or_level": payload.get("grade_or_level") or _level_from_instruction(instruction),
        "source_url": payload.get("source_url") or "",
        "raw_text": instruction,
        "key_points": [title, "把抽象概念转成可观察的模型", "用例题或生活情境解释公式含义"],
        "examples": ["结合一个具体场景说明受力、运动和公式之间的关系。"],
        "common_misunderstandings": ["只背公式，不分析力的来源和适用条件。"],
    }


def _video_result_source(source_payload: dict[str, Any], instruction: str) -> dict[str, Any]:
    if _is_real_conical_pendulum_request(instruction):
        return _conical_pendulum_example_payload()["source"]
    textbook_source = _china_textbook_source(source_payload, instruction)
    if textbook_source:
        return textbook_source
    source_url = source_payload.get("source_url")
    return {
        "title": source_payload.get("title"),
        "subject": source_payload.get("subject"),
        "grade_or_level": source_payload.get("grade_or_level"),
        "source_url": source_url or "未提供来源，需要人工补充或复核",
        "basis": "用户任务输入和生成脚本。发布前需要人工复核资料来源、定义、例题和解答过程。",
    }


def _video_textbook_example(source_payload: dict[str, Any], instruction: str) -> dict[str, Any] | None:
    if _is_real_conical_pendulum_request(instruction):
        example = _conical_pendulum_example_payload()
        return {
            "source": example["source"],
            "question": example["question"],
            "solution": list(example["solution"]),
        }
    source = _china_textbook_source(source_payload, instruction)
    if source is None:
        return None
    title = str(source_payload.get("title") or _title_from_instruction(instruction) or "这个知识点")
    basis = _plain_text(str(source.get("basis") or ""))
    question = _textbook_original_question_from_basis(title, basis)
    solution = _textbook_solution_from_basis(title, basis, question)
    if _requires_complete_textbook_example(instruction) and not _has_complete_textbook_solution_block(basis, solution):
        return None
    source = {
        **source,
        "basis": _textbook_source_basis_summary(source, basis, question),
    }
    return {
        "source": source,
        "question": question,
        "solution": solution,
    }


def _requires_complete_textbook_example(instruction: str) -> bool:
    return any(marker in instruction for marker in ("例题", "例子", "完整解题", "解题过程"))


def _has_complete_textbook_solution_block(basis: str, solution: list[str]) -> bool:
    text = _plain_text(basis)
    if not re.search(r"(?:分析与解答|分析|解|答案)\s*[:：]?", text):
        return False
    meaningful = [step for step in solution if len(_plain_text(step)) >= 12 and not _is_textbook_chatter(step)]
    return len(meaningful) >= 2 or any(any(marker in step for marker in ("所以", "可得", "代入", "答案", "=")) for step in meaningful)


def _textbook_original_question_from_basis(title: str, basis: str) -> str:
    basis = _textbook_flow_text(basis)
    explicit = _extract_explicit_textbook_question(basis)
    if explicit:
        return explicit
    example_sentence = _extract_textbook_example_sentence(basis)
    if example_sentence:
        return f"教材原文例句：{example_sentence}"
    question_sentence = _sentence_with_keywords(basis, ["求", "计算", "回答", "为什么", "吗？", "哪些", "如何"])
    if question_sentence and _looks_like_textbook_question(question_sentence):
        return question_sentence
    return _textbook_question_candidate_from_page(basis)


def _extract_textbook_example_sentence(basis: str) -> str:
    patterns = [
        r"(例如，某反应.+?平均反应速率为\s*[^。]+。)",
        r"(例如，[^。]*(?:求|计算|平均|速率|浓度|质量|物质的量|能量|电流|电压)[^。]*。)",
        r"(如图[^。]*(?:求|计算|说明|为什么)[^。]*。)",
    ]
    for pattern in patterns:
        match = re.search(pattern, basis)
        if match:
            return _plain_text(match.group(1))
    return ""


def _extract_explicit_textbook_question(basis: str) -> str:
    near_marker = _extract_question_near_example_marker(basis)
    if near_marker:
        return near_marker
    patterns = [
        r"【\s*例题\s*】\s*(.+?)(?=分析与解答|解答|答案|\s解\s|$)",
        r"【\s*例题\s*\d+\s*】\s*(.+?)(?=分析与解答|解答|答案|\s解\s|$)",
        r"(?:^|\n)\s*例题(?:\s*\d+)?\s+(.+?)(?=分析与解答|解答|答案|\s解\s|$)",
        r"回答下列问题。?\s*(.+?)(?:\n\s*2\.|$)",
        r"问题\s*(.+?)(?:\n\s*[一-龥A-Za-z0-9].{0,12}\n|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, basis, flags=re.DOTALL)
        if not match:
            continue
        question = _clean_textbook_question(match.group(1))
        if len(question) >= 20 and ("？" in question or "?" in question or "求" in question or "计算" in question):
            return question
    return ""


def _extract_question_near_example_marker(basis: str) -> str:
    text = _plain_text(basis)
    marker = re.search(r"【\s*例题\s*\d*\s*】", text)
    if not marker:
        return ""

    after = text[marker.end() :]
    after_question = _clean_textbook_question(_before_solution_marker(after))
    if _looks_like_textbook_question(after_question):
        return f"{_normalize_example_marker(marker.group(0))}\n{after_question}"

    before = text[max(0, marker.start() - 700) : marker.start()]
    before_question = _clean_textbook_question(_before_solution_marker(before))
    if _looks_like_textbook_question(before_question):
        return f"{_normalize_example_marker(marker.group(0))}\n{before_question}"
    return ""


def _normalize_example_marker(text: str) -> str:
    match = re.search(r"例题\s*(\d*)", text)
    number = match.group(1).strip() if match else ""
    return f"【例题 {number}】" if number else "【例题】"


def _before_solution_marker(text: str) -> str:
    return _strip_textbook_solution_tail(text)


def _clean_textbook_question(text: str) -> str:
    text = re.sub(r"【\s*例题\s*\d*\s*】", "", text)
    text = _strip_textbook_solution_tail(text)
    text = _plain_text(text).strip(" ，。；")
    contextual = re.search(r"(如图[^。？！]{0,120}?所示，[^。？！]*(?:求|计算|判断|说明|多少|大小|方向|？|\?).*)", text)
    if contextual:
        return _strip_textbook_solution_tail(contextual.group(1)).strip(" ，。；")
    starts = [
        match.start()
        for pattern in (
            r"一个",
            r"一辆",
            r"一架",
            r"某",
            r"带电",
            r"电子",
            r"小球",
            r"汽车",
            r"飞机",
            r"线圈",
        )
        for match in re.finditer(pattern, text)
    ]
    for start in sorted(starts):
        candidate = _strip_textbook_solution_tail(text[start:]).strip(" ，。；")
        if _looks_like_textbook_question(candidate):
            return candidate
    return _strip_textbook_solution_tail(text)


def _strip_textbook_solution_tail(text: str) -> str:
    text = _plain_text(text)
    boundary_patterns = [
        r"(?:^|\n)\s*(?:分析与解答|解答|答案)\s*[:：]?\s",
        r"(?:^|\n)\s*解\s+(?=根据|由|设|得|可得|因为|把|将|答)",
        r"(?:。|；|;)\s*(?:分析与解答|解答|答案)\s*[:：]?\s",
        r"(?:。|；|;)\s*解\s+(?=根据|由|设|得|可得|因为|把|将|答)",
        r"\s+(?:分析与解答|解答|答案)\s*[:：]?\s",
        r"\s+解\s+(?=根据|由|设|得|可得|因为|把|将|答)",
    ]
    cuts = [match.start() for pattern in boundary_patterns for match in re.finditer(pattern, text)]
    return text[: min(cuts)].strip() if cuts else text.strip()


def _looks_like_textbook_question(text: str) -> bool:
    if len(text) < 20:
        return False
    if any(bad in text for bad in ("上述例题", "例题中", "本章第")):
        return False
    return any(marker in text for marker in ("？", "?", "求", "计算", "判断", "说明", "多少", "大小", "方向"))


def _textbook_question_candidate_from_page(basis: str) -> str:
    text = _plain_text(basis)
    candidates: list[str] = []
    for sentence in re.split(r"[。？！?]\s*|\n+", text):
        candidate = _clean_textbook_question(_remove_example_discussion_prefix(sentence))
        if len(candidate) < 16:
            continue
        if any(marker in candidate for marker in ("吗", "求", "计算", "判断", "说明", "多少", "大小", "方向")):
            candidates.append(candidate)
    if candidates:
        return max(candidates, key=_question_candidate_score)

    paragraphs = [_clean_textbook_question(_remove_example_discussion_prefix(line)) for line in text.splitlines()]
    paragraphs = [line for line in paragraphs if len(line) >= 20 and not _is_textbook_chatter(line)]
    if paragraphs:
        return max(paragraphs, key=len)[:500]

    cleaned = _short_inline_text(text, 1000)
    return cleaned or "当前教材页为空，无法提取题目内容。"


def _remove_example_discussion_prefix(text: str) -> str:
    text = re.sub(r"^.*?(?:上述例题中|例题中)[，,]?", "", text).strip()
    return text or _plain_text(text)


def _question_candidate_score(text: str) -> int:
    score = len(text)
    for marker in ("求", "计算", "判断", "说明", "多少", "大小", "方向", "吗", "？", "?"):
        if marker in text:
            score += 20
    if _is_textbook_chatter(text):
        score -= 80
    return score


def _is_textbook_chatter(text: str) -> bool:
    return any(marker in text for marker in ("发布前", "人工复核", "上述例题", "本章第"))


def _textbook_solution_from_basis(title: str, basis: str, question: str = "") -> list[str]:
    reaction_rate = _reaction_rate_solution(question or basis)
    if reaction_rate:
        return reaction_rate
    explicit_solution = _extract_textbook_solution_steps(basis)
    if explicit_solution:
        return explicit_solution
    return []


def _extract_textbook_solution_steps(basis: str) -> list[str]:
    text = _textbook_flow_text(basis)
    marker_pattern = r"(?:^|\n|\s|[。；;])\s*(分析与解答|解答|解|答案)\s*[:：]?"
    matches = list(re.finditer(marker_pattern, text))
    if not matches:
        return []
    segments: list[str] = []
    for index, match in enumerate(matches):
        label = match.group(1)
        next_marker_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[match.end() : next_marker_start]
        segment = _trim_textbook_solution_segment(segment, stop_at_exercise=label in ("分析与解答", "解答"))
        if segment:
            segments.append(segment)
    solution_text = "\n".join(segments)
    parts = [
        _plain_text(part).strip(" ；;。")
        for part in re.split(r"(?:\n+|(?<=[。；;]))", solution_text)
        if _plain_text(part).strip(" ；;。")
    ]
    steps: list[str] = []
    for part in parts:
        if len(part) < 8:
            continue
        if _is_textbook_chatter(part):
            continue
        if _is_textbook_extraction_noise(part):
            continue
        steps.append(part)
    if not steps and len(solution_text.strip()) >= 20:
        steps = [_plain_text(solution_text).strip()]
    return steps


def _trim_textbook_solution_segment(segment: str, stop_at_exercise: bool) -> str:
    boundaries = [
        r"\n\s*【\s*例题\s*\d*\s*】",
        r"\n\s*例题\s*\d*\s*(?:\n|$)",
        r"\n\s*(?:复习与提高|本章小结|课后练习|思考与讨论|科学漫步|做一做)\b",
        r"\n\s*\d+\s*\n\s*高中[\u4e00-\u9fff]+",
    ]
    if stop_at_exercise:
        boundaries.extend(
            [
                r"\n\s*(?:练习与应用|习题)\b",
                r"\n\s*\d+[\.．]\s+[\u4e00-\u9fff]",
            ]
        )
    boundary = "(?:" + "|".join(boundaries) + ")"
    return re.split(boundary, segment, maxsplit=1)[0].strip()


def _is_textbook_extraction_noise(text: str) -> bool:
    cleaned = _plain_text(text)
    if re.search(r"高中[\u4e00-\u9fff]*必修", cleaned):
        return True
    if re.fullmatch(r"图\s*[\d\-.]+.*", cleaned):
        return True
    return False


def _textbook_flow_text(text: str) -> str:
    text = _plain_text(text)
    structural_line = r"(?:【|例题|分析与解答|分析|解|答案|练习与应用|习题|复习与提高|本章小结|课后练习|\d+[\.．])"
    text = re.sub(rf"(?<![。？！；;：:])\n(?!\s*{structural_line})", "", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _reaction_rate_solution(text: str) -> list[str]:
    if "反应速率" not in text and "速率" not in text:
        return []
    concentration_values = [float(value) for value in re.findall(r"(\d+(?:\.\d+)?)\s*mol/L", text)]
    time_match = re.search(r"(\d+(?:\.\d+)?)\s*min", text)
    if len(concentration_values) < 2 or not time_match:
        return []
    start, end = concentration_values[0], concentration_values[1]
    minutes = float(time_match.group(1))
    delta = abs(start - end)
    rate = delta / minutes
    return [
        "明确公式：平均化学反应速率 v = Δc / Δt，反应物浓度减小也按正值表示。",
        f"提取原题数据：初始浓度为 {start:g} mol/L，末浓度为 {end:g} mol/L，时间为 {minutes:g} min。",
        f"计算浓度变化量：Δc = {start:g} mol/L - {end:g} mol/L = {delta:g} mol/L。",
        f"代入公式：v = Δc / Δt = {delta:g} / {minutes:g} = {rate:g} mol/(L·min)。",
        f"答案：这段时间内的平均化学反应速率为 {rate:g} mol/(L·min)。",
        "易错点：反应物浓度在减小，但化学反应速率通常取正值，不写成负数。",
    ]


def _sentence_with_keywords(text: str, keywords: list[str]) -> str:
    sentences = re.split(r"(?<=[。？！])|\n+", _plain_text(text))
    for sentence in sentences:
        cleaned = sentence.strip()
        if len(cleaned) < 12:
            continue
        if any(keyword and keyword in cleaned for keyword in keywords):
            return cleaned[:220]
    return ""


def _textbook_example_material_text(example: dict[str, Any]) -> str:
    source = example["source"]
    solution = "\n".join(f"{index}. {item}" for index, item in enumerate(example["solution"], start=1))
    return f"""资料来源：
仓库：{source.get("repository", "未提供来源，需要人工补充或复核")}
PDF：{source.get("pdf", "未提供")}
页码：{source.get("pages", "未提供")}
依据：{source.get("basis", "未提供")}

完整题目：
{example["question"]}

解答过程：
{solution}"""


def _textbook_example_key_points(source_payload: dict[str, Any], example: dict[str, Any]) -> list[str]:
    title = str(source_payload.get("title") or "这个知识点")
    return [
        f"讲清楚“{title}”的核心含义",
        "结合教材来源和教材片段说明",
        "按完整题目或知识点任务给出讲解过程",
    ]


def _textbook_example_misunderstandings(source_payload: dict[str, Any], example: dict[str, Any]) -> list[str]:
    return [
        "只背结论，不说明教材中的适用条件和概念边界",
        "把资料来源、题目和解答过程混在一起，导致页面不可复核",
    ]


def _structured_solution_from_source_payload(source_payload: dict[str, Any], question: str) -> list[str]:
    raw_text = _plain_text(str(source_payload.get("raw_text") or ""))
    title = str(source_payload.get("title") or "这个知识点")
    point = _plain_text(str(source_payload.get("key_points", [""])[0] if source_payload.get("key_points") else ""))
    example = _plain_text(str(source_payload.get("examples", [""])[0] if source_payload.get("examples") else ""))
    misunderstanding = _plain_text(
        str(source_payload.get("common_misunderstandings", [""])[0] if source_payload.get("common_misunderstandings") else "")
    )
    return [
        f"先明确任务：围绕“{title}”解释题目或知识点。",
        f"核心概念：{point or raw_text[:120] or question[:120]}。",
        f"结合例子：{example or question[:160]}。",
        f"分析方法：先看题目条件，再找对应定义、公式或现象，最后代入或解释。",
        f"易错提醒：{misunderstanding or '不要只背结论，要说明适用条件和概念边界。'}",
    ]


def _remotion_script_from_result(
    *,
    title: str,
    question: str,
    solution: list[str],
    knowledge: EducationKnowledgePoint,
) -> VideoChannelScript:
    clean_title = _plain_text(title or knowledge.title or "K12 知识点讲解")[:24]
    cover_text = _plain_text(clean_title)[:12] or "知识点讲解"
    clean_solution_steps = _clean_solution_steps_for_video(solution)
    first_step = _plain_text(clean_solution_steps[0] if clean_solution_steps else question)
    method_voiceover = _solution_method_voiceover(clean_title, question, solution)
    voiceover_parts = [
        f"今天我们讲一个{knowledge.grade_or_level or 'K12'}{knowledge.subject or ''}{_example_suffix(clean_title)}：{clean_title}。",
        "视频不逐字朗读题干，我们先提取关键信息，再用动画讲清楚分析过程。",
        method_voiceover,
        "最后回顾：先抓条件和模型，再列关系、代入并解释结果。",
    ]
    voiceover = "\n".join(part for part in voiceover_parts if part)
    return VideoChannelScript(
        title=clean_title,
        cover_text=cover_text,
        hook=first_step[:80] or "先看题目，再一步步分析。",
        voiceover=voiceover,
        storyboard_markdown="",
        cover_prompt=f"竖屏 9:16 K12 科教封面图，主体是“{cover_text}”知识点示意，所有可见文字只使用简体中文：{cover_text}。",
        publish_copy="",
        hashtags=[],
        source_review=[],
        risk_flags=[],
        generation_prompt=(
            "视频生成强制要求：先使用 PDF Skill（skills/pdf）获取和复核教材内容，"
            "从教材页提取例题来源、完整原始题目和解答依据；再使用 Remotion best practices skill "
            "（skills/video-remotion/SKILL.md，特别是 Remotion Best Practices Skill Rules 和 rules/3d.md）"
            "根据结构化题目和解答过程生成 3D 解析动画视频。动画必须使用 useCurrentFrame、"
            "interpolate、Sequence、calculateMetadata/staticFile 等 Remotion 最佳实践，"
            "用 3D 场景表现条件提取、建模、受力/场力、公式推导和结果回到图形；"
            "不能只是把题目文字做成旋转的 3D 字幕卡。最后使用 voice-tts skill 调用火山引擎"
            "文字转语音 API 将讲解文本转换为解说音，并按真实音频时长同步字幕和动画。"
            "本链路不调用视频脚本 LLM Agent。"
        ),
        llm_usage=None,
    )


def _remotion_timeline_from_solution(title: str, question: str, solution: list[str]) -> list[StoryboardClip]:
    clean_question = _plain_text(question)
    first_steps = _clean_solution_steps_for_video(solution)[:4]
    known_values = _known_values_text(clean_question)
    formula_text = _formula_text(first_steps)
    answer_text = _answer_text(first_steps)
    scene_type = _animation_scene_type(title, clean_question, first_steps)
    intro_voiceover = f"讲这道{title}{_example_suffix(title)}：从研究对象出发，推出结果。"
    question_voiceover = _question_focus_voiceover(clean_question)
    condition_voiceover = _condition_phase_voiceover(clean_question, first_steps)
    model_voiceover = _model_voiceover(formula_text)
    specs: list[tuple[float, str, str, str, str]] = [
        (
            4.0,
            _aligned_visual("开场建模", intro_voiceover, f"标题“{title}”和研究对象同时出现。"),
            intro_voiceover,
            _short_text(title, 18),
            "intro",
        ),
        (
            5.0,
            _aligned_visual("题图转动态模型", question_voiceover, f"题图内容：{clean_question[:160]}"),
            question_voiceover,
            "提取条件",
            "question",
        ),
        (
            6.0,
            _aligned_visual("关系标注", condition_voiceover, f"在对应对象旁标注：{known_values}。"),
            condition_voiceover,
            _short_text(known_values, 28),
            "conditions",
        ),
        (
            8.0,
            _aligned_visual("建立模型", model_voiceover, f"核心关系：{formula_text}。"),
            model_voiceover,
            _formula_or_short_text(formula_text, "核心关系", 42),
            "model",
        ),
    ]
    specs.extend(
        (
            8.0,
            _aligned_visual(f"解题第{index + 1}步", _solution_step_voiceover(index, step, formula_text, answer_text), f"原步骤：{step[:120]}。"),
            _solution_step_voiceover(index, step, formula_text, answer_text),
            _solution_step_display_text(index, step),
            "solve",
        )
        for index, step in enumerate(first_steps[:3])
    )
    specs.append(
        (
            7.0,
            _aligned_visual("结果核对", _result_voiceover(answer_text), f"最终结果：{answer_text}。"),
            _result_voiceover(answer_text),
            _formula_or_short_text(answer_text, "结果", 42),
            "result",
        )
    )
    clips: list[StoryboardClip] = []
    cursor = 0.0
    for duration, visual, voiceover, subtitle, phase in specs:
        clips.append(
            StoryboardClip(
                start=cursor,
                end=cursor + duration,
                visual=visual,
                voiceover=voiceover,
                subtitle=subtitle,
                scene_type=scene_type,
                scene_phase=phase,
            )
        )
        cursor += duration
    return clips


def _aligned_visual(stage: str, voiceover: str, detail: str) -> str:
    return f"{stage}：画面必须同步表现口播“{_short_inline_text(voiceover, 96)}”。{detail}"


def _question_focus_voiceover(question: str) -> str:
    if "静电感应" in question or "验电器" in question:
        return "带电体靠近导体，自由电荷重新分布；判断近端、远端电性，并解释箔片张开。"
    if "磁场" in question or "洛伦兹力" in question:
        return "带电粒子进入磁场受到洛伦兹力，轨迹弯成圆弧；把洛伦兹力对应向心力。"
    if "圆周运动" in question or "向心力" in question:
        return "圆周运动中，指向圆心的合力提供向心力；从受力分解开始。"
    if "点电荷" in question and "静电力" in question:
        return "三个点电荷成等边三角形，受力对称；只分析其中一个点电荷。"
    return "确定研究对象，判断相互作用，再把题目所求转成可计算或可解释的量。"


def _condition_phase_voiceover(question: str, steps: list[str]) -> str:
    first_step = _spoken_solution_step(steps[0]) if steps else ""
    if first_step:
        return _short_inline_text(first_step, 72)
    if "静电感应" in question or "验电器" in question:
        return "带电体吸引自由电子，近端和远端因此出现不同电性。"
    if "磁场" in question or "洛伦兹力" in question:
        return "洛伦兹力始终垂直速度方向，粒子因此做圆周运动。"
    if "点电荷" in question and "静电力" in question:
        return "三个电荷相同、距离相同，两个分力大小相等。"
    return "把相互作用、运动方向和题目所求放到同一个模型里。"


def _model_voiceover(formula_text: str) -> str:
    if _looks_like_empty_formula(formula_text):
        return "建立模型，把图中的关系转成可计算或可判断的关系。"
    return f"建立模型，核心关系是：{_voiceover_fragment(formula_text, 72)}。"


def _result_voiceover(answer_text: str) -> str:
    if _looks_like_empty_formula(answer_text):
        return "最后检查结论是否和方向、单位、现象一致。"
    return f"结果是：{_voiceover_fragment(answer_text, 72)}。再检查方向和单位。"


def _solution_method_voiceover(title: str, question: str, solution: list[str]) -> str:
    steps = _clean_solution_steps_for_video(solution)
    formula = _formula_text(steps)
    answer = _answer_text(steps)
    parts = [
        f"这道{title}{_example_suffix(title)}的解法从研究对象开始。",
        f"建立模型后使用核心关系：{formula}。",
        f"沿着关系推到题目所求，得到：{answer}。",
    ]
    return "\n".join(part for part in parts if part)


def _example_suffix(title: str) -> str:
    return "" if "例题" in title else "例题"


def _clean_solution_steps_for_video(solution: list[str]) -> list[str]:
    steps: list[str] = []
    for step in solution:
        cleaned = _plain_text(step)
        if not cleaned:
            continue
        if _looks_like_generated_solution_fallback(cleaned):
            continue
        steps.append(cleaned)
    return steps


def _looks_like_generated_solution_fallback(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "先定位教材知识点",
            "教材片段未给出完整例题情境",
            "人工复核",
            "复核要求",
            "需要人工",
            "发布前",
        )
    )


def _solution_step_voiceover(index: int, step: str, formula_text: str, answer_text: str) -> str:
    cleaned = _spoken_solution_step(step)
    if cleaned:
        prefixes = ["第一步，", "第二步，", "第三步，", "接着，"]
        return f"{prefixes[index] if index < len(prefixes) else '继续，'}{cleaned}"
    if index == 0:
        return "第一步先确定研究对象和关键关系。"
    if index == 1:
        return "第二步把条件放进模型，写出核心关系。"
    if index == 2:
        return "第三步沿着公式做变形，求出未知量。"
    if index == 3:
        return f"最后把推导结果落回题目要求：{answer_text}。"
    return "继续沿着模型关系推进，直到得到题目要求的量。"


def _spoken_solution_step(step: str) -> str:
    cleaned = _plain_text(step)
    cleaned = re.sub(r"^(?:分析与解答|分析|解|答案)\s*[:：]?", "", cleaned).strip()
    if _looks_like_generated_solution_fallback(cleaned) or _is_textbook_extraction_noise(cleaned):
        return ""
    return _short_inline_text(cleaned, 72)


def _voiceover_fragment(text: str, limit: int) -> str:
    return _short_inline_text(text, limit).rstrip("。；;，, ")


def _looks_like_empty_formula(text: str) -> bool:
    return not text or text in {"根据题目条件列出核心关系。", "完成解答。"}


def _solution_step_display_text(index: int, step: str) -> str:
    formula = _formula_or_short_text(step, "", 42)
    if formula:
        return formula
    labels = ["建模关系", "代入条件", "推导变形", "核对结果"]
    if index < len(labels):
        return labels[index]
    return _short_text(step, 18)


def _formula_or_short_text(text: str, fallback: str, limit: int) -> str:
    cleaned = _plain_text(text)
    formulas = re.findall(
        r"[A-Za-zΑ-Ωα-ωπθΔ][A-Za-z0-9Α-Ωα-ωπθΔ₁₂₃₄₅₆₇₈₉₀²³·./()（）+\-×÷=＝^° ]{2,}",
        cleaned,
    )
    formulas = [formula.strip(" ，。；;") for formula in formulas if any(op in formula for op in ("=", "＝", "×", "÷", "/", "^"))]
    if formulas:
        return _short_inline_text(max(formulas, key=len), limit)
    return _short_text(fallback, limit)


def _animation_scene_type(title: str, question: str, steps: list[str]) -> str:
    text = f"{title}\n{question}\n" + "\n".join(steps)
    if any(word in text for word in ("点电荷", "库仑定律", "库仑力", "静电力", "等边三角形")):
        return "physics_charge"
    if any(word in text for word in ("电磁场", "电场", "磁场", "洛伦兹力", "安培力", "电荷", "电势", "感应电流")):
        return "physics_field"
    if any(word in text for word in ("圆锥摆", "圆周运动", "向心力", "角速度", "线速度", "拉力", "重力", "合力")):
        return "physics_force"
    if any(word in text for word in ("反应", "浓度", "mol/L", "化学", "溶液", "酸", "碱", "速率")):
        return "chemistry_reaction"
    if any(word in text for word in ("函数", "坐标", "图像", "单调", "几何", "方程", "抛物线", "斜率")):
        return "math_graph"
    if any(word in text for word in ("细胞", "有丝分裂", "减数分裂", "DNA", "染色体", "光合作用", "呼吸作用")):
        return "biology_process"
    return "concept"


def _known_values_text(question: str) -> str:
    values = re.findall(r"\d+(?:\.\d+)?\s*(?:mol/L|mol/\(L·min\)|min|s|秒|分钟|℃|K|L|mL|g|kg|m|N|rad/s|弧度/秒)", question)
    if values:
        return "，".join(dict.fromkeys(values))[:90]
    terms = _known_condition_terms(question)
    if terms:
        return "，".join(terms)[:90]
    return "题图中的对象、相互作用和要求量"


def _known_condition_terms(question: str) -> list[str]:
    candidates = [
        ("速度 v", ("速度 v", "速度为 v", "以速度v", "以速度 v")),
        ("磁感应强度 B", ("磁感应强度为 B", "磁感应强度 B", "磁场 B")),
        ("电荷量 q", ("电荷量为 q", "电荷量 q", "带电量 q")),
        ("质量 m", ("质量为 m", "质量 m")),
        ("半径 r", ("半径为 r", "半径 r")),
        ("周期 T", ("周期为 T", "周期 T")),
        ("电场强度 E", ("电场强度为 E", "电场强度 E")),
        ("电势差 U", ("电势差为 U", "电势差 U")),
        ("电流 I", ("电流为 I", "电流 I")),
        ("电压 U", ("电压为 U", "电压 U")),
        ("时间 t", ("时间为 t", "时间 t")),
    ]
    terms: list[str] = []
    for label, markers in candidates:
        if any(marker in question for marker in markers):
            terms.append(label)
    if "求" in question:
        ask = question.split("求", 1)[1]
        ask = re.split(r"[。；;，,]", ask, maxsplit=1)[0].strip()
        if ask:
            terms.append(f"要求：{ask[:24]}")
    return list(dict.fromkeys(terms))


def _formula_text(steps: list[str]) -> str:
    formula_steps = [step for step in steps if any(marker in step for marker in ("=", "＝", "Δ", "v", "T", "mg", "F", "k", "cos"))]
    if formula_steps:
        return _short_text(max(formula_steps, key=_formula_step_score), 100)
    for step in steps:
        if any(marker in step for marker in ("公式", "速率")):
            return _short_text(step, 100)
    return _short_text(steps[0] if steps else "根据题目条件列出核心关系。", 100)


def _formula_step_score(step: str) -> int:
    score = 0
    for marker in ("F", "=", "＝", "k", "cos", "Δ", "mv", "qvB", "mg"):
        if marker in step:
            score += 10
    score += min(len(step), 80)
    return score


def _answer_text(steps: list[str]) -> str:
    for step in reversed(steps):
        if any(marker in step for marker in ("答案", "所以", "得到", "为", "=")):
            return _short_text(step, 100)
    return _short_text(steps[-1] if steps else "完成解答。", 100)


def _short_text(value: str, limit: int) -> str:
    return _plain_text(value)[:limit]


def _short_inline_text(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", _plain_text(value)).strip()[:limit]


def _china_textbook_source(source_payload: dict[str, Any], instruction: str) -> dict[str, Any] | None:
    if not any(keyword in instruction for keyword in ("ChinaTextbook", "TapXWorld", "教材", "课本", "人教版", "必修", "教科书")):
        return None
    try:
        from scripts.textbook_pdf_search import DEFAULT_TEXTBOOK_DIR, search_pdfs
    except Exception:
        return None
    title = str(source_payload.get("title") or "")
    subject = str(source_payload.get("subject") or "")
    query_words = _textbook_query_words(title, subject, instruction)
    glob_pattern = _textbook_glob(subject, str(source_payload.get("grade_or_level") or ""), instruction)
    try:
        hits = search_pdfs(DEFAULT_TEXTBOOK_DIR, glob_pattern, query_words, limit=8)
        hits = _filter_textbook_hits_by_topic(hits, title, instruction)
        if not hits and _ensure_china_textbook_pdf(DEFAULT_TEXTBOOK_DIR, glob_pattern, title, subject, instruction):
            hits = search_pdfs(DEFAULT_TEXTBOOK_DIR, glob_pattern, query_words, limit=8)
            hits = _filter_textbook_hits_by_topic(hits, title, instruction)
    except Exception:
        return None
    if not hits:
        return None
    hit = hits[0]
    return {
        "repository": "https://github.com/TapXWorld/ChinaTextbook",
        "pdf": hit.source,
        "pages": _textbook_pages_label(hit),
        "basis": _plain_text(hit.excerpt),
    }


def _textbook_pages_label(hit: Any) -> str:
    pdf_label = f"PDF 第 {hit.page} 页"
    textbook_page = getattr(hit, "textbook_page", None)
    if textbook_page:
        return f"{pdf_label}，教材页码第 {textbook_page} 页"
    return f"{pdf_label}，教材页码待人工复核"


def _textbook_source_basis_summary(source: dict[str, Any], basis: str, question: str) -> str:
    chapter = _textbook_chapter_title(basis)
    question_summary = _short_inline_text(question, 120)
    if chapter and question_summary and not question_summary.startswith("未从当前教材页"):
        return f"{chapter}中的例题：{question_summary}"
    if question_summary and not question_summary.startswith("未从当前教材页"):
        return f"教材例题原文：{question_summary}"
    return _short_inline_text(basis, 180) or "教材原文依据待人工复核。"


def _textbook_chapter_title(text: str) -> str:
    for line in _plain_text(text).splitlines()[:8]:
        line = line.strip()
        if re.match(r"^第[一二三四五六七八九十\d]+章", line):
            return line[:40]
    match = re.search(r"(第[一二三四五六七八九十\d]+章[^。\n]{0,24})", text)
    return match.group(1).strip() if match else ""


def _ensure_china_textbook_pdf(root: Path, glob_pattern: str, title: str, subject: str, instruction: str) -> bool:
    """Materialize a matching ChinaTextbook PDF before running PDF parsing."""
    if any(root.glob(glob_pattern)) and not _textbook_required_topic_terms(title, instruction):
        return True
    if not _ensure_china_textbook_repo(root):
        return False
    candidate_paths = _china_textbook_pdf_paths(root, glob_pattern)
    if not candidate_paths:
        return False
    chosen = max(
        candidate_paths,
        key=lambda path: _china_textbook_path_score(path, title=title, subject=subject, instruction=instruction),
    )
    try:
        subprocess.run(
            ["git", "-C", str(root), "checkout", "HEAD", "--", chosen],
            check=True,
            capture_output=True,
            text=True,
            timeout=240,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return (root / chosen).exists()


def _ensure_china_textbook_repo(root: Path) -> bool:
    if (root / ".git").exists():
        return True
    if root.exists() and any(root.iterdir()):
        return False
    try:
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "https://github.com/TapXWorld/ChinaTextbook.git",
                str(root),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return (root / ".git").exists()


def _china_textbook_pdf_paths(root: Path, glob_pattern: str) -> list[str]:
    paths = _git_textbook_paths(root, ["ls-files", "-z"])
    if not paths:
        paths = _git_textbook_paths(root, ["ls-tree", "-r", "-z", "--name-only", "HEAD"])
    return [
        path
        for path in paths
        if path.endswith(".pdf")
        and "_merge_folder/" not in path
        and PurePosixPath(path).match(glob_pattern)
    ]


def _git_textbook_paths(root: Path, args: list[str]) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    return [path.decode("utf-8", errors="ignore") for path in completed.stdout.split(b"\0") if path]


def _china_textbook_path_score(path: str, *, title: str, subject: str, instruction: str) -> int:
    score = 0
    for term in _textbook_path_terms(title, subject, instruction):
        if term and term in path:
            score += max(2, len(term))
    if "人教版" in path or "人民教育出版社" in path:
        score += 6
    if "必修 第二册" in path and any(marker in instruction for marker in ("必修2", "必修 2", "必修二", "必修第二", "必修 第二")):
        score += 20
    if "必修 第一册" in path and any(marker in instruction for marker in ("必修1", "必修 1", "必修一", "必修第一", "必修 第一")):
        score += 20
    if any(marker in instruction for marker in ("静电感应", "静电", "电荷", "电场")) and "必修 第三册" in path:
        score += 35
    if any(marker in instruction for marker in ("电磁场", "电场", "磁场", "电磁")) and "选择性必修 第二册" in path:
        score += 30
    if any(marker in instruction for marker in ("电磁感应", "交流电", "传感器")) and "选择性必修 第三册" in path:
        score += 30
    return score


def _textbook_path_terms(title: str, subject: str, instruction: str) -> list[str]:
    terms = [subject]
    terms.extend(term for term in ("小学", "初中", "高中", "必修", "选择性必修", "人教版") if term in instruction)
    clean_title = re.sub(r"^(什么是|为什么|如何|怎样)", "", title).strip(" ？?")
    if clean_title and not _is_generic_textbook_example_title(clean_title):
        terms.append(clean_title)
    return [term for term in terms if term]


def _textbook_query_words(title: str, subject: str, instruction: str) -> list[str]:
    title = re.sub(r"^(什么是|为什么|如何|怎样)", "", title).strip(" ？?")
    words = [] if _is_generic_textbook_example_title(title) else ([title] if title else [])
    words.extend(_textbook_required_topic_terms(title, instruction))
    if "例题" in instruction or not words:
        words.append("例题")
    if "向心力" in instruction and "向心力" not in words:
        words.append("向心力")
    if "惯性" in instruction and "惯性" not in words:
        words.extend(["惯性", "牛顿第一定律"])
    if "圆周运动" in instruction and "圆周运动" not in words:
        words.append("圆周运动")
    return list(dict.fromkeys(word for word in words if word))


def _filter_textbook_hits_by_topic(hits: list[Any], title: str, instruction: str) -> list[Any]:
    required_terms = _textbook_required_topic_terms(title, instruction)
    hits = [hit for hit in hits if _textbook_hit_text_is_usable(str(getattr(hit, "excerpt", "")))]
    if _requires_complete_textbook_example(instruction):
        hits = [
            hit
            for hit in hits
            if _has_complete_textbook_solution_block(
                str(getattr(hit, "excerpt", "")),
                _textbook_solution_from_basis(title, str(getattr(hit, "excerpt", ""))),
            )
        ]
    if not required_terms:
        return hits
    return [hit for hit in hits if _textbook_topic_matches(str(getattr(hit, "excerpt", "")), required_terms)]


def _textbook_hit_text_is_usable(text: str) -> bool:
    normalized = _plain_text(text)
    if len(normalized) < 20:
        return False
    if re.search(r"[犀-犿]{2,}|[△∠槡]{2,}", normalized):
        return False
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", normalized))
    weird_count = len(re.findall(r"[^\u4e00-\u9fff0-9A-Za-z，。？！、；：,.?;:（）()《》【】\s+\-×÷=·^²³πθωΔ/]", normalized))
    return cjk_count >= 12 and weird_count <= max(8, len(normalized) // 12)


def _textbook_topic_matches(text: str, required_terms: list[str]) -> bool:
    normalized = _plain_text(text)
    return any(term in normalized for term in required_terms)


def _textbook_required_topic_terms(title: str, instruction: str) -> list[str]:
    text = f"{title}\n{instruction}"
    topic_groups = [
        (("静电感应", "感应起电"), ["静电感应", "感应起电", "静电", "导体", "自由电子", "电荷", "验电器"]),
        (("电磁场", "电磁", "电场", "磁场"), ["电磁场", "电场", "磁场", "电荷", "带电粒子", "洛伦兹力", "安培力"]),
        (("电磁感应",), ["电磁感应", "感应电流", "磁通量", "法拉第", "楞次"]),
        (("向心力", "圆周运动", "圆锥摆"), ["向心力", "圆周运动", "圆锥摆", "角速度"]),
        (("惯性", "牛顿第一定律"), ["惯性", "牛顿第一定律"]),
    ]
    for markers, terms in topic_groups:
        if any(marker in text for marker in markers):
            return terms
    return []


def _is_generic_textbook_example_title(title: str) -> bool:
    return any(marker in title for marker in ("教材例题", "课本例题", "课本上的例题", "对应的例子"))


def _textbook_glob(subject: str, level: str, instruction: str = "") -> str:
    if level == "K12":
        prefix = "**"
    elif "高中" in level:
        prefix = "高中"
    elif "初中" in level:
        prefix = "初中"
    elif "小学" in level:
        prefix = "小学"
    else:
        prefix = "**"
    subject_dir = {"生物": "生物学"}.get(subject, subject)
    if subject == "物理" and any(marker in instruction for marker in ("必修2", "必修 2", "必修二", "必修第二", "必修 第二")):
        return f"{prefix}/物理/人教版-人民教育出版社/*必修 第二册.pdf"
    if subject_dir:
        return f"{prefix}/{subject_dir}/人教版*/*.pdf"
    return f"{prefix}/**/人教版*/*.pdf"


def _video_full_question(instruction: str, source: dict[str, Any]) -> str:
    if _is_real_conical_pendulum_request(instruction):
        return _conical_pendulum_example_payload()["question"]
    if source.get("pdf"):
        basis = str(source.get("basis") or "").strip()
        if basis:
            return f"{instruction}\n\n教材依据片段：{basis[:360]}"
    return instruction


def _video_explanation_steps(script: VideoChannelScript, source_payload: dict[str, Any]) -> list[str]:
    if source_payload.get("title") == "圆锥摆运动例题":
        return list(_conical_pendulum_example_payload()["solution"])
    markdown = _video_script_markdown(script)
    section = _markdown_section(markdown, "讲解过程")
    if section:
        steps = [
            re.sub(r"^\s*(?:[-*]|\d+[.、)])\s*", "", line).strip()
            for line in section.splitlines()
            if line.strip()
        ]
        steps = [step for step in steps if step]
        if steps:
            return steps[:6]
    title = str(source_payload.get("title") or script.title or "这个知识点")
    voiceover = _plain_text(script.voiceover)
    summary = voiceover[:120].strip(" ，。") if voiceover else f"围绕{title}进行讲解。"
    return [
        f"先明确任务：讲清楚“{title}”。",
        f"再给出核心解释：{summary}。",
        "然后通过例子、画面或类比帮助理解。",
        "最后指出常见误区，并保留资料来源和人工复核提示。",
    ]


def _markdown_section(markdown: str, title: str) -> str:
    pattern = rf"###\s*{re.escape(title)}\s*\n+(.*?)(?=\n###\s+|\Z)"
    match = re.search(pattern, markdown, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def _title_from_instruction(instruction: str) -> str:
    generic_example = _generic_textbook_example_title(instruction)
    if generic_example:
        return generic_example
    patterns = [
        r"主题[:：]\s*([^。\n，,]+)",
        r"知识点[:：]\s*([^。\n，,]+)",
        r"例题[:：]\s*([^。\n，,]+)",
        r"(?:找一个|生成一个|讲一个|关于)(?:人教版|高中|初中|小学|物理|数学|化学|生物|必修|的|小)*([^，。:：\n]+?)知识点",
        r"生成一个[^：:]*[:：]\s*([^。\n，,]+)",
        r"(什么是[^。\n，,]+)",
        r"(为什么[^。\n，,]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, instruction)
        if match:
            return match.group(1).strip()[:30]
    if "圆锥摆" in instruction and not _mentions_conical_as_reference(instruction):
        return "圆锥摆运动"
    if "向心力" in instruction:
        return "什么是向心力"
    return instruction.strip().splitlines()[0][:30] or "题目解析"


def _generic_textbook_example_title(instruction: str) -> str:
    if "例题" not in instruction and "例子" not in instruction:
        return ""
    if not any(marker in instruction for marker in ("教材", "课本", "教科书", "ChinaTextbook", "TapXWorld")):
        return ""
    subject = _subject_from_instruction(instruction)
    level = _level_from_instruction(instruction)
    topic = _requested_textbook_topic(instruction)
    if level == "K12":
        return f"{subject}{topic}教材例题" if topic else f"{subject}教材例题"
    return f"{level}{subject}{topic}教材例题" if topic else f"{level}{subject}教材例题"


def _requested_textbook_topic(instruction: str) -> str:
    for topic in ("静电感应", "感应起电", "电磁场", "电磁感应", "电场", "磁场", "圆锥摆", "圆周运动", "向心力", "惯性", "牛顿第一定律"):
        if topic in instruction:
            return topic
    match = re.search(r"找一个([^，。:：\n]{1,18})的例题", instruction)
    if match:
        topic = match.group(1).strip()
        topic = re.sub(r"^(?:高中|初中|小学|物理|数学|化学|生物|教材|课本|教科书)+", "", topic).strip()
        if topic:
            return topic[:12]
    return ""


def _subject_from_instruction(instruction: str) -> str:
    for subject in ("数学", "物理", "化学", "生物", "地理", "历史", "语文", "英语", "政治"):
        if subject in instruction:
            return subject
    physics_terms = (
        "力",
        "惯性",
        "运动",
        "速度",
        "圆周",
        "静电",
        "静电感应",
        "感应起电",
        "电荷",
        "电场",
        "磁场",
        "电磁",
        "电势",
        "电流",
        "电压",
        "导体",
        "验电器",
        "自由电子",
    )
    return "物理" if any(word in instruction for word in physics_terms) else "数学"


def _level_from_instruction(instruction: str) -> str:
    if any(word in instruction for word in ("小学初高中", "小初高", "中小学", "K12", "k12")):
        return "K12"
    for level in ("小学", "初中", "高中"):
        if level in instruction:
            return level
    return "高中" if any(word in instruction for word in ("必修", "高一", "高二", "高三")) else "K12"


def _review_gate_text(state: HotspotState) -> str:
    flags = state.get("review_flags") or state.get("quality_flags") or []
    lines = ["文章已生成，但当前 workflow 标记为需要人工审核，暂不直接返回可发布正文。", "", "审核项："]
    lines.extend(f"- {flag}" for flag in flags)
    return "\n".join(lines)


def _review_gate_html(state: HotspotState) -> str:
    flags = state.get("review_flags") or state.get("quality_flags") or []
    items = "".join(f"<li>{escape(str(flag))}</li>" for flag in flags) or "<li>需要人工确认。</li>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>需要人工审核</title></head>
<body style="font:16px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; padding:32px;">
  <h1>文章需要人工审核</h1>
  <p>文章已生成，但当前 workflow 标记为需要人工审核，暂不直接返回可发布正文。</p>
  <ul>{items}</ul>
</body>
</html>"""


def _image_prompt_from_text(value: str) -> str:
    text = _plain_text(value)
    if not text:
        return ""

    prompt_match = re.search(r"(?:AIGC\s*)?提示词[：:]\s*(.+)", text, flags=re.IGNORECASE)
    if prompt_match:
        return _temporary_image_generation_prompt(prompt_match.group(1))

    card_match = re.search(r"配图建议[：:]\s*(.+?)(?:\n\s*\n|###|$)", text, flags=re.DOTALL)
    if card_match:
        return _temporary_image_generation_prompt(card_match.group(1))

    section_match = re.search(r"###\s*配图建议\s*(.+?)(?:###|$)", text, flags=re.DOTALL)
    if section_match:
        return _temporary_image_generation_prompt(section_match.group(1))

    return _temporary_image_generation_prompt(text)


def _temporary_image_generation_prompt(suggestion: str) -> str:
    """Temporary image skill: turn article image suggestions into generation-ready prompts."""
    core = _clip_image_prompt(suggestion, limit=220)
    if not core:
        return ""
    return _clip_image_prompt(
        "临时图片生成 skill：为 AI 知识型微信公众号重绘原创配图。"
        f"严格依据这条配图建议生成：{core}。"
        "画面要直接表达建议里的主题、对象和结构；优先使用信息图、流程图、决策树、概念插画或科技封面构图。"
        "文字要求：如果画面必须出现文字，只能使用清晰、可读、语义正确的简体中文；优先使用 3-6 个大号中文标签词。"
        "即使配图建议里有英文术语、缩写或代码词，也要翻译成简体中文标签，不要直接把英文画进图里。"
        "风格：清晰、干净、科技蓝、少量绿色点缀，适合公众号正文阅读。"
        "限制：不要公司 Logo、不要真实截图、不要仿原图排版、不要密集小字、不要英文单词、不要英文字母、不要繁体字、不要拼音、不要伪中文、不要乱码字母、不要无意义符号、不要版权角色或水印。"
    )


def _image_negative_prompt() -> str:
    return (
        "英文单词, 英文字母, 繁体字, 拼音, 乱码文字, 伪中文, 假汉字, pseudo text, "
        "English words, Latin letters, gibberish letters, misspelled words, random symbols, "
        "unreadable text, tiny text, dense text, watermark, logo, blurry text"
    )


def _plain_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>|</li\s*>|</h[1-6]\s*>|</section\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _clip_image_prompt(value: str, limit: int = 500) -> str:
    prompt = " ".join(value.split())
    if len(prompt) <= limit:
        return prompt
    return prompt[:limit].rstrip()


def _image_urls_from_output(output: str) -> list[str]:
    urls = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        path = Path(stripped)
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            urls.append(f"/workflow/generated/images/{path.name}")
    return urls


def _clean_subprocess_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        output = (exc.stderr or exc.stdout or str(exc)).strip()
        return output[-500:] if output else str(exc)
    return str(exc)


def _is_reference_image_too_small_error(message: str) -> bool:
    lowered = message.lower()
    return "resolution must be at least" in lowered and "240x240" in lowered


def _without_reference_image_args(command: list[str]) -> list[str]:
    result: list[str] = []
    skip_next = False
    for item in command:
        if skip_next:
            skip_next = False
            continue
        if item == "--reference-image":
            skip_next = True
            continue
        result.append(item)
    return result


def _source_image_urls_for_selection(state: HotspotState, content_id: str) -> list[str]:
    contents = {content.content_id: content for content in state.get("normalized_contents", [])}
    content = contents.get(content_id)
    if content is None:
        return []
    return _source_image_urls(_enrich_content_detail(content).raw_payload)


def _source_image_urls(payload: Any) -> list[str]:
    urls: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"cover", "cover_url", "thumb_url", "image", "image_url", "pic_url"} and isinstance(item, str):
                    urls.append(item)
                elif key in {"image_urls", "media_urls"} and isinstance(item, list):
                    urls.extend(str(url) for url in item)
                elif isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    result: list[str] = []
    for url in urls:
        normalized = str(url).strip()
        if normalized.startswith("//"):
            normalized = "https:" + normalized
        if normalized.startswith("http://") and "qpic.cn" in normalized:
            normalized = "https://" + normalized.removeprefix("http://")
        if normalized.startswith(("http://", "https://")) and normalized not in result:
            result.append(normalized)
    return result[:12]


def _augment_content_with_image_text(content: NormalizedContent) -> tuple[NormalizedContent, dict[str, Any]]:
    image_urls = _source_image_urls(content.raw_payload)
    evidence: dict[str, Any] = {
        "status": "no_images" if not image_urls else "skipped",
        "image_count": len(image_urls),
        "processed_image_count": 0,
        "items": [],
        "text": "",
        "message": "原文没有图片，无需 OCR。",
    }
    if not image_urls:
        return content, evidence
    if not _image_ocr_enabled():
        evidence["message"] = "未配置视觉 OCR，已跳过图片文字提取。"
        return content, evidence

    max_images = max(1, int(os.getenv("WECHAT_IMAGE_OCR_MAX_IMAGES", "3")))
    items: list[dict[str, Any]] = []
    for index, image_url in enumerate(image_urls[:max_images], start=1):
        text, error = _extract_image_text_with_qwen(image_url, title=content.title)
        item = {"index": index, "image_url": image_url, "text": text, "error": error}
        items.append(item)

    extracted = [item["text"].strip() for item in items if item.get("text")]
    evidence.update(
        {
            "status": "extracted" if extracted else "empty",
            "processed_image_count": len(items),
            "items": items,
            "text": "\n\n".join(extracted),
            "message": (
                f"已从 {len(extracted)} / {len(items)} 张图片提取文字。"
                if extracted
                else f"已检查 {len(items)} 张图片，未提取到可用文字。"
            ),
        }
    )
    if not extracted:
        return content, evidence

    appended_text = (
        f"{content.text or ''}\n\n"
        "【图片文字 OCR 补充证据】\n"
        + "\n\n".join(f"- 图片 {item['index']}：{item['text'].strip()}" for item in items if item.get("text"))
    ).strip()
    raw_payload = dict(content.raw_payload or {})
    raw_payload["image_text_evidence"] = evidence
    return replace(content, text=appended_text, raw_payload=raw_payload), evidence


def _image_ocr_enabled() -> bool:
    if os.getenv("WECHAT_IMAGE_OCR_ENABLED", "1").lower() in {"0", "false", "no"}:
        return False
    api_key = os.getenv("QWEN_VISION_API_KEY") or os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    return bool(api_key and not api_key.startswith("your_"))


def _extract_image_text_with_qwen(image_url: str, *, title: str) -> tuple[str, str | None]:
    api_key = os.getenv("QWEN_VISION_API_KEY") or os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        return "", "missing QWEN_VISION_API_KEY/QWEN_API_KEY/DASHSCOPE_API_KEY"
    base_url = os.getenv("QWEN_VISION_BASE_URL", os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")).rstrip("/") + "/"
    model = os.getenv("QWEN_VISION_MODEL", "qwen-vl-max-latest")
    timeout = int(os.getenv("QWEN_VISION_TIMEOUT_SECONDS", "60"))
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "请只提取这张微信公众号文章图片里的可见中文/英文文字。"
                            f"文章标题：{title}。"
                            "如果没有文字，输出空字符串；不要解释，不要编造。"
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    }
    request = Request(
        urljoin(base_url, "chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
        data = json.loads(body)
        choices = data.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content")
        if isinstance(content, list):
            text = "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
        else:
            text = str(content or "")
        text = text.strip().strip('"').strip()
        if text in {"空字符串", "无", "没有文字", "无文字"}:
            text = ""
        return text[:2000], None
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return "", f"HTTP {exc.code}: {detail[:200]}"
    except (TimeoutError, URLError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return "", str(exc)[:200]


def _cached_workflow_state(*, refresh: bool, cache_only: bool = False) -> HotspotState | None:
    now = datetime.now(timezone.utc)
    expires_at = _WORKFLOW_CACHE.get("expires_at")
    cached = _WORKFLOW_CACHE.get("state")
    if not refresh and cached is not None and isinstance(expires_at, datetime) and expires_at > now:
        state = _sanitize_rewrite_candidate_state(cached)
        _WORKFLOW_CACHE["state"] = state
        return state
    if not refresh:
        cached = _load_workflow_state_cache(now=now, allow_expired=cache_only)
        if cached is not None:
            return cached
    if cache_only:
        return None
    state = _sanitize_rewrite_candidate_state(_build_rewrite_candidate_state())
    _WORKFLOW_CACHE["state"] = state
    _WORKFLOW_CACHE["expires_at"] = now + _WORKFLOW_CACHE_TTL
    _WORKFLOW_CACHE["cached_at"] = now
    _save_workflow_state_cache(state, expires_at=now + _WORKFLOW_CACHE_TTL, cached_at=now)
    return state


def _build_rewrite_candidate_state() -> HotspotState:
    if os.getenv("WECHAT_REWRITE_CANDIDATES_FROM_SUBSCRIPTIONS", "1").lower() in {"1", "true", "yes"}:
        state = _build_rewrite_candidate_state_from_subscriptions()
        if state is not None:
            return state
    return build_rewrite_candidate_workflow().invoke({})


def _build_rewrite_candidate_state_from_subscriptions() -> HotspotState | None:
    client = WechatDownloadApiClient.from_env()
    if client is None:
        return None
    try:
        account_limit = int(os.getenv("WECHAT_REWRITE_SUBSCRIPTION_ACCOUNT_LIMIT", "0"))
        page_size = int(os.getenv("WECHAT_REWRITE_SUBSCRIPTION_PAGE_SIZE", "5"))
        articles_per_account = int(os.getenv("WECHAT_REWRITE_ARTICLES_PER_ACCOUNT", "3"))
        article_keywords = _wechat_article_match_keywords()
        minimum_candidates = int(os.getenv("WECHAT_REWRITE_MIN_CANDIDATES_BEFORE_FALLBACK", "20"))
        max_age_days = 2
        raw_contents = client.fetch_subscription_articles(
            account_limit=account_limit,
            page_size=page_size,
            article_keywords=article_keywords,
            max_age_days=max_age_days,
            articles_per_account=articles_per_account,
        )
        if len(raw_contents) < minimum_candidates:
            max_age_days = int(os.getenv("WECHAT_REWRITE_FALLBACK_MAX_AGE_DAYS", "4"))
            raw_contents = client.fetch_subscription_articles(
                account_limit=account_limit,
                page_size=page_size,
                article_keywords=article_keywords,
                max_age_days=max_age_days,
                articles_per_account=articles_per_account,
            )
    except RuntimeError as exc:
        return {
            "raw_contents": [],
            "normalized_contents": [],
            "hotness_scores": [],
            "quality_flags": [f"fetch_failed:wechat:subscription_articles:{exc}"],
            "quality_info": [],
            "review_flags": [f"fetch_failed:wechat:subscription_articles:{exc}"],
            "human_review_required": True,
        }
    if not raw_contents:
        return None

    state: HotspotState = {
        "raw_contents": raw_contents,
        "quality_flags": [f"wechat_subscription_articles:{len(raw_contents)}"],
        "quality_info": ["rewrite_candidates_source:subscriptions", f"rewrite_candidates_max_age_days:{max_age_days}"],
    }
    for agent in (NormalizationAgent(), AIRelevanceAgent(), HotnessScoringAgent(), TrendAnalysisAgent(), QualityControlAgent()):
        state.update(agent.invoke(state))
    return _sanitize_rewrite_candidate_state(state)


def _sanitize_rewrite_candidate_state(state: HotspotState) -> HotspotState:
    contents = list(state.get("normalized_contents", []))
    if not contents:
        return state
    kept_contents: list[NormalizedContent] = []
    removed = 0
    for content in contents:
        if content.platform == Platform.WECHAT and content.media_type == MediaType.ARTICLE and not _is_valid_wechat_candidate(content):
            removed += 1
            continue
        kept_contents.append(content)
    if removed <= 0:
        return state
    kept_ids = {content.content_id for content in kept_contents}
    quality_info = list(state.get("quality_info", []))
    quality_info.append(f"rewrite_candidates_filtered_by_policy:{removed}")
    return {
        **state,
        "normalized_contents": kept_contents,
        "hotness_scores": [score for score in state.get("hotness_scores", []) if score.content_id in kept_ids],
        "quality_info": sorted(set(quality_info)),
    }


def _wechat_article_match_keywords() -> list[str]:
    configured = [item.strip() for item in os.getenv("WECHAT_ARTICLE_MATCH_KEYWORDS", "").split(",") if item.strip()]
    keywords = configured or DEFAULT_ACCOUNT_KEYWORDS
    deduped: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        lowered = keyword.lower()
        if lowered not in seen:
            deduped.append(keyword)
            seen.add(lowered)
    return deduped


def _save_workflow_state_cache(state: HotspotState, *, expires_at: datetime, cached_at: datetime | None = None) -> None:
    try:
        cached_at = cached_at or datetime.now(timezone.utc)
        WORKFLOW_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "cached_at": cached_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "state": jsonable_encoder(
                {
                    "normalized_contents": state.get("normalized_contents", []),
                    "hotness_scores": state.get("hotness_scores", []),
                    "quality_flags": state.get("quality_flags", []),
                    "quality_info": state.get("quality_info", []),
                    "review_flags": state.get("review_flags", []),
                    "human_review_required": state.get("human_review_required", False),
                }
            ),
        }
        WORKFLOW_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"Failed to write workflow cache: {exc}", flush=True)


def _delete_previous_wechat_download_cache(*, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    article_list_deleted = 0
    if ARTICLE_LIST_CACHE_DIR.exists():
        for path in ARTICLE_LIST_CACHE_DIR.glob("*.json"):
            cached_at = _cached_at_from_json_file(path)
            if cached_at is None or cached_at.date() < today:
                if _delete_cache_file(path):
                    article_list_deleted += 1

    article_detail_deleted = 0
    if ARTICLE_DETAIL_CACHE_DIR.exists():
        for path in ARTICLE_DETAIL_CACHE_DIR.glob("*.json"):
            cached_at = _cached_at_from_json_file(path)
            if cached_at is None or cached_at.date() < today:
                if _delete_cache_file(path):
                    article_detail_deleted += 1

    workflow_cache_deleted = 0
    cached_at = _cached_at_from_json_file(WORKFLOW_CACHE_FILE)
    if cached_at is None or cached_at.date() < today:
        if _delete_cache_file(WORKFLOW_CACHE_FILE):
            workflow_cache_deleted += 1
    _WORKFLOW_CACHE["state"] = None
    _WORKFLOW_CACHE["expires_at"] = None
    _WORKFLOW_CACHE["cached_at"] = None
    return {
        "article_list_cache_deleted": article_list_deleted,
        "article_detail_cache_deleted": article_detail_deleted,
        "workflow_cache_deleted": workflow_cache_deleted,
    }


def _cached_at_from_json_file(path: Path) -> datetime | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return _parse_cached_datetime(payload.get("cached_at"))


def _delete_cache_file(path: Path) -> bool:
    try:
        if not path.exists():
            return False
        path.unlink()
        return True
    except OSError:
        return False


def _format_elapsed(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, rest_seconds = divmod(total_seconds, 60)
    if minutes <= 0:
        return f"{rest_seconds}秒"
    return f"{minutes}分{rest_seconds:02d}秒"


def _load_workflow_state_cache(*, now: datetime | None = None, allow_expired: bool = False) -> HotspotState | None:
    now = now or datetime.now(timezone.utc)
    try:
        payload = json.loads(WORKFLOW_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    try:
        expires_at = _parse_cached_datetime(payload.get("expires_at"))
        cached_at = _parse_cached_datetime(payload.get("cached_at"))
        if expires_at is None:
            return None
        if expires_at <= now and not allow_expired:
            return None
        state_payload = payload["state"]
        quality_flags = list(state_payload.get("quality_flags", []))
        quality_info = list(state_payload.get("quality_info", []))
        quality_info.extend(flag for flag in quality_flags if str(flag).startswith("wechat_accounts_discovered:"))
        quality_flags = [flag for flag in quality_flags if not str(flag).startswith("wechat_accounts_discovered:")]
        review_flags = list(state_payload.get("review_flags", [])) or _review_flags_from_quality_flags(quality_flags)
        state: HotspotState = {
            "normalized_contents": [_normalized_content_from_cache(item) for item in state_payload.get("normalized_contents", [])],
            "hotness_scores": [HotnessScore(**item) for item in state_payload.get("hotness_scores", [])],
            "quality_flags": quality_flags,
            "quality_info": sorted(set(quality_info)),
            "review_flags": review_flags,
            "human_review_required": bool(review_flags),
        }
        state = _sanitize_rewrite_candidate_state(state)
    except (KeyError, TypeError, ValueError):
        return None

    _WORKFLOW_CACHE["state"] = state
    _WORKFLOW_CACHE["expires_at"] = expires_at
    _WORKFLOW_CACHE["cached_at"] = cached_at
    return state


def _normalized_content_from_cache(item: dict[str, Any]) -> NormalizedContent:
    metrics = item.get("metrics") or {}
    return NormalizedContent(
        platform=Platform(item["platform"]),
        content_id=str(item["content_id"]),
        author=item.get("author"),
        title=str(item["title"]),
        text=str(item.get("text") or ""),
        media_type=MediaType(item["media_type"]),
        published_at=_parse_cached_datetime(item.get("published_at")),
        metrics=EngagementMetrics(**metrics),
        url=item.get("url"),
        source_api=str(item.get("source_api") or ""),
        raw_payload=item.get("raw_payload") or {},
    )


def _parse_cached_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _isoformat_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _workflow_cache_status() -> dict[str, Any]:
    cached_at = _WORKFLOW_CACHE.get("cached_at")
    expires_at = _WORKFLOW_CACHE.get("expires_at")
    return {
        "source": "workflow_rewrite_state",
        "cached_at": _isoformat_datetime(cached_at if isinstance(cached_at, datetime) else None),
        "expires_at": _isoformat_datetime(expires_at if isinstance(expires_at, datetime) else None),
        "file": str(WORKFLOW_CACHE_FILE),
        "has_memory_cache": _WORKFLOW_CACHE.get("state") is not None,
    }


def _review_flags_from_quality_flags(quality_flags: list[str]) -> list[str]:
    review_prefixes = (
        "missing_client:",
        "fetch_failed:",
        "wechat_download_unavailable:",
        "wechat_account_discovery_failed:",
        "wechat_account_subscribe_failed:",
        "low_ai_relevance_confidence",
        "no_trend_detected",
        "duplicate_title:",
    )
    return sorted({flag for flag in quality_flags if str(flag).startswith(review_prefixes)})


def _rewrite_candidates(state: HotspotState, limit: int = 20) -> list[dict[str, Any]]:
    contents = {content.content_id: content for content in state.get("normalized_contents", [])}
    rows_by_id: dict[str, dict[str, Any]] = {}
    scores = state.get("hotness_scores", [])
    for score in scores:
        content = contents.get(score.content_id)
        if content is None or not _is_valid_wechat_candidate(content):
            continue
        rows_by_id[content.content_id] = _candidate_row(content, score.hotness_score, rank=0, total=limit)

    fallback_contents = [
        content
        for content in state.get("normalized_contents", [])
        if _is_valid_wechat_candidate(content) and content.content_id not in rows_by_id
    ]
    fallback_contents.sort(key=_content_recency_timestamp, reverse=True)
    for content in fallback_contents:
        rows_by_id[content.content_id] = _candidate_row(content, _fallback_candidate_score(content), rank=0, total=limit)
    rows = list(rows_by_id.values())
    rows.sort(
        key=lambda item: (
            float(item.get("ai_hot_score") or 0),
            1 if item.get("readiness") == "ready" else 0,
            float(item.get("hotness_score") or 0),
            int(item.get("reads") or 0),
        ),
        reverse=True,
    )
    rows = rows[:limit]
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        row["light"] = _candidate_light(index, limit, float(row.get("ai_hot_score") or row.get("hotness_score") or 0))
    return rows


def _wechat_article_feed(state: HotspotState, limit: int = 50) -> list[dict[str, Any]]:
    rows = [
        _candidate_row(content, _score_for_content(state, content.content_id), rank=0, total=limit)
        for content in state.get("normalized_contents", [])
        if _is_valid_wechat_candidate(content)
    ]
    rows.sort(key=lambda item: (float(item.get("published_timestamp") or 0), int(item.get("reads") or 0)), reverse=True)
    rows = rows[: max(1, limit)]
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        row["source"] = "wechat-subscription-feed"
        row["feed_reason"] = "按发布时间倒序浏览订阅号文章，不参与改写候选排序。"
    return rows


def _knowledge_first_candidates(state: HotspotState, limit: int = 20) -> list[dict[str, Any]]:
    rows = _rewrite_candidates(state, limit=max(limit, 100))
    rows.sort(key=_knowledge_first_sort_key, reverse=True)
    rows = rows[: max(1, limit)]
    for index, row in enumerate(rows, start=1):
        knowledge_score = float(row.get("knowledge_content_score") or 0)
        row["rank"] = index
        row["knowledge_rank"] = index
        row["source"] = "knowledge-first"
        row["knowledge_badge"] = _knowledge_badge(row)
        row["knowledge_reason"] = _knowledge_reason(row)
        row["light"] = _candidate_light(index, limit, knowledge_score)
    return rows


def _knowledge_first_sort_key(item: dict[str, Any]) -> tuple[float, float, int, float, float]:
    return (
        float(item.get("knowledge_content_score") or 0),
        float(item.get("knowledge_score") or 0),
        1 if item.get("detail_status") in {"ready", "short"} else 0,
        float(item.get("ai_relevance_score") or 0),
        float(item.get("published_timestamp") or 0),
    )


def _knowledge_badge(item: dict[str, Any]) -> str:
    marketing_signals = item.get("marketing_signals") if isinstance(item.get("marketing_signals"), list) else []
    if marketing_signals:
        return "营销风险"
    content_type = str(item.get("knowledge_content_type") or "知识型")
    score = float(item.get("knowledge_content_score") or 0)
    if score >= 70:
        return f"优质{content_type}"
    if score >= 45:
        return content_type
    return "知识候选"


def _knowledge_reason(item: dict[str, Any]) -> str:
    signals = item.get("knowledge_signals") if isinstance(item.get("knowledge_signals"), list) else []
    structures = item.get("structure_signals") if isinstance(item.get("structure_signals"), list) else []
    marketing = item.get("marketing_signals") if isinstance(item.get("marketing_signals"), list) else []
    parts = []
    if signals:
        parts.append("知识信号：" + " / ".join(str(value) for value in signals[:4]))
    if structures:
        parts.append("结构：" + " / ".join(str(value) for value in structures[:3]))
    if marketing:
        parts.append("营销风险：" + " / ".join(str(value) for value in marketing[:3]))
    return "；".join(parts) or "标题和摘要暂未命中明显知识结构，建议查看详情确认。"


def _wechat_10w_hot_candidates(state: HotspotState, limit: int = 20) -> list[dict[str, Any]]:
    rows = _rewrite_candidates(state, limit=max(limit, 100))
    rows.sort(key=_wechat_10w_hot_sort_key, reverse=True)
    rows = rows[: max(1, limit)]
    for index, row in enumerate(rows, start=1):
        reads = _int_or_none(row.get("reads"))
        hot_score = float(row.get("ai_hot_score") or row.get("hotness_score") or 0)
        row["rank"] = index
        row["hot_rank"] = index
        row["source"] = "wechat-10w-hot"
        row["hot_badge"] = _wechat_10w_hot_badge(reads, hot_score)
        row["hot_reason"] = _wechat_10w_hot_reason(reads, hot_score)
        row["light"] = _candidate_light(index, limit, hot_score)
    return rows


def _wechat_10w_hot_sort_key(item: dict[str, Any]) -> tuple[int, int, float, float]:
    reads = _int_or_none(item.get("reads"))
    has_reads = 1 if reads is not None else 0
    return (
        has_reads,
        reads or 0,
        float(item.get("ai_hot_score") or 0),
        float(item.get("hotness_score") or 0),
    )


def _wechat_10w_hot_badge(reads: int | None, hot_score: float) -> str:
    if reads is not None and reads >= 100000:
        return "10w+"
    if reads is not None and reads >= 50000:
        return "准10w"
    if reads is not None:
        return "本地热文"
    if hot_score >= 70:
        return "AI热榜"
    return "候选热文"


def _wechat_10w_hot_reason(reads: int | None, hot_score: float) -> str:
    if reads is not None:
        return f"按阅读量 {reads} 和 AI 热度 {hot_score:.1f} 排序。"
    return "当前 wechat-download-api 未返回阅读量，按 AI 热度和本地热度排序。"


def _is_valid_wechat_candidate(content: NormalizedContent) -> bool:
    if content.platform != Platform.WECHAT or content.media_type != MediaType.ARTICLE:
        return False
    if not _has_usable_article_title(content.title):
        return False
    if _title_matches_wechat_account_name(content):
        return False
    if _looks_like_marketing_wechat_article(content):
        return False
    if _looks_like_hollow_wechat_article(content):
        return False
    account = content.raw_payload.get("account") if isinstance(content.raw_payload.get("account"), dict) else {}
    fakeid = str(account.get("fakeid") or "")
    nickname = str(account.get("nickname") or content.author or "")
    if fakeid and not _looks_like_wechat_fakeid(fakeid):
        return False
    if nickname and _is_excluded_account_name(nickname):
        return False
    return True


def _has_usable_article_title(title: str | None) -> bool:
    cleaned = _plain_text(str(title or "")).strip(" \t\r\n-—_｜|：:，,。.")
    if not cleaned:
        return False
    normalized = re.sub(r"\s+", "", cleaned).lower()
    return normalized not in {value.lower() for value in CANDIDATE_PLACEHOLDER_TITLES}


def _compact_wechat_title_key(value: str | None) -> str:
    cleaned = _plain_text(str(value or "")).strip(" \t\r\n-—_｜|：:，,。.")
    return re.sub(r"[\W_]+", "", cleaned, flags=re.UNICODE).lower()


def _title_matches_wechat_account_name(content: NormalizedContent) -> bool:
    title_key = _compact_wechat_title_key(content.title)
    if not title_key:
        return False
    account = content.raw_payload.get("account") if isinstance(content.raw_payload.get("account"), dict) else {}
    candidate_names = [
        content.author,
        account.get("nickname"),
        account.get("wechat_name"),
        account.get("name"),
    ]
    return any(title_key == _compact_wechat_title_key(str(name)) for name in candidate_names if name)


def _looks_like_marketing_wechat_article(content: NormalizedContent) -> bool:
    source = f"{content.title or ''}\n{content.text or ''}".lower()
    return bool(_matched_keywords(source, KNOWLEDGE_MARKETING_KEYWORDS))


def _looks_like_hollow_wechat_article(content: NormalizedContent) -> bool:
    title = _plain_text(str(content.title or ""))
    text = _plain_text(str(content.text or ""))
    source = f"{title}\n{text}".lower()
    hollow_signals = _matched_keywords(source, HOLLOW_ARTICLE_KEYWORDS)
    if not hollow_signals:
        return False
    concrete_signals = _matched_keywords(source, KNOWLEDGE_SIGNAL_KEYWORDS) + _matched_keywords(source, KNOWLEDGE_STRUCTURE_KEYWORDS)
    if concrete_signals:
        return False
    title_hollow_signals = _matched_keywords(title.lower(), HOLLOW_ARTICLE_KEYWORDS)
    if len(title_hollow_signals) >= 2:
        return True
    return len(hollow_signals) >= 3 and _plain_text_length(text) < 600


def _candidate_row(content: NormalizedContent, hotness_score: float, *, rank: int, total: int) -> dict[str, Any]:
    metrics = content.metrics
    reads = metrics.reads if metrics.reads is not None else metrics.views
    image_count = len(_source_image_urls(content.raw_payload))
    readiness, readiness_label, readiness_detail = _candidate_readiness(content)
    text_length = len((content.text or "").strip())
    ai_signals = _ai_knowledge_signals(content)
    ai_hot_score = _ai_hot_candidate_score(content, hotness_score, ai_signals, readiness)
    cache_status = _workflow_cache_status()
    return {
        "rank": rank,
        "content_id": content.content_id,
        "light": _candidate_light(rank, total, ai_hot_score),
        "title": content.title,
        "author": content.author or _author_from_payload(content.raw_payload),
        "hotness_score": round(hotness_score, 2),
        "ai_hot_score": round(ai_hot_score, 2),
        "ai_relevance_score": round(ai_signals["ai_relevance_score"], 2),
        "knowledge_score": round(ai_signals["knowledge_score"], 2),
        "knowledge_content_score": round(ai_signals["knowledge_content_score"], 2),
        "knowledge_content_type": ai_signals["knowledge_content_type"],
        "matched_keywords": ai_signals["matched_keywords"],
        "knowledge_signals": ai_signals["knowledge_signals"],
        "structure_signals": ai_signals["structure_signals"],
        "marketing_signals": ai_signals["marketing_signals"],
        "marketing_penalty": round(ai_signals["marketing_penalty"], 2),
        "published_at": _isoformat_datetime(_parse_cached_datetime(content.published_at)),
        "published_timestamp": _content_recency_timestamp(content),
        "text_length": text_length,
        "readiness": readiness,
        "readiness_label": readiness_label,
        "readiness_detail": readiness_detail,
        "detail_status": readiness,
        "detail_status_label": readiness_label,
        "detail_status_detail": readiness_detail,
        "image_count": image_count,
        "has_images": image_count > 0,
        "reads": reads,
        "read_source": "wechat-download-api" if reads is not None else "missing",
        "likes": metrics.likes,
        "comments": metrics.comments,
        "url": content.url,
        "cache_source": "workflow_rewrite_state",
        "cache_cached_at": cache_status.get("cached_at"),
        "cache_expires_at": cache_status.get("expires_at"),
    }


def _ai_knowledge_signals(content: NormalizedContent) -> dict[str, Any]:
    source = f"{content.title} {content.author or ''} {content.text or ''}".lower()
    matched_keywords = _matched_keywords(source, AI_KNOWLEDGE_KEYWORDS)
    knowledge_signals = _matched_keywords(source, KNOWLEDGE_SIGNAL_KEYWORDS)
    structure_signals = _matched_keywords(source, KNOWLEDGE_STRUCTURE_KEYWORDS)
    marketing_signals = _matched_keywords(source, KNOWLEDGE_MARKETING_KEYWORDS)
    title_source = (content.title or "").lower()
    title_ai_matches = _matched_keywords(title_source, AI_KNOWLEDGE_KEYWORDS)
    title_knowledge_matches = _matched_keywords(title_source, KNOWLEDGE_SIGNAL_KEYWORDS)
    title_structure_matches = _matched_keywords(title_source, KNOWLEDGE_STRUCTURE_KEYWORDS)
    marketing_penalty = min(35.0, len(marketing_signals) * 10.0)
    ai_relevance_score = min(40.0, len(matched_keywords) * 5.0 + len(title_ai_matches) * 6.0)
    knowledge_score = min(35.0, len(knowledge_signals) * 3.5 + len(title_knowledge_matches) * 5.0)
    structure_score = min(15.0, len(structure_signals) * 3.0 + len(title_structure_matches) * 4.0)
    freshness_score = _knowledge_freshness_score(content)
    knowledge_content_score = max(
        0.0,
        min(
            100.0,
            knowledge_score
            + min(25.0, ai_relevance_score * 0.65)
            + structure_score
            + freshness_score
            - marketing_penalty,
        ),
    )
    return {
        "matched_keywords": matched_keywords[:8],
        "knowledge_signals": knowledge_signals[:8],
        "structure_signals": structure_signals[:8],
        "marketing_signals": marketing_signals[:8],
        "ai_relevance_score": ai_relevance_score,
        "knowledge_score": knowledge_score,
        "knowledge_content_score": knowledge_content_score,
        "knowledge_content_type": _knowledge_content_type(knowledge_signals, structure_signals, title_source),
        "marketing_penalty": marketing_penalty,
    }


def _knowledge_freshness_score(content: NormalizedContent) -> float:
    published_at = _parse_cached_datetime(content.published_at)
    if published_at is None:
        return 2.0
    age_hours = max(0.0, (datetime.now(timezone.utc) - published_at.astimezone(timezone.utc)).total_seconds() / 3600.0)
    if age_hours <= 24:
        return 10.0
    if age_hours <= 72:
        return 7.0
    if age_hours <= 168:
        return 4.0
    return 1.0


def _knowledge_content_type(
    knowledge_signals: list[str],
    structure_signals: list[str],
    title_source: str,
) -> str:
    source = " ".join([title_source, *knowledge_signals, *structure_signals])
    if any(keyword in source for keyword in ("面试题", "面试总结")):
        return "面试题型"
    if any(keyword in source for keyword in ("对比", "区别", "选型", "核心区别")):
        return "对比型"
    if any(keyword in source for keyword in ("原理", "底层", "核心逻辑", "什么是", "为什么")):
        return "原理型"
    if any(keyword in source for keyword in ("教程", "指南", "入门", "进阶", "实战", "实践", "如何", "怎么做")):
        return "教程型"
    if any(keyword in source for keyword in ("案例", "复盘", "实际项目", "工程实践")):
        return "案例复盘型"
    return "知识型"


def _matched_keywords(source: str, keywords: tuple[str, ...]) -> list[str]:
    normalized = source.lower()
    return [keyword for keyword in keywords if keyword.lower() in normalized]


def _ai_hot_candidate_score(
    content: NormalizedContent,
    hotness_score: float,
    signals: dict[str, Any],
    readiness: str,
) -> float:
    metrics = content.metrics
    reads = float(metrics.reads or metrics.views or 0)
    near_100k_bonus = min(20.0, reads / 5000.0)
    engagement_bonus = min(8.0, float((metrics.likes or 0) + (metrics.comments or 0)) / 100.0)
    image_bonus = min(4.0, len(_source_image_urls(content.raw_payload)) * 1.0)
    readiness_bonus = {"ready": 8.0, "short": 2.0, "missing": -12.0}.get(readiness, -6.0)
    return max(
        0.0,
        min(
            100.0,
            float(hotness_score) * 0.35
            + float(signals["ai_relevance_score"])
            + float(signals["knowledge_score"])
            + near_100k_bonus
            + engagement_bonus
            + image_bonus
            + readiness_bonus,
        ),
    )


def _candidate_readiness(content: NormalizedContent) -> tuple[str, str, str]:
    text_length = len((content.text or "").strip())
    if text_length >= 800:
        return "ready", "全文就绪", f"缓存正文约 {text_length} 字，可直接改写"
    if text_length >= 200:
        return "short", "需补全文", f"缓存正文约 {text_length} 字，改写前会补拉全文"
    return "missing", "待补全文", "缓存正文不足，改写前会从原文链接补拉"


def _fallback_candidate_score(content: NormalizedContent) -> float:
    metrics = content.metrics
    engagement = sum(value or 0 for value in (metrics.reads, metrics.views, metrics.likes, metrics.comments))
    recency_bonus = 10.0 if _content_recency_timestamp(content) else 0.0
    return min(34.0, 12.0 + recency_bonus + min(float(engagement) / 1000, 12.0))


def _content_recency_timestamp(content: NormalizedContent) -> float:
    parsed = _parse_cached_datetime(content.published_at)
    return parsed.timestamp() if parsed is not None else 0.0


def _candidate_light(rank: int, total: int, hotness_score: float) -> str:
    if rank <= max(1, total // 3) or hotness_score >= 70:
        return "green"
    if rank <= max(2, total * 2 // 3) or hotness_score >= 35:
        return "yellow"
    return "red"


def _rewrite_selected_article(state: HotspotState, content_id: str) -> tuple[GeneratedArticle | None, dict[str, Any]]:
    contents = {content.content_id: content for content in state.get("normalized_contents", [])}
    content = contents.get(content_id)
    if content is None:
        return None, {}
    if not _is_valid_wechat_candidate(content):
        return None, {}
    content = _enrich_content_detail(content)
    if not _is_valid_wechat_candidate(content):
        return None, {}
    content, image_text_evidence = _augment_content_with_image_text(content)
    trend = TrendCluster(
        trend_id=f"selected-{content.content_id}",
        name=_selected_topic(content.title),
        summary=f"用户选择的公众号热度文章：{content.title}",
        content_ids=[content.content_id],
        platforms=[content.platform],
        hotness_score=_score_for_content(state, content.content_id),
        lifecycle="rising",
        evidence=[content.content_id],
    )
    rewrite_state: HotspotState = {
        "normalized_contents": [content],
        "hotness_scores": [score for score in state.get("hotness_scores", []) if score.content_id == content_id],
        "trends": [trend],
        "product_insights": [],
    }
    rewrite_update = WechatArticleWritingAgent().invoke(rewrite_state)
    article = rewrite_update.get("generated_article")
    review_state: HotspotState = {**rewrite_state, **rewrite_update}
    review_update = QualityControlAgent().invoke(review_state)
    return article, {
        "content_id": content.content_id,
        "title": content.title,
        "author": content.author,
        "url": content.url,
        "image_text_evidence": image_text_evidence,
        "article_compliance": rewrite_update.get("article_compliance"),
        "quality_flags": review_update.get("quality_flags", []),
        "quality_info": review_update.get("quality_info", []),
        "review_flags": review_update.get("review_flags", []),
        "human_review_required": bool(review_update.get("human_review_required")),
    }


def _state_from_candidate_snapshot(candidate: Any) -> HotspotState | None:
    if not isinstance(candidate, dict):
        return None
    content_id = str(candidate.get("content_id") or "")
    title = str(candidate.get("title") or "")
    if not content_id or not title:
        return None
    content = NormalizedContent(
        platform=Platform.WECHAT,
        content_id=content_id,
        author=candidate.get("author"),
        title=title,
        text="",
        media_type=MediaType.ARTICLE,
        published_at=None,
        metrics=EngagementMetrics(
            reads=_int_or_none(candidate.get("reads")),
            likes=_int_or_none(candidate.get("likes")),
            comments=_int_or_none(candidate.get("comments")),
        ),
        url=candidate.get("url"),
        source_api="wechat-download-api",
        raw_payload={"provider_payload": candidate},
    )
    if not _is_valid_wechat_candidate(content):
        return None
    score = HotnessScore(
        content_id=content_id,
        hotness_score=float(candidate.get("hotness_score") or 0),
        velocity_score=0.0,
        engagement_quality_score=0.0,
        platform_weight=1.0,
        reason="从页面候选快照恢复",
    )
    return {"normalized_contents": [content], "hotness_scores": [score]}


def _allow_stale_candidate_rewrite() -> bool:
    return os.getenv("WECHAT_REWRITE_ALLOW_STALE_CANDIDATE", "0").lower() in {"1", "true", "yes"}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _wechat_article_detail_payload(
    state: HotspotState,
    content_id: str,
    *,
    fetch_detail: bool,
) -> dict[str, Any] | None:
    contents = {content.content_id: content for content in state.get("normalized_contents", [])}
    content = contents.get(content_id)
    if content is None:
        return None

    base_row = _candidate_row(content, _score_for_content(state, content.content_id), rank=0, total=1)
    detail_status = {
        "status": base_row["detail_status"],
        "initial_text_length": base_row["text_length"],
        "final_text_length": base_row["text_length"],
        "message": base_row["detail_status_detail"],
    }
    enriched = content
    if fetch_detail:
        enriched, detail_status = _enrich_content_detail_with_status(content)

    text = enriched.text or ""
    images = _source_image_urls(enriched.raw_payload)
    return {
        "content_id": enriched.content_id,
        "article": {
            **base_row,
            "title": enriched.title,
            "author": enriched.author or base_row.get("author"),
            "url": enriched.url,
            "text_length": len(text.strip()),
            "image_count": len(images),
            "has_images": bool(images),
        },
        "detail_status": detail_status,
        "source_images": images,
        "text_preview": _clip_text_preview(text),
        "full_text": text if len(text) <= int(os.getenv("WECHAT_DETAIL_FULL_TEXT_MAX_CHARS", "12000")) else "",
        "full_text_truncated": len(text) > int(os.getenv("WECHAT_DETAIL_FULL_TEXT_MAX_CHARS", "12000")),
    }


def _clip_text_preview(text: str, limit: int = 1200) -> str:
    normalized = "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _enrich_content_detail(content):
    enriched, _status = _enrich_content_detail_with_status(content)
    return enriched


def _enrich_content_detail_with_status(content) -> tuple[NormalizedContent, dict[str, Any]]:
    initial_length = len((content.text or "").strip())
    if not content.url or len((content.text or "").strip()) >= 200:
        return content, {
            "status": "ready" if initial_length >= 200 else "missing_url",
            "initial_text_length": initial_length,
            "final_text_length": initial_length,
            "message": "缓存正文已足够。" if initial_length >= 200 else "候选没有原文链接，无法补拉全文。",
        }
    client = WechatDownloadApiClient.from_env()
    if client is None:
        return content, {
            "status": "missing_client",
            "initial_text_length": initial_length,
            "final_text_length": initial_length,
            "message": "未配置 wechat-download-api 客户端。",
        }
    try:
        raw_contents = client.fetch(
            SourcePlan(
                platform=Platform.WECHAT,
                dimension=ApiDimension.ARTICLE_DETAIL,
                query=content.url,
                metadata={"url": content.url},
            )
        )
    except RuntimeError as exc:
        return content, {
            "status": "fetch_failed",
            "initial_text_length": initial_length,
            "final_text_length": initial_length,
            "message": _clean_subprocess_error(exc),
        }
    if not raw_contents:
        return content, {
            "status": "empty_detail",
            "initial_text_length": initial_length,
            "final_text_length": initial_length,
            "message": "文章详情接口没有返回可用内容。",
        }
    update = NormalizationAgent().invoke({"raw_contents": raw_contents})
    details = update.get("normalized_contents", [])
    if not details:
        return content, {
            "status": "normalization_empty",
            "initial_text_length": initial_length,
            "final_text_length": initial_length,
            "message": "文章详情返回后归一化为空。",
        }
    detail = details[0]
    enriched = replace(
        content,
        title=detail.title or content.title,
        text=detail.text or content.text,
        author=detail.author or content.author,
        url=detail.url or content.url,
        raw_payload={**content.raw_payload, "detail": detail.raw_payload},
    )
    final_length = len((enriched.text or "").strip())
    return enriched, {
        "status": "ready" if final_length >= 200 else "short_after_detail",
        "initial_text_length": initial_length,
        "final_text_length": final_length,
        "message": (
            f"详情补拉成功，正文 {final_length} 字。"
            if final_length >= 200
            else f"详情接口返回后正文仍只有 {final_length} 字。"
        ),
    }


def _score_for_content(state: HotspotState, content_id: str) -> float:
    for score in state.get("hotness_scores", []):
        if score.content_id == content_id:
            return score.hotness_score
    return 0.0


def _selected_topic(title: str) -> str:
    cleaned = " ".join(str(title or "微信热点文章").split())
    if len(cleaned) <= 14:
        return cleaned
    return cleaned[:13] + "…"


def _author_from_payload(payload: dict[str, Any]) -> str:
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    return str(account.get("nickname") or payload.get("nickname") or "未知")


def _summarize_state(state: HotspotState) -> dict[str, Any]:
    return {
        "raw_content_count": len(state.get("raw_contents", [])),
        "normalized_content_count": len(state.get("normalized_contents", [])),
        "trend_count": len(state.get("trends", [])),
        "insight_count": len(state.get("product_insights", [])),
        "strategy_count": len(state.get("content_strategies", [])),
        "quality_flags": state.get("quality_flags", []),
        "quality_info": state.get("quality_info", []),
        "review_flags": state.get("review_flags", []),
        "human_review_required": bool(state.get("human_review_required")),
    }


def _rewrite_workspace_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>微信热点改写工作台</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --card: #ffffff;
      --line: #d9e2ef;
      --text: #172033;
      --muted: #667085;
      --blue: #2563eb;
      --green: #10b981;
      --yellow: #f59e0b;
      --red: #ef4444;
    }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }
    main { max-width: 1440px; margin: 0 auto; padding: 24px; }
    h1, h2, h3 { margin: 0 0 12px; }
    .steps {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 14px;
      margin: 16px 0 20px;
    }
    .step, .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
      padding: 18px;
    }
    .step strong { color: var(--blue); }
    .layout { display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 18px; align-items: start; }
    table { width: 100%; border-collapse: collapse; min-width: 820px; }
    th, td { border-bottom: 1px solid var(--line); padding: 10px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 13px; }
    .table-wrap { overflow-x: auto; }
    .light {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-weight: 700;
      white-space: nowrap;
    }
    .dot { width: 12px; height: 12px; border-radius: 999px; display: inline-block; }
    .green .dot { background: var(--green); box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.12); }
    .yellow .dot { background: var(--yellow); box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.14); }
    .red .dot { background: var(--red); box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.12); }
    button {
      border: 0;
      border-radius: 10px;
      background: var(--blue);
      color: white;
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 700;
    }
    button.secondary { background: #475467; }
    button.tertiary { background: #0f766e; }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .muted { color: var(--muted); }
    .workspace-links { display: flex; gap: 10px; flex-wrap: wrap; margin: 8px 0 18px; }
    .workspace-links a { display: inline-flex; align-items: center; text-decoration: none; border-radius: 999px; border: 1px solid var(--line); background: white; color: var(--blue); padding: 7px 12px; font-weight: 800; }
    .title-cell { max-width: 340px; }
    .article-frame {
      width: 100%;
      min-height: 720px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: white;
    }
    .actions { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
    .selected { outline: 2px solid rgba(37, 99, 235, 0.35); background: #f8fbff; }
    .row-actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .detail-card {
      border: 1px solid var(--line);
      background: #f8fbff;
      border-radius: 12px;
      padding: 12px;
      margin: 0 0 14px;
    }
    .detail-card dl { display: grid; grid-template-columns: 110px 1fr; gap: 4px 10px; margin: 8px 0; }
    .detail-card dt { color: var(--muted); }
    .detail-card dd { margin: 0; }
    .detail-preview {
      max-height: 240px;
      overflow: auto;
      white-space: pre-wrap;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      margin: 8px 0 0;
    }
    .notice {
      border-left: 4px solid var(--yellow);
      background: #fffbeb;
      margin: 0 0 20px;
    }
    .notice a {
      color: var(--blue);
      font-weight: 700;
    }
    .notice ul { margin: 8px 0 0; padding-left: 20px; }
    @media (max-width: 1000px) {
      .steps, .layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <h1>微信热点改写工作台</h1>
    <p class="muted">流程：发现 AI 知识型高热公众号文章 -> 人工选择 -> 图文 OCR 证据增强 -> 流式交给 wechat-rewrite Agent 生成可发布稿。</p>
    <div class="workspace-links">
      <a href="/workflow/video/agent" target="_blank">视频 Agent 任务入口</a>
      <a href="/workflow/video/agent/run/stream" target="_blank">视频流式处理页</a>
      <a href="/workflow/graph" target="_blank">LangGraph 流程图</a>
    </div>

    <div class="steps">
      <div class="step"><strong>1. 发现 AI 热文</strong><br>优先排序 AI 相关、知识性强、阅读接近 10w+ 的公众号文章。</div>
      <div class="step"><strong>2. 人工选择</strong><br>查看知识信号、全文状态和图片数，再选择要改写的文章。</div>
      <div class="step"><strong>3. OCR 增强改写</strong><br>原文有图片时先尝试提取图片文字，再调用微信改写 Agent。</div>
    </div>

    <section class="panel notice">
      <h2>拉取和发布前先完成微信登录</h2>
      <p>
        公众号数据来自本机 <code>wechat-download-api</code> 服务。重新拉取前，请先打开
        <a href="http://localhost:5000/login.html" target="_blank">数据拉取登录页</a>
        ，用公众号后台管理员微信扫码登录。
      </p>
      <p>
        文章改写完成后，需要人工复制到
        <a href="https://mp.weixin.qq.com/" target="_blank" rel="noopener noreferrer">微信公众号后台发布入口</a>
        进行排版预览、原创/转载声明、合规复核和发布。
      </p>
    </section>

    <div class="layout">
      <section class="panel">
        <div class="actions">
          <h2 style="margin-right:auto;">热度公众号文章</h2>
          <button id="manual-subscription-refresh-btn" onclick="manualRefreshSubscriptions()">手动更新订阅号文章</button>
          <button class="secondary" onclick="loadCandidates(true)">重新拉取</button>
          <button class="secondary" onclick="loadArticleFeed(false)">今日订阅流</button>
          <button class="secondary" onclick="loadKnowledgeCandidates(false)">知识型优先</button>
          <button class="secondary" onclick="loadHotCandidates(false)">wechat-10w-hot 高热榜</button>
        </div>
        <p id="status" class="muted">正在加载候选文章...</p>
        <p class="muted">手动更新会先删除前一天及更早的下载缓存，并在下方实时显示清理和拉取已耗时。</p>
        <ol id="refresh-progress" class="progress-list"></ol>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>灯</th><th>排名</th><th>标题</th><th>公众号</th><th>AI热度</th><th>阅读</th><th>状态/图片</th><th>操作</th>
              </tr>
            </thead>
            <tbody id="candidate-body"></tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <h2>选中文章改写结果</h2>
        <div id="article-detail" class="detail-card">
          <strong>文章详情</strong>
          <p class="muted">点击左侧“查看详情”会先补拉全文并展示预览，不会触发改写。</p>
        </div>
        <p id="rewrite-status" class="muted">请选择左侧一篇文章。</p>
        <ol id="rewrite-progress" class="progress-list"></ol>
        <p id="image-status" class="muted">生成改写稿后，每条“配图建议”旁会出现图片生成图标。</p>
        <iframe id="article-frame" class="article-frame" title="改写结果"></iframe>
      </section>
    </div>
  </main>

  <script>
    const lightLabels = { green: "绿灯", yellow: "黄灯", red: "红灯" };
    const candidatesById = new Map();
    const candidateCacheKey = "langgraph-study:rewrite:candidates:v5";
    const autoBackgroundRefresh = false;
    let currentArticleMarkdown = "";
    let currentSourceImages = [];
    let activeRewriteRequestId = 0;
    let activeManualRefreshId = 0;
    let activeRefreshTimerId = null;
    let activeRefreshTimerStartMs = 0;
    let activeRefreshTimerItem = null;
    let activeCandidateLoadTimerId = null;
    let activeCandidateLoadTimerStartMs = 0;
    let activeRewriteTimerId = null;
    let activeRewriteTimerStartMs = 0;
    let activeRewriteTimerItem = null;
    let currentCandidateMode = "candidates";
    let activeDetailRequestId = 0;

    async function loadCandidates(refresh = false) {
      const showedLocalCache = !refresh && renderCachedCandidates();
      try {
        if (showedLocalCache) {
          startCandidateLoadElapsedStatus("已先显示本地缓存候选文章，正在后台检查更新");
        } else {
          startCandidateLoadElapsedStatus(refresh ? "正在重新拉取候选文章" : "正在加载候选文章");
        }
        const data = await fetchJson(`/workflow/rewrite/candidates?refresh=${refresh ? "true" : "false"}&cache_only=${refresh ? "false" : "true"}`);
        const items = data.items || [];
        if (!refresh && !data.cached && items.length === 0) {
          stopCandidateLoadElapsedStatus();
          if (showedLocalCache) {
            setStatus("服务端暂无可用缓存，已继续显示浏览器本地缓存。点击“重新拉取”可更新公众号文章。");
            return;
          }
          setStatus("暂无服务端缓存。请点击“重新拉取”获取公众号文章。");
          return;
        }
        currentCandidateMode = "candidates";
        renderCandidates(items);
        if (items.length > 0) {
          cacheCandidates(data);
        }
        const elapsedText = formatSeconds((Date.now() - activeCandidateLoadTimerStartMs) / 1000);
        stopCandidateLoadElapsedStatus();
        setStatus(`已加载 ${items.length} 篇候选文章。${refresh ? "本次已重新拉取。" : ""}用时 ${elapsedText}。`);
        if (!refresh && autoBackgroundRefresh) {
          refreshCandidatesInBackground();
        }
      } catch (error) {
        stopCandidateLoadElapsedStatus();
        throw error;
      }
    }

    async function loadHotCandidates(refresh = false) {
      setStatus(refresh ? "正在刷新 wechat-10w-hot 高热榜..." : "正在读取 wechat-10w-hot 高热榜...");
      const data = await fetchJson(`/workflow/rewrite/hot-candidates?refresh=${refresh ? "true" : "false"}&cache_only=${refresh ? "false" : "true"}&limit=20`);
      const items = data.items || [];
      currentCandidateMode = "hot";
      renderCandidates(items);
      if (items.length > 0) {
        cacheCandidates({ ...data, items });
      }
      const note = data.summary && data.summary.hot_rank_note ? ` ${data.summary.hot_rank_note}` : "";
      setStatus(`已用 wechat-10w-hot 生成高热榜 ${items.length} 篇。${note}`);
    }

    async function loadArticleFeed(refresh = false) {
      setStatus(refresh ? "正在刷新今日订阅流..." : "正在读取今日订阅流...");
      const data = await fetchJson(`/workflow/wechat/articles?refresh=${refresh ? "true" : "false"}&cache_only=${refresh ? "false" : "true"}&limit=50`);
      const items = data.items || [];
      currentCandidateMode = "feed";
      renderCandidates(items);
      if (items.length > 0) {
        cacheCandidates({ ...data, items });
      }
      const cachedAt = data.cache && data.cache.cached_at ? ` 候选缓存：${formatDateTime(data.cache.cached_at)}。` : "";
      setStatus(`已加载今日订阅流 ${items.length} 篇，按发布时间倒序。${cachedAt}`);
    }

    async function loadKnowledgeCandidates(refresh = false) {
      setStatus(refresh ? "正在刷新知识型优先候选..." : "正在读取知识型优先候选...");
      const data = await fetchJson(`/workflow/rewrite/knowledge-candidates?refresh=${refresh ? "true" : "false"}&cache_only=${refresh ? "false" : "true"}&limit=20`);
      const items = data.items || [];
      currentCandidateMode = "knowledge";
      renderCandidates(items);
      if (items.length > 0) {
        cacheCandidates({ ...data, items });
      }
      const note = data.summary && data.summary.knowledge_rank_note ? ` ${data.summary.knowledge_rank_note}` : "";
      setStatus(`已加载知识型优先候选 ${items.length} 篇。${note}`);
    }

    async function refreshCandidatesInBackground() {
      try {
        const data = await fetchJson("/workflow/rewrite/candidates?refresh=true&cache_only=false");
        const items = data.items || [];
        if (items.length === 0) {
          const detail = data.error ? `：${data.error}` : "";
          setStatus(`已显示缓存候选文章；后台刷新暂无新候选${detail}`);
          return;
        }
        renderCandidates(items);
        cacheCandidates(data);
        setStatus(`已后台刷新 ${items.length} 篇候选文章。`);
      } catch (error) {
        setStatus(`已显示缓存候选文章；后台刷新失败：${error}`);
      }
    }

    async function manualRefreshSubscriptions() {
      const requestId = ++activeManualRefreshId;
      const button = document.getElementById("manual-subscription-refresh-btn");
      const list = document.getElementById("refresh-progress");
      button.disabled = true;
      stopRefreshElapsedProgress();
      list.innerHTML = "";
      setStatus("正在手动更新订阅号文章...");
      try {
        const response = await fetch("/workflow/rewrite/subscriptions/refresh/stream", { method: "POST" });
        const contentType = response.headers.get("content-type") || "";
        if (!response.ok) throw new Error(await response.text());
        if (!contentType.includes("application/x-ndjson")) {
          throw new Error(`接口返回非 JSON 流：${(await response.text()).slice(0, 160)}`);
        }
        if (!response.body) throw new Error("当前浏览器不支持流式读取响应");
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (true) {
          if (requestId !== activeManualRefreshId) {
            await reader.cancel();
            return;
          }
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (line.trim()) handleManualRefreshEvent(JSON.parse(line));
          }
        }
        if (buffer.trim()) handleManualRefreshEvent(JSON.parse(buffer));
      } catch (error) {
        setStatus(`手动更新订阅号文章失败：${error}`);
        stopRefreshElapsedProgress();
        appendRefreshProgress(`失败：${error}`);
      } finally {
        if (requestId === activeManualRefreshId) {
          button.disabled = false;
        }
      }
    }

    function handleManualRefreshEvent(event) {
      if (event.phase === "fetching") {
        const elapsedSeconds = Number(event.elapsed_seconds) || 0;
        const prefix = elapsedSeconds > 0
          ? "订阅号文章仍在拉取中"
          : "正在拉取订阅号文章并重建候选列表";
        updateRefreshElapsedProgress(prefix, elapsedSeconds);
        return;
      }
      stopRefreshElapsedProgress();
      if (event.message) {
        appendRefreshProgress(event.message);
        setStatus(event.message);
      }
      if (event.event === "done" && event.result) {
        const items = event.result.items || [];
        if (currentCandidateMode === "hot") {
          loadHotCandidates(false);
        } else if (currentCandidateMode === "feed") {
          loadArticleFeed(false);
        } else if (currentCandidateMode === "knowledge") {
          loadKnowledgeCandidates(false);
        } else {
          renderCandidates(items);
        }
        if (items.length > 0) cacheCandidates({ items, summary: event.result.summary || {}, cached: false });
      }
      if (event.event === "error") {
        throw new Error(event.message || "手动更新失败");
      }
    }

    function appendRefreshProgress(message) {
      const item = document.createElement("li");
      item.textContent = message;
      document.getElementById("refresh-progress").appendChild(item);
    }

    function updateRefreshElapsedProgress(prefix, elapsedSeconds) {
      if (!activeRefreshTimerItem) {
        activeRefreshTimerItem = document.createElement("li");
        document.getElementById("refresh-progress").appendChild(activeRefreshTimerItem);
      }
      activeRefreshTimerStartMs = Date.now() - Math.max(0, Number(elapsedSeconds) || 0) * 1000;
      const render = () => {
        const elapsed = (Date.now() - activeRefreshTimerStartMs) / 1000;
        const message = `${prefix}，已耗时 ${formatSeconds(elapsed)}。`;
        activeRefreshTimerItem.textContent = message;
        setStatus(message);
      };
      render();
      if (activeRefreshTimerId) {
        window.clearInterval(activeRefreshTimerId);
      }
      activeRefreshTimerId = window.setInterval(render, 500);
    }

    function stopRefreshElapsedProgress() {
      if (activeRefreshTimerId) {
        window.clearInterval(activeRefreshTimerId);
        activeRefreshTimerId = null;
      }
      activeRefreshTimerItem = null;
      activeRefreshTimerStartMs = 0;
    }

    function startCandidateLoadElapsedStatus(prefix) {
      stopCandidateLoadElapsedStatus();
      activeCandidateLoadTimerStartMs = Date.now();
      const render = () => {
        const elapsed = (Date.now() - activeCandidateLoadTimerStartMs) / 1000;
        setStatus(`${prefix}，已耗时 ${formatSeconds(elapsed)}。`);
      };
      render();
      activeCandidateLoadTimerId = window.setInterval(render, 500);
    }

    function stopCandidateLoadElapsedStatus() {
      if (activeCandidateLoadTimerId) {
        window.clearInterval(activeCandidateLoadTimerId);
        activeCandidateLoadTimerId = null;
      }
    }

    async function fetchJson(url, options = {}, attempt = 0) {
      const requestUrl = attempt > 0 ? withFetchRetryCacheBust(url) : url;
      const requestOptions = { cache: "no-store", ...options };
      let response;
      try {
        response = await fetch(requestUrl, requestOptions);
      } catch (error) {
        if (attempt < 1 && isRetryableFetchError(error)) {
          return fetchJson(url, options, attempt + 1);
        }
        throw error;
      }
      const contentType = response.headers.get("content-type") || "";
      let bodyText;
      try {
        bodyText = await response.text();
      } catch (error) {
        if (attempt < 1 && isRetryableFetchError(error)) {
          return fetchJson(url, options, attempt + 1);
        }
        throw error;
      }
      if (!response.ok) {
        throw new Error(formatFetchError(response.status, bodyText, response.statusText));
      }
      if (!contentType.includes("application/json")) {
        throw new Error(`接口返回非 JSON：${bodyText.slice(0, 160)}`);
      }
      try {
        return JSON.parse(bodyText);
      } catch (error) {
        throw new Error(`JSON 解析失败：${error}`);
      }
    }

    function isRetryableFetchError(error) {
      const text = String(error && (error.message || error) || "");
      return text.includes("Content-Length")
        || text.includes("Failed to fetch")
        || text.includes("NetworkError")
        || text.includes("network response")
        || text.includes("Load failed");
    }

    function withFetchRetryCacheBust(url) {
      const separator = url.includes("?") ? "&" : "?";
      return `${url}${separator}_retry=${Date.now()}`;
    }

    function formatFetchError(status, bodyText, statusText) {
      if (status === 502 || status === 504) {
        return `HTTP ${status}: 刷新耗时过长，网关已中断。请稍后再点“重新拉取”。`;
      }
      const plainText = (bodyText || "")
        .replace(/<script[\\s\\S]*?<\\/script>/gi, " ")
        .replace(/<style[\\s\\S]*?<\\/style>/gi, " ")
        .replace(/<[^>]+>/g, " ")
        .replace(/\\s+/g, " ")
        .trim();
      return `HTTP ${status}: ${plainText.slice(0, 160) || statusText}`;
    }

    function renderCachedCandidates() {
      try {
        const cached = JSON.parse(localStorage.getItem(candidateCacheKey) || "null");
        if (!cached || !Array.isArray(cached.items) || cached.items.length === 0) return false;
        renderCandidates(cached.items);
        const cachedAt = cached.cached_at ? new Date(cached.cached_at).toLocaleString() : "未知时间";
        setStatus(`已显示本地缓存候选文章 ${cached.items.length} 篇，缓存时间：${cachedAt}`);
        return true;
      } catch (_error) {
        return false;
      }
    }

    function cacheCandidates(data) {
      try {
        localStorage.setItem(candidateCacheKey, JSON.stringify({ ...data, cached_at: new Date().toISOString() }));
      } catch (_error) {
        // localStorage can be unavailable in some locked-down browsers.
      }
    }

    function renderCandidates(items) {
      const tbody = document.getElementById("candidate-body");
      tbody.innerHTML = "";
      candidatesById.clear();
      for (const item of items) {
        candidatesById.set(item.content_id, item);
        const tr = document.createElement("tr");
        tr.dataset.contentId = item.content_id;
        tr.innerHTML = `
          <td><span class="light ${item.light}"><span class="dot"></span>${lightLabels[item.light]}</span></td>
          <td>${item.rank}</td>
          <td class="title-cell">
            <strong>${escapeHtml(item.title || "")}</strong>
            <br>${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">原文</a>` : `<span class="muted">无原文链接</span>`}
            <br><span class="muted">${formatSignals(item)}</span>
            <br><span class="muted">${formatCacheSignals(item)}</span>
          </td>
          <td>${escapeHtml(item.author || "未知")}</td>
          <td>${item.ai_hot_score || item.hotness_score}<br><span class="muted">知识 ${item.knowledge_content_score || item.knowledge_score || 0}</span><br><span class="muted">原热度 ${item.hotness_score}</span></td>
          <td>${formatMetric(item.reads)}</td>
          <td>
            ${escapeHtml(item.knowledge_badge || item.hot_badge || item.readiness_label || "待检查")}
            <br><span class="muted">${escapeHtml(item.knowledge_reason || item.hot_reason || `${item.image_count || 0} 张图`)}</span>
          </td>
          <td>
            <div class="row-actions">
              <button class="tertiary" onclick="viewArticleDetail('${item.content_id}')">查看详情</button>
              <button onclick="rewriteSelected('${item.content_id}')">选择改写</button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      }
    }

    function formatMetric(value) {
      if (value === null || value === undefined || value === "") return "未知";
      const number = Number(value);
      if (!Number.isFinite(number)) return escapeHtml(String(value));
      if (number >= 10000) return `${(number / 10000).toFixed(number >= 100000 ? 0 : 1)}万`;
      return String(number);
    }

    function formatDateTime(value) {
      try {
        return new Date(value).toLocaleString();
      } catch (_error) {
        return String(value || "未知");
      }
    }

    function formatSignals(item) {
      const keywords = Array.isArray(item.matched_keywords) ? item.matched_keywords.slice(0, 4) : [];
      const knowledge = Array.isArray(item.knowledge_signals) ? item.knowledge_signals.slice(0, 3) : [];
      const structures = Array.isArray(item.structure_signals) ? item.structure_signals.slice(0, 3) : [];
      const marketing = Array.isArray(item.marketing_signals) ? item.marketing_signals.slice(0, 2) : [];
      const parts = [];
      if (item.knowledge_content_type) parts.push(`类型: ${item.knowledge_content_type}`);
      if (keywords.length) parts.push(`AI: ${keywords.join(" / ")}`);
      if (knowledge.length) parts.push(`知识: ${knowledge.join(" / ")}`);
      if (structures.length) parts.push(`结构: ${structures.join(" / ")}`);
      if (marketing.length) parts.push(`营销风险: ${marketing.join(" / ")}`);
      if (item.readiness_detail) parts.push(item.readiness_detail);
      return parts.join("；") || "暂无明显 AI 知识信号";
    }

    function formatCacheSignals(item) {
      const parts = [];
      if (item.published_at) parts.push(`发布：${formatDateTime(item.published_at)}`);
      parts.push(`正文：${item.text_length || 0} 字`);
      parts.push(`阅读来源：${item.read_source === "missing" ? "未返回" : "接口返回"}`);
      parts.push(`详情：${item.detail_status_label || item.readiness_label || "待检查"}`);
      if (item.cache_cached_at) parts.push(`候选缓存：${formatDateTime(item.cache_cached_at)}`);
      return parts.join("；");
    }

    async function viewArticleDetail(contentId) {
      const requestId = ++activeDetailRequestId;
      document.querySelectorAll("tr.selected").forEach(row => row.classList.remove("selected"));
      const row = document.querySelector(`tr[data-content-id="${CSS.escape(contentId)}"]`);
      if (row) row.classList.add("selected");
      const item = candidatesById.get(contentId) || {};
      renderArticleDetailLoading(item);
      try {
        const data = await fetchJson(`/workflow/wechat/articles/${encodeURIComponent(contentId)}?fetch_detail=true`);
        if (requestId !== activeDetailRequestId) return;
        if (!data.ok) throw new Error(data.error || "详情不存在");
        renderArticleDetail(data);
      } catch (error) {
        if (requestId === activeDetailRequestId) {
          document.getElementById("article-detail").innerHTML = `<strong>文章详情</strong><p class="muted">详情读取失败：${escapeHtml(error)}</p>`;
        }
      }
    }

    function renderArticleDetailLoading(item) {
      document.getElementById("article-detail").innerHTML = `
        <strong>${escapeHtml(item.title || "文章详情")}</strong>
        <p class="muted">正在补拉全文详情，只用于预览，不会触发改写...</p>
      `;
    }

    function renderArticleDetail(data) {
      const article = data.article || {};
      const status = data.detail_status || {};
      const cache = data.cache || {};
      const preview = data.text_preview || "暂无正文预览。";
      const contentId = article.content_id || data.content_id || "";
      document.getElementById("article-detail").innerHTML = `
        <strong>${escapeHtml(article.title || "文章详情")}</strong>
        <dl>
          <dt>公众号</dt><dd>${escapeHtml(article.author || "未知")}</dd>
          <dt>原文</dt><dd>${article.url ? `<a href="${escapeHtml(article.url)}" target="_blank" rel="noopener noreferrer">打开原文</a>` : "无链接"}</dd>
          <dt>发布</dt><dd>${article.published_at ? formatDateTime(article.published_at) : "未知"}</dd>
          <dt>详情状态</dt><dd>${escapeHtml(status.message || article.detail_status_detail || "未知")}</dd>
          <dt>正文长度</dt><dd>${article.text_length || 0} 字</dd>
          <dt>图片</dt><dd>${article.image_count || 0} 张</dd>
          <dt>缓存</dt><dd>${cache.cached_at ? `候选缓存 ${formatDateTime(cache.cached_at)}` : "暂无候选缓存时间"}</dd>
        </dl>
        <div class="row-actions">
          <button onclick="rewriteSelected('${escapeHtml(contentId)}')">用这篇改写</button>
        </div>
        <div class="detail-preview">${escapeHtml(preview)}</div>
      `;
    }

    async function rewriteSelected(contentId) {
      const requestId = ++activeRewriteRequestId;
      document.querySelectorAll("tr.selected").forEach(row => row.classList.remove("selected"));
      const row = document.querySelector(`tr[data-content-id="${CSS.escape(contentId)}"]`);
      if (row) row.classList.add("selected");
      currentArticleMarkdown = "";
      currentSourceImages = [];
      stopRewriteElapsedProgress();
      document.getElementById("rewrite-progress").innerHTML = "";
      document.getElementById("rewrite-status").textContent = "正在连接改写流式接口...";
      document.getElementById("image-status").textContent = "正在等待当前选中文章的改写结果...";
      document.getElementById("article-frame").srcdoc = "";
      try {
        const response = await fetch("/workflow/rewrite/selected/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content_id: contentId, candidate: candidatesById.get(contentId) || null }),
        });
        const contentType = response.headers.get("content-type") || "";
        if (!response.ok) throw new Error(await response.text());
        if (!contentType.includes("application/x-ndjson")) {
          throw new Error(`改写接口返回非 JSON 流：${(await response.text()).slice(0, 160)}`);
        }
        if (!response.body) throw new Error("当前浏览器不支持流式读取响应");
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (true) {
          if (requestId !== activeRewriteRequestId) {
            await reader.cancel();
            return;
          }
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (line.trim()) handleRewriteStreamEvent(JSON.parse(line), requestId);
          }
        }
        if (buffer.trim()) handleRewriteStreamEvent(JSON.parse(buffer), requestId);
      } catch (error) {
        if (requestId === activeRewriteRequestId) {
          const message = formatStreamError(error);
          document.getElementById("rewrite-status").textContent = message;
          stopRewriteElapsedProgress();
          appendRewriteProgress(message);
        }
      }
    }

    function handleRewriteStreamEvent(event, requestId) {
      if (requestId !== activeRewriteRequestId) return;
      if (event.phase === "rewrite-detail" || event.phase === "image-ocr" || event.phase === "rewriting") {
        updateRewriteElapsedProgress(event.message || "正在处理选中文章...", event.elapsed_seconds || 0);
        return;
      }
      stopRewriteElapsedProgress();
      if (event.message) {
        appendRewriteProgress(event.message);
        document.getElementById("rewrite-status").textContent = event.message;
      }
      if (event.event === "error") {
        throw new Error(event.message || "改写失败");
      }
      if (event.event === "done" && event.result) {
        renderRewriteResult(event.result);
      }
    }

    function appendRewriteProgress(message) {
      const item = document.createElement("li");
      item.textContent = message;
      document.getElementById("rewrite-progress").appendChild(item);
    }

    function updateRewriteElapsedProgress(message, elapsedSeconds) {
      if (!activeRewriteTimerItem) {
        activeRewriteTimerItem = document.createElement("li");
        document.getElementById("rewrite-progress").appendChild(activeRewriteTimerItem);
      }
      const prefix = String(message || "正在处理选中文章...").replace(/，已耗时\s*\d+分?\d*秒。?$/, "");
      activeRewriteTimerStartMs = Date.now() - Math.max(0, Number(elapsedSeconds) || 0) * 1000;
      const render = () => {
        if (!activeRewriteTimerItem || !document.body.contains(activeRewriteTimerItem)) {
          stopRewriteElapsedProgress();
          return;
        }
        const elapsed = (Date.now() - activeRewriteTimerStartMs) / 1000;
        const dynamicMessage = `${prefix}，已耗时 ${formatSeconds(elapsed)}。`;
        activeRewriteTimerItem.textContent = dynamicMessage;
        document.getElementById("rewrite-status").textContent = dynamicMessage;
      };
      render();
      if (activeRewriteTimerId) {
        window.clearInterval(activeRewriteTimerId);
      }
      activeRewriteTimerId = window.setInterval(render, 500);
    }

    function stopRewriteElapsedProgress() {
      if (activeRewriteTimerId) {
        window.clearInterval(activeRewriteTimerId);
        activeRewriteTimerId = null;
      }
      activeRewriteTimerItem = null;
      activeRewriteTimerStartMs = 0;
    }

    function formatStreamError(error) {
      const text = String(error && (error.message || error) || "未知错误");
      if (text.includes("Error in input stream")) {
        return "改写流连接中断：开发服务可能正在重载或网络连接被中断，请重新点击“选择改写”。";
      }
      return `改写失败：${text}`;
    }

    function renderRewriteResult(data) {
      currentArticleMarkdown = data.article.body_markdown || "";
      currentSourceImages = Array.isArray(data.source_images) ? data.source_images : [];
      const sourceTitle = data.source && data.source.title ? data.source.title : data.article.title;
      const sourceTextLength = data.source && Number.isFinite(Number(data.source.source_text_length)) ? Number(data.source.source_text_length) : 0;
      const rewriteTextLength = data.source && Number.isFinite(Number(data.source.rewrite_text_length)) ? Number(data.source.rewrite_text_length) : 0;
      const timings = data.source && data.source.stage_timings ? data.source.stage_timings : {};
      const tokenSummary = formatLlmUsage(data.article.llm_usage);
      document.getElementById("rewrite-status").textContent = `已生成：${data.article.title}；当前改写来源：${sourceTitle}；原文 ${sourceTextLength} 字；改写稿 ${rewriteTextLength} 字；总耗时 ${formatSeconds(timings.total_seconds)}；${tokenSummary}`;
      document.getElementById("image-status").textContent = "正在识别正文中的配图建议...";
      const frame = document.getElementById("article-frame");
      frame.onload = () => enhanceImageSuggestions();
      frame.srcdoc = data.article_html;
    }

    function formatSeconds(seconds) {
      if (seconds === undefined || seconds === null || Number.isNaN(Number(seconds))) return "未知";
      const total = Math.max(0, Math.floor(Number(seconds)));
      const minutes = Math.floor(total / 60);
      const rest = total % 60;
      if (minutes <= 0) return `${rest}秒`;
      return `${minutes}分${String(rest).padStart(2, "0")}秒`;
    }

    function formatLlmUsage(usage) {
      if (!usage) return "LLM 未调用，token 使用 0";
      const model = usage.model || "unknown";
      const total = usage.total_tokens;
      const prompt = usage.prompt_tokens;
      const completion = usage.completion_tokens;
      if (total === null || total === undefined) {
        return `LLM ${model} 已调用，但服务端未返回 token usage`;
      }
      return `LLM ${model} token：总计 ${total}，输入 ${prompt ?? "未知"}，输出 ${completion ?? "未知"}`;
    }

    function enhanceImageSuggestions() {
      const frame = document.getElementById("article-frame");
      const doc = frame.contentDocument;
      if (!doc) {
        document.getElementById("image-status").textContent = "无法访问改写稿内容，暂不能插入配图按钮。";
        return;
      }
      injectImageActionStyles(doc);
      doc.querySelectorAll(".inline-image-action").forEach(node => node.remove());
      const blocks = findImageSuggestionBlocks(doc);
      if (blocks.length === 0) {
        document.getElementById("image-status").textContent = "未找到可识别的配图建议。建议正文中使用“### 配图建议”或“AIGC 提示词：”。";
        return;
      }
      blocks.forEach((block, index) => {
        const suggestion = buildSuggestionText(block);
        if (!suggestion) return;
        const action = doc.createElement("div");
        action.className = "inline-image-action";
        const button = doc.createElement("button");
        button.type = "button";
        button.className = "inline-image-icon-button";
        button.title = "根据这条配图建议生成图片";
        button.setAttribute("aria-label", "根据这条配图建议生成图片");
        button.textContent = "🖼";
        const status = doc.createElement("p");
        status.className = "inline-image-status";
        status.textContent = `点击图标生成第 ${index + 1} 张配图。`;
        const promptBox = doc.createElement("details");
        promptBox.className = "inline-image-prompt";
        const promptSummary = doc.createElement("summary");
        promptSummary.textContent = "临时出图 prompt 模板";
        const promptText = doc.createElement("pre");
        promptText.textContent = buildTemporaryPromptTemplate(suggestion);
        promptBox.append(promptSummary, promptText);
        const referenceBox = buildReferenceImagePicker(doc);
        const result = doc.createElement("div");
        result.className = "inline-image-result";
        button.addEventListener("click", () => generateImageForSuggestion(suggestion, referenceBox, button, status, promptText, result));
        action.append(button, status);
        if (referenceBox) action.append(referenceBox);
        action.append(promptBox, result);
        insertImageAction(block, action);
      });
      document.getElementById("image-status").textContent = `已在正文配图建议处加入 ${blocks.length} 个图片生成图标。`;
    }

    function insertImageAction(block, action) {
      const anchor = block.anchor;
      if (block.inside && anchor && anchor.appendChild) {
        anchor.appendChild(action);
        return;
      }
      anchor.insertAdjacentElement("afterend", action);
    }

    function injectImageActionStyles(doc) {
      if (doc.getElementById("inline-image-action-style")) return;
      const style = doc.createElement("style");
      style.id = "inline-image-action-style";
      style.textContent = `
        .inline-image-action {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
          border: 1px dashed #93c5fd;
          background: #eff6ff;
          border-radius: 12px;
          padding: 12px;
          margin: 8px 0 20px;
        }
        .inline-image-action .inline-image-icon-button {
          width: 36px;
          height: 36px;
          border: 0;
          border-radius: 999px;
          background: #2563eb;
          color: #fff;
          padding: 0;
          cursor: pointer;
          font-size: 18px;
          line-height: 36px;
          box-shadow: 0 8px 18px rgba(37, 99, 235, 0.22);
        }
        .inline-image-action .inline-image-icon-button:disabled { opacity: 0.55; cursor: not-allowed; }
        .inline-image-status { color: #667085; font-size: 14px; margin: 0; }
        .inline-image-prompt {
          flex-basis: 100%;
          color: #475467;
          font-size: 13px;
        }
        .inline-reference-images {
          flex-basis: 100%;
          display: flex;
          gap: 10px;
          overflow-x: auto;
          padding: 4px 0;
        }
        .inline-reference-image {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          border: 1px solid #d9e2ef;
          background: #fff;
          border-radius: 10px;
          padding: 6px;
          color: #475467;
          font-size: 12px;
          white-space: nowrap;
        }
        .inline-reference-image img {
          width: 54px;
          height: 54px;
          object-fit: cover;
          border-radius: 8px;
          border: 1px solid #e5e7eb;
        }
        .inline-image-prompt summary {
          cursor: pointer;
          color: #2563eb;
          font-weight: 700;
          margin: 4px 0;
        }
        .inline-image-prompt pre {
          white-space: pre-wrap;
          word-break: break-word;
          background: #ffffff;
          border: 1px solid #d9e2ef;
          border-radius: 10px;
          padding: 10px;
          margin: 6px 0 0;
          font: 13px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        .inline-image-result { flex-basis: 100%; }
        .inline-image-result img {
          max-width: 100%;
          border-radius: 12px;
          border: 1px solid #d9e2ef;
          margin: 8px 0 14px;
        }
      `;
      doc.head.appendChild(style);
    }

    function findImageSuggestionBlocks(doc) {
      const seen = new Set();
      const blocks = [];
      const addGroup = (nodes, options = {}) => {
        const group = nodes.filter(Boolean);
        if (group.length === 0) return;
        const anchor = group[group.length - 1];
        if (seen.has(anchor)) return;
        const text = group.map(node => node.textContent || "").join(" ").replace(/\s+/g, " ").trim();
        if (!isConcreteImageSuggestion(text)) return;
        seen.add(anchor);
        blocks.push({ anchor, text, inside: Boolean(options.inside) });
      };
      Array.from(doc.querySelectorAll("section")).forEach(node => {
        const text = node.textContent || "";
        if (text.includes("配图建议") && isInlineImageSuggestionCard(node)) {
          addGroup([node], { inside: true });
        }
      });
      const headings = Array.from(doc.querySelectorAll("h2,h3,h4")).filter(node => (node.textContent || "").includes("配图建议"));
      for (const heading of headings) {
        let node = heading.nextElementSibling;
        while (node && !["H2", "H3"].includes(node.tagName)) {
          addGroup(collectSuggestionGroup(node));
          node = node.nextElementSibling;
        }
      }
      Array.from(doc.querySelectorAll("p,li,blockquote")).forEach(node => {
        if ((node.textContent || "").includes("配图建议")) {
          const card = closestInlineImageSuggestionCard(node);
          if (card) {
            addGroup([card], { inside: true });
          } else {
            addGroup(collectSuggestionGroup(node));
          }
        }
      });
      return blocks.slice(0, 6);
    }

    function isInlineImageSuggestionCard(node) {
      const text = node.textContent || "";
      if (!text.includes("配图建议")) return false;
      if (node.querySelector(".inline-image-action")) return false;
      if (text.length > 1200 || text.indexOf("配图建议") > 120) return false;
      if (Array.from(node.querySelectorAll("section")).some(child => child !== node && (child.textContent || "").includes("配图建议"))) return false;
      return /(AIGC\s*)?提示词|封面图|正文配图|重新绘制|画面|风格|用途|版权/.test(text);
    }

    function closestInlineImageSuggestionCard(node) {
      const section = node.closest("section");
      if (!section || section === document.body) return null;
      return isInlineImageSuggestionCard(section) ? section : null;
    }

    function collectSuggestionGroup(startNode) {
      if (!startNode) return [];
      if (startNode.tagName === "SECTION" && (startNode.textContent || "").includes("配图建议")) {
        return [startNode];
      }
      const group = [startNode];
      let node = startNode.nextElementSibling;
      while (node && !["H2", "H3"].includes(node.tagName)) {
        const text = node.textContent || "";
        if (text.includes("配图建议") || /^(来源与复核提醒|发布风险自查|Tags)$/i.test(text.trim())) break;
        if (node.classList && node.classList.contains("inline-image-action")) break;
        if (["UL", "OL", "LI", "P", "BLOCKQUOTE"].includes(node.tagName)) {
          group.push(node);
          node = node.nextElementSibling;
          continue;
        }
        break;
      }
      return group;
    }

    function isConcreteImageSuggestion(text) {
      const normalized = String(text || "").replace(/\s+/g, " ").trim();
      return normalized.length > 12 && /(AIGC\s*)?提示词|封面图|正文配图|配图\s*\d|配图建议|重新绘制|画面|风格/.test(normalized);
    }

    function buildSuggestionText(block) {
      const text = String(block.text || block.textContent || "").replace(/\s+/g, " ").trim();
      if (!text) return "";
      const promptMatch = text.match(/(?:AIGC\s*)?提示词[：:]\s*(.+)$/i);
      return clipImagePrompt(promptMatch ? promptMatch[1] : text);
    }

    function clipImagePrompt(prompt) {
      return prompt.length <= 500 ? prompt : prompt.slice(0, 500).trim();
    }

    function buildTemporaryPromptTemplate(suggestion) {
      const core = clipImagePrompt(suggestion);
      return clipImagePrompt(`临时图片生成 skill：为 AI 知识型微信公众号重绘原创配图。严格依据这条配图建议生成：${core}。画面要直接表达建议里的主题、对象和结构；优先使用信息图、流程图、决策树、概念插画或科技封面构图。文字要求：如果画面必须出现文字，只能使用清晰、可读、语义正确的简体中文；优先使用 3-6 个大号中文标签词。即使配图建议里有英文术语、缩写或代码词，也要翻译成简体中文标签，不要直接把英文画进图里。风格：清晰、干净、科技蓝、少量绿色点缀，适合公众号正文阅读。限制：不要公司 Logo、不要真实截图、不要仿原图排版、不要密集小字、不要英文单词、不要英文字母、不要繁体字、不要拼音、不要伪中文、不要乱码字母、不要无意义符号、不要版权角色或水印。`);
    }

    function buildReferenceImagePicker(doc) {
      if (!currentSourceImages.length) return null;
      const box = doc.createElement("div");
      box.className = "inline-reference-images";
      const noneLabel = doc.createElement("label");
      noneLabel.className = "inline-reference-image";
      noneLabel.innerHTML = `<input type="radio" name="reference-image-${Math.random().toString(36).slice(2)}" value="" checked> 不参考原图`;
      const radioName = noneLabel.querySelector("input").name;
      box.appendChild(noneLabel);
      currentSourceImages.slice(0, 6).forEach((url, index) => {
        const label = doc.createElement("label");
        label.className = "inline-reference-image";
        const input = doc.createElement("input");
        input.type = "radio";
        input.name = radioName;
        input.value = url;
        const img = doc.createElement("img");
        img.src = url;
        img.alt = `原文图片 ${index + 1}`;
        label.append(input, img, doc.createTextNode(`原图 ${index + 1}`));
        box.appendChild(label);
      });
      return box;
    }

    function selectedReferenceImage(referenceBox) {
      if (!referenceBox) return "";
      const selected = referenceBox.querySelector("input:checked");
      return selected ? selected.value : "";
    }

    async function generateImageForSuggestion(suggestion, referenceBox, button, status, promptText, result) {
      button.disabled = true;
      const referenceImage = selectedReferenceImage(referenceBox);
      status.textContent = referenceImage
        ? "正在参考原文图片换风格重绘，可能需要 1-3 分钟..."
        : "正在用临时出图 prompt 重新规划并生成图片，可能需要 1-3 分钟...";
      const response = await fetch("/workflow/rewrite/image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ suggestion, reference_image: referenceImage, size: "1024x1024", count: 1 }),
      });
      const data = await response.json();
      button.disabled = false;
      if (!data.ok) {
        status.textContent = data.error || "图片生成失败";
        return;
      }
      const warning = data.warning ? `${data.warning} ` : "";
      status.textContent = `${warning}已生成 ${data.images.length} 张图片。临时出图 prompt：${data.prompt}`;
      promptText.textContent = data.prompt || promptText.textContent;
      result.innerHTML = data.images.map(url => `
        <p><a href="${url}" target="_blank">打开图片</a></p>
        <img src="${url}" alt="生成配图" style="max-width:100%; border-radius:12px; border:1px solid #d9e2ef; margin:8px 0 16px;">
      `).join("");
    }

    function setStatus(text) {
      document.getElementById("status").textContent = text;
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      })[char]);
    }

    loadCandidates(false).catch(error => setStatus(`加载失败：${error}`));
  </script>
</body>
</html>"""


def _video_workspace_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url=/workflow/video/agent">
  <title>视频 Agent</title>
</head>
<body style="font:16px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; padding:32px;">
  <h1>视频 Agent 已切换到 Remotion 直出链路</h1>
  <p>请打开 <a href="/workflow/video/agent">/workflow/video/agent</a> 使用 Remotion 直出视频链路。</p>
</body>
</html>"""

def _video_script_markdown(script: VideoChannelScript) -> str:
    return f"""### 视频标题

{script.title}

### 封面字

{script.cover_text}

### 3 秒开头钩子

{script.hook}

### 口播稿

{script.voiceover}

### 分镜脚本

{script.storyboard_markdown}"""


def _video_script_from_payload(payload: Any) -> VideoChannelScript:
    if not isinstance(payload, dict):
        raise RuntimeError("缺少视频脚本，请先生成脚本。")
    return VideoChannelScript(
        title=str(payload.get("title") or "未命名视频"),
        cover_text=str(payload.get("cover_text") or payload.get("title") or "知识点讲解"),
        hook=str(payload.get("hook") or ""),
        voiceover=str(payload.get("voiceover") or ""),
        storyboard_markdown=str(payload.get("storyboard_markdown") or ""),
        cover_prompt=str(payload.get("cover_prompt") or ""),
        publish_copy=str(payload.get("publish_copy") or ""),
        hashtags=[str(item) for item in payload.get("hashtags", []) if str(item).strip()],
        source_review=[str(item) for item in payload.get("source_review", []) if str(item).strip()],
        risk_flags=[str(item) for item in payload.get("risk_flags", []) if str(item).strip()],
        generation_prompt=payload.get("generation_prompt"),
        llm_usage=payload.get("llm_usage") if isinstance(payload.get("llm_usage"), dict) else None,
    )


def _generated_video_url(path: Path) -> str:
    job = path.parent.name
    return f"/workflow/generated/videos/{job}/{path.name}"


def _video_script_html(script: VideoChannelScript) -> str:
    markdown = _video_script_markdown(script)
    lines = []
    in_table = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if in_table:
                lines.append("</table>")
                in_table = False
            continue
        if line.startswith("### "):
            if in_table:
                lines.append("</table>")
                in_table = False
            lines.append(f"<h3>{escape(line.removeprefix('### '))}</h3>")
        elif line.startswith("|") and line.endswith("|"):
            cells = [escape(cell.strip()) for cell in line.strip("|").split("|")]
            if set(cells) == {"---"}:
                continue
            tag = "th" if cells and cells[0] == "时间" else "td"
            if not in_table:
                lines.append("<table>")
                in_table = True
            lines.append("<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in cells) + "</tr>")
        elif line.startswith(("1. ", "- ")):
            if in_table:
                lines.append("</table>")
                in_table = False
            lines.append(f"<p>{escape(line)}</p>")
        else:
            if in_table:
                lines.append("</table>")
                in_table = False
            lines.append(f"<p>{escape(line)}</p>")
    if in_table:
        lines.append("</table>")
    return "\n".join(lines)


def _workflow_graph_html() -> str:
    nodes = [_node_card(node_name) for node_name in NODE_ORDER]
    compact_flow = _compact_flow_html()
    cards = "\n".join(nodes)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LangGraph Agent 流程图</title>
  <style>
    body {{
      margin: 0;
      background: #f6f8fb;
      color: #172033;
      font: 15px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 28px 20px 56px; }}
    h1, h2, h3 {{ margin: 0 0 12px; line-height: 1.25; }}
    .hero, .panel, .node-card {{
      background: #fff;
      border: 1px solid #d9e2ef;
      border-radius: 14px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
      padding: 20px;
      margin: 16px 0;
    }}
    .links {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }}
    a.button {{
      display: inline-block;
      background: #2563eb;
      color: #fff;
      text-decoration: none;
      border-radius: 10px;
      padding: 8px 12px;
      font-weight: 700;
    }}
    .graph-wrap {{ overflow-x: auto; }}
    .compact-flow {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
      gap: 8px 14px;
      align-items: center;
    }}
    .flow-node {{
      min-height: 58px;
      border: 1px solid #bfdbfe;
      border-radius: 8px;
      background: #eff6ff;
      color: #1e3a8a;
      padding: 5px 6px;
      font-size: 10px;
      line-height: 1.2;
      display: grid;
      align-content: center;
      gap: 2px;
    }}
    .flow-title {{ font-weight: 800; text-align: center; }}
    .flow-io {{ color: #475569; font-size: 9px; overflow-wrap: anywhere; }}
    .flow-node.review {{
      border-color: #f97316;
      background: #fff7ed;
      color: #9a3412;
    }}
    .flow-arrow {{
      color: #94a3b8;
      font-size: 13px;
      text-align: center;
      align-self: center;
    }}
    .nodes {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px;
    }}
    .node-card {{ margin: 0; }}
    .node-card h3 {{ color: #1d4ed8; }}
    .meta {{ color: #667085; font-size: 13px; }}
    .review-badge {{
      display: inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 700;
      background: #ecfdf3;
      color: #047857;
    }}
    .review-badge.need {{
      background: #fff7ed;
      color: #c2410c;
    }}
    code {{ background: #eef2ff; padding: 2px 6px; border-radius: 6px; }}
    @media (max-width: 900px) {{
      main {{ padding: 18px 12px 40px; }}
      .compact-flow {{ grid-template-columns: 1fr; }}
      .flow-arrow {{ transform: rotate(90deg); }}
      .graph-wrap {{ padding-bottom: 8px; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>LangGraph Agent 流程图</h1>
      <p>这个页面展示当前 <code>NODE_ORDER</code> 中定义的多智能体执行顺序。上方流程图是紧凑总览；每个节点的输入、输出和人工 review 信息在下方卡片中查看。</p>
      <div class="links">
        <a class="button" href="/workflow/report/html">查看分析报告</a>
        <a class="button" href="/workflow/rewrite">进入微信改写工作台</a>
        <a class="button" href="/workflow/video/agent">进入视频 Agent</a>
        <a class="button" href="/docs">查看 API 文档</a>
      </div>
    </section>
    <section class="panel graph-wrap">
      <h2>流程图</h2>
      {compact_flow}
    </section>
    <section class="panel">
      <h2>Agent 节点说明</h2>
      <div class="nodes">
        {cards}
      </div>
    </section>
  </main>
</body>
</html>"""


def _compact_flow_html() -> str:
    parts: list[str] = ["<div class='compact-flow' aria-label='LangGraph Agent 紧凑流程图'>"]
    for index, node_name in enumerate(NODE_ORDER):
        info = _NODE_DESCRIPTIONS.get(node_name, {})
        review = info.get("review", "不需要")
        review_class = " review" if _needs_review(review) else ""
        title = escape(_node_title(node_name))
        review_suffix = " · Review" if _needs_review(review) else ""
        input_text = escape(_short_graph_text(info.get("input", "HotspotState"), limit=30))
        output_text = escape(_short_graph_text(info.get("output", "HotspotState update"), limit=30))
        parts.append(
            f"<div class='flow-node{review_class}' title='{escape(node_name)}'>"
            f"<div class='flow-title'>{title}{review_suffix}</div>"
            f"<div class='flow-io'>入：{input_text}</div>"
            f"<div class='flow-io'>出：{output_text}</div>"
            "</div>"
        )
        if index < len(NODE_ORDER) - 1:
            parts.append("<div class='flow-arrow' aria-hidden='true'>→</div>")
    parts.append("</div>")
    return "".join(parts)


def _node_card(node_name: str) -> str:
    info = _NODE_DESCRIPTIONS.get(node_name, {})
    review = info.get("review", "不需要")
    badge_class = "review-badge need" if _needs_review(review) else "review-badge"
    return (
        "<article class='node-card'>"
        f"<p class='meta'>{escape(node_name)}</p>"
        f"<h3>{escape(_node_title(node_name))}</h3>"
        f"<p>{escape(info.get('description', '执行该节点对应的 Agent 逻辑。'))}</p>"
        f"<p><strong>输入：</strong>{escape(info.get('input', 'HotspotState'))}</p>"
        f"<p><strong>输出：</strong>{escape(info.get('output', 'HotspotState update'))}</p>"
        f"<p><strong>人工 Review：</strong><span class='{badge_class}'>{escape(review)}</span></p>"
        "</article>"
    )


def _mermaid_node_label(node_name: str) -> str:
    info = _NODE_DESCRIPTIONS.get(node_name, {})
    review = info.get("review", "不需要")
    suffix = " · Review" if _needs_review(review) else ""
    return _escape_mermaid_label(f"{_node_title(node_name)}{suffix}")


def _needs_review(review: str) -> bool:
    return bool(review and review != "不需要" and "需要" in review)


def _short_graph_text(value: str, limit: int = 34) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _escape_mermaid_label(value: str) -> str:
    return escape(value).replace('"', "&quot;")


def _node_title(node_name: str) -> str:
    return _NODE_DESCRIPTIONS.get(node_name, {}).get("title", node_name)


_NODE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "task_router": {
        "title": "任务路由",
        "description": "生成默认热点分析任务，确定关键词、平台和采集维度。",
        "input": "初始 state / 用户 payload",
        "output": "task",
        "review": "不需要",
    },
    "source_discovery": {
        "title": "数据源规划",
        "description": "把任务拆成具体平台采集计划，例如搜索、账号、文章列表。",
        "input": "task",
        "output": "source_plans",
        "review": "不需要",
    },
    "wechat_account_discovery": {
        "title": "公众号发现订阅",
        "description": "搜索 AI 相关公众号，过滤匹配账号，并可自动订阅到 wechat-download-api。",
        "input": "task / source_plans",
        "output": "wechat_accounts / quality_info / quality_flags",
        "review": "质量告警时需要",
    },
    "platform_collection": {
        "title": "平台内容采集",
        "description": "调用各平台客户端采集原始内容；微信会委托 WechatDownloadCollectionAgent。",
        "input": "source_plans / wechat_accounts",
        "output": "raw_contents",
        "review": "质量告警时需要",
    },
    "normalization": {
        "title": "内容标准化",
        "description": "把不同平台返回值统一成 NormalizedContent。",
        "input": "raw_contents",
        "output": "normalized_contents",
        "review": "不需要",
    },
    "ai_relevance": {
        "title": "AI 相关性判断",
        "description": "判断内容是否真正和 AI、模型、工具、工作流有关，并给出分类。",
        "input": "normalized_contents",
        "output": "ai_relevance",
        "review": "不需要",
    },
    "hotness_scoring": {
        "title": "热度评分",
        "description": "结合阅读、点赞、评论、AI 相关性和平台权重计算热度。",
        "input": "normalized_contents / ai_relevance",
        "output": "hotness_scores",
        "review": "不需要",
    },
    "trend_analysis": {
        "title": "趋势聚类",
        "description": "按 AI 分类聚合内容，形成趋势候选和代表证据。",
        "input": "hotness_scores / ai_relevance",
        "output": "trends",
        "review": "不需要",
    },
    "product_insight": {
        "title": "产品机会洞察",
        "description": "把趋势翻译成用户痛点、产品机会和验证假设。",
        "input": "trends",
        "output": "product_insights",
        "review": "不需要",
    },
    "content_strategy": {
        "title": "内容策略",
        "description": "根据趋势生成平台化选题建议和内容角度。",
        "input": "trends / product_insights",
        "output": "content_strategies",
        "review": "不需要",
    },
    "wechat_article_writing": {
        "title": "微信文章改写",
        "description": "结合热度文章和 wechat-rewrite skill 生成公众号发布稿或改写 prompt。",
        "input": "trends / normalized_contents / hotness_scores",
        "output": "generated_article",
        "review": "发布前需要",
    },
    "quality_control": {
        "title": "质量检查",
        "description": "检查结果是否需要人工复核，并汇总质量告警。",
        "input": "workflow state",
        "output": "human_review_required / review_flags / quality_flags",
        "review": "需要",
    },
    "report_generation": {
        "title": "报告生成",
        "description": "生成最终热点分析报告，可渲染 Markdown 或 HTML。",
        "input": "workflow state",
        "output": "report",
        "review": "继承 quality_control",
    },
}


def _article_html(title: str, subtitle: str, body_markdown: str) -> str:
    body = "\n".join(_markdown_line_to_html(line) for line in body_markdown.splitlines())
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{
      margin: 0;
      background: #f6f8fb;
      color: #172033;
      font: 17px/1.85 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    main {{
      max-width: 820px;
      margin: 0 auto;
      padding: 42px 22px 72px;
      background: #fff;
    }}
    h1 {{ font-size: 32px; line-height: 1.25; margin: 0 0 8px; }}
    .subtitle {{ color: #667085; margin-bottom: 28px; }}
    h2 {{ margin-top: 34px; font-size: 24px; }}
    p {{ margin: 14px 0; }}
    li {{ margin: 8px 0; }}
    strong {{ color: #1d4ed8; }}
    a {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(title)}</h1>
    <p class="subtitle">{escape(subtitle)}</p>
    {body}
  </main>
</body>
</html>"""


def _markdown_line_to_html(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.startswith("## "):
        return f"<h2>{escape(stripped.removeprefix('## '))}</h2>"
    if stripped.startswith("### "):
        return f"<h3>{escape(stripped.removeprefix('### '))}</h3>"
    if stripped.startswith("- "):
        return f"<li>{escape(stripped.removeprefix('- '))}</li>"
    if _is_skill_html_line(stripped):
        return stripped
    return f"<p>{escape(stripped)}</p>"


def _is_skill_html_line(line: str) -> bool:
    allowed_prefixes = (
        "<section ",
        "</section>",
        "<p>",
        "<p ",
        "</p>",
        "<h2>",
        "<h2 ",
        "</h2>",
        "<ul>",
        "<ul ",
        "</ul>",
        "<ol>",
        "<ol ",
        "</ol>",
        "<li>",
        "<li ",
        "</li>",
        "<blockquote>",
        "<blockquote ",
        "</blockquote>",
        "<strong>",
        "<strong ",
        "</strong>",
        "<span>",
        "<span ",
        "</span>",
        "<br>",
        "<br/>",
        "<br />",
    )
    return line.startswith(allowed_prefixes)
