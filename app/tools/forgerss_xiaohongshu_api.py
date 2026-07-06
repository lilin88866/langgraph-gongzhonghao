"""Xiaohongshu client backed by ForgeRSS-generated RSS feeds."""

from __future__ import annotations

import os
import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from app.schemas.hotspot import Platform, RawContent, SourcePlan


RSS_NAMESPACES = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
}


class ForgeRSSXiaohongshuClient:
    """Reads Xiaohongshu notes from a ForgeRSS feed URL or local feed file."""

    source_api = "forgerss-xiaohongshu-rss"

    def __init__(
        self,
        *,
        feed_url: str | None = None,
        feed_file: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.feed_url = feed_url
        self.feed_file = feed_file
        self.timeout_seconds = timeout_seconds or float(os.getenv("FORGERSS_TIMEOUT_SECONDS", "30"))

    @classmethod
    def from_env(cls) -> "ForgeRSSXiaohongshuClient | None":
        feed_url = os.getenv("XIAOHONGSHU_FORGERSS_FEED_URL") or os.getenv("FORGERSS_XIAOHONGSHU_FEED_URL")
        feed_file = os.getenv("XIAOHONGSHU_FORGERSS_FEED_FILE") or os.getenv("FORGERSS_XIAOHONGSHU_FEED_FILE")
        if not feed_url and not feed_file:
            return None
        return cls(feed_url=feed_url, feed_file=feed_file)

    def fetch(self, plan: SourcePlan) -> list[RawContent]:
        if plan.platform != Platform.XIAOHONGSHU:
            raise ValueError(f"{self.source_api} cannot fetch platform {plan.platform.value}")
        xml_text = self._read_feed()
        items = _parse_feed_items(xml_text)
        query = (plan.query or "").lower()
        if query:
            items = [
                item
                for item in items
                if query in item.get("title", "").lower() or query in item.get("text", "").lower()
            ] or items
        return [
            RawContent(
                platform=Platform.XIAOHONGSHU,
                dimension=plan.dimension,
                source_api=self.source_api,
                raw_payload=item,
            )
            for item in items[: plan.page_size]
        ]

    def _read_feed(self) -> str:
        if self.feed_file:
            return Path(self.feed_file).expanduser().read_text(encoding="utf-8")
        if not self.feed_url:
            raise RuntimeError("ForgeRSS Xiaohongshu feed is not configured")
        request = Request(self.feed_url, headers={"Accept": "application/rss+xml, application/xml, text/xml"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.source_api} HTTP {exc.code}: {detail[:500]}") from exc
        except (TimeoutError, URLError) as exc:
            raise RuntimeError(f"{self.source_api} request failed: {exc}") from exc


def _parse_feed_items(xml_text: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    channel = root.find("channel")
    item_nodes = channel.findall("item") if channel is not None else root.findall(".//item")
    items: list[dict[str, Any]] = []
    for item in item_nodes:
        title = _node_text(item, "title")
        link = _node_text(item, "link")
        guid = _node_text(item, "guid") or link
        description = _node_text(item, "description")
        content = _node_text(item, "content:encoded") or description
        author = _node_text(item, "author") or _node_text(item, "dc:creator")
        published_at = _node_text(item, "pubDate")
        media_urls = [
            value
            for value in (
                node.attrib.get("url")
                for node in item.findall("media:content", RSS_NAMESPACES)
            )
            if value
        ]
        items.append(
            {
                "id": guid or title,
                "author": author,
                "title": title,
                "text": _html_to_text(content),
                "media_type": "note",
                "published_at": published_at,
                "url": link,
                "metrics": _extract_metrics(description),
                "media_urls": media_urls,
                "provider_payload": {
                    "description": description,
                    "content": content,
                },
            }
        )
    return items


def _node_text(item: ElementTree.Element, tag: str) -> str:
    node = item.find(tag, RSS_NAMESPACES)
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _html_to_text(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>|</div\s*>|</section\s*>|</li\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return "\n".join(line.strip() for line in unescape(text).splitlines() if line.strip())


def _extract_metrics(value: str) -> dict[str, int]:
    text = _html_to_text(value)
    patterns = {
        "likes": r"(?:点赞|赞)[:：\s]*(\d+)",
        "comments": r"(?:评论|留言)[:：\s]*(\d+)",
        "saves": r"(?:收藏|收收藏)[:：\s]*(\d+)",
        "shares": r"(?:分享|转发)[:：\s]*(\d+)",
    }
    metrics: dict[str, int] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            metrics[key] = int(match.group(1))
    return metrics
