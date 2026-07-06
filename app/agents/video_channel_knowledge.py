"""Video Channel knowledge explainer agents."""

from __future__ import annotations

from hashlib import sha1
from typing import Any

from app.schemas.hotspot import EducationKnowledgePoint, HotspotState


class EducationKnowledgeSourceAgent:
    """Normalizes user-provided K12 education material into one knowledge point."""

    def invoke(self, state: HotspotState) -> HotspotState:
        payload = state.get("video_source", {})
        if not isinstance(payload, dict):
            payload = {}
        text = _clean_text(str(payload.get("raw_text") or payload.get("text") or ""))
        title = _clean_text(str(payload.get("title") or _title_from_text(text) or "未命名知识点"))
        grade_or_level = _clean_optional(payload.get("grade_or_level") or payload.get("stage"))
        source_url = _clean_text(str(payload.get("source_url") or payload.get("url") or "")) or None
        knowledge = EducationKnowledgePoint(
            knowledge_id=_stable_id(title, source_url or "", text[:200]),
            title=title,
            subject=_clean_optional(payload.get("subject")),
            grade_or_level=grade_or_level,
            source_url=source_url,
            key_points=_list_or_infer(payload.get("key_points"), text),
            examples=_list_or_infer(payload.get("examples"), text, fallback=["用一个生活化例子帮助读者理解这个知识点。"]),
            common_misunderstandings=_list_or_infer(
                payload.get("common_misunderstandings"),
                text,
                fallback=["把概念背下来但没有理解适用条件。"],
            ),
            raw_text=text,
        )
        review_flags = list(state.get("review_flags", []))
        if source_url is None:
            review_flags.append("video_source_missing_url")
        if len(text) < 80:
            review_flags.append("video_source_too_short")
        return {"education_knowledge": knowledge, "review_flags": sorted(set(review_flags))}


class VideoComplianceCheckAgent:
    """Adds review flags for education-video-specific risks."""

    def invoke(self, state: HotspotState) -> HotspotState:
        knowledge = state.get("education_knowledge")
        script = state.get("video_channel_script")
        review_flags = list(state.get("review_flags", []))
        risk_flags: list[str] = []
        if knowledge is not None and not knowledge.source_url:
            risk_flags.append("缺少可复核来源链接")
        if script is not None:
            combined = f"{script.title}\n{script.voiceover}\n{script.publish_copy}"
            if any(word in combined for word in ("必考", "满分", "保证", "绝对", "唯一答案")):
                risk_flags.append("可能包含教育类绝对化或夸大表达")
            if any(word in script.cover_prompt for word in ("英文单词", "英文字母", "繁体字")):
                pass
        if risk_flags:
            review_flags.extend(f"video_risk:{item}" for item in risk_flags)
        return {
            "review_flags": sorted(set(review_flags)),
            "human_review_required": bool(review_flags),
        }

def _list_or_infer(value: object, text: str, fallback: list[str] | None = None) -> list[str]:
    if isinstance(value, list):
        items = [_clean_text(str(item)) for item in value if _clean_text(str(item))]
        if items:
            return items[:5]
    sentences = [item.strip(" 。；;") for item in __import__("re").split(r"[。；;\n]", text) if item.strip()]
    return sentences[:3] or (fallback or [])


def _title_from_text(text: str) -> str:
    first = _clean_text(text.splitlines()[0] if text.splitlines() else text)
    return _clip(first, 24)


def _clean_optional(value: object) -> str | None:
    cleaned = _clean_text(str(value or ""))
    return cleaned or None


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def _clip(value: str, limit: int) -> str:
    value = _clean_text(value)
    return value if len(value) <= limit else value[:limit].rstrip()


def _stable_id(*parts: str) -> str:
    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
