"""WeChat article writing agent based on discovered hotspot evidence."""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from html import unescape
from typing import Any

from app.schemas.hotspot import GeneratedArticle, HotnessScore, HotspotState, NormalizedContent, ProductInsight, TrendCluster
from app.tools.qwen_rewrite_client import QwenRewriteClient, is_quota_error, is_timeout_error
from app.tools.api import WechatRewriteSkill


REWRITE_SIMILARITY_MIN = 25
REWRITE_SIMILARITY_MAX = 30


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
        rewrite_prompt = _rewrite_prompt_for(primary, scores, skill)
        rewrite_result, llm_usage = _execute_rewrite_prompt(rewrite_prompt)
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

    return f"""### 改写标题

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


def _append_compliance_report(body_markdown: str, compliance: dict[str, object]) -> str:
    if "### 合规检测" in body_markdown:
        return body_markdown

    report = _compliance_report_from_result(compliance)
    return f"{body_markdown.rstrip()}\n\n{report}"


def _compliance_report(body_markdown: str, primary: NormalizedContent | None) -> str:
    return _compliance_report_from_result(_compliance_result(body_markdown, primary))


def _compliance_result(body_markdown: str, primary: NormalizedContent | None) -> dict[str, object]:
    source_text = _comparison_text(f"{primary.title}\n{primary.text}" if primary else "")
    rewrite_text = _comparison_text(_published_text_for_similarity(body_markdown))
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
        reason = "与原文相似度偏低，说明改动过大；建议恢复原文结构、信息顺序和关键表达。"
    else:
        reason = "与原文相似度偏高，建议替换连续句式和局部表达，但不要大改原文结构。"
    return f"""### 合规检测

- 与原文相似度：{similarity}%
- 合规判断：{verdict}
- 判断标准：目标相似度为 {min_similarity}%-{max_similarity}%；低于 {min_similarity}% 说明改动过大，高于 {max_similarity}% 说明过于接近
- 说明：{reason}"""


def _published_text_for_similarity(body_markdown: str) -> str:
    text = re.split(r"\n### 内部改写依据\b|\n### wechat-rewrite 任务 Prompt\b", body_markdown, maxsplit=1)[0]
    return text


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
    return round(max(sequence_ratio, dice_ratio) * 100)


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
            if client is None:
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
    return os.getenv("QWEN_REWRITE_PREFER_LOCAL", "1").lower() not in {"0", "false", "no"}


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

<p>为了避免把长文压缩成短摘要，下面按原文顺序保留主要信息块，并用更适合公众号阅读的表达重新组织。</p>

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
