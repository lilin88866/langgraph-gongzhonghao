"""Workflow graph for AI hotspot analysis.

The module exposes a LangGraph builder when ``langgraph`` is installed and a
sequential fallback runner for local study without extra dependencies.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from html import escape, unescape
from typing import Any

from app.agents import (
    AIRelevanceAgent,
    ContentStrategyAgent,
    HotnessScoringAgent,
    NormalizationAgent,
    PlatformCollectionAgent,
    ProductInsightAgent,
    QualityControlAgent,
    ReportGenerationAgent,
    SourceDiscoveryAgent,
    TaskRouterAgent,
    TrendAnalysisAgent,
    WechatAccountDiscoveryAgent,
    WechatArticleWritingAgent,
)
from app.config.env import load_dotenv
from app.schemas.hotspot import ContentStrategy, FollowUpDecision, HotspotState, Platform

load_dotenv()

GraphNode = Callable[[HotspotState], HotspotState]


NODE_ORDER: tuple[str, ...] = (
    "task_router",
    "source_discovery",
    "wechat_account_discovery",
    "platform_collection",
    "normalization",
    "ai_relevance",
    "hotness_scoring",
    "trend_analysis",
    "product_insight",
    "content_strategy",
    "wechat_article_writing",
    "quality_control",
    "report_generation",
)

CANDIDATE_NODE_ORDER: tuple[str, ...] = (
    "task_router",
    "source_discovery",
    "wechat_account_discovery",
    "platform_collection",
    "normalization",
    "ai_relevance",
    "hotness_scoring",
    "trend_analysis",
    "quality_control",
)


def build_nodes() -> dict[str, GraphNode]:
    """Build all workflow nodes with explicit agent ownership."""

    return {
        "task_router": TaskRouterAgent().invoke,
        "source_discovery": SourceDiscoveryAgent().invoke,
        "wechat_account_discovery": WechatAccountDiscoveryAgent().invoke,
        "platform_collection": PlatformCollectionAgent().invoke,
        "normalization": NormalizationAgent().invoke,
        "ai_relevance": AIRelevanceAgent().invoke,
        "hotness_scoring": HotnessScoringAgent().invoke,
        "trend_analysis": TrendAnalysisAgent().invoke,
        "product_insight": ProductInsightAgent().invoke,
        "content_strategy": ContentStrategyAgent().invoke,
        "wechat_article_writing": WechatArticleWritingAgent().invoke,
        "quality_control": QualityControlAgent().invoke,
        "report_generation": ReportGenerationAgent().invoke,
    }


class SequentialHotspotGraph:
    """Small runner with the same invoke shape as a compiled LangGraph app."""

    def __init__(self, nodes: dict[str, GraphNode] | None = None, node_order: tuple[str, ...] = NODE_ORDER) -> None:
        self.nodes = nodes or build_nodes()
        self.node_order = node_order

    def invoke(self, state: HotspotState | None = None) -> HotspotState:
        current: HotspotState = dict(state or {})
        for node_name in self.node_order:
            update = self.nodes[node_name](current)
            current.update(update)
        return current


def build_langgraph_app() -> Any:
    """Compile the workflow with LangGraph when the dependency is installed."""

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("Install langgraph to build the compiled graph.") from exc

    graph = StateGraph(HotspotState)
    nodes = build_nodes()
    for node_name, node in nodes.items():
        graph.add_node(node_name, node)

    graph.add_edge(START, "task_router")
    for current, following in zip(NODE_ORDER, NODE_ORDER[1:]):
        graph.add_edge(current, following)
    graph.add_edge(NODE_ORDER[-1], END)
    return graph.compile()


def build_hotspot_workflow(prefer_langgraph: bool = True) -> Any:
    """Return a compiled LangGraph app or a sequential fallback runner."""

    if prefer_langgraph:
        try:
            return build_langgraph_app()
        except RuntimeError:
            pass
    return SequentialHotspotGraph()


def build_rewrite_candidate_workflow() -> SequentialHotspotGraph:
    """Build the candidate refresh workflow without article generation or Qwen calls."""

    return SequentialHotspotGraph(node_order=CANDIDATE_NODE_ORDER)


def requires_human_review(state: HotspotState) -> bool:
    """Human gate predicate for API layers or durable workflow orchestration."""

    return bool(state.get("human_review_required"))


def format_hotspot_report(state: HotspotState) -> str:
    """Render a CLI-friendly Chinese report from the workflow state."""

    report = state.get("report")
    if report is None:
        return "暂无报告：workflow 尚未生成 report。"

    lines: list[str] = [
        f"# {report.title}",
        "",
        report.summary,
        "",
        "## 热点榜",
    ]
    lines.extend(_format_hotspot_ranking(state))
    lines.extend(["", "## 趋势"])
    lines.extend(_format_trends(state))
    lines.extend(["", "## 分类内容明细"])
    lines.extend(_format_classified_contents(state))
    lines.extend(["", "## 自动发现公众号"])
    lines.extend(_format_wechat_accounts(state))
    lines.extend(["", "## 产品机会"])
    lines.extend(_format_product_insights(state))
    lines.extend(["", "## 选题建议"])
    lines.extend(_format_content_strategies(state))
    lines.extend(["", "## Agent 生成公众号文章"])
    lines.extend(_format_generated_article(state))
    lines.extend(["", "## 审核项"])
    lines.extend(_format_review_items(state))
    return "\n".join(lines)


def format_hotspot_report_html(state: HotspotState) -> str:
    """Render a browser-friendly HTML report with zebra tables."""

    report = state.get("report")
    if report is None:
        return _html_page("暂无报告", "<p>workflow 尚未生成 report。</p>")

    sections = [
        f"<section class='hero'><h1>{_html_text(report.title)}</h1><p>{_html_text(report.summary)}</p></section>",
        "<section><h2>热点榜</h2>" + _format_hotspot_ranking_html(state) + "</section>",
        "<section><h2>趋势</h2>" + _format_trends_html(state) + "</section>",
        "<section><h2>分类内容明细</h2>" + _format_classified_contents_html(state) + "</section>",
        "<section><h2>自动发现公众号</h2>" + _format_wechat_accounts_html(state) + "</section>",
        "<section><h2>产品机会</h2>" + _format_product_insights_html(state) + "</section>",
        "<section><h2>选题建议</h2>" + _format_content_strategies_html(state) + "</section>",
        "<section><h2>Agent 生成公众号文章</h2>" + _format_generated_article_html(state) + "</section>",
        "<section><h2>审核项</h2>" + _format_review_items_html(state) + "</section>",
    ]
    return _html_page(report.title, "\n".join(sections))


def _format_hotspot_ranking(state: HotspotState, limit: int = 10) -> list[str]:
    contents = {content.content_id: content for content in state.get("normalized_contents", [])}
    relevance_by_id = {item.content_id: item for item in state.get("ai_relevance", [])}
    trend_by_content_id = _trend_by_content_id(state)
    rows: list[str] = []
    rows.append("| 排名 | 分类 | 平台 | 公众号/作者 | 标题 | 热度 | 阅读 | 点赞 | 评论 | 链接 |")
    rows.append("| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |")
    for index, score in enumerate(state.get("hotness_scores", [])[:limit], start=1):
        content = contents.get(score.content_id)
        if content is None:
            continue
        metrics = content.metrics
        category = trend_by_content_id.get(score.content_id)
        if category is None:
            relevance = relevance_by_id.get(score.content_id)
            category = _category_label(relevance.categories[0]) if relevance and relevance.categories else "未分类"
        rows.append(
            "| "
            f"{index} | "
            f"{_table_cell(category)} | "
            f"{_platform_label(content.platform)} | "
            f"{_table_cell(_author_label(content))} | "
            f"{_link_cell(_clip(_clean_text(content.title), 72), content.url)} | "
            f"{score.hotness_score} | "
            f"{metrics.views or metrics.reads or 0} | "
            f"{metrics.likes or 0} | "
            f"{metrics.comments or 0} | "
            f"{_link_cell('原文', content.url)} |"
        )
    return rows if len(rows) > 2 else ["暂无可展示热点内容。"]


def _format_hotspot_ranking_html(state: HotspotState, limit: int = 20) -> str:
    contents = {content.content_id: content for content in state.get("normalized_contents", [])}
    relevance_by_id = {item.content_id: item for item in state.get("ai_relevance", [])}
    trend_by_content_id = _trend_by_content_id(state)
    rows: list[list[str]] = []
    for index, score in enumerate(state.get("hotness_scores", [])[:limit], start=1):
        content = contents.get(score.content_id)
        if content is None:
            continue
        metrics = content.metrics
        category = trend_by_content_id.get(score.content_id)
        if category is None:
            relevance = relevance_by_id.get(score.content_id)
            category = _category_label(relevance.categories[0]) if relevance and relevance.categories else "未分类"
        rows.append(
            [
                str(index),
                _badge(category),
                _html_text(_platform_label(content.platform)),
                _html_text(_author_label(content)),
                _html_link(_clip(_clean_text(content.title), 96), content.url),
                _number(score.hotness_score),
                str(metrics.views or metrics.reads or 0),
                str(metrics.likes or 0),
                str(metrics.comments or 0),
                _html_link("原文", content.url),
            ]
        )
    if not rows:
        return "<p class='empty'>暂无可展示热点内容。</p>"
    return _html_table(["排名", "分类", "平台", "公众号/作者", "标题", "热度", "阅读", "点赞", "评论", "链接"], rows)


def _format_trends(state: HotspotState) -> list[str]:
    contents = {content.content_id: content for content in state.get("normalized_contents", [])}
    rows: list[str] = []
    for index, trend in enumerate(state.get("trends", []), start=1):
        platforms = "、".join(_platform_label(platform) for platform in trend.platforms)
        rows.append(
            f"{index}. {trend.name} | 热度 {trend.hotness_score} | "
            f"生命周期：{_lifecycle_label(trend.lifecycle)} | 平台：{platforms}"
        )
        rows.append(f"   摘要：{trend.summary}")
        evidence_titles = [
            _clean_text(contents[content_id].title) for content_id in trend.evidence if content_id in contents
        ]
        rows.append(f"   代表内容：{'；'.join(evidence_titles) if evidence_titles else '暂无'}")
    return rows or ["暂无趋势。"]


def _format_trends_html(state: HotspotState) -> str:
    contents = {content.content_id: content for content in state.get("normalized_contents", [])}
    rows: list[list[str]] = []
    for index, trend in enumerate(state.get("trends", []), start=1):
        platforms = "、".join(_platform_label(platform) for platform in trend.platforms)
        evidence_titles = [
            _clean_text(contents[content_id].title) for content_id in trend.evidence if content_id in contents
        ]
        rows.append(
            [
                str(index),
                _html_text(trend.name),
                _number(trend.hotness_score),
                _html_text(_lifecycle_label(trend.lifecycle)),
                _html_text(platforms),
                _html_text(trend.summary),
                _html_text("；".join(evidence_titles) if evidence_titles else "暂无"),
            ]
        )
    if not rows:
        return "<p class='empty'>暂无趋势。</p>"
    return _html_table(["序号", "趋势", "热度", "生命周期", "平台", "摘要", "代表内容"], rows)


def _format_classified_contents(state: HotspotState, limit_per_group: int = 12) -> list[str]:
    contents = {content.content_id: content for content in state.get("normalized_contents", [])}
    score_by_id = {score.content_id: score for score in state.get("hotness_scores", [])}
    relevance_by_id = {item.content_id: item for item in state.get("ai_relevance", [])}
    rows: list[str] = []

    used_content_ids: set[str] = set()
    for trend in state.get("trends", []):
        content_ids = sorted(
            trend.content_ids,
            key=lambda content_id: score_by_id.get(content_id).hotness_score if content_id in score_by_id else 0,
            reverse=True,
        )
        rows.append(f"### {trend.name}")
        rows.append("| 标题 | 平台 | 公众号/作者 | 热度 | AI 置信度 | 关键词 | 链接 |")
        rows.append("| --- | --- | --- | ---: | ---: | --- | --- |")
        added = 0
        for content_id in content_ids:
            content = contents.get(content_id)
            if content is None:
                continue
            score = score_by_id.get(content_id)
            relevance = relevance_by_id.get(content_id)
            rows.append(
                "| "
                f"{_link_cell(_clip(_clean_text(content.title), 80), content.url)} | "
                f"{_platform_label(content.platform)} | "
                f"{_table_cell(_author_label(content))} | "
                f"{score.hotness_score if score else 0} | "
                f"{relevance.confidence if relevance else 0} | "
                f"{_table_cell('、'.join(relevance.keywords[:5]) if relevance else '')} | "
                f"{_link_cell('原文', content.url)} |"
            )
            used_content_ids.add(content_id)
            added += 1
            if added >= limit_per_group:
                break
        if len(content_ids) > limit_per_group:
            rows.append(f"表格仅展示前 {limit_per_group} 条，本分类共 {len(content_ids)} 条。")
        rows.append("")

    uncategorized = [
        content_id
        for content_id, relevance in relevance_by_id.items()
        if relevance.is_ai_related and content_id not in used_content_ids
    ]
    if uncategorized:
        rows.append("### 其他 AI 相关内容")
        rows.append("| 标题 | 平台 | 公众号/作者 | AI 分类 | AI 置信度 | 链接 |")
        rows.append("| --- | --- | --- | --- | ---: | --- |")
        for content_id in uncategorized[:limit_per_group]:
            content = contents.get(content_id)
            relevance = relevance_by_id.get(content_id)
            if content is None or relevance is None:
                continue
            rows.append(
                "| "
                f"{_link_cell(_clip(_clean_text(content.title), 80), content.url)} | "
                f"{_platform_label(content.platform)} | "
                f"{_table_cell(_author_label(content))} | "
                f"{_table_cell('、'.join(_category_label(category) for category in relevance.categories) or 'AI 综合热点')} | "
                f"{relevance.confidence} | "
                f"{_link_cell('原文', content.url)} |"
            )
    return rows or ["暂无分类内容。"]


def _format_classified_contents_html(state: HotspotState, limit_per_group: int = 20) -> str:
    contents = {content.content_id: content for content in state.get("normalized_contents", [])}
    score_by_id = {score.content_id: score for score in state.get("hotness_scores", [])}
    relevance_by_id = {item.content_id: item for item in state.get("ai_relevance", [])}
    cards: list[str] = []
    used_content_ids: set[str] = set()

    for trend in state.get("trends", []):
        content_ids = sorted(
            trend.content_ids,
            key=lambda content_id: score_by_id.get(content_id).hotness_score if content_id in score_by_id else 0,
            reverse=True,
        )
        rows: list[list[str]] = []
        for content_id in content_ids[:limit_per_group]:
            content = contents.get(content_id)
            if content is None:
                continue
            score = score_by_id.get(content_id)
            relevance = relevance_by_id.get(content_id)
            rows.append(
                [
                    _html_link(_clip(_clean_text(content.title), 100), content.url),
                    _html_text(_platform_label(content.platform)),
                    _html_text(_author_label(content)),
                    _number(score.hotness_score if score else 0),
                    _number(relevance.confidence if relevance else 0),
                    _html_text("、".join(relevance.keywords[:5]) if relevance else ""),
                    _html_link("原文", content.url),
                ]
            )
            used_content_ids.add(content_id)
        note = ""
        if len(content_ids) > limit_per_group:
            note = f"<p class='note'>仅展示前 {limit_per_group} 条，本分类共 {len(content_ids)} 条。</p>"
        cards.append(
            "<div class='category-card'>"
            f"<h3>{_html_text(trend.name)}</h3>"
            + _html_table(["标题", "平台", "公众号/作者", "热度", "AI 置信度", "关键词", "链接"], rows)
            + note
            + "</div>"
        )

    uncategorized = [
        content_id
        for content_id, relevance in relevance_by_id.items()
        if relevance.is_ai_related and content_id not in used_content_ids
    ]
    if uncategorized:
        rows = []
        for content_id in uncategorized[:limit_per_group]:
            content = contents.get(content_id)
            relevance = relevance_by_id.get(content_id)
            if content is None or relevance is None:
                continue
            rows.append(
                [
                    _html_link(_clip(_clean_text(content.title), 100), content.url),
                    _html_text(_platform_label(content.platform)),
                    _html_text(_author_label(content)),
                    _html_text("、".join(_category_label(category) for category in relevance.categories) or "AI 综合热点"),
                    _number(relevance.confidence),
                    _html_link("原文", content.url),
                ]
            )
        cards.append(
            "<div class='category-card'>"
            "<h3>其他 AI 相关内容</h3>"
            + _html_table(["标题", "平台", "公众号/作者", "AI 分类", "AI 置信度", "链接"], rows)
            + "</div>"
        )
    return "\n".join(cards) if cards else "<p class='empty'>暂无分类内容。</p>"


def _format_product_insights(state: HotspotState) -> list[str]:
    trend_by_id = {trend.trend_id: trend for trend in state.get("trends", [])}
    rows: list[str] = []
    for index, insight in enumerate(state.get("product_insights", []), start=1):
        trend_name = trend_by_id.get(insight.trend_id).name if insight.trend_id in trend_by_id else insight.trend_id
        rows.append(f"{index}. {trend_name} | 建议：{_decision_label(insight.decision)}")
        rows.append(f"   用户痛点：{insight.user_pain}")
        rows.append(f"   产品机会：{insight.product_opportunity}")
        rows.append(f"   验证假设：{insight.validation_hypothesis}")
        rows.append(f"   目标用户：{'、'.join(insight.target_users)}")
    return rows or ["暂无产品机会。"]


def _format_wechat_accounts(state: HotspotState) -> list[str]:
    accounts = state.get("wechat_accounts", [])
    if not accounts:
        return ["暂无自动发现公众号。"]
    rows = ["| 公众号 | fakeid | 匹配关键词 | 相关度 | 已订阅 | 原因 |", "| --- | --- | --- | ---: | --- | --- |"]
    for account in accounts:
        rows.append(
            "| "
            f"{_table_cell(account.nickname)} | "
            f"{_table_cell(account.fakeid)} | "
            f"{_table_cell('、'.join(account.matched_keywords))} | "
            f"{account.relevance_score} | "
            f"{'是' if account.subscribed else '否'} | "
            f"{_table_cell(account.reason)} |"
        )
    return rows


def _format_wechat_accounts_html(state: HotspotState) -> str:
    rows = []
    for account in state.get("wechat_accounts", []):
        rows.append(
            [
                _html_text(account.nickname),
                _html_text(account.fakeid),
                _html_text("、".join(account.matched_keywords)),
                _number(account.relevance_score),
                _html_text("是" if account.subscribed else "否"),
                _html_text(account.reason),
            ]
        )
    if not rows:
        return "<p class='empty'>暂无自动发现公众号。</p>"
    return _html_table(["公众号", "fakeid", "匹配关键词", "相关度", "已订阅", "原因"], rows)


def _format_product_insights_html(state: HotspotState) -> str:
    trend_by_id = {trend.trend_id: trend for trend in state.get("trends", [])}
    rows: list[list[str]] = []
    for index, insight in enumerate(state.get("product_insights", []), start=1):
        trend_name = trend_by_id.get(insight.trend_id).name if insight.trend_id in trend_by_id else insight.trend_id
        rows.append(
            [
                str(index),
                _html_text(trend_name),
                _html_text(_decision_label(insight.decision)),
                _html_text(insight.user_pain),
                _html_text(insight.product_opportunity),
                _html_text(insight.validation_hypothesis),
                _html_text("、".join(insight.target_users)),
            ]
        )
    if not rows:
        return "<p class='empty'>暂无产品机会。</p>"
    return _html_table(["序号", "趋势", "建议", "用户痛点", "产品机会", "验证假设", "目标用户"], rows)


def _format_content_strategies(state: HotspotState) -> list[str]:
    trend_by_id = {trend.trend_id: trend for trend in state.get("trends", [])}
    grouped: dict[Platform, list[ContentStrategy]] = {}
    for strategy in state.get("content_strategies", []):
        grouped.setdefault(strategy.platform, []).append(strategy)

    rows: list[str] = []
    for platform, strategies in sorted(grouped.items(), key=lambda item: item[0].value):
        rows.append(f"### {_platform_label(platform)}")
        for strategy in strategies:
            trend_name = (
                trend_by_id[strategy.trend_id].name
                if strategy.trend_id in trend_by_id
                else strategy.trend_id
            )
            rows.append(f"- {strategy.title_direction}")
            rows.append(f"  趋势：{trend_name} | 形式：{strategy.format_suggestion}")
            rows.append(f"  核心观点：{strategy.core_argument}")
    return rows or ["暂无选题建议。"]


def _format_content_strategies_html(state: HotspotState) -> str:
    trend_by_id = {trend.trend_id: trend for trend in state.get("trends", [])}
    rows: list[list[str]] = []
    for strategy in state.get("content_strategies", []):
        trend_name = (
            trend_by_id[strategy.trend_id].name
            if strategy.trend_id in trend_by_id
            else strategy.trend_id
        )
        rows.append(
            [
                _html_text(_platform_label(strategy.platform)),
                _html_text(strategy.title_direction),
                _html_text(trend_name),
                _html_text(strategy.format_suggestion),
                _html_text(strategy.core_argument),
            ]
        )
    if not rows:
        return "<p class='empty'>暂无选题建议。</p>"
    return _html_table(["平台", "标题方向", "趋势", "形式", "核心观点"], rows)


def _format_review_items(state: HotspotState) -> list[str]:
    flags = state.get("quality_flags", [])
    if not state.get("human_review_required") and not flags:
        return ["无需人工审核：未发现质量告警。"]
    rows = ["需要人工审核。"]
    rows.extend(f"- {_clean_text(flag)}" for flag in flags)
    return rows


def _format_generated_article(state: HotspotState) -> list[str]:
    article = state.get("generated_article")
    if article is None:
        return ["暂无生成文章。"]
    return [
        f"### {article.title}",
        "",
        article.subtitle,
        "",
        article.body_markdown,
        "",
        _format_llm_usage(article.llm_usage),
        "",
        f"推荐标签：{'、'.join(article.recommended_tags)}",
    ]


def _format_review_items_html(state: HotspotState) -> str:
    flags = state.get("quality_flags", [])
    if not state.get("human_review_required") and not flags:
        return "<p class='ok'>无需人工审核：未发现质量告警。</p>"
    items = "".join(f"<li>{_html_text(flag)}</li>" for flag in flags)
    return f"<p class='warn'>需要人工审核。</p><ul class='flags'>{items}</ul>"


def _format_generated_article_html(state: HotspotState) -> str:
    article = state.get("generated_article")
    if article is None:
        return "<p class='empty'>暂无生成文章。</p>"
    paragraphs = []
    for line in article.body_markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            paragraphs.append(f"<h3>{_html_text(stripped.removeprefix('## '))}</h3>")
        elif stripped.startswith("- "):
            paragraphs.append(f"<li>{_html_text(stripped.removeprefix('- '))}</li>")
        else:
            paragraphs.append(f"<p>{_html_text(stripped)}</p>")
    tags = "".join(f"<span class='badge'>{_html_text(tag)}</span>" for tag in article.recommended_tags)
    usage = _format_llm_usage(article.llm_usage)
    return (
        "<article class='generated-article'>"
        f"<h3>{_html_text(article.title)}</h3>"
        f"<p class='note'>{_html_text(article.subtitle)}</p>"
        + "\n".join(paragraphs)
        + f"<p class='note'>{_html_text(usage)}</p>"
        + f"<p>推荐标签：{tags}</p>"
        + "</article>"
    )


def _format_llm_usage(usage: dict[str, Any] | None) -> str:
    if not usage:
        return "LLM Token：未调用，token 使用 0。"
    model = str(usage.get("model") or "unknown")
    total = usage.get("total_tokens")
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if total is None:
        return f"LLM Token：{model} 已调用，但服务端未返回 token usage。"
    return f"LLM Token：{model} 总计 {total}，输入 {prompt if prompt is not None else '未知'}，输出 {completion if completion is not None else '未知'}。"


def _platform_label(platform: Platform) -> str:
    return {
        Platform.DOUYIN: "抖音",
        Platform.XIAOHONGSHU: "小红书",
        Platform.WECHAT: "微信公众号",
        Platform.TOUTIAO: "今日头条",
    }[platform]


def _decision_label(decision: FollowUpDecision) -> str:
    return {
        FollowUpDecision.WATCH: "值得关注",
        FollowUpDecision.VALIDATE: "值得验证",
        FollowUpDecision.SKIP: "暂不跟进",
    }[decision]


def _lifecycle_label(lifecycle: str) -> str:
    return {
        "emerging": "萌芽",
        "rising": "上升",
        "peaking": "高峰",
        "cooling": "降温",
    }.get(lifecycle, lifecycle)


def _trend_by_content_id(state: HotspotState) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for trend in state.get("trends", []):
        for content_id in trend.content_ids:
            mapping[content_id] = trend.name
    return mapping


def _category_label(category: str) -> str:
    return {
        "large_model": "大模型产品更新",
        "ai_product": "AI 产品与智能体工作流",
        "ai_content": "AI 内容生成",
        "ai_coding": "AI 编程工具",
        "ai_business": "AI 商业化与创业",
        "ai_policy": "AI 政策与合规",
        "ai_general": "AI 综合热点",
    }.get(category, category)


def _author_label(content: Any) -> str:
    if content.author:
        return _clean_text(content.author)
    account = content.raw_payload.get("account") if isinstance(content.raw_payload, dict) else None
    if isinstance(account, dict):
        nickname = account.get("nickname") or account.get("name") or account.get("wechat_name")
        if nickname:
            return _clean_text(str(nickname))
    return "未知"


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", unescape(value or ""))
    return " ".join(text.split())


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _table_cell(value: str) -> str:
    return _clean_text(str(value)).replace("|", "\\|")


def _link_cell(label: str, url: str | None) -> str:
    safe_label = _table_cell(label)
    if not url:
        return safe_label
    return f"[{safe_label}]({url})"


def _html_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html_text(title)}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f6f8fb;
      --card: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #d9e2ef;
      --head: #edf3fb;
      --stripe: #f8fbff;
      --accent: #2563eb;
      --warn: #b45309;
      --ok: #047857;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #0b1020;
        --card: #121a2b;
        --text: #e5e7eb;
        --muted: #9ca3af;
        --line: #263244;
        --head: #1b2740;
        --stripe: #0f172a;
        --accent: #60a5fa;
      }}
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    main {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px 20px 56px;
    }}
    section, .category-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
      margin: 18px 0;
      padding: 20px;
      overflow-x: auto;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(37, 99, 235, 0.12), rgba(14, 165, 233, 0.08)), var(--card);
    }}
    h1, h2, h3 {{
      margin: 0 0 12px;
      line-height: 1.25;
    }}
    h1 {{ font-size: 28px; }}
    h2 {{ font-size: 22px; }}
    h3 {{ font-size: 18px; }}
    p {{ margin: 8px 0; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      border-spacing: 0;
      min-width: 860px;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: var(--head);
      color: var(--text);
      font-weight: 700;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    tbody tr:nth-child(even) {{ background: var(--stripe); }}
    tbody tr:hover {{ background: rgba(37, 99, 235, 0.08); }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .badge {{
      display: inline-block;
      border-radius: 999px;
      background: rgba(37, 99, 235, 0.12);
      color: var(--accent);
      padding: 2px 9px;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 600;
    }}
    .note, .empty {{ color: var(--muted); }}
    .warn {{ color: var(--warn); font-weight: 700; }}
    .ok {{ color: var(--ok); font-weight: 700; }}
    .flags {{ margin: 8px 0 0; padding-left: 20px; }}
  </style>
</head>
<body>
  <main>
    {body}
  </main>
</body>
</html>"""


def _html_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "<p class='empty'>暂无数据。</p>"
    head = "".join(f"<th>{_html_text(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _html_text(value: Any) -> str:
    return escape(_clean_text(str(value)), quote=True)


def _html_link(label: str, url: str | None) -> str:
    safe_label = _html_text(label)
    if not url:
        return safe_label
    return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{safe_label}</a>'


def _badge(value: str) -> str:
    return f"<span class='badge'>{_html_text(value)}</span>"


def _number(value: float | int) -> str:
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


if __name__ == "__main__":
    workflow = build_hotspot_workflow(prefer_langgraph=False)
    result = workflow.invoke({})
    print(format_hotspot_report(result))
