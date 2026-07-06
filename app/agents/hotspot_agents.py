"""Compatibility exports for AI hotspot agents.

The concrete implementations live in one module per responsibility. This file
keeps older imports working while the graph and external callers migrate to
``app.agents`` or the specific modules.
"""

from __future__ import annotations

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
]
