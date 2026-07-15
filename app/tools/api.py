"""Loader for the external wechat-rewrite skill."""

from __future__ import annotations

import os
import re
from html import unescape
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_KEYWORDS = [
    "指南",
    "教程",
    "解析",
    "秘籍",
    "经验分享",
    "挑战",
    "故事",
    "案例分析",
    "趋势预测",
    "重要事件",
]

SUPPORTING_SKILL_NAMES = [
    "wechat-ai-topic-selector",
    "title-generator",
    "xiaolin-rewrite",
    "source-organizer",
    "image-caption-prompt",
    "wechat-prohibited-word",
]

WORKFLOW_PROMPT_RULES = {
    "wechat-ai-topic-selector": "优先选择 AI 概念、模型工具、Agent 工作流、自动化实践、工程方法和普通人可理解的知识型选题；放弃纯情绪、纯资讯、纯营销和缺少解释价值的热点。",
    "title-generator": "给出一个推荐标题和 3-5 个标题候选；标题要像订阅号知识文章，突出具体概念、读者收益和学习入口，不超过 20 字，避免“震惊、必看、100%”等夸张词。",
    "xiaolin-rewrite": "正文保持知识讲解型订阅号表达，但优先贴近原文的版式骨架、信息顺序和小标题层级；仅在原文结构混乱或缺少解释时，补充类比、流程、示例、常见误区、选型建议和重点回顾；禁止面试对话体。",
    "source-organizer": "保留原文链接和来源说明；对事实、数据、产品名、图片、截图、引用内容标记需要人工复核的点，不编造来源或授权。",
    "image-caption-prompt": "给出封面图方向，并把正文配图建议直接插入正文 HTML 的对应段落后；来源图片默认只参考信息结构，建议重新绘制，不复刻截图、Logo 或受版权保护元素。",
    "wechat-prohibited-word": "发布前自查夸大承诺、绝对化表达、医疗/金融/法律敏感表述、未经验证数据、版权、隐私和标题党风险，并给出替代表达。",
}


@dataclass(slots=True)
class WechatRewriteSkill:
    """Reads reusable rules from project-local WeChat publishing skills."""

    skill_dir: Path
    rules: str
    keywords: list[str]
    workflow_rules: str = ""

    @classmethod
    def from_env(cls) -> "WechatRewriteSkill":
        skill_dir = Path(os.getenv("WECHAT_REWRITE_SKILL_DIR", _default_skill_dir())).expanduser()
        rules = _read_rules(skill_dir)
        keywords = _extract_keywords(rules) or DEFAULT_KEYWORDS
        workflow_rules = _read_workflow_rules(skill_dir.parent)
        return cls(skill_dir=skill_dir, rules=rules, keywords=keywords, workflow_rules=workflow_rules)

    def choose_keywords(self, text: str, *, limit: int = 3) -> list[str]:
        selected = [keyword for keyword in self.keywords if keyword in text]
        for keyword in self.keywords:
            if len(selected) >= limit:
                break
            if keyword not in selected:
                selected.append(keyword)
        return selected[:limit]

    def tags_for(self, topic: str, text: str) -> list[str]:
        keywords = self.choose_keywords(text)
        base_tags = ["AI", "智能体", _tag_text(topic), *keywords]
        tags: list[str] = []
        for tag in base_tags:
            cleaned = _tag_text(tag)
            if cleaned and cleaned not in tags:
                tags.append(cleaned)
        return tags[:8]

    def build_task_prompt(self, article: dict[str, Any]) -> str:
        title = _clean(article.get("title"))
        text = _clean(article.get("text"))
        author = _clean(article.get("author"))
        url = _clean(article.get("url"))
        source_outline = str(article.get("source_outline") or "").strip()
        source_text_length = len(text)
        minimum_rewrite_length = _minimum_rewrite_length(source_text_length)
        source_image_count = _source_image_count(article)
        source_image_urls = _source_image_urls_from_article(article)
        metrics = article.get("metrics") if isinstance(article.get("metrics"), dict) else {}
        metric_line = "，".join(
            f"{label} {value}"
            for label, value in (
                ("阅读", metrics.get("reads") or metrics.get("views")),
                ("点赞", metrics.get("likes")),
                ("评论", metrics.get("comments")),
                ("转发", metrics.get("shares")),
                ("收藏", metrics.get("saves")),
                ("热度", metrics.get("hotness_score")),
            )
            if value not in (None, "")
        )
        keywords = "、".join(self.choose_keywords(f"{title}\n{text}"))
        rules = self.rules or "使用可信、有信息量、适合手机阅读的公众号表达，输出改写标题、公众号改写正文和 Tags。"
        workflow_rules = self.workflow_rules or "使用项目内置微信发布链路：选题筛选、标题优化、公众号改写、来源整理、配图建议和发布风险检查。"
        return f"""你是 `langgraph-study` 的微信公众号改写 Agent。账号定位是“AI 知识型/讲解型订阅号”：用通俗语言解释 AI 概念、模型工具、Agent 工作流和工程实践。目标是把原文改写成可人工发布的公众号草稿，要求贴近原文主题、结构和信息顺序，但替换具体表达。

【已接入的本地 Skills 工作流】
{workflow_rules}

【公众号规则】
{rules}

【原文信息】
- 标题：{title}
- 作者/公众号：{author or "未知"}
- 原文链接：{url or "无"}
- 热度指标：{metric_line or "暂无"}
- 建议关键词：{keywords}
- 原文图片：{_source_image_reference_text(source_image_urls, source_image_count)}

【原文正文/摘要】
{text or title}

【确定性原文骨架】
{source_outline or "未提供；请严格按照原文正文顺序改写。"}

【改写要求】
1. 必须先沿“确定性原文骨架”逐段润色：每个原文段落和章节主线都要覆盖，顺序不能重排，不能换成另一篇文章；正文里禁止出现任何内部实现标签、系统说明或失败兜底说明。
2. 文章必须偏知识解释和教程拆解，少写情绪、热词和营销判断；读者读完要获得一个可复用的 AI 概念、方法或工作流。
3. 保留核心事实、术语、方法价值和必要链接；不得编造案例、数据、发布日期、官方结论或授权信息。
4. LLM 只负责表达润色、句式替换、局部解释补充和公众号排版；不要重新设计选题、不要另起案例、不要把原文改成另一篇教程。
5. 原文正文长度约 {source_text_length} 字。{_length_requirement_text(source_text_length, minimum_rewrite_length)}
6. 相似度目标区间是 20%-25%。低于 20% 说明改动过大，需要恢复原文结构和关键表述；高于 25% 说明过于接近，需要替换连续句式和局部表达。降重主要通过换句式、换类比、调整段落表达和补少量解释完成，不连续复用原文句子。
7. 如果原文正文较短，只能基于标题、摘要和可复核事实扩写；不确定内容写入“来源与复核提醒”。
8. 正文必须是微信富文本 HTML, 只使用 <section>、<p>、<h2>、<ul>、<ol>、<li>、<blockquote>、<strong>、<span>、<br>，并使用内联 style。
9. {_inline_image_requirement_text(source_image_count, source_text_length)}
10. 禁止输出内部过程、提示词分析、模型失败原因、系统实现、兜底说明、广告引流和“关注公众号”等话术。
11. 下面结构中的配图卡片只是格式示例，禁止照抄“示例主题 / 示例位置 / 示例画面 / 示例用途”，必须根据原文内容重新生成每条正文配图建议。
12. 输出必须严格使用下面结构：

### 改写标题

[不超过 20 字的推荐标题]

### 标题候选

1. [标题候选]
2. [标题候选]
3. [标题候选]

### 公众号改写正文

<section style="font-size:16px; line-height:1.85; color:#1f2937; letter-spacing:0.02em;">
[可直接复制到公众号编辑器的正文。优先保持原文的小标题层级、列表/引用/步骤顺序和段落节奏；在不改变原文版式骨架的前提下补充必要的 AI 知识解释。正文中要在对应位置插入下面这种配图占位卡片：]
<section style="margin:18px 0; padding:14px 16px; border-radius:12px; background:#f8fafc; border:1px dashed #93c5fd;">
  <p style="margin:0 0 8px; font-weight:700; color:#1d4ed8;">配图建议：[根据原文当前段落生成的具体主题]</p>
  <ul style="margin:0; padding-left:18px; color:#374151;">
    <li>位置：[写清放在原文哪个小标题、步骤或关键段落后]</li>
    <li>参考原图：[原文图片 N；如果有 URL 写入 URL；说明参考其信息结构、布局关系或视觉重点]</li>
    <li>画面：[提炼原文当前段落里的对象、流程、对比关系或结构，不使用模板固定流程]</li>
    <li>用途：[说明这张图帮助读者理解原文里的哪个知识点]</li>
    <li>版权：建议重新绘制，不使用公司 Logo 或受版权保护元素。</li>
  </ul>
</section>
</section>

### 来源与复核提醒

1. [原文链接/事实/数据/图片/版权中需要人工确认的事项]

### 配图建议

1. 封面图：[主题、画面结构、颜色、中文字建议、AIGC 提示词、版权提醒]

### 发布风险自查

1. [可能的夸大、绝对化、事实、版权、隐私或敏感风险；没有明显风险也要写“暂无明显高风险，仍需人工复核”]

### Tags

#标签1 #标签2 #标签3 #标签4 #标签5
"""


def _default_skill_dir() -> str:
    project_root = Path(__file__).resolve().parents[2]
    return str(project_root / "skills" / "wechat-rewrite")


def _read_rules(skill_dir: Path) -> str:
    rules_file = skill_dir / "assets" / "platform-rules.md"
    if not rules_file.exists():
        return ""
    content = rules_file.read_text(encoding="utf-8")
    match = re.search(r"^## 公众号\n(.*)", content, re.DOTALL | re.MULTILINE)
    return ("## 公众号\n" + match.group(1).strip()) if match else content


def _read_workflow_rules(skills_root: Path) -> str:
    sections = []
    for skill_name in SUPPORTING_SKILL_NAMES:
        summary = _workflow_prompt_for(skills_root, skill_name)
        if summary:
            sections.append(f"### {skill_name}\n{summary}")
    return "\n\n".join(sections)


def _workflow_prompt_for(skills_root: Path, skill_name: str) -> str:
    if not (skills_root / skill_name / "SKILL.md").exists():
        return ""
    return WORKFLOW_PROMPT_RULES.get(skill_name, "")


def _read_skill_summary(skill_dir: Path, *, limit: int = 1200) -> str:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return ""
    content = skill_file.read_text(encoding="utf-8")
    description = ""
    match = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
    if match:
        description = match.group(1).strip()
    content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL).strip()
    content = "\n".join(line.rstrip() for line in content.splitlines() if line.strip())
    if len(content) > limit:
        content = content[:limit].rstrip() + "\n..."
    if description and description not in content:
        return f"职责：{description}\n{content}"
    return content


def _extract_keywords(rules: str) -> list[str]:
    keywords: list[str] = []
    for match in re.finditer(r"^\d+\.\s*([^：:\n]+)[：:]", rules, re.MULTILINE):
        keyword = match.group(1).strip()
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return keywords


def _minimum_rewrite_length(source_text_length: int) -> int:
    if source_text_length >= 3000:
        return int(source_text_length * 0.7)
    return 0


def _maximum_rewrite_length(source_text_length: int) -> int:
    if source_text_length >= 3000:
        return int(source_text_length * 0.8)
    return 0


def _source_image_count(article: dict[str, Any]) -> int | None:
    for key in ("source_image_count", "image_count"):
        explicit_count = article.get(key)
        if isinstance(explicit_count, int) and explicit_count >= 0:
            return explicit_count
    for key in ("source_images", "image_urls", "images"):
        value = article.get(key)
        if isinstance(value, list):
            return len([item for item in value if str(item).strip()])
    raw_payload = article.get("raw_payload")
    urls = _source_image_urls(raw_payload)
    if urls:
        return len(urls)
    text = str(article.get("text") or "")
    html_image_count = len(re.findall(r"<img\b", text, flags=re.IGNORECASE))
    return html_image_count if html_image_count > 0 else None


def _source_image_urls_from_article(article: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("source_images", "image_urls", "images"):
        value = article.get(key)
        if isinstance(value, list):
            urls.extend(str(item) for item in value if str(item).strip())
    urls.extend(_source_image_urls(article.get("raw_payload")))
    result: list[str] = []
    for url in urls:
        normalized = str(url).strip()
        if normalized.startswith("//"):
            normalized = "https:" + normalized
        if normalized.startswith(("http://", "https://")) and normalized not in result:
            result.append(normalized)
    return result


def _source_image_reference_text(source_image_urls: list[str], source_image_count: int | None) -> str:
    if source_image_urls:
        lines = [
            f"共 {source_image_count or len(source_image_urls)} 张；改写配图建议必须逐张参考原文图片的信息结构并重新绘制："
        ]
        lines.extend(f"  - 原文图片 {index}：{url}" for index, url in enumerate(source_image_urls[:12], start=1))
        return "\n".join(lines)
    if source_image_count is None:
        return "未检测到明确图片清单。"
    if source_image_count <= 0:
        return "原文未检测到正文配图。"
    return f"检测到 {source_image_count} 张，但未拿到 URL；正文配图建议仍需按原文图片编号逐张复刻信息结构并重新绘制。"


def _source_image_urls(payload: Any) -> list[str]:
    urls: list[str] = []

    def visit(value: Any) -> None:
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


def _inline_image_requirement_text(source_image_count: int | None, source_text_length: int) -> str:
    card_format = (
        "卡片用 <section> + <p> + <ul><li> 输出，内容包括图片类型、画面结构、用途和版权提醒；"
        "不要只在文末列配图建议。"
    )
    if source_image_count is None:
        estimated_count = _estimated_inline_image_count(source_text_length)
        return (
            f"未检测到明确的原文配图数量，按正文长度估算插入 {estimated_count} 个“配图占位卡片”；"
            f"优先放在原文对应段落或相邻段落后，不能破坏原文原有的章节节奏。{card_format}"
        )
    if source_image_count <= 0:
        return (
            "原文未检测到正文配图，正文配图占位卡片可不插入；"
            "如为了知识讲解新增解释图，最多插入 1 个，并在卡片中标明“新增重绘图”。"
            f"{card_format}"
        )
    return (
        f"原文检测到 {source_image_count} 张配图，正文中必须对应插入 {source_image_count} 个“配图占位卡片”；"
        "每个卡片必须写清“参考原图：原文图片 N / URL”，以原图的信息结构、布局关系、截图重点或流程关系为参考重新绘制原创图，"
        f"优先放在原文对应图片的段落或相邻段落后，不能破坏原文原有的章节节奏。{card_format}"
    )


def _estimated_inline_image_count(source_text_length: int) -> int:
    if source_text_length >= 3000:
        return 3
    if source_text_length >= 1200:
        return 2
    return 1


def _length_requirement_text(source_text_length: int, minimum_rewrite_length: int) -> str:
    if minimum_rewrite_length > 0:
        maximum_rewrite_length = _maximum_rewrite_length(source_text_length)
        return (
            f"这是长文改写，公众号改写正文去除 HTML 标签后的正文长度应控制在 {minimum_rewrite_length}-{maximum_rewrite_length} 字，"
            "约为原文 70%-80%；不是越长越好，最好落在该区间内，禁止超过原文长度。必须保留原文的小标题、论证顺序、关键解释、示例和结论。"
        )
    return "原文未达到长文阈值，仍需保留主要信息，不要把完整段落压缩成几句摘要。"


def _tag_text(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lstrip("#"))


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = re.sub(r"<[^>]+>", "", unescape(str(value)))
    return " ".join(text.split())
