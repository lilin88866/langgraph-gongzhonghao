"""Periodically refresh downloaded articles in the external wechat-download-api service."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import ProxyHandler, Request, build_opener


DEFAULT_INTERVAL_SECONDS = 2 * 60 * 60
ROOT_DIR = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT_DIR / ".wechat_refresh_state.json"


def main() -> None:
    args = _parse_args()
    interval_seconds = args.interval_seconds or int(
        os.getenv("WECHAT_REFRESH_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))
    )
    base_url = args.base_url or os.getenv("WECHAT_DOWNLOAD_API_BASE_URL", "http://localhost:5000")
    history_count = args.history_count or int(os.getenv("WECHAT_REFRESH_HISTORY_COUNT", "20"))
    request_timeout = args.request_timeout or int(os.getenv("WECHAT_REFRESH_REQUEST_TIMEOUT_SECONDS", "300"))
    batch_size = args.batch_size or int(os.getenv("WECHAT_REFRESH_BATCH_SIZE", "10"))
    use_rss_poll = args.use_rss_poll or os.getenv("WECHAT_REFRESH_USE_RSS_POLL", "0").lower() in {"1", "true", "yes"}
    warm_workflow_cache = args.warm_workflow_cache or os.getenv("WECHAT_REFRESH_WARM_WORKFLOW_CACHE", "1").lower() in {"1", "true", "yes"}
    workflow_base_url = args.workflow_base_url or os.getenv("LANGGRAPH_WORKFLOW_BASE_URL", _default_workflow_base_url())

    while True:
        try:
            refresh_once(
                base_url=base_url,
                history_count=history_count,
                request_timeout=request_timeout,
                batch_size=batch_size,
                use_rss_poll=use_rss_poll,
                warm_workflow_cache=warm_workflow_cache,
                workflow_base_url=workflow_base_url,
            )
        except RuntimeError as exc:
            print(f"[wechat-refresh] refresh failed: {exc}", flush=True)
        if args.once:
            return
        print(f"[wechat-refresh] sleeping {interval_seconds} seconds", flush=True)
        time.sleep(interval_seconds)


def refresh_once(
    *,
    base_url: str,
    history_count: int,
    request_timeout: int = 300,
    batch_size: int = 10,
    use_rss_poll: bool = False,
    warm_workflow_cache: bool = False,
    workflow_base_url: str | None = None,
) -> None:
    client = WechatRefreshClient(base_url=base_url, request_timeout=request_timeout)
    print("[wechat-refresh] checking service health", flush=True)
    client.get_json("/api/health")

    if use_rss_poll:
        print("[wechat-refresh] triggering RSS poll", flush=True)
        try:
            poll_result = client.post_json("/api/rss/poll", None)
            print(f"[wechat-refresh] poll result: {_compact_json(poll_result)}", flush=True)
        except RuntimeError as exc:
            print(f"[wechat-refresh] RSS poll failed: {exc}", flush=True)

    subscriptions = client.get_json("/api/rss/subscriptions")
    fakeids = _subscription_fakeids(subscriptions)
    batch = _next_batch(fakeids, batch_size)
    print(f"[wechat-refresh] subscriptions: {len(fakeids)}, batch: {len(batch)}", flush=True)
    for fakeid in batch:
        try:
            result = client.post_json("/api/admin/history/fetch", {"fakeid": fakeid, "count": history_count})
            print(f"[wechat-refresh] fetched history for {fakeid}: {_compact_json(result)}", flush=True)
        except RuntimeError as exc:
            print(f"[wechat-refresh] fetch history failed for {fakeid}: {exc}", flush=True)
    if warm_workflow_cache and workflow_base_url:
        _warm_rewrite_candidates_cache(workflow_base_url, request_timeout=request_timeout)


class WechatRefreshClient:
    def __init__(self, *, base_url: str, request_timeout: int = 300) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.request_timeout = request_timeout
        self.opener = build_opener(ProxyHandler({}))

    def get_json(self, path: str) -> Any:
        return self._send(Request(urljoin(self.base_url, path.lstrip("/")), method="GET"))

    def post_json(self, path: str, payload: dict[str, Any] | None) -> Any:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._send(
            Request(
                urljoin(self.base_url, path.lstrip("/")),
                data=body,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                method="POST",
            )
        )

    def _send(self, request: Request) -> Any:
        try:
            with self.opener.open(request, timeout=self.request_timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {error_body}") from exc
        except (TimeoutError, URLError) as exc:
            raise RuntimeError(f"request failed: {exc}") from exc

        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError("service returned non-JSON response") from exc


def _subscription_fakeids(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        data = payload.get("data", payload)
    else:
        data = payload
    if not isinstance(data, list):
        return []
    fakeids: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        fakeid = item.get("fakeid") or item.get("fake_id") or item.get("id")
        if fakeid:
            fakeids.append(str(fakeid))
    return fakeids


def _next_batch(fakeids: list[str], batch_size: int) -> list[str]:
    if not fakeids:
        return []
    state = _read_state()
    cursor = int(state.get("cursor", 0)) % len(fakeids)
    safe_batch_size = max(1, min(batch_size, len(fakeids)))
    batch = [fakeids[(cursor + offset) % len(fakeids)] for offset in range(safe_batch_size)]
    state["cursor"] = (cursor + safe_batch_size) % len(fakeids)
    _write_state(state)
    return batch


def _read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:500]


def _warm_rewrite_candidates_cache(base_url: str, *, request_timeout: int) -> None:
    client = WechatRefreshClient(base_url=base_url, request_timeout=request_timeout)
    try:
        result = client.get_json("/workflow/rewrite/candidates?refresh=true&cache_only=false")
        if isinstance(result, dict):
            items = result.get("items")
            count = len(items) if isinstance(items, list) else 0
            print(f"[wechat-refresh] warmed rewrite candidates cache: {count} items", flush=True)
        else:
            print("[wechat-refresh] warmed rewrite candidates cache", flush=True)
    except RuntimeError as exc:
        print(f"[wechat-refresh] warm rewrite candidates cache failed: {exc}", flush=True)


def _default_workflow_base_url() -> str:
    host = os.getenv("LANGGRAPH_SERVER_HOST", "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    port = os.getenv("LANGGRAPH_SERVER_PORT", "8000")
    return f"http://{host}:{port}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="wechat-download-api base URL")
    parser.add_argument("--interval-seconds", type=int, help="refresh interval, defaults to 7200 seconds")
    parser.add_argument("--history-count", type=int, help="history fetch count per subscribed account")
    parser.add_argument("--request-timeout", type=int, help="HTTP request timeout, defaults to 300 seconds")
    parser.add_argument("--batch-size", type=int, help="number of subscribed accounts to refresh per cycle")
    parser.add_argument("--use-rss-poll", action="store_true", help="also trigger /api/rss/poll before history fetch")
    parser.add_argument("--warm-workflow-cache", action="store_true", help="warm /workflow/rewrite candidates cache after refresh")
    parser.add_argument("--workflow-base-url", help="langgraph-study server base URL for cache warming")
    parser.add_argument("--once", action="store_true", help="run a single refresh and exit")
    return parser.parse_args()


if __name__ == "__main__":
    main()
