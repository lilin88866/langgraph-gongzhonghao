"""Domain models shared by all AI hotspot agents.

The models intentionally use dataclasses instead of framework-specific types so
the workflow can run before API providers, databases, or LangGraph are wired in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, TypedDict


class Platform(StrEnum):
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"
    WECHAT = "wechat"
    TOUTIAO = "toutiao"


class ApiDimension(StrEnum):
    ACCOUNT_INFO = "account_info"
    ARTICLE_DETAIL = "article_detail"
    WORK_LIST = "work_list"
    SEARCH_QUERY = "search_query"


class MediaType(StrEnum):
    ARTICLE = "article"
    VIDEO = "video"
    NOTE = "note"
    ACCOUNT = "account"
    UNKNOWN = "unknown"


class FollowUpDecision(StrEnum):
    WATCH = "worth_watching"
    VALIDATE = "worth_validating"
    SKIP = "skip_for_now"


@dataclass(slots=True)
class HotspotTask:
    objective: str
    keywords: list[str]
    platforms: list[Platform]
    dimensions: list[ApiDimension]
    time_window_hours: int = 24
    max_items_per_platform: int = 20
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class SourcePlan:
    platform: Platform
    dimension: ApiDimension
    query: str | None = None
    account_id: str | None = None
    priority: int = 50
    page_size: int = 20
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RawContent:
    platform: Platform
    dimension: ApiDimension
    source_api: str
    raw_payload: dict[str, Any]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class EngagementMetrics:
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    reads: int | None = None
    watching: int | None = None


@dataclass(slots=True)
class NormalizedContent:
    platform: Platform
    content_id: str
    author: str | None
    title: str
    text: str
    media_type: MediaType
    published_at: datetime | None
    metrics: EngagementMetrics
    url: str | None
    source_api: str
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class AIRelevanceResult:
    content_id: str
    is_ai_related: bool
    confidence: float
    categories: list[str]
    keywords: list[str]
    reason: str


@dataclass(slots=True)
class HotnessScore:
    content_id: str
    hotness_score: float
    velocity_score: float
    engagement_quality_score: float
    platform_weight: float
    reason: str


@dataclass(slots=True)
class TrendCluster:
    trend_id: str
    name: str
    summary: str
    content_ids: list[str]
    platforms: list[Platform]
    hotness_score: float
    lifecycle: Literal["emerging", "rising", "peaking", "cooling"]
    evidence: list[str]


@dataclass(slots=True)
class ProductInsight:
    trend_id: str
    decision: FollowUpDecision
    user_pain: str
    product_opportunity: str
    validation_hypothesis: str
    target_users: list[str]
    competitors_or_references: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContentStrategy:
    trend_id: str
    platform: Platform
    title_direction: str
    core_argument: str
    format_suggestion: str
    supporting_content_ids: list[str]


@dataclass(slots=True)
class WechatAccountCandidate:
    fakeid: str
    nickname: str
    alias: str | None
    relevance_score: float
    matched_keywords: list[str]
    subscribed: bool
    reason: str


@dataclass(slots=True)
class GeneratedArticle:
    title: str
    subtitle: str
    body_markdown: str
    source_trend_id: str
    source_content_ids: list[str]
    recommended_tags: list[str]
    rewrite_prompt: str | None = None
    llm_usage: dict[str, Any] | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class EducationKnowledgePoint:
    knowledge_id: str
    title: str
    subject: str | None
    grade_or_level: str | None
    source_url: str | None
    key_points: list[str]
    examples: list[str]
    common_misunderstandings: list[str]
    raw_text: str


@dataclass(slots=True)
class VideoChannelScript:
    title: str
    cover_text: str
    hook: str
    voiceover: str
    storyboard_markdown: str
    cover_prompt: str
    publish_copy: str
    hashtags: list[str]
    source_review: list[str]
    risk_flags: list[str]
    generation_prompt: str | None = None
    llm_usage: dict[str, Any] | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class HotspotReport:
    title: str
    summary: str
    top_content_ids: list[str]
    trend_ids: list[str]
    insight_ids: list[str]
    strategy_count: int
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HotspotState(TypedDict, total=False):
    video_source: dict[str, Any]
    task: HotspotTask
    source_plans: list[SourcePlan]
    raw_contents: list[RawContent]
    normalized_contents: list[NormalizedContent]
    ai_relevance: list[AIRelevanceResult]
    hotness_scores: list[HotnessScore]
    trends: list[TrendCluster]
    product_insights: list[ProductInsight]
    content_strategies: list[ContentStrategy]
    wechat_accounts: list[WechatAccountCandidate]
    generated_article: GeneratedArticle
    article_compliance: dict[str, Any]
    llm_usage: dict[str, Any]
    education_knowledge: EducationKnowledgePoint
    video_channel_script: VideoChannelScript
    report: HotspotReport
    quality_flags: list[str]
    quality_info: list[str]
    review_flags: list[str]
    human_review_required: bool
