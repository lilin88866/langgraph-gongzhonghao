"""WeChat account discovery and auto-subscription agent."""

from __future__ import annotations

import os

from app.schemas.hotspot import HotspotState, Platform, WechatAccountCandidate
from app.tools.wechat_download_api import WechatDownloadApiClient


DEFAULT_ACCOUNT_KEYWORDS = [
    "CI",
    "CD",
    "DevOps",
    "ZUUL",
    "Jenkins",
    "GitHub",
    "GitLab",
    "AI",
    "AIGC",
    "Agent",
    "AI Agent",
    "Code Agent",
    "智能体",
    "代码智能体",
    "人工智能",
    "Claude",
    "Claude Code",
    "ChatGPT",
    "OpenAI",
    "DeepSeek",
    "Gemini",
    "Kimi",
    "Qwen",
    "豆包",
    "通义千问",
    "大模型",
    "大模型蒸馏",
    "大语言模型",
    "LLM",
    "生成式AI",
    "多模态",
    "AI工具",
    "AI产品",
    "AI应用",
    "AI编程",
    "AI教育",
    "AI办公",
    "AI视频",
    "AI自动化",
    "提示词",
    "Prompts",
    "LangGraph",
    "LangChain",
    "loop",
    "RAG",
    "知识库",
    "向量数据库",
    "Embedding",
    "MCP",
    "Copilot",
    "Cursor",
    "代码生成",
    "自动写代码",
    "自动修Bug",
    "代码审查",
    "AI重构",
    "token",
    "Sora",
    "Ollama",
    "llama.cpp",
    "TensorRT-LLM",
    "GPU",
    "算力",
    "推理成本",
    "深度解析",
    "一文看懂",
    "完全指南",
    "实践指南",
    "最佳实践",
    "落地实践",
]

DEFAULT_EXCLUDED_ACCOUNT_NAMES = [
    "AI简说局",
    "thinkingloop",
]

DEFAULT_EXCLUDED_ACCOUNT_KEYWORDS = [
    "Promotion",
    "推广",
    "营销",
    "广告",
    "培训",
    "课程",
    "公开课",
    "训练营",
    "商学院",
    "学院",
    "课堂",
    "副业",
    "赚钱",
    "变现",
    "招商",
    "代理",
    "带货",
    "私域",
    "引流",
    "视频号运营",
]


class WechatAccountDiscoveryAgent:
    """Discovers AI-related WeChat accounts and subscribes them for scheduled refresh."""

    def __init__(self, client: WechatDownloadApiClient | None = None) -> None:
        self.client = client

    def invoke(self, state: HotspotState) -> HotspotState:
        task = state.get("task")
        if task is None or Platform.WECHAT not in task.platforms:
            return {}

        client = self.client or WechatDownloadApiClient.from_env()
        quality_flags = list(state.get("quality_flags", []))
        quality_info = list(state.get("quality_info", []))
        if client is None:
            quality_flags.append("missing_client:wechat_account_discovery")
            return {"quality_flags": quality_flags}

        candidates: list[WechatAccountCandidate] = []
        seen_fakeids: set[str] = set()
        for query in _discovery_queries(task.keywords):
            try:
                accounts = client.search_accounts(query, limit=_search_limit())
            except RuntimeError as exc:
                quality_flags.append(f"wechat_account_discovery_failed:{query}:{exc}")
                continue

            for account in accounts:
                candidate = _candidate_from_account(account)
                if candidate is None or candidate.fakeid in seen_fakeids:
                    continue
                seen_fakeids.add(candidate.fakeid)
                if candidate.relevance_score <= 0:
                    continue
                subscribed = False
                if _auto_subscribe_enabled():
                    try:
                        subscribed = client.subscribe_account(account)
                    except RuntimeError as exc:
                        quality_flags.append(f"wechat_account_subscribe_failed:{candidate.fakeid}:{exc}")
                candidates.append(
                    WechatAccountCandidate(
                        fakeid=candidate.fakeid,
                        nickname=candidate.nickname,
                        alias=candidate.alias,
                        relevance_score=candidate.relevance_score,
                        matched_keywords=candidate.matched_keywords,
                        subscribed=subscribed,
                        reason=candidate.reason,
                    )
                )

        if candidates:
            quality_info.append(f"wechat_accounts_discovered:{len(candidates)}")
        return {"wechat_accounts": candidates, "quality_flags": quality_flags, "quality_info": quality_info}


def _discovery_queries(task_keywords: list[str]) -> list[str]:
    configured = _split_csv(os.getenv("WECHAT_ACCOUNT_DISCOVERY_KEYWORDS", ""))
    queries = [*task_keywords, *DEFAULT_ACCOUNT_KEYWORDS, *configured]
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = query.strip()
        lowered = normalized.lower()
        if normalized and lowered not in seen:
            deduped.append(normalized)
            seen.add(lowered)
    return deduped


def _candidate_from_account(account: dict) -> WechatAccountCandidate | None:
    account_info = account.get("account") if isinstance(account.get("account"), dict) else {}
    fakeid = str(account_info.get("fakeid") or account.get("id") or "")
    nickname = str(account_info.get("nickname") or account.get("author") or account.get("title") or "")
    alias = account_info.get("alias")
    if not fakeid or not nickname:
        return None
    if _is_excluded_account(nickname, alias):
        return None
    searchable = f"{nickname} {alias or ''} {account.get('text') or ''}".lower()
    matched = [keyword for keyword in DEFAULT_ACCOUNT_KEYWORDS if keyword.lower() in searchable]
    configured = [keyword for keyword in _split_csv(os.getenv("WECHAT_ACCOUNT_MATCH_KEYWORDS", "")) if keyword.lower() in searchable]
    matched.extend(configured)
    unique_matched = sorted(set(matched), key=str.lower)
    score = min(1.0, 0.2 + len(unique_matched) * 0.2) if unique_matched else 0.0
    return WechatAccountCandidate(
        fakeid=fakeid,
        nickname=nickname,
        alias=str(alias) if alias else None,
        relevance_score=round(score, 2),
        matched_keywords=unique_matched,
        subscribed=False,
        reason=f"账号名称或简介命中：{'、'.join(unique_matched)}" if unique_matched else "未命中 AI 账号关键词。",
    )


def _auto_subscribe_enabled() -> bool:
    return os.getenv("WECHAT_ACCOUNT_AUTO_SUBSCRIBE", "0").lower() in {"1", "true", "yes"}


def _search_limit() -> int:
    return int(os.getenv("WECHAT_ACCOUNT_DISCOVERY_LIMIT", "20"))


def _is_excluded_account(nickname: str, alias: object = None) -> bool:
    excluded = [*DEFAULT_EXCLUDED_ACCOUNT_NAMES, *_split_csv(os.getenv("WECHAT_EXCLUDED_ACCOUNT_NAMES", ""))]
    excluded_keywords = [
        *DEFAULT_EXCLUDED_ACCOUNT_KEYWORDS,
        *_split_csv(os.getenv("WECHAT_EXCLUDED_ACCOUNT_KEYWORDS", "")),
    ]
    searchable = f"{nickname} {alias or ''}".lower()
    return any(name.lower() in searchable for name in excluded if name) or any(
        keyword.lower() in searchable for keyword in excluded_keywords if keyword
    )


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
