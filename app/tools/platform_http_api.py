"""Reusable HTTP client base for real platform content APIs."""

from __future__ import annotations

import json
import os
from hashlib import sha1
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from app.schemas.hotspot import ApiDimension, Platform, RawContent, SourcePlan


DEFAULT_DIMENSION_PATHS: dict[ApiDimension, str] = {
    ApiDimension.SEARCH_QUERY: "/search",
    ApiDimension.ACCOUNT_INFO: "/accounts",
    ApiDimension.ARTICLE_DETAIL: "/articles",
    ApiDimension.WORK_LIST: "/works",
}


class PlatformHttpApiClient:
    """HTTP adapter for provider APIs that return content-like JSON.

    Configure each platform with environment variables:

    - ``<PREFIX>_API_BASE_URL``: required to enable the real client.
    - ``<PREFIX>_API_KEY``: optional token.
    - ``<PREFIX>_<DIMENSION>_PATH``: optional endpoint override, for example
      ``DOUYIN_SEARCH_QUERY_PATH=/v1/douyin/search``.
    """

    def __init__(
        self,
        *,
        platform: Platform,
        env_prefix: str,
        base_url: str,
        api_key: str | None = None,
        source_api: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.platform = platform
        self.env_prefix = env_prefix
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key
        self.source_api = source_api or f"{platform.value}-http-api"
        self.timeout_seconds = timeout_seconds or float(os.getenv("CONTENT_API_TIMEOUT_SECONDS", "20"))

    @classmethod
    def from_env(cls, *, platform: Platform, env_prefix: str, source_api: str | None = None) -> "PlatformHttpApiClient | None":
        base_url = os.getenv(f"{env_prefix}_API_BASE_URL")
        if not base_url:
            return None
        return cls(
            platform=platform,
            env_prefix=env_prefix,
            base_url=base_url,
            api_key=os.getenv(f"{env_prefix}_API_KEY"),
            source_api=source_api,
        )

    def fetch(self, plan: SourcePlan) -> list[RawContent]:
        if plan.platform != self.platform:
            raise ValueError(f"{self.source_api} cannot fetch platform {plan.platform.value}")

        payload = self._request_json(plan)
        items = self._extract_items(payload)
        return [
            RawContent(
                platform=plan.platform,
                dimension=plan.dimension,
                source_api=self.source_api,
                raw_payload=self._normalize_provider_item(item, plan),
            )
            for item in items
        ]

    def _request_json(self, plan: SourcePlan) -> Any:
        url = self._build_url(plan)
        request = Request(url, headers=self._headers(), method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.source_api} HTTP {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"{self.source_api} request failed: {exc.reason}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.source_api} returned non-JSON response") from exc

    def _build_url(self, plan: SourcePlan) -> str:
        path = os.getenv(f"{self.env_prefix}_{plan.dimension.value.upper()}_PATH")
        path = path or DEFAULT_DIMENSION_PATHS[plan.dimension]
        query = {
            "platform": plan.platform.value,
            "dimension": plan.dimension.value,
            "query": plan.query,
            "account_id": plan.account_id,
            "page_size": plan.page_size,
        }
        query.update({key: value for key, value in plan.metadata.items() if isinstance(value, str | int | float | bool)})
        compact_query = {key: value for key, value in query.items() if value is not None}
        return f"{urljoin(self.base_url, path.lstrip('/'))}?{urlencode(compact_query)}"

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if not self.api_key:
            return headers

        header_name = os.getenv(f"{self.env_prefix}_API_AUTH_HEADER", "Authorization")
        auth_scheme = os.getenv(f"{self.env_prefix}_API_AUTH_SCHEME", "Bearer")
        header_value = f"{auth_scheme} {self.api_key}".strip() if auth_scheme else self.api_key
        headers[header_name] = header_value
        return headers

    def _extract_items(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("items", "results", "data", "list", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested_items = self._extract_items(value)
                if nested_items:
                    return nested_items
        return [payload]

    def _normalize_provider_item(self, item: dict[str, Any], plan: SourcePlan) -> dict[str, Any]:
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        metrics = {
            "views": _pick_int(item, metrics, "views", "view_count", "play_count", "read_count"),
            "likes": _pick_int(item, metrics, "likes", "like_count", "digg_count"),
            "comments": _pick_int(item, metrics, "comments", "comment_count"),
            "shares": _pick_int(item, metrics, "shares", "share_count", "forward_count"),
            "saves": _pick_int(item, metrics, "saves", "collect_count", "favorite_count"),
            "reads": _pick_int(item, metrics, "reads", "read_count"),
            "watching": _pick_int(item, metrics, "watching", "watching_count", "like_extra_count"),
        }
        content_id = _pick_str(item, "id", "content_id", "item_id", "article_id", "note_id", "aweme_id")
        url = _pick_str(item, "url", "share_url", "link", "source_url")
        return {
            "id": content_id or _stable_id(self.platform.value, plan.dimension.value, str(item)),
            "author": _pick_str(item, "author", "author_name", "nickname", "user_name", "account_name"),
            "title": _pick_str(item, "title", "desc", "description", "name") or plan.query or "",
            "text": _pick_str(item, "text", "content", "summary", "desc", "description") or "",
            "media_type": _pick_str(item, "media_type", "type") or _default_media_type(self.platform, plan.dimension),
            "published_at": _pick_str(item, "published_at", "publish_time", "created_at", "create_time"),
            "url": url,
            "metrics": {key: value for key, value in metrics.items() if value is not None},
            "provider_payload": item,
        }


def _pick_str(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def _pick_int(item: dict[str, Any], metrics: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = metrics.get(key, item.get(key))
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _default_media_type(platform: Platform, dimension: ApiDimension) -> str:
    if dimension == ApiDimension.ACCOUNT_INFO:
        return "account"
    if platform == Platform.DOUYIN:
        return "video"
    if platform == Platform.XIAOHONGSHU:
        return "note"
    return "article"


def _stable_id(*parts: str) -> str:
    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
