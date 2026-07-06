"""TianAPI WeChat article client.

TianAPI's wxnew endpoint is useful for validating the real-data path, but its
documentation says the dataset is no longer updated. Treat it as a development
adapter, not as a production hotspot source.
"""

from __future__ import annotations

import json
import os
from hashlib import sha1
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.schemas.hotspot import ApiDimension, Platform, RawContent, SourcePlan


class TianapiWechatClient:
    """Fetches WeChat article list/search data from TianAPI wxnew."""

    source_api = "tianapi-wxnew"
    endpoint = "https://apis.tianapi.com/wxnew/index"

    def __init__(self, *, api_key: str, timeout_seconds: float | None = None) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds or float(os.getenv("CONTENT_API_TIMEOUT_SECONDS", "20"))

    @classmethod
    def from_env(cls) -> "TianapiWechatClient | None":
        api_key = os.getenv("TIANAPI_API_KEY") or os.getenv("WECHAT_API_KEY")
        if not api_key or api_key in {"your_tianapi_key", "你的天行数据key"}:
            return None
        return cls(api_key=api_key)

    def fetch(self, plan: SourcePlan) -> list[RawContent]:
        if plan.platform != Platform.WECHAT:
            raise ValueError(f"{self.source_api} cannot fetch platform {plan.platform.value}")
        if plan.dimension not in {
            ApiDimension.SEARCH_QUERY,
            ApiDimension.ARTICLE_DETAIL,
            ApiDimension.WORK_LIST,
        }:
            return []

        payload = self._request_json(plan)
        items = self._extract_items(payload)
        return [
            RawContent(
                platform=Platform.WECHAT,
                dimension=plan.dimension,
                source_api=self.source_api,
                raw_payload=self._normalize_item(item, plan),
            )
            for item in items
        ]

    def _request_json(self, plan: SourcePlan) -> dict[str, Any]:
        page_size = max(1, min(plan.page_size, 50))
        query = {
            "key": self.api_key,
            "num": page_size,
            "page": int(plan.metadata.get("page", 1)),
            "word": plan.query,
        }
        url = f"{self.endpoint}?{urlencode({key: value for key, value in query.items() if value is not None})}"
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.source_api} HTTP {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"{self.source_api} request failed: {exc.reason}") from exc

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.source_api} returned non-JSON response") from exc

        code = payload.get("code")
        if code not in (200, "200", 0, "0"):
            message = payload.get("msg") or payload.get("message") or "unknown error"
            raise RuntimeError(f"{self.source_api} business error {code}: {message}")
        return payload

    def _extract_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        result = payload.get("result", payload)
        candidates: list[Any] = []
        if isinstance(result, dict):
            candidates.extend(result.get(key) for key in ("newslist", "list", "items", "data"))
        candidates.extend(payload.get(key) for key in ("newslist", "list", "items", "data"))

        for value in candidates:
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _normalize_item(self, item: dict[str, Any], plan: SourcePlan) -> dict[str, Any]:
        article_id = _pick_str(item, "id", "url") or _stable_id(str(item))
        title = _pick_str(item, "title") or plan.query or ""
        description = _pick_str(item, "description", "digest", "content") or ""
        author = _pick_str(item, "author", "username", "wxnum")
        return {
            "id": article_id,
            "author": author,
            "title": title,
            "text": description,
            "media_type": "article",
            "published_at": _pick_str(item, "ctime", "time", "publish_time"),
            "url": _pick_str(item, "url"),
            "metrics": {
                "reads": _pick_int(item, "readnum", "read_count", "views"),
                "likes": _pick_int(item, "likenum", "like_count", "likes"),
            },
            "account": {
                "wxnum": _pick_str(item, "wxnum"),
                "username": _pick_str(item, "username"),
                "description": _pick_str(item, "description"),
            },
            "cover_url": _pick_str(item, "picurl", "pic", "image"),
            "category": _pick_str(item, "type", "category"),
            "provider_payload": item,
        }


def _pick_str(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return str(value)
    return None


def _pick_int(item: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = item.get(key)
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _stable_id(*parts: str) -> str:
    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
