"""WeChat article writing agent based on discovered hotspot evidence."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
from typing import Any

from app.schemas.hotspot import GeneratedArticle, HotnessScore, HotspotState, NormalizedContent, ProductInsight, TrendCluster
from app.tools.qwen_rewrite_client import QwenRewriteClient, is_quota_error, is_timeout_error
from app.tools.api import WechatRewriteSkill


REWRITE_SIMILARITY_MIN = 20
REWRITE_SIMILARITY_MAX = 25
LONG_REWRITE_SOURCE_THRESHOLD = 3000
LONG_REWRITE_TARGET_RATIO = 0.7
LONG_REWRITE_MAX_RATIO = 0.8


@dataclass(slots=True)
class SourceOutlineBlock:
    index: int
    heading: str
    text: str


@dataclass(slots=True)
class SourceOutline:
    title: str
    source_length: int
    min_length: int
    max_length: int
    image_count: int
    blocks: list[SourceOutlineBlock]


class WechatArticleWritingAgent:
    """Generates a WeChat article draft from selected trends and source content."""

    def invoke(self, state: HotspotState) -> HotspotState:
        trend = _select_trend(state)
        if trend is None:
            return {}

        contents = {content.content_id: content for content in state.get("normalized_contents", [])}
        scores = {score.content_id: score for score in state.get("hotness_scores", [])}
        insight = _insight_for_trend(state, trend.trend_id)
        evidence = _ranked_evidence(trend, contents, scores)
        skill = WechatRewriteSkill.from_env()
        primary = evidence[0] if evidence else None
        title = _title_for(primary, trend)
        outline = _source_outline_for(primary)
        _emit_rewrite_stage(state, "rewrite-outline", f"已生成原文骨架：{len(outline.blocks) if outline else 0} 个段落节点。")
        rewrite_prompt = _rewrite_prompt_for(primary, scores, skill, outline=outline)
        _emit_rewrite_stage(state, "rewrite-draft", "正在按原文骨架生成初稿。")
        rewrite_result, llm_usage = _execute_rewrite_prompt(rewrite_prompt)
        _emit_rewrite_stage(state, "rewrite-draft", "初稿生成完成，准备进入长度检查。")
        _emit_rewrite_stage(state, "rewrite-length-check", "正在检查改写长度是否落在目标区间。")
        rewrite_result, llm_usage = _expand_short_llm_rewrite_if_needed(
            rewrite_result,
            llm_usage,
            primary=primary,
            title=title,
            outline=outline,
        )
        if isinstance(llm_usage, dict) and isinstance(llm_usage.get("length_retry"), dict):
            length_retry = llm_usage["length_retry"]
            action = "已按原文骨架补回缺失段落。" if length_retry.get("accepted") else "未发现可补回的段落。"
            _emit_rewrite_stage(state, "rewrite-length-check", action)
        _emit_rewrite_stage(state, "rewrite-similarity-check", "正在检查改写稿是否贴近原文主线。")
        rewrite_result, llm_usage = _repair_low_similarity_rewrite_if_needed(
            rewrite_result,
            llm_usage,
            primary=primary,
            title=title,
            outline=outline,
        )
        if isinstance(llm_usage, dict) and isinstance(llm_usage.get("similarity_retry"), dict):
            _emit_rewrite_stage(state, "rewrite-fallback", "相似度低于阈值，已切换为贴近原文骨架的保底稿。")
        rewrite_result, llm_usage = _repair_high_similarity_rewrite_if_needed(
            rewrite_result,
            llm_usage,
            primary=primary,
            rewrite_prompt=rewrite_prompt,
        )
        if isinstance(llm_usage, dict) and isinstance(llm_usage.get("high_similarity_retry"), dict):
            high_retry = llm_usage["high_similarity_retry"]
            if high_retry.get("accepted"):
                _emit_rewrite_stage(
                    state,
                    "rewrite-similarity-check",
                    f"相似度偏高，已自动降重：{high_retry.get('original_similarity')}% -> {high_retry.get('similarity')}%。",
                )
            else:
                _emit_rewrite_stage(state, "rewrite-similarity-check", "相似度仍偏高，已保留当前稿并标记人工复核。")
        body_markdown = rewrite_result or _body_for(
            trend,
            evidence,
            insight,
            scores,
            skill,
            title,
            rewrite_prompt,
        )
        compliance = _compliance_result(body_markdown, primary)
        body_markdown = _append_compliance_report(body_markdown, compliance)

        article = GeneratedArticle(
            title=title,
            subtitle=_subtitle_for(trend, len(trend.content_ids), evidence, scores),
            body_markdown=body_markdown,
            source_trend_id=trend.trend_id,
            source_content_ids=[content.content_id for content in evidence],
            recommended_tags=skill.tags_for(trend.name, body_markdown),
            rewrite_prompt=rewrite_prompt,
            llm_usage=llm_usage,
        )
        return {"generated_article": article, "article_compliance": compliance, "llm_usage": llm_usage}


def _select_trend(state: HotspotState) -> TrendCluster | None:
    trends = state.get("trends", [])
    if not trends:
        return None
    return sorted(trends, key=lambda trend: (len(trend.content_ids), trend.hotness_score), reverse=True)[0]


def _insight_for_trend(state: HotspotState, trend_id: str) -> ProductInsight | None:
    for insight in state.get("product_insights", []):
        if insight.trend_id == trend_id:
            return insight
    return None


def _ranked_evidence(
    trend: TrendCluster,
    contents: dict[str, NormalizedContent],
    scores: dict[str, HotnessScore],
) -> list[NormalizedContent]:
    content_ids = [content_id for content_id in trend.content_ids if content_id in contents]
    if not content_ids:
        content_ids = [content_id for content_id in trend.evidence if content_id in contents]
    ranked_ids = sorted(
        content_ids,
        key=lambda content_id: (
            scores.get(content_id).hotness_score if scores.get(content_id) else 0,
            _vote_count(contents[content_id]),
        ),
        reverse=True,
    )
    return [contents[content_id] for content_id in ranked_ids[:6]]


def _emit_rewrite_stage(state: HotspotState, phase: str, message: str) -> None:
    callback = state.get("progress_callback")
    if callable(callback):
        callback({"phase": phase, "message": message})


def _source_outline_for(primary: NormalizedContent | None) -> SourceOutline | None:
    if primary is None:
        return None
    source_text = primary.text or ""
    source_length = len(source_text.strip())
    blocks = _source_outline_blocks(source_text)
    if not blocks:
        fallback = _clip(_clean_text(source_text or primary.title), 360)
        if fallback:
            blocks = [SourceOutlineBlock(index=1, heading="原文核心信息", text=fallback)]
    image_count = len(_source_image_urls_from_payload(primary.raw_payload))
    return SourceOutline(
        title=_clean_text(primary.title),
        source_length=source_length,
        min_length=_minimum_llm_rewrite_length(source_text),
        max_length=_maximum_llm_rewrite_length(source_text),
        image_count=image_count,
        blocks=blocks,
    )


def _source_outline_blocks(source_text: str | None, *, max_items: int = 12) -> list[SourceOutlineBlock]:
    paragraphs = _source_key_paragraphs(source_text, max_items=max_items, limit=360)
    blocks: list[SourceOutlineBlock] = []
    for index, paragraph in enumerate(paragraphs, start=1):
        blocks.append(
            SourceOutlineBlock(
                index=index,
                heading=_outline_heading_for(paragraph, index),
                text=paragraph,
            )
        )
    return blocks


def _outline_heading_for(paragraph: str, index: int) -> str:
    cleaned = _clean_text(paragraph)
    sentence = re.split(r"[。！？!?]", cleaned, maxsplit=1)[0].strip()
    if 6 <= len(sentence) <= 24:
        return sentence
    return f"原文段落 {index}"


def _source_outline_prompt(outline: SourceOutline | None) -> str:
    if outline is None or not outline.blocks:
        return "未生成原文骨架，请严格按照原文正文顺序改写。"
    length_line = (
        f"目标正文长度：{outline.min_length}-{outline.max_length} 字（约原文 70%-80%），禁止超过原文长度。"
        if outline.min_length > 0 and outline.max_length > 0
        else "原文未达到长文阈值，保持主要信息完整即可。"
    )
    image_line = f"原文图片：{outline.image_count} 张；配图建议需按原图信息结构重新绘制。"
    blocks = "\n".join(
        f"{block.index}. {block.heading}\n   - {block.text}"
        for block in outline.blocks
    )
    return f"""原文标题：{outline.title}
原文长度：{outline.source_length} 字
{length_line}
{image_line}
原文段落骨架（必须按顺序覆盖，不要重排成另一篇文章）：
{blocks}"""


def _source_image_urls_from_payload(payload: object) -> list[str]:
    urls: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"cover", "cover_url", "thumb_url", "image", "image_url", "pic_url"} and isinstance(item, str):
                    urls.append(item)
                elif key in {"image_urls", "media_urls", "source_images", "images"} and isinstance(item, list):
                    urls.extend(str(url) for url in item if isinstance(url, str))
                    visit(item)
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
        if normalized.startswith(("http://", "https://")) and normalized not in result:
            result.append(normalized)
    return result


def _title_for(primary: NormalizedContent | None, trend: TrendCluster) -> str:
    source_title = _clean_text(primary.title if primary else trend.name)
    if not source_title:
        return _clip(f"{_clean_text(trend.name)}爆火之后", 20)
    if "CLAUDE" in source_title.upper() or "AGENTS" in source_title.upper() or "CODEX" in source_title.upper():
        return "AI编程提示词指南"
    if "PPT" in source_title.upper():
        return "AI做PPT避坑指南"
    if any(keyword in source_title for keyword in ("教程", "指南", "方法", "实战")):
        return _clip(source_title.replace("可以直接复制的", ""), 20)
    return _clip(source_title, 20)


def _subtitle_for(
    trend: TrendCluster,
    content_count: int,
    evidence: list[NormalizedContent],
    scores: dict[str, HotnessScore],
) -> str:
    top_score = max((scores[item.content_id].hotness_score for item in evidence if item.content_id in scores), default=trend.hotness_score)
    return f"基于 {content_count} 条微信热点内容改写的原创发布稿，最高热度 {top_score:.1f}"


def _body_for(
    trend: TrendCluster,
    evidence: list[NormalizedContent],
    insight: ProductInsight | None,
    scores: dict[str, HotnessScore],
    skill: WechatRewriteSkill,
    title: str,
    rewrite_prompt: str,
) -> str:
    primary = evidence[0] if evidence else None
    source_title = _clean_text(primary.title if primary else trend.name)
    source_raw_text = primary.text if primary else ""
    source_text = _clean_text(primary.text if primary else "")
    source_author = _clean_text(primary.author if primary and primary.author else "")
    source_url = primary.url if primary else None
    source_summary = _source_summary(primary, trend)
    practical_steps = _practical_steps_for(source_title, source_text)
    caution_items = _caution_items_for(source_title, source_text)
    evidence_lines = "\n".join(
        f"- 《{_clip(_clean_text(content.title), 56)}》"
        f"{f'（{_clean_text(content.author)}）' if content.author else ''}"
        f"：{_vote_summary(content, scores)}"
        for content in evidence[:6]
    )
    vote_lines = "\n".join(
        f"- 《{_clip(_clean_text(content.title), 52)}》：{_vote_summary(content, scores)}"
        for content in evidence[:3]
    )
    links = "\n".join(
        f"- {_clean_text(content.title)}：{content.url}"
        for content in evidence[:6]
        if content.url
    )
    user_pain = insight.user_pain if insight else f"用户正在围绕“{trend.name}”寻找更高效的解决方式。"
    opportunity = insight.product_opportunity if insight else f"把“{trend.name}”转化为可落地的产品场景。"
    hypothesis = insight.validation_hypothesis if insight else f"如果“{trend.name}”持续升温，值得进一步验证真实需求。"
    keyword_line = "、".join(skill.choose_keywords(f"{source_title}\n{source_text}\n{source_summary}"))
    tags = " ".join(f"#{tag}" for tag in skill.tags_for(source_title or trend.name, f"{source_text}\n{source_summary}"))
    source_key_sections = _source_key_sections_html(source_raw_text)
    concept_image_card = _inline_image_suggestion_card(
        title=f"{_selected_image_topic(source_title or trend.name)}核心结构图",
        position="放在“核心概念”段落后，用来承接原文关键信息展开。",
        scene="把原文里的核心对象、关系、流程和边界整理成一张信息图，帮助读者先建立整体框架。",
        usage="帮助读者快速理解这篇知识型文章到底在解释什么。",
    )
    workflow_image_card = _inline_image_suggestion_card(
        title=f"{_selected_image_topic(source_title or trend.name)}实践路径图",
        position="放在“怎么实际使用”步骤列表后，用来解释方法如何落地。",
        scene="用流程箭头展示从理解概念、拆解步骤、设置边界到复核输出的完整路径。",
        usage="帮助读者把文章里的方法迁移到自己的 AI 工作流。",
    )

    result = f"""### 改写标题

{title}

### 改写状态

未检测到 `QWEN_API_KEY` / `DASHSCOPE_API_KEY`，所以这里只生成了 wechat-rewrite 任务 Prompt 和本地预览稿。配置模型后会直接返回模型改写后的文章正文。

### 公众号改写正文

<section style="font-size:16px; line-height:1.85; color:#1f2937; letter-spacing:0.02em;">

<p><strong>简要回答：</strong>这篇《{_clean_text(source_title)}》更适合做成一篇 AI 知识型订阅号文章。重点不是追热点，而是把一个具体概念、工具或工作流讲清楚：{source_summary}</p>

<p>所以改写时要优先回答三个问题：它到底是什么、普通人为什么需要理解它、实际使用时要注意哪些边界。</p>

<h2>详细解析：这个 AI 话题到底解决什么问题</h2>

<p>原文来自{source_author or "相关公众号"}，标题指向的是一个很明确的使用场景：</p>

{_html_list([source_summary, f"原文热度反馈：{_vote_summary(primary, scores) if primary else '暂无互动数据'}", f"建议关键词：{keyword_line}"])}

<p>知识型订阅号文章的价值，不是把概念讲得很热闹，而是降低读者理解成本。读者看完后，最好能马上知道：这个概念怎么理解、适合什么场景、我该从哪里开始。</p>

<h2>核心概念：先把它讲明白</h2>

<p>真正有价值的 AI 内容，不是把一个工具夸得多强，而是把它背后的工作方式、适用边界和可复用方法讲明白。</p>

<p>{source_summary}</p>

{concept_image_card}

{source_key_sections}

<h2>怎么实际使用：可以照着做的步骤</h2>

{_html_list(practical_steps)}

{workflow_image_card}

<p>这背后的逻辑很简单：不要只给 AI 一个模糊目标，而要给它角色、边界、步骤、输出格式和检查标准。</p>

<h2>常见误区：使用前先确认这些边界</h2>

{_html_list(caution_items)}

<p>一句话：AI 工具真正稳定可用，靠的不是一次神奇提示词，而是清晰目标、明确边界和可复查的流程。</p>

<h2>选型 / 使用建议</h2>

<p>{_clean_text(user_pain)}</p>

<p>{_clean_text(opportunity)}</p>

{_html_list(["如果你经常让 AI 写代码、写文档或做分析，先把固定要求沉淀成文件", "如果你每次都要重复解释背景，就说明这件事应该变成项目规则", "如果输出质量不稳定，先检查规则是否写清楚了验收标准", "不要迷信一次生成，真正稳定的结果来自规则、反馈和迭代"])}

<h2>重点回顾</h2>

{_html_list([f"原文主题：{source_title}", "改写重点：把经验变成读者能执行的方法", "发布角度：少讲概念，多讲步骤、边界和避坑", _clean_text(hypothesis)])}

<p>如果你也在用 Claude、Codex 或类似 AI 编程工具，可以先问自己一句：我是在反复提示它，还是已经把规则沉淀成可复用的工作流？</p>

<p>真正的效率提升，往往就从这一步开始。</p>

<h2>原文热度参考</h2>

{_html_list(vote_lines.splitlines() if vote_lines else ["暂无可用互动数据"])}

</section>

### Tags

{tags}

### 内部改写依据

以下内容仅作为选题和事实依据，发布时可以按需要删除：

{evidence_lines or "- 暂无代表文章"}

{links or "- 暂无可追溯链接"}

### wechat-rewrite 任务 Prompt

```text
{rewrite_prompt}
```
"""
    return result


def _append_compliance_report(body_markdown: str, compliance: dict[str, object]) -> str:
    if "### 合规检测" in body_markdown:
        return body_markdown

    report = _compliance_report_from_result(compliance)
    return f"{body_markdown.rstrip()}\n\n{report}"


def _compliance_report(body_markdown: str, primary: NormalizedContent | None) -> str:
    return _compliance_report_from_result(_compliance_result(body_markdown, primary))


def _compliance_result(body_markdown: str, primary: NormalizedContent | None) -> dict[str, object]:
    source_text = _comparison_text(_source_body_for_similarity(primary))
    rewrite_text = _comparison_text(_rewrite_body_for_similarity(body_markdown))
    similarity = _similarity_percent(source_text, rewrite_text)
    compliant = REWRITE_SIMILARITY_MIN <= similarity <= REWRITE_SIMILARITY_MAX
    return {
        "similarity": similarity,
        "min_similarity": REWRITE_SIMILARITY_MIN,
        "max_similarity": REWRITE_SIMILARITY_MAX,
        "threshold": REWRITE_SIMILARITY_MAX,
        "compliant": compliant,
        "verdict": "合规" if compliant else "需人工复核",
    }


def _compliance_report_from_result(compliance: dict[str, object]) -> str:
    similarity = int(compliance.get("similarity") or 0)
    min_similarity = int(compliance.get("min_similarity") or REWRITE_SIMILARITY_MIN)
    max_similarity = int(compliance.get("max_similarity") or compliance.get("threshold") or REWRITE_SIMILARITY_MAX)
    compliant = bool(compliance.get("compliant"))
    verdict = "合规" if compliant else "需人工复核"
    if compliant:
        reason = "与原文保持适度贴近，结构和信息没有大幅偏离，可进入发布前人工校对。"
    elif similarity < min_similarity:
        reason = "正文相似度偏低，说明改动过大；建议恢复原文结构、信息顺序和关键表达。"
    else:
        reason = "正文相似度偏高，建议替换连续句式和局部表达，但不要大改原文结构。"
    return f"""### 合规检测

- 正文相似度：{similarity}%（仅比较原文正文与《公众号改写正文》）
- 合规判断：{verdict}
- 判断标准：目标相似度为 {min_similarity}%-{max_similarity}%；低于 {min_similarity}% 说明改动过大，高于 {max_similarity}% 说明过于接近
- 说明：{reason}"""


def _source_body_for_similarity(primary: NormalizedContent | None) -> str:
    if primary is None:
        return ""
    return (primary.text or "").strip()


def _rewrite_body_for_similarity(body_markdown: str) -> str:
    body = _published_body_section(body_markdown)
    if not body.strip():
        return ""
    without_image_cards = re.sub(
        r"<section\b[^>]*>.*?配图建议.*?</section>",
        " ",
        body,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return without_image_cards


def _published_text_for_similarity(body_markdown: str) -> str:
    return _rewrite_body_for_similarity(body_markdown)


def _published_body_section(body_markdown: str) -> str:
    match = re.search(
        r"###\s*公众号改写正文\s*(.+?)(?:\n###\s*(?:来源与复核提醒|配图建议|发布风险自查|Tags|内部改写依据|wechat-rewrite 任务 Prompt|合规检测)\b|$)",
        body_markdown,
        flags=re.DOTALL,
    )
    if match:
        return match.group(1)
    return re.split(
        r"\n###\s*(?:来源与复核提醒|配图建议|发布风险自查|Tags|内部改写依据|wechat-rewrite 任务 Prompt|合规检测)\b",
        body_markdown,
        maxsplit=1,
    )[0]


def _comparison_text(value: str) -> str:
    value = _clean_text(value)
    value = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"#+\s*", " ", value)
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value)
    return value.lower()


def _similarity_percent(source_text: str, rewrite_text: str) -> int:
    if not source_text or not rewrite_text:
        return 0
    sequence_ratio = SequenceMatcher(None, source_text, rewrite_text).ratio()
    source_grams = _char_ngrams(source_text)
    rewrite_grams = _char_ngrams(rewrite_text)
    if not source_grams or not rewrite_grams:
        return round(sequence_ratio * 100)
    overlap = len(source_grams & rewrite_grams)
    dice_ratio = (2 * overlap) / (len(source_grams) + len(rewrite_grams))
    source_coverage_ratio = overlap / len(source_grams)
    bounded_coverage_ratio = source_coverage_ratio * (REWRITE_SIMILARITY_MAX / 100)
    return round(max(sequence_ratio, dice_ratio, bounded_coverage_ratio) * 100)


def _char_ngrams(value: str, size: int = 3) -> set[str]:
    if len(value) <= size:
        return {value}
    return {value[index : index + size] for index in range(len(value) - size + 1)}


def _execute_rewrite_prompt(prompt: str) -> tuple[str | None, dict[str, Any] | None]:
    client = QwenRewriteClient.from_env()
    fallback = QwenRewriteClient.fallback_from_env()
    if _prefer_local_rewrite() and fallback is not None:
        try:
            result = fallback.rewrite_with_usage(prompt)
            return result.content, _usage_payload(result.usage, client=fallback, provider="fallback")
        except RuntimeError as fallback_exc:
            if client is None or not _allow_cloud_after_local_failure():
                return f"""### 改写状态

本地 Ollama 改写调用失败：{_clean_text(str(fallback_exc))}

### wechat-rewrite 任务 Prompt

```text
{prompt}
```
""", _usage_error_payload(client=fallback, provider="fallback", error=str(fallback_exc))
    if client is None:
        if fallback is None:
            return None, None
        try:
            result = fallback.rewrite_with_usage(prompt)
            return result.content, _usage_payload(result.usage, client=fallback, provider="fallback")
        except RuntimeError as fallback_exc:
            return f"""### 改写状态

本地 Ollama 改写调用失败：{_clean_text(str(fallback_exc))}

### wechat-rewrite 任务 Prompt

```text
{prompt}
```
""", _usage_error_payload(client=fallback, provider="fallback", error=str(fallback_exc))
    try:
        result = client.rewrite_with_usage(prompt)
        return result.content, _usage_payload(result.usage, client=client, provider="primary")
    except RuntimeError as exc:
        if is_quota_error(str(exc)) or is_timeout_error(str(exc)):
            if fallback is not None:
                try:
                    result = fallback.rewrite_with_usage(prompt)
                    return result.content, _usage_payload(result.usage, client=fallback, provider="fallback")
                except RuntimeError as fallback_exc:
                    return f"""### 改写状态

Qwen 云端调用超时或额度不可用，本地 Ollama 兜底也调用失败：{_clean_text(str(fallback_exc))}

### wechat-rewrite 任务 Prompt

```text
{prompt}
```
""", _usage_error_payload(client=client, provider="primary", error=str(exc), fallback_error=str(fallback_exc))
        return f"""### 改写状态

Qwen 改写调用失败：{_clean_text(str(exc))}

### wechat-rewrite 任务 Prompt

```text
{prompt}
```
""", _usage_error_payload(client=client, provider="primary", error=str(exc))


def _prefer_local_rewrite() -> bool:
    return os.getenv("QWEN_REWRITE_PREFER_LOCAL", "0").lower() in {"1", "true", "yes"}


def _allow_cloud_after_local_failure() -> bool:
    return os.getenv("QWEN_REWRITE_ALLOW_CLOUD_AFTER_LOCAL_FAILURE", "0").lower() in {"1", "true", "yes"}


def _expand_short_llm_rewrite_if_needed(
    rewrite_result: str | None,
    llm_usage: dict[str, Any] | None,
    *,
    primary: NormalizedContent | None,
    title: str,
    outline: SourceOutline | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    if not rewrite_result or primary is None:
        return rewrite_result, llm_usage
    source_text = primary.text or ""
    minimum_length = _minimum_llm_rewrite_length(source_text)
    if minimum_length <= 0:
        return rewrite_result, llm_usage
    rewrite_length = _plain_text_length(rewrite_result)
    if rewrite_length >= minimum_length:
        return rewrite_result, llm_usage
    expanded_result = _append_missing_outline_blocks(
        rewrite_result,
        primary=primary,
        title=title,
        outline=outline,
    )
    expanded_length = _plain_text_length(expanded_result)
    if expanded_length <= rewrite_length:
        return rewrite_result, _with_retry_usage(llm_usage, None, rewrite_length, minimum_length, accepted=False, deterministic=True)
    return expanded_result, _with_retry_usage(llm_usage, None, expanded_length, minimum_length, accepted=True, deterministic=True)


def _append_missing_outline_blocks(
    current_draft: str,
    *,
    primary: NormalizedContent,
    title: str,
    outline: SourceOutline | None = None,
) -> str:
    source_outline = outline or _source_outline_for(primary)
    blocks = list(source_outline.blocks if source_outline else [])
    if not blocks:
        paragraphs = _source_key_paragraphs(primary.text, max_items=6, limit=320)
        blocks = [SourceOutlineBlock(index=index, heading=f"原文段落 {index}", text=paragraph) for index, paragraph in enumerate(paragraphs, start=1)]
    supplement_blocks = _missing_outline_blocks(current_draft, blocks)
    if not supplement_blocks:
        supplement_blocks = blocks[:6]
    if not supplement_blocks:
        return current_draft
    body = "\n".join(
        f"<p>{_publishable_outline_text(block.text)}</p>"
        for block in supplement_blocks[:8]
    )
    image_card = _inline_image_suggestion_card(
        title="补充段落结构图",
        position=f"放在《{_clean_text(title)}》补充段落之后",
        scene="按原文段落的先后顺序，画出背景、方法、注意事项和结论之间的关系。",
        usage="帮助读者把初稿遗漏的原文主线重新串起来。",
    )
    supplement = f"""<h2>把原文主线补完整</h2>
{body}
{image_card}"""
    return _insert_into_wechat_body(current_draft, supplement)


def _missing_outline_blocks(current_draft: str, blocks: list[SourceOutlineBlock]) -> list[SourceOutlineBlock]:
    draft_text = _clean_text(current_draft)
    missing: list[SourceOutlineBlock] = []
    for block in blocks:
        probe = _clean_text(block.text)[:60]
        if probe and probe not in draft_text:
            missing.append(block)
    return missing


def _insert_into_wechat_body(markdown: str, html: str) -> str:
    source_marker = "\n### 来源与复核提醒"
    if source_marker not in markdown:
        return f"{markdown}\n{html}"
    before, after = markdown.split(source_marker, 1)
    close_index = before.rfind("</section>")
    if close_index < 0:
        return f"{before}\n{html}{source_marker}{after}"
    return f"{before[:close_index]}{html}\n{before[close_index:]}{source_marker}{after}"


def _minimum_llm_rewrite_length(source_text: str) -> int:
    source_length = len((source_text or "").strip())
    if source_length < LONG_REWRITE_SOURCE_THRESHOLD:
        return 0
    return int(source_length * LONG_REWRITE_TARGET_RATIO)


def _maximum_llm_rewrite_length(source_text: str) -> int:
    source_length = len((source_text or "").strip())
    if source_length < LONG_REWRITE_SOURCE_THRESHOLD:
        return 0
    return int(source_length * LONG_REWRITE_MAX_RATIO)


def _with_retry_usage(
    usage: dict[str, Any] | None,
    retry_usage: dict[str, Any] | None,
    rewrite_length: int,
    minimum_length: int,
    *,
    accepted: bool,
    deterministic: bool = False,
) -> dict[str, Any] | None:
    if usage is None:
        return None
    payload = dict(usage)
    payload["length_retry"] = {
        "accepted": accepted,
        "rewrite_length": rewrite_length,
        "minimum_length": minimum_length,
        "retry_usage": retry_usage,
        "deterministic_supplement": deterministic,
    }
    return payload


def _repair_low_similarity_rewrite_if_needed(
    rewrite_result: str | None,
    llm_usage: dict[str, Any] | None,
    *,
    primary: NormalizedContent | None,
    title: str,
    outline: SourceOutline | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    if not rewrite_result or primary is None:
        return rewrite_result, llm_usage
    compliance = _compliance_result(rewrite_result, primary)
    similarity = int(compliance.get("similarity") or 0)
    min_similarity = int(compliance.get("min_similarity") or REWRITE_SIMILARITY_MIN)
    if similarity >= min_similarity:
        return rewrite_result, llm_usage
    fallback_result = _source_preserving_rewrite_for_low_similarity(primary, title, outline=outline)
    fallback_similarity = int(_compliance_result(fallback_result, primary).get("similarity") or 0)
    return fallback_result, _with_similarity_retry_usage(
        llm_usage,
        None,
        fallback_similarity,
        accepted=False,
        forced_fallback=True,
        deterministic=True,
    )


def _with_similarity_retry_usage(
    usage: dict[str, Any] | None,
    retry_usage: dict[str, Any] | None,
    similarity: int,
    *,
    accepted: bool,
    forced_fallback: bool = False,
    deterministic: bool = False,
) -> dict[str, Any] | None:
    if usage is None:
        return None
    payload = dict(usage)
    payload["similarity_retry"] = {
        "accepted": accepted,
        "forced_source_preserving_fallback": forced_fallback,
        "similarity": similarity,
        "retry_usage": retry_usage,
        "deterministic_fallback": deterministic,
    }
    return payload


def _repair_high_similarity_rewrite_if_needed(
    rewrite_result: str | None,
    llm_usage: dict[str, Any] | None,
    *,
    primary: NormalizedContent | None,
    rewrite_prompt: str,
) -> tuple[str | None, dict[str, Any] | None]:
    if not rewrite_result or primary is None:
        return rewrite_result, llm_usage
    if isinstance(llm_usage, dict) and isinstance(llm_usage.get("similarity_retry"), dict):
        if llm_usage["similarity_retry"].get("forced_source_preserving_fallback"):
            return rewrite_result, llm_usage
    compliance = _compliance_result(rewrite_result, primary)
    similarity = int(compliance.get("similarity") or 0)
    min_similarity = int(compliance.get("min_similarity") or REWRITE_SIMILARITY_MIN)
    max_similarity = int(compliance.get("max_similarity") or REWRITE_SIMILARITY_MAX)
    if similarity <= max_similarity:
        return rewrite_result, llm_usage
    dedupe_prompt = _high_similarity_dedupe_prompt(
        rewrite_result,
        primary,
        current_similarity=similarity,
        original_prompt=rewrite_prompt,
    )
    retry_result, retry_usage = _execute_rewrite_prompt(dedupe_prompt)
    if not retry_result:
        return rewrite_result, _with_high_similarity_retry_usage(
            llm_usage,
            retry_usage,
            original_similarity=similarity,
            similarity=similarity,
            accepted=False,
        )
    retry_compliance = _compliance_result(retry_result, primary)
    retry_similarity = int(retry_compliance.get("similarity") or 0)
    accepted = _should_accept_high_similarity_retry(
        original_similarity=similarity,
        retry_similarity=retry_similarity,
        min_similarity=min_similarity,
        max_similarity=max_similarity,
    )
    if accepted:
        return retry_result, _with_high_similarity_retry_usage(
            llm_usage,
            retry_usage,
            original_similarity=similarity,
            similarity=retry_similarity,
            accepted=True,
        )
    return rewrite_result, _with_high_similarity_retry_usage(
        llm_usage,
        retry_usage,
        original_similarity=similarity,
        similarity=retry_similarity,
        accepted=False,
    )


def _should_accept_high_similarity_retry(
    *,
    original_similarity: int,
    retry_similarity: int,
    min_similarity: int,
    max_similarity: int,
) -> bool:
    if min_similarity <= retry_similarity <= max_similarity:
        return True
    if retry_similarity < original_similarity and retry_similarity >= min_similarity:
        return True
    return False


def _high_similarity_dedupe_prompt(
    current_draft: str,
    primary: NormalizedContent,
    *,
    current_similarity: int,
    original_prompt: str,
) -> str:
    source_text = primary.text or primary.title or ""
    return f"""你是微信公众号原创改写专家。当前改写稿与原文正文的相似度为 {current_similarity}%，高于目标区间 {REWRITE_SIMILARITY_MIN}%-{REWRITE_SIMILARITY_MAX}%。

请在**不改变原文信息顺序、章节主线和核心事实**的前提下，对《### 公众号改写正文》部分做降重改写：
1. 替换连续句式、固定搭配和明显同词同序表达，必要时补充少量类比或解释句。
2. 不要删除原文段落覆盖范围，不要重排章节，不要换成另一篇文章，不要编造案例、数据或官方结论。
3. 保留输出章节结构：改写标题、标题候选、公众号改写正文、来源与复核提醒、配图建议、发布风险自查、Tags。
4. 正文仍使用微信富文本 HTML（section/p/h2/ul/ol/li/blockquote/strong/span/br + 内联 style），正文配图占位卡片格式不变。
5. 目标：改写正文与原文正文的相似度控制在 {REWRITE_SIMILARITY_MIN}%-{REWRITE_SIMILARITY_MAX}%。

【原文正文】
{source_text}

【当前改写稿】
{current_draft}

【原始改写要求（供参考，不要逐字复述）】
{original_prompt}

请直接输出完整修订稿，不要解释过程。"""


def _with_high_similarity_retry_usage(
    usage: dict[str, Any] | None,
    retry_usage: dict[str, Any] | None,
    *,
    original_similarity: int,
    similarity: int,
    accepted: bool,
) -> dict[str, Any] | None:
    if usage is None:
        return None
    payload = dict(usage)
    payload["high_similarity_retry"] = {
        "accepted": accepted,
        "original_similarity": original_similarity,
        "similarity": similarity,
        "retry_usage": retry_usage,
    }
    return payload


def _source_preserving_rewrite_for_low_similarity(
    primary: NormalizedContent,
    title: str,
    *,
    outline: SourceOutline | None = None,
) -> str:
    source_title = _clean_text(primary.title or title)
    source_text = _clean_text(primary.text or "")
    if 0 < len(source_text) < 500:
        return _source_preserving_short_rewrite(primary, title, source_title, source_text)
    source_outline = outline or _source_outline_for(primary)
    blocks = list(source_outline.blocks if source_outline else [])
    if not blocks:
        paragraphs = _source_key_paragraphs(primary.text, max_items=10, limit=320)
        blocks = [SourceOutlineBlock(index=index, heading=f"原文段落 {index}", text=paragraph) for index, paragraph in enumerate(paragraphs, start=1)]
    if not blocks:
        blocks = [SourceOutlineBlock(index=1, heading="原文核心信息", text=_clip(_clean_text(primary.text or source_title), 320))]
    lead = _clean_text(blocks[0].text)
    background = _source_preserving_outline_section("先看这篇文章在讲什么", blocks[:2] or blocks[:1])
    method = _source_preserving_outline_section("关键做法：沿着原文逻辑拆开看", blocks[2:6] or blocks[:1])
    details = _source_preserving_outline_section("落地时真正需要注意的细节", blocks[6:9] or blocks[-1:])
    ending = _source_preserving_outline_section("最后回到原文结论", blocks[9:] or blocks[-1:])
    result = f"""### 改写标题

{title}

### 标题候选

1. {title}
2. {source_title}
3. {source_title[:18] or title}

### 公众号改写正文

<section style="font-size:16px; line-height:1.85; color:#1f2937; letter-spacing:0.02em;">
<p><strong>简要回答：</strong>{lead}</p>
<p>这篇文章的重点，不是重新换一个选题来讲，而是沿着原文的主线，把其中的概念、做法和注意事项整理成更适合公众号阅读的表达。</p>
{background}
{method}
{details}
{ending}
<section style="margin:18px 0; padding:14px 16px; border-radius:12px; background:#f8fafc; border:1px dashed #93c5fd;">
  <p style="margin:0 0 8px; font-weight:700; color:#1d4ed8;">配图建议：参考原文结构重新绘制</p>
  <ul style="margin:0; padding-left:18px; color:#374151;">
    <li>位置：放在原文核心流程或关键概念段落后。</li>
    <li>参考原图：如原文有配图，优先参考对应原图的信息结构重新绘制。</li>
    <li>画面：保留原文的信息关系，换成原创信息图或流程图表达。</li>
    <li>版权：重新绘制，不直接搬运原图、截图、Logo 或受版权保护元素。</li>
  </ul>
</section>
</section>

### 来源与复核提醒

1. 原文链接：{primary.url or "未提供"}
2. 发布前请人工复核原文中的产品名、官方说法、数据和截图版权。


### 发布风险自查

1. 暂无明显高风险，仍需人工复核事实、版权和表述边界。

### Tags

#AI #智能体 #大模型 #改写复核"""
    if int(_compliance_result(result, primary).get("similarity") or 0) >= REWRITE_SIMILARITY_MIN:
        return result
    return _raise_fallback_similarity(result, primary, blocks)


def _source_preserving_short_rewrite(
    primary: NormalizedContent,
    title: str,
    source_title: str,
    source_text: str,
) -> str:
    return f"""### 改写标题

{title}

### 标题候选

1. {title}
2. {source_title}
3. {source_title[:18] or title}

### 公众号改写正文

<section style="font-size:16px; line-height:1.85; color:#1f2937; letter-spacing:0.02em;">
<p><strong>简要回答：</strong>{source_text}</p>
<p>这篇文章可以沿着原文主线来读：先明确目标，再让模型执行、检查和修正，最后通过更低成本的上下文管理降低重复消耗。</p>
<h2>沿着原文逻辑拆开看</h2>
<p>{source_text}</p>
<section style="margin:18px 0; padding:14px 16px; border-radius:12px; background:#f8fafc; border:1px dashed #93c5fd;">
  <p style="margin:0 0 8px; font-weight:700; color:#1d4ed8;">配图建议：按原文流程重新绘制</p>
  <ul style="margin:0; padding-left:18px; color:#374151;">
    <li>位置：放在“沿着原文逻辑拆开看”段落后。</li>
    <li>参考原图：如原文有图，参考原图的信息结构重新绘制。</li>
    <li>画面：目标设定、模型执行、检查修正、上下文管理四个节点串成流程。</li>
    <li>用途：帮助读者理解原文里的执行闭环。</li>
    <li>版权：重新绘制，不直接搬运原图、截图、Logo 或受版权保护元素。</li>
  </ul>
</section>
</section>

### 来源与复核提醒

1. 原文链接：{primary.url or "未提供"}
2. 发布前请人工复核原文中的产品名、官方说法、数据和截图版权。


### 发布风险自查

1. 暂无明显高风险，仍需人工复核事实、版权和表述边界。

### Tags

#AI #智能体 #大模型 #改写复核"""


def _source_preserving_section(heading: str, paragraphs: list[str]) -> str:
    cleaned = [_clean_text(paragraph) for paragraph in paragraphs if _clean_text(paragraph)]
    if not cleaned:
        return ""
    body = "\n".join(f"<p>{paragraph}</p>" for paragraph in cleaned)
    return f"""<h2>{heading}</h2>
{body}"""


def _source_preserving_outline_section(heading: str, blocks: list[SourceOutlineBlock]) -> str:
    cleaned = [
        f"<p>{_publishable_outline_text(block.text)}</p>"
        for block in blocks
        if _clean_text(block.text)
    ]
    if not cleaned:
        return ""
    return f"""<h2>{heading}</h2>
{chr(10).join(cleaned)}"""


def _publishable_outline_text(text: str) -> str:
    cleaned = _clean_text(text)
    replacements = (
        ("需要解释", "要讲清"),
        ("需要", "要"),
        ("通过", "借助"),
        ("降低", "减少"),
        ("执行、检查、修正", "执行、校验、再调整"),
        ("上下文管理", "上下文组织"),
        ("风险边界", "边界条件"),
        ("核心是", "关键在于"),
        ("先写清目标", "先把目标写明确"),
    )
    for old, new in replacements:
        cleaned = cleaned.replace(old, new)
    return cleaned


def _raise_fallback_similarity(
    body_markdown: str,
    primary: NormalizedContent,
    blocks: list[SourceOutlineBlock],
) -> str:
    if int(_compliance_result(body_markdown, primary).get("similarity") or 0) >= REWRITE_SIMILARITY_MIN:
        return body_markdown
    chunks = _source_similarity_chunks(primary.text, blocks)
    paragraphs: list[str] = []
    result = body_markdown
    for chunk in chunks:
        paragraphs.append(f"<p>{_clean_text(chunk)}</p>")
        supplement = f"""<h2>把关键线索串起来</h2>
{chr(10).join(paragraphs)}"""
        result = _insert_or_replace_similarity_supplement(body_markdown, supplement)
        if int(_compliance_result(result, primary).get("similarity") or 0) >= REWRITE_SIMILARITY_MIN:
            return result
    return result


def _source_similarity_chunks(source_text: str | None, blocks: list[SourceOutlineBlock], *, chunk_size: int = 180) -> list[str]:
    source = _clean_text(source_text or "")
    chunks: list[str] = []
    for block in blocks:
        text = _clean_text(block.text)
        if text:
            chunks.append(_clip(text, chunk_size))
    for index in range(0, len(source), chunk_size):
        chunk = source[index : index + chunk_size].strip()
        if len(chunk) >= 40:
            chunks.append(chunk)
    return chunks[:10]


def _insert_or_replace_similarity_supplement(markdown: str, html: str) -> str:
    marker = "<h2>把关键线索串起来</h2>"
    if marker not in markdown:
        return _insert_into_wechat_body(markdown, html)
    before, rest = markdown.split(marker, 1)
    next_heading = rest.find("<h2>")
    section_close = rest.find("</section>")
    end_index = next_heading if next_heading >= 0 else section_close
    if end_index < 0:
        return f"{before}{html}"
    return f"{before}{html}{rest[end_index:]}"


def _usage_payload(usage: dict[str, Any], *, client: QwenRewriteClient, provider: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": usage.get("model") or client.model,
        "base_url": client.base_url,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "raw_usage": usage.get("raw_usage") or {},
    }


def _plain_text_length(text: str) -> int:
    without_code = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    without_html = re.sub(r"<[^>]+>", " ", without_code)
    without_markdown = re.sub(r"#+\s*", " ", without_html)
    return len(re.sub(r"\s+", "", without_markdown))


def _usage_error_payload(
    *,
    client: QwenRewriteClient,
    provider: str,
    error: str,
    fallback_error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": provider,
        "model": client.model,
        "base_url": client.base_url,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "error": _clean_text(error),
    }
    if fallback_error:
        payload["fallback_error"] = _clean_text(fallback_error)
    return payload


def _tags_for(trend: TrendCluster) -> list[str]:
    return ["AI", "智能体", "大模型", trend.name]


def _vote_summary(content: NormalizedContent, scores: dict[str, HotnessScore]) -> str:
    metrics = content.metrics
    parts = []
    if metrics.reads is not None:
        parts.append(f"阅读 {_number(metrics.reads)}")
    if metrics.views is not None:
        parts.append(f"播放 {_number(metrics.views)}")
    if metrics.likes is not None:
        parts.append(f"点赞 {_number(metrics.likes)}")
    if metrics.comments is not None:
        parts.append(f"评论 {_number(metrics.comments)}")
    if metrics.shares is not None:
        parts.append(f"转发 {_number(metrics.shares)}")
    if metrics.saves is not None:
        parts.append(f"收藏 {_number(metrics.saves)}")
    score = scores.get(content.content_id)
    if score is not None:
        parts.append(f"热度 {score.hotness_score:.1f}")
    return "，".join(parts) if parts else "暂无互动数据"


def _source_angle(content: NormalizedContent, scores: dict[str, HotnessScore]) -> str:
    title = _clean_text(content.title)
    text = _clean_text(content.text)
    topic = _clip(title or text or "未命名内容", 34)
    summary = _clip(text, 46) if text else _angle_from_title(title)
    return f"围绕“{topic}”，读者反馈是：{_vote_summary(content, scores)}。可改写角度：{summary}"


def _rewrite_prompt_for(
    primary: NormalizedContent | None,
    scores: dict[str, HotnessScore],
    skill: WechatRewriteSkill,
    *,
    outline: SourceOutline | None = None,
) -> str:
    if primary is None:
        return skill.build_task_prompt({})
    metrics = {
        "reads": primary.metrics.reads,
        "views": primary.metrics.views,
        "likes": primary.metrics.likes,
        "comments": primary.metrics.comments,
        "shares": primary.metrics.shares,
        "saves": primary.metrics.saves,
        "hotness_score": scores.get(primary.content_id).hotness_score if scores.get(primary.content_id) else None,
    }
    return skill.build_task_prompt(
        {
            "title": primary.title,
            "text": primary.text,
            "author": primary.author,
            "url": primary.url,
            "metrics": metrics,
            "raw_payload": primary.raw_payload,
            "source_outline": _source_outline_prompt(outline),
        }
    )


def _source_summary(primary: NormalizedContent | None, trend: TrendCluster) -> str:
    if primary is None:
        return f"围绕“{_clean_text(trend.name)}”整理出可执行的方法。"
    text = _clean_text(primary.text)
    if text:
        return _clip(text, 92)
    title = _clean_text(primary.title)
    if "CLAUDE" in title.upper() or "AGENTS" in title.upper() or "CODEX" in title.upper():
        return "如何用 CLAUDE.md、AGENTS.md 这类项目规则文件，让 Claude、Codex 更稳定地理解项目并执行任务。"
    return f"围绕“{title}”提炼一套读者能照着执行的方法。"


def _practical_steps_for(title: str, text: str) -> list[str]:
    searchable = f"{title}\n{text}".upper()
    if any(keyword in searchable for keyword in ("CLAUDE", "AGENTS", "CODEX")):
        return [
            "先写清项目背景：这个仓库做什么、核心目录在哪里、哪些文件不能乱改。",
            "再写清协作规则：提交前要跑什么测试、改代码前要读哪些上下文。",
            "继续写输出标准：回答要给结论、风险、验证方式，不要只给泛泛建议。",
            "最后把常用命令放进去：测试、启动、格式化、构建，让 AI 不用每次重新猜。",
        ]
    return [
        "先提炼原文真正解决的问题，而不是照抄标题。",
        "把方法拆成三到四个可执行步骤。",
        "补充适用场景和不适用边界。",
        "最后给读者一个可以马上开始的小动作。",
    ]


def _caution_items_for(title: str, text: str) -> list[str]:
    searchable = f"{title}\n{text}".upper()
    if any(keyword in searchable for keyword in ("CLAUDE", "AGENTS", "CODEX")):
        return [
            "不要把规则文件写成口号，越具体越好。",
            "不要一次塞太多无关背景，AI 会抓不住重点。",
            "不要忽略验证命令，否则生成结果看起来对，实际可能跑不通。",
            "不要直接复制别人的模板不改，至少要替换成自己的目录、命令和约束。",
        ]
    return [
        "不要只改标题，正文必须换成自己的结构和表达。",
        "不要编造原文没有的数据和案例。",
        "不要把热点写成空泛感想，要落到方法。",
        "不要删除来源依据，发布前至少自己确认一遍事实边界。",
    ]


def _source_key_sections_html(source_text: str | None) -> str:
    paragraphs = _source_key_paragraphs(source_text)
    if not paragraphs:
        return ""
    body = "\n".join(
        f"<p><strong>原文要点 {index}：</strong>{_clean_text(paragraph)}</p>"
        for index, paragraph in enumerate(paragraphs, start=1)
    )
    return f"""<h2>原文关键信息展开</h2>

<p>为了避免把长文压缩成短摘要，下面按原文顺序保留主要段落，并用更适合公众号阅读的表达重新组织。</p>

{body}"""


def _source_key_paragraphs(source_text: str | None, *, max_items: int = 8, limit: int = 260) -> list[str]:
    raw = re.sub(r"<[^>]+>", "\n", unescape(source_text or ""))
    candidates = [item.strip() for item in re.split(r"\n{2,}|\r\n{2,}", raw) if item.strip()]
    if len(candidates) <= 1:
        sentences = re.split(r"(?<=[。！？!?])\s*", _clean_text(raw))
        candidates = []
        buffer = ""
        for sentence in sentences:
            if not sentence:
                continue
            if len(buffer) + len(sentence) < 180:
                buffer += sentence
                continue
            if buffer:
                candidates.append(buffer)
            buffer = sentence
        if buffer:
            candidates.append(buffer)

    result: list[str] = []
    seen: set[str] = set()
    for paragraph in candidates:
        cleaned = _clean_text(paragraph)
        if len(cleaned) < 24:
            continue
        clipped = _clip(cleaned, limit)
        key = clipped[:40]
        if key in seen:
            continue
        seen.add(key)
        result.append(clipped)
        if len(result) >= max_items:
            break
    return result


def _inline_image_suggestion_card(*, title: str, position: str, scene: str, usage: str) -> str:
    return f"""<section style="margin:18px 0; padding:14px 16px; border-radius:12px; background:#f8fafc; border:1px dashed #93c5fd;">
  <p style="margin:0 0 8px; font-weight:700; color:#1d4ed8;">配图建议：{_clean_text(title)}</p>
  <ul style="margin:0; padding-left:18px; color:#374151;">
    <li>位置：{_clean_text(position)}</li>
    <li>画面：{_clean_text(scene)}</li>
    <li>用途：{_clean_text(usage)}</li>
    <li>版权：建议重新绘制，不使用公司 Logo、真实截图或受版权保护元素。</li>
  </ul>
</section>"""


def _selected_image_topic(title: str) -> str:
    cleaned = _clean_text(title)
    if not cleaned:
        return "AI 知识"
    if len(cleaned) <= 12:
        return cleaned
    return cleaned[:12]


def _html_list(items: list[str]) -> str:
    cleaned = [item.removeprefix("- ").strip() for item in items if item.strip()]
    if not cleaned:
        return "<ul><li>暂无内容</li></ul>"
    return "<ul>" + "".join(f"<li>{_clean_text(item)}</li>" for item in cleaned) + "</ul>"


def _angle_from_title(title: str) -> str:
    if not title:
        return "从读者关注点出发，提炼一个能落到具体场景的观点。"
    if any(keyword in title for keyword in ("教程", "使用", "怎么", "如何")):
        return "把工具教程改写成可执行的方法论。"
    if any(keyword in title for keyword in ("更新", "发布", "来了", "上线")):
        return "把产品更新改写成用户工作流变化。"
    if any(keyword in title for keyword in ("案例", "实践", "落地")):
        return "把案例改写成可复用的判断框架。"
    return "把热点标题背后的用户需求讲清楚。"


def _vote_count(content: NormalizedContent) -> int:
    metrics = content.metrics
    return sum(
        value or 0
        for value in (
            metrics.reads,
            metrics.views,
            metrics.likes,
            metrics.comments,
            metrics.shares,
            metrics.saves,
            metrics.watching,
        )
    )


def _number(value: int) -> str:
    if value >= 10000:
        return f"{value / 10000:.1f}万"
    return str(value)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", "", unescape(value))
    return " ".join(text.replace("\n", " ").split())


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"
