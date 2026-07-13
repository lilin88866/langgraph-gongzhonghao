"""Client for a self-hosted wechat-download-api service."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from app.schemas.hotspot import ApiDimension, Platform, RawContent, SourcePlan

ROOT_DIR = Path(__file__).resolve().parents[2]
ARTICLE_LIST_CACHE_DIR = ROOT_DIR / ".cache" / "wechat_article_lists"
ARTICLE_DETAIL_CACHE_DIR = ROOT_DIR / ".cache" / "wechat_article_details"
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
    "红狐",
]
DEFAULT_EXCLUDED_ARTICLE_TITLE_KEYWORDS = [
    "训练营",
    "公开课",
    "直播课",
    "课程",
    "培训",
    "报名",
    "招生",
    "开营",
    "开班",
    "学员",
    "讲师",
    "老师",
    "优惠",
    "福利",
    "限时",
    "领取",
    "扫码",
    "加群",
    "进群",
    "私信",
    "副业",
    "赚钱",
    "变现",
    "接单",
    "代理",
    "招商",
    "项目",
    "视频号运营",
    "红狐",
]


class WechatDownloadApiClient:
    """Fetches WeChat data from a self-hosted wechat-download-api instance."""

    source_api = "wechat-download-api"

    def __init__(self, *, base_url: str, timeout_seconds: float | None = None) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds or float(os.getenv("CONTENT_API_TIMEOUT_SECONDS", "20"))
        self.default_fakeids = _split_csv(os.getenv("WECHAT_DOWNLOAD_DEFAULT_FAKEIDS", ""))
        self.account_names_by_fakeid: dict[str, str] = {}

    @classmethod
    def from_env(cls) -> "WechatDownloadApiClient | None":
        base_url = os.getenv("WECHAT_DOWNLOAD_API_BASE_URL")
        if not base_url:
            return None
        return cls(base_url=base_url)

    def fetch(self, plan: SourcePlan) -> list[RawContent]:
        if plan.platform != Platform.WECHAT:
            raise ValueError(f"{self.source_api} cannot fetch platform {plan.platform.value}")

        if plan.dimension == ApiDimension.ACCOUNT_INFO:
            return self._fetch_account_search(plan)
        if plan.dimension == ApiDimension.WORK_LIST:
            return self._fetch_work_list(plan)
        if plan.dimension == ApiDimension.SEARCH_QUERY:
            return self._fetch_article_search(plan)
        if plan.dimension == ApiDimension.ARTICLE_DETAIL:
            return self._fetch_article_detail(plan)
        return []

    def check_health(self) -> bool:
        payload = self._get_json("/api/health", {})
        if isinstance(payload, dict):
            status = str(payload.get("status") or payload.get("message") or "").lower()
            return status in {"ok", "healthy", "success"} or bool(payload)
        return payload is not None

    def search_accounts(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        payload = self._get_json("/api/public/searchbiz", {"query": query})
        accounts: list[dict[str, Any]] = []
        for item in self._extract_items(payload):
            normalized = self._normalize_account_item(
                item,
                SourcePlan(platform=Platform.WECHAT, dimension=ApiDimension.ACCOUNT_INFO, query=query),
            )
            accounts.append(normalized)
            if len(accounts) >= limit:
                break
        return accounts

    def subscribe_account(self, account: dict[str, Any]) -> bool:
        account_info = account.get("account") if isinstance(account.get("account"), dict) else {}
        fakeid = _pick_str(account_info, "fakeid") or _pick_str(account, "id")
        if not fakeid:
            return False
        payload = {
            "fakeid": fakeid,
            "nickname": _pick_str(account_info, "nickname") or _pick_str(account, "author", "title") or "",
            "alias": _pick_str(account_info, "alias") or "",
            "head_img": _pick_str(account_info, "avatar") or "",
        }
        result = self._post_json("/api/rss/subscribe", payload)
        if isinstance(result, dict):
            success = result.get("success")
            if isinstance(success, bool):
                return success
        return True

    def list_subscriptions(self, *, limit: int | None = None) -> list[dict[str, str]]:
        payload = self._get_json("/api/rss/subscriptions", {})
        subscriptions: list[dict[str, str]] = []
        for item in self._extract_items(payload):
            fakeid = _pick_str(item, "fakeid", "fake_id", "id")
            if not fakeid or not _looks_like_wechat_fakeid(fakeid):
                continue
            nickname = _pick_str(item, "nickname", "name", "wechat_name", "title") or fakeid
            if _is_excluded_account_name(nickname):
                continue
            self.account_names_by_fakeid[fakeid] = nickname
            subscriptions.append({"fakeid": fakeid, "nickname": nickname})
            if limit is not None and len(subscriptions) >= limit:
                break
        return subscriptions

    def fetch_subscription_articles(
        self,
        *,
        account_limit: int = 12,
        page_size: int = 20,
        article_keywords: list[str] | None = None,
        max_age_days: int = 2,
        articles_per_account: int = 1,
    ) -> list[RawContent]:
        contents: list[RawContent] = []
        subscription_limit = None if account_limit <= 0 else max(1, account_limit)
        subscriptions = self.list_subscriptions(limit=subscription_limit)
        for subscription in subscriptions:
            fakeid = subscription["fakeid"]
            plan = SourcePlan(
                platform=Platform.WECHAT,
                dimension=ApiDimension.WORK_LIST,
                query=subscription.get("nickname") or fakeid,
                account_id=fakeid,
                page_size=page_size,
                metadata={"fakeid": fakeid, "nickname": subscription.get("nickname") or fakeid},
            )
            try:
                payload = self._get_cached_article_list(plan, fakeid)
            except RuntimeError:
                continue
            account_articles: list[dict[str, Any]] = []
            for item in self._extract_items(payload):
                normalized = self._normalize_article_item(item, plan, fakeid=fakeid)
                if not _article_is_recent(normalized, max_age_days=max_age_days):
                    continue
                if _article_title_has_excluded_keywords(normalized):
                    continue
                if article_keywords and not _article_matches_keywords(normalized, article_keywords):
                    continue
                account_articles.append(normalized)
            if not account_articles:
                continue
            latest_articles = sorted(account_articles, key=_article_timestamp, reverse=True)[: max(1, articles_per_account)]
            contents.extend(self._raw(plan, article) for article in latest_articles)
        return contents

    def _get_cached_article_list(self, plan: SourcePlan, fakeid: str) -> Any:
        if os.getenv("WECHAT_ARTICLE_LIST_CACHE", "1").lower() in {"0", "false", "no"}:
            return self._get_article_list(plan, fakeid)

        cache_path = _article_list_cache_path(fakeid, plan.page_size)
        cached = _read_article_list_cache(cache_path, allow_stale=False)
        if cached is not None:
            return cached

        try:
            payload = self._get_article_list(plan, fakeid)
        except RuntimeError:
            stale = _read_article_list_cache(cache_path, allow_stale=True)
            if stale is not None:
                return stale
            raise
        _write_article_list_cache(cache_path, payload)
        return payload

    def _fetch_account_search(self, plan: SourcePlan) -> list[RawContent]:
        query = plan.query or plan.account_id
        if not query:
            return []
        payload = self._get_json("/api/public/searchbiz", {"query": query})
        return [
            self._raw(plan, self._normalize_account_item(item, plan))
            for item in self._extract_items(payload)
        ]

    def _fetch_work_list(self, plan: SourcePlan) -> list[RawContent]:
        fakeids = self._fakeids_for(plan)
        contents: list[RawContent] = []
        for fakeid in fakeids:
            payload = self._get_article_list(plan, fakeid)
            contents.extend(
                self._raw(plan, self._normalize_article_item(item, plan, fakeid=fakeid))
                for item in self._extract_items(payload)
            )
        return contents

    def _fetch_article_search(self, plan: SourcePlan) -> list[RawContent]:
        query = plan.query or "AI"
        fakeids = self._fakeids_for(plan)
        if not fakeids:
            fakeids = self._discover_fakeids(query, limit=3)

        contents: list[RawContent] = []
        for fakeid in fakeids:
            payload = self._search_articles(plan, fakeid, query)
            contents.extend(
                self._raw(plan, self._normalize_article_item(item, plan, fakeid=fakeid))
                for item in self._extract_items(payload)
            )

        if contents:
            return contents
        return self._fetch_account_search(plan)

    def _fetch_article_detail(self, plan: SourcePlan) -> list[RawContent]:
        url = str(plan.metadata.get("url") or plan.query or "")
        if not url.startswith("http"):
            return []
        payload = self._get_cached_article_detail(url)
        detail = self._extract_detail(payload)
        if detail is not None:
            return [self._raw(plan, self._normalize_article_item(detail, plan))]
        return []

    def _get_cached_article_detail(self, url: str) -> Any:
        cache_path = _article_detail_cache_path(url)
        if os.getenv("WECHAT_ARTICLE_DETAIL_CACHE", "1").lower() not in {"0", "false", "no"}:
            cached = _read_article_list_cache(cache_path, allow_stale=False)
            if cached is not None:
                return cached

        timeout_seconds = float(os.getenv("WECHAT_ARTICLE_DETAIL_TIMEOUT_SECONDS", "45"))
        attempts = max(1, int(os.getenv("WECHAT_ARTICLE_DETAIL_ATTEMPTS", "2")))
        last_error: RuntimeError | None = None
        for attempt in range(attempts):
            try:
                payload = self._post_json("/api/article", {"url": url}, timeout_seconds=timeout_seconds)
                if os.getenv("WECHAT_ARTICLE_DETAIL_CACHE", "1").lower() not in {"0", "false", "no"}:
                    _write_article_list_cache(cache_path, payload)
                return payload
            except RuntimeError as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    continue

        stale = _read_article_list_cache(cache_path, allow_stale=True)
        if stale is not None:
            return stale
        if last_error is not None:
            raise last_error
        raise RuntimeError("wechat-download-api article detail returned no payload")

    def _get_article_list(self, plan: SourcePlan, fakeid: str) -> Any:
        return self._get_json(
            "/api/public/articles",
            {
                "fakeid": fakeid,
                "id": fakeid,
                "begin": int(plan.metadata.get("begin", 0)),
                "count": min(plan.page_size, 100),
            },
        )

    def _search_articles(self, plan: SourcePlan, fakeid: str, query: str) -> Any:
        request_query = {
            "fakeid": fakeid,
            "query": query,
            "begin": int(plan.metadata.get("begin", 0)),
            "count": min(plan.page_size, 100),
        }
        try:
            return self._get_json("/api/public/articles/search", request_query)
        except RuntimeError:
            # Older wechat-download-api deployments expose keyword search on
            # /api/public/articles instead of the dedicated /search endpoint.
            return self._get_json(
                "/api/public/articles",
                {
                    **request_query,
                    "keyword": query,
                },
            )

    def _discover_fakeids(self, query: str, *, limit: int) -> list[str]:
        payload = self._get_json("/api/public/searchbiz", {"query": query})
        fakeids: list[str] = []
        for item in self._extract_items(payload):
            fakeid = _pick_str(item, "fakeid", "fake_id", "id")
            if fakeid:
                fakeids.append(fakeid)
                nickname = _pick_str(item, "nickname", "name", "wechat_name", "username")
                if nickname:
                    self.account_names_by_fakeid[fakeid] = nickname
            if len(fakeids) >= limit:
                break
        return fakeids

    def _fakeids_for(self, plan: SourcePlan) -> list[str]:
        if plan.account_id:
            return [plan.account_id]
        metadata_fakeid = plan.metadata.get("fakeid") or plan.metadata.get("fake_id")
        if metadata_fakeid:
            return [str(metadata_fakeid)]
        return self.default_fakeids

    def _get_json(self, path: str, query: dict[str, Any]) -> Any:
        compact_query = {key: value for key, value in query.items() if value is not None}
        url = f"{urljoin(self.base_url, path.lstrip('/'))}?{urlencode(compact_query)}"
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        return self._send(request)

    def _post_json(self, path: str, payload: dict[str, Any], *, timeout_seconds: float | None = None) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        return self._send(request, timeout_seconds=timeout_seconds)

    def _send(self, request: Request, *, timeout_seconds: float | None = None) -> Any:
        try:
            opener = _local_no_proxy_opener(request.full_url)
            open_request = opener.open if opener is not None else urlopen
            with open_request(request, timeout=timeout_seconds or self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.source_api} HTTP {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"{self.source_api} request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError(f"{self.source_api} request timed out") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.source_api} returned non-JSON response") from exc

    def _extract_items(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in (
            "data",
            "items",
            "list",
            "articles",
            "app_msg_list",
            "appmsg_list",
            "news_item",
            "biz_list",
            "results",
            "records",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = self._extract_items(value)
                if nested:
                    return nested
        return [payload]

    def _extract_detail(self, payload: Any) -> dict[str, Any] | None:
        if isinstance(payload, list):
            return next((item for item in payload if isinstance(item, dict)), None)
        if not isinstance(payload, dict):
            return None
        for key in ("data", "article", "item", "result"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        return payload

    def _normalize_account_item(self, item: dict[str, Any], plan: SourcePlan) -> dict[str, Any]:
        fakeid = _pick_str(item, "fakeid", "fake_id", "id")
        nickname = _pick_str(item, "nickname", "name", "wechat_name", "username") or plan.query or ""
        if fakeid and nickname:
            self.account_names_by_fakeid[fakeid] = nickname
        return {
            "id": fakeid or _stable_id("account", str(item)),
            "author": nickname,
            "title": nickname,
            "text": _pick_str(item, "profile", "description", "signature", "alias") or "",
            "media_type": "account",
            "published_at": None,
            "url": _pick_str(item, "profile_url", "url"),
            "metrics": {},
            "account": {
                "fakeid": fakeid,
                "nickname": nickname,
                "alias": _pick_str(item, "alias", "wechat_id"),
                "avatar": _pick_str(item, "round_head_img", "headimage", "avatar"),
            },
            "provider_payload": item,
        }

    def _normalize_article_item(
        self,
        item: dict[str, Any],
        plan: SourcePlan,
        *,
        fakeid: str | None = None,
    ) -> dict[str, Any]:
        article = item.get("article") if isinstance(item.get("article"), dict) else item
        account = _pick_dict(item, "gzh", "account")
        title = _pick_str(article, "title", "name") or ""
        html = _pick_str(article, "content", "html", "article_html", "text", "rich_media_content") or ""
        text = _html_to_text(_pick_str(article, "text", "plain_content", "content", "digest", "summary", "abstract", "desc") or "")
        url = _pick_str(article, "url", "link", "content_url")
        image_urls = _extract_image_urls(article, html)
        account_fakeid = fakeid or _pick_str(article, "fakeid", "fake_id") or _pick_str(account, "fakeid", "fake_id")
        account_nickname = (
            _pick_str(account, "nickname", "wechat_name", "name")
            or (self.account_names_by_fakeid.get(account_fakeid) if account_fakeid else None)
        )
        return {
            "id": _pick_str(article, "id", "aid", "article_id", "appmsgid", "msgid", "url", "link")
            or _stable_id("article", title, url or str(item)),
            "author": _pick_str(article, "author", "source_nickname")
            or account_nickname,
            "title": title,
            "text": text,
            "html": html,
            "image_urls": image_urls,
            "media_type": "article",
            "published_at": _pick_str(article, "publish_time", "update_time", "time", "datetime", "create_time"),
            "url": url,
            "metrics": {
                "reads": _article_metric(
                    article,
                    item,
                    "readnum",
                    "read_num",
                    "read_count",
                    "readCount",
                    "readNum",
                    "read_count_num",
                    "readNumStr",
                    "read_num_str",
                ),
                "likes": _article_metric(
                    article,
                    item,
                    "likenum",
                    "like_num",
                    "like_count",
                    "likeCount",
                    "likeNum",
                    "like_count_num",
                ),
                "comments": _article_metric(
                    article,
                    item,
                    "comment_count",
                    "comment_num",
                    "commentCount",
                    "commentNum",
                ),
            },
            "account": {
                "fakeid": account_fakeid,
                "nickname": account_nickname,
                "profile_url": _pick_str(account, "profile_url"),
            },
            "provider_payload": item,
        }

    def _raw(self, plan: SourcePlan, payload: dict[str, Any]) -> RawContent:
        return RawContent(
            platform=Platform.WECHAT,
            dimension=plan.dimension,
            source_api=self.source_api,
            raw_payload=payload,
        )


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _article_list_cache_path(fakeid: str, page_size: int) -> Path:
    key = sha1(f"{fakeid}|{page_size}".encode("utf-8")).hexdigest()[:16]
    return ARTICLE_LIST_CACHE_DIR / f"{key}.json"


def _article_detail_cache_path(url: str) -> Path:
    key = sha1(url.encode("utf-8")).hexdigest()[:16]
    return ARTICLE_DETAIL_CACHE_DIR / f"{key}.json"


def _read_article_list_cache(path: Path, *, allow_stale: bool) -> Any | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    cached_at = _parse_article_datetime(payload.get("cached_at"))
    if cached_at is None:
        return None
    ttl_seconds = int(os.getenv("WECHAT_ARTICLE_LIST_CACHE_TTL_SECONDS", "7200"))
    if not allow_stale and datetime.now(timezone.utc) - cached_at > timedelta(seconds=ttl_seconds):
        return None
    return payload.get("payload")


def _write_article_list_cache(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"cached_at": datetime.now(timezone.utc).isoformat(), "payload": payload},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def _article_matches_keywords(payload: dict[str, Any], keywords: list[str]) -> bool:
    fields = ("title",)
    if os.getenv("WECHAT_ARTICLE_MATCH_FULL_TEXT", "0").lower() in {"1", "true", "yes"}:
        fields = ("title", "text", "html")
    searchable = " ".join(str(payload.get(key) or "") for key in fields).lower()
    return any(keyword.strip().lower() in searchable for keyword in keywords if keyword.strip())


def _article_title_has_excluded_keywords(payload: dict[str, Any]) -> bool:
    title = str(payload.get("title") or "").lower()
    excluded = [
        *DEFAULT_EXCLUDED_ARTICLE_TITLE_KEYWORDS,
        *_split_csv(os.getenv("WECHAT_EXCLUDED_ARTICLE_TITLE_KEYWORDS", "")),
    ]
    return any(keyword.lower() in title for keyword in excluded if keyword)


def _article_is_recent(payload: dict[str, Any], *, max_age_days: int = 2) -> bool:
    published_at = _parse_article_datetime(payload.get("published_at"))
    if published_at is None:
        return False
    tz = timezone(timedelta(hours=float(os.getenv("WECHAT_HOTNESS_TIMEZONE_OFFSET_HOURS", "8"))))
    local_published_at = published_at.astimezone(tz)
    today = datetime.now(tz).date()
    safe_days = max(1, max_age_days)
    return today - timedelta(days=safe_days - 1) <= local_published_at.date() <= today


def _article_timestamp(payload: dict[str, Any]) -> float:
    published_at = _parse_article_datetime(payload.get("published_at"))
    return published_at.timestamp() if published_at is not None else 0.0


def _parse_article_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        parsed = datetime.fromtimestamp(number, tz=timezone.utc)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_excluded_account_name(nickname: str) -> bool:
    excluded = ["AI简说局", "thinkingloop", *_split_csv(os.getenv("WECHAT_EXCLUDED_ACCOUNT_NAMES", ""))]
    excluded_keywords = [
        *DEFAULT_EXCLUDED_ACCOUNT_KEYWORDS,
        *_split_csv(os.getenv("WECHAT_EXCLUDED_ACCOUNT_KEYWORDS", "")),
    ]
    lowered = nickname.lower()
    return any(name.lower() in lowered for name in excluded if name) or any(
        keyword.lower() in lowered for keyword in excluded_keywords if keyword
    )


def _looks_like_wechat_fakeid(value: str) -> bool:
    # Real official-account fakeids from WeChat are base64-ish strings, usually
    # ending with ==. Some RSS rows expose short internal IDs instead; using
    # those can make the upstream API fall back to the logged-in account.
    return bool(re.fullmatch(r"[A-Za-z0-9+/]{12,}={0,2}", value)) and value.endswith("=")


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
        parsed = _coerce_metric_int(value)
        if parsed is not None:
            return parsed
    return None


def _article_metric(article: dict[str, Any], item: dict[str, Any], *keys: str) -> int | None:
    candidates = [article, item]
    for container_key in ("appmsgstat", "stat", "stats", "metrics", "app_msg_stat", "appmsg_stat"):
        nested = article.get(container_key)
        if isinstance(nested, dict):
            candidates.append(nested)
        nested = item.get(container_key)
        if isinstance(nested, dict):
            candidates.append(nested)
    for candidate in candidates:
        value = _pick_int(candidate, *keys)
        if value is not None:
            return value
    return None


def _coerce_metric_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace(",", "").replace("，", "")
    if not normalized:
        return None
    plus_100k = "10万+" in normalized or "100000+" in normalized.lower()
    if plus_100k:
        return 100000
    multiplier = 1
    if "万" in normalized:
        multiplier = 10000
    elif normalized.lower().endswith("k"):
        multiplier = 1000
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return int(float(match.group(0)) * multiplier)
    except ValueError:
        return None


def _html_to_text(value: str) -> str:
    if "<" not in value and "&" not in value:
        return " ".join(value.split())
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>|</section\s*>|</h[1-6]\s*>|</li\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return "\n".join(line.strip() for line in unescape(text).splitlines() if line.strip())


def _extract_image_urls(article: dict[str, Any], html: str) -> list[str]:
    urls: list[str] = []
    for key in ("cover", "cover_url", "thumb_url", "image", "image_url", "pic_url"):
        value = _pick_str(article, key)
        if value:
            urls.append(value)
    for match in re.finditer(r"""(?:src|data-src|data-original)=["']([^"']+)["']""", html, flags=re.IGNORECASE):
        urls.append(unescape(match.group(1)))
    result: list[str] = []
    for url in urls:
        normalized = url.strip()
        if normalized.startswith("//"):
            normalized = "https:" + normalized
        if normalized.startswith("http://") and "qpic.cn" in normalized:
            normalized = "https://" + normalized.removeprefix("http://")
        if normalized.startswith(("http://", "https://")) and normalized not in result:
            result.append(normalized)
    return result[:12]


def _local_no_proxy_opener(url: str) -> Any | None:
    hostname = urlparse(url).hostname
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return build_opener(ProxyHandler({}))
    return None


def _pick_dict(item: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _stable_id(*parts: str) -> str:
    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
