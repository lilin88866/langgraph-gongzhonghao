#!/usr/bin/env python3
"""Local WeChat article feed helpers for langgraph-study skills.

These helpers intentionally avoid third-party data providers. They read the
project's local rewrite candidate endpoint, which is backed by the configured
wechat-download-api service.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def fetch_candidates(*, refresh: bool = False, cache_only: bool = False, hot_rank: bool = False) -> dict:
    base_url = os.getenv("LANGGRAPH_STUDY_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    endpoint = "/workflow/rewrite/hot-candidates" if hot_rank else "/workflow/rewrite/candidates"
    query = urlencode(
        {
            "refresh": "true" if refresh else "false",
            "cache_only": "true" if cache_only else "false",
        }
    )
    request = Request(f"{base_url}{endpoint}?{query}", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=float(os.getenv("LANGGRAPH_STUDY_FEED_TIMEOUT_SECONDS", "120"))) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"local rewrite candidates HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"无法连接本工程服务：{exc.reason}。请先启动 `python scripts/start_dev_server.py`。"
        ) from exc


def normalize_article(item: dict) -> dict:
    reads = _int(item.get("reads"))
    likes = _int(item.get("likes"))
    comments = _int(item.get("comments"))
    hotness = float(item.get("ai_hot_score") or item.get("hotness_score") or 0)
    return {
        "id": str(item.get("content_id") or item.get("url") or item.get("title") or ""),
        "title": str(item.get("title") or ""),
        "author": str(item.get("author") or "未知"),
        "url": item.get("url") or "",
        "publicTime": item.get("published_at") or "",
        "clicksCount": reads,
        "readCount": reads,
        "likeCount": likes,
        "commentCount": comments,
        "watchCount": 0,
        "totalScore": round(min(15.0, hotness / 7), 2),
        "relevanceScore": round(min(10.0, hotness / 10), 2),
        "hotScore": round(min(3.0, reads / 50000), 2),
        "timeScore": 2.0,
        "summary": item.get("hot_reason") or item.get("readiness_detail") or "",
        "category": item.get("hot_badge") or item.get("light") or "",
    }


def filter_articles(items: list[dict], keyword: str = "", limit: int = 20) -> list[dict]:
    keywords = [part.strip().lower() for part in keyword.split(",") if part.strip()]
    articles = [normalize_article(item) for item in items]
    if keywords:
        articles = [
            article
            for article in articles
            if any(keyword in f"{article['title']} {article['author']} {article['summary']}".lower() for keyword in keywords)
        ]
    articles.sort(key=lambda item: (item["clicksCount"], item["totalScore"]), reverse=True)
    return articles[: max(1, limit)]


def build_search_payload(keyword: str = "", *, refresh: bool = False, max_items: int = 20, hot_rank: bool = False) -> dict:
    data = fetch_candidates(refresh=refresh, cache_only=not refresh, hot_rank=hot_rank)
    items = data.get("items") or []
    articles = filter_articles(items, keyword, max_items)
    return {
        "keyword": keyword,
        "source": "langgraph-study local wechat-download-api" + (" / wechat-10w-hot" if hot_rank else ""),
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "articles": articles,
        "latestHotArticles": filter_articles(items, "", max_items),
        "hotTopics": [],
        "relatedSearches": [],
        "summary": data.get("summary") or {},
    }


def print_markdown(payload: dict) -> None:
    articles = payload.get("articles") or []
    print(f"📅 本地候选数据时间：{payload.get('generatedAt')}")
    print(f"数据来源：{payload.get('source')}")
    print()
    if not articles:
        print("暂无匹配文章。请先在 `/workflow/rewrite` 手动更新订阅号文章，或换一个关键词。")
        return
    print("| 文章标题 | 作者 | 阅读数 | 热度分 | 链接 |")
    print("| --- | --- | ---: | ---: | --- |")
    for article in articles:
        title = article["title"].replace("|", " ")
        author = article["author"].replace("|", " ")
        link = article["url"] or ""
        title_cell = f"[{title}]({link})" if link else title
        print(f"| {title_cell} | {author} | {article['clicksCount']} | {article['totalScore']} | {link} |")


def write_html(payload: dict, output: str | None = None) -> Path:
    output_path = Path(output or "本地公众号候选日报.html").expanduser()
    rows = "\n".join(
        "<tr>"
        f"<td><a href='{_html(article['url'])}'>{_html(article['title'])}</a></td>"
        f"<td>{_html(article['author'])}</td>"
        f"<td>{article['clicksCount']}</td>"
        f"<td>{article['totalScore']}</td>"
        "</tr>"
        for article in payload.get("articles", [])
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<title>本地公众号候选日报</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f6f8fb;color:#172033;padding:24px;}}
table{{width:100%;border-collapse:collapse;background:#fff;}}
th,td{{border-bottom:1px solid #d9e2ef;padding:10px;text-align:left;}}
th{{color:#667085;}}
a{{color:#2563eb;}}
</style>
<h1>本地公众号候选日报</h1>
<p>生成时间：{_html(payload.get("generatedAt", ""))}</p>
<p>数据来源：{_html(payload.get("source", ""))}</p>
<table><thead><tr><th>标题</th><th>作者</th><th>阅读</th><th>热度分</th></tr></thead><tbody>{rows}</tbody></table>
</html>"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None, *, default_hot_rank: bool = False) -> int:
    parser = argparse.ArgumentParser(description="读取 langgraph-study 本地公众号候选数据")
    parser.add_argument("--keyword", default="", help="按标题、作者或摘要关键词过滤，多个关键词用英文逗号分隔")
    parser.add_argument("--max-items", "--limit", type=int, default=20)
    parser.add_argument("--refresh", action="store_true", help="强制刷新本地候选数据")
    parser.add_argument("--output-format", choices=["json", "markdown", "html"], default="json")
    parser.add_argument("--output", help="HTML 输出路径")
    parser.add_argument("--type", default="", help="兼容 wechat-10w-hot 的分类参数，会作为关键词参与过滤")
    parser.add_argument("--start-date", "--start_date", default="", help="兼容参数，本地候选接口会忽略具体日期")
    parser.add_argument("--end-date", "--end_date", default="", help="兼容参数，本地候选接口会忽略具体日期")
    parser.add_argument("--mode", default="preview", help="兼容参数")
    parser.add_argument("--hot-rank", action="store_true", default=default_hot_rank, help="使用 /workflow/rewrite/hot-candidates 高热榜接口")
    args = parser.parse_args(argv)

    keyword = args.keyword or ("" if args.type in {"", "总排名"} else args.type)
    payload = build_search_payload(keyword, refresh=args.refresh, max_items=args.max_items, hot_rank=args.hot_rank)
    if args.output_format == "markdown":
        print_markdown(payload)
    elif args.output_format == "html":
        path = write_html(payload, args.output)
        print(path)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def hot_main(argv: list[str] | None = None) -> int:
    return main(argv, default_hot_rank=True)


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _html(value: object) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


if __name__ == "__main__":
    raise SystemExit(main())
