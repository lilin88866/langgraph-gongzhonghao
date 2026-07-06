"""Agent node implementations for the AI hotspot workflow."""

from app.agents.ai_relevance import AIRelevanceAgent
from app.agents.content_strategy import ContentStrategyAgent
from app.agents.hotness_scoring import HotnessScoringAgent
from app.agents.normalization import NormalizationAgent
from app.agents.platform_collection import PlatformCollectionAgent
from app.agents.product_insight import ProductInsightAgent
from app.agents.quality_control import QualityControlAgent
from app.agents.report_generation import ReportGenerationAgent
from app.agents.source_discovery import SourceDiscoveryAgent
from app.agents.task_router import TaskRouterAgent
from app.agents.trend_analysis import TrendAnalysisAgent
from app.agents.video_channel_knowledge import EducationKnowledgeSourceAgent, VideoComplianceCheckAgent
from app.agents.wechat_account_discovery import WechatAccountDiscoveryAgent
from app.agents.wechat_article_writing import WechatArticleWritingAgent
from app.agents.wechat_download_collection import WechatDownloadCollectionAgent

__all__ = [
    "AIRelevanceAgent",
    "ContentStrategyAgent",
    "HotnessScoringAgent",
    "NormalizationAgent",
    "PlatformCollectionAgent",
    "ProductInsightAgent",
    "QualityControlAgent",
    "ReportGenerationAgent",
    "SourceDiscoveryAgent",
    "TaskRouterAgent",
    "TrendAnalysisAgent",
    "EducationKnowledgeSourceAgent",
    "VideoComplianceCheckAgent",
    "WechatAccountDiscoveryAgent",
    "WechatArticleWritingAgent",
    "WechatDownloadCollectionAgent",
]
