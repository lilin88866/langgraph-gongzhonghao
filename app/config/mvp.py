"""MVP defaults for AI hotspot tracking."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.hotspot import ApiDimension, Platform


@dataclass(frozen=True, slots=True)
class MvpPlatformScope:
    platform: Platform
    dimensions: tuple[ApiDimension, ...]
    primary_metrics: tuple[str, ...]
    role: str


MVP_PLATFORMS: tuple[MvpPlatformScope, ...] = (
    MvpPlatformScope(
        platform=Platform.DOUYIN,
        dimensions=(ApiDimension.SEARCH_QUERY, ApiDimension.WORK_LIST, ApiDimension.ACCOUNT_INFO),
        primary_metrics=("views", "likes", "comments", "shares"),
        role="发现短视频爆点、强情绪反馈和大众化 AI 使用场景。",
    ),
    MvpPlatformScope(
        platform=Platform.XIAOHONGSHU,
        dimensions=(ApiDimension.SEARCH_QUERY, ApiDimension.WORK_LIST, ApiDimension.ACCOUNT_INFO),
        primary_metrics=("likes", "comments", "saves"),
        role="发现教程、种草、效率工具体验和用户真实痛点。",
    ),
    MvpPlatformScope(
        platform=Platform.WECHAT,
        dimensions=(ApiDimension.SEARCH_QUERY, ApiDimension.ARTICLE_DETAIL, ApiDimension.ACCOUNT_INFO),
        primary_metrics=("reads", "likes", "watching", "comments"),
        role="发现深度观点、行业判断、创业案例和专家账号。",
    ),
    MvpPlatformScope(
        platform=Platform.TOUTIAO,
        dimensions=(ApiDimension.SEARCH_QUERY, ApiDimension.ARTICLE_DETAIL),
        primary_metrics=("views", "comments", "shares"),
        role="作为补充发现源，扩大搜索覆盖和热点验证样本。",
    ),
)


DEFAULT_AI_KEYWORDS: tuple[str, ...] = (
    "AI",
    "大模型",
    "智能体",
    "AI 产品",
    "AI 编程",
    "AI 视频",
    "AI 创业",
)


REPORT_SECTIONS: tuple[str, ...] = (
    "今日 AI 热点榜",
    "跨平台趋势",
    "产品机会卡片",
    "平台选题建议",
    "低置信度与人工审核项",
)
