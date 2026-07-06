"""Shared constants for hotspot agents."""

from __future__ import annotations

from app.schemas.hotspot import Platform


AI_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "large_model": ("大模型", "LLM", "GPT", "Claude", "通义", "豆包", "kimi"),
    "ai_product": ("AI 产品", "智能体", "agent", "copilot", "工作流", "自动化"),
    "ai_content": ("AI 绘画", "AI 视频", "数字人", "AIGC", "文生图", "文生视频"),
    "ai_coding": ("AI 编程", "Cursor", "代码生成", "编程助手"),
    "ai_business": ("AI 创业", "AI 变现", "商业化", "降本增效"),
    "ai_policy": ("监管", "政策", "合规", "版权"),
}


PLATFORM_WEIGHTS: dict[Platform, float] = {
    Platform.DOUYIN: 1.15,
    Platform.XIAOHONGSHU: 1.05,
    Platform.WECHAT: 1.1,
    Platform.TOUTIAO: 1.0,
}
