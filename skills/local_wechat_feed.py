#!/usr/bin/env python3
"""Unified local WeChat article feed helpers for langgraph-study skills.

The helpers prefer project-local data and avoid third-party providers. They can
read cached FastAPI endpoints, the full local WeChat article feed, or the
configured self-hosted wechat-download-api client, then normalize everything into
one article shape for hot lists, HTML reports, and account analysis.
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
SOURCE_CHOICES = ("auto", "cache", "feed", "hot", "download")
TOTAL_TYPES = {"", "总排名", "总榜", "全部", "综合", "热点", "热门", "爆文", "10w+", "推荐", "最新"}
CATEGORY_KEYWORDS = {
    "科技数码": "科技,数码,手机,电脑,智能,AI,人工智能,互联网,软件,硬件,芯片,5G,新能源,电动车,特斯拉,大模型,智能体,模型",
    "AI": "AI,人工智能,大模型,智能体,模型,Agent,Claude,OpenAI,DeepSeek",
    "人工智能": "AI,人工智能,大模型,智能体,模型,Agent,Claude,OpenAI,DeepSeek",
    "知识百科": "知识,科普,百科,常识,学习,原理,教程,指南,解析",
    "创投商业": "创投,创业,投资,商业,企业,公司,管理,营销,融资,上市,产品",
    "职场发展": "职场,工作,求职,面试,简历,跳槽,升职,职业,效率,协作",
    "教育考试": "教育,考试,学习,课程,学校,大学,培训,辅导",
    "学术研究": "学术,研究,论文,科研,实验,发现,成果,专家",
    "企业品牌": "企业,品牌,公司,案例,战略,转型,创新,产品,服务",
    "财富理财": "财富,理财,投资,基金,股票,财经,金融,银行,保险",
}


def fetch_candidates(
    *,
    refresh: bool = False,
    cache_only: bool = False,
    hot_rank: bool = False,
    limit: int = 20,
    source: str | None = None,
) -> dict:
    """Backward-compatible endpoint fetcher used by existing skills."""
    resolved_source = source or ("hot" if hot_rank else "cache")
    if resolved_source == "download":
        return fetch_download_articles(limit=limit)
    endpoint = {
        "cache": "/workflow/rewrite/candidates",
        "hot": "/workflow/rewrite/hot-candidates",
        "feed": "/workflow/wechat/articles",
    }.get(resolved_source, "/workflow/rewrite/candidates")
    return fetch_local_endpoint(endpoint, refresh=refresh, cache_only=cache_only, limit=limit)


def fetch_local_endpoint(endpoint: str, *, refresh: bool = False, cache_only: bool = True, limit: int = 20) -> dict:
    base_url = os.getenv("LANGGRAPH_STUDY_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    query = urlencode(
        {
            "refresh": "true" if refresh else "false",
            "cache_only": "true" if cache_only else "false",
            "limit": max(1, int(limit or 20)),
        }
    )
    request = Request(f"{base_url}{endpoint}?{query}", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=float(os.getenv("LANGGRAPH_STUDY_FEED_TIMEOUT_SECONDS", "120"))) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"local WeChat endpoint {endpoint} HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"无法连接本工程服务：{exc.reason}。请先启动 `python scripts/start_dev_server.py`。"
        ) from exc


def fetch_download_articles(*, limit: int = 50) -> dict:
    """Read directly from the configured wechat-download-api client."""
    try:
        from app.tools.wechat_download_api import WechatDownloadApiClient
    except ImportError as exc:  # pragma: no cover - depends on invocation path.
        raise RuntimeError(f"无法导入 WechatDownloadApiClient：{exc}") from exc

    client = WechatDownloadApiClient.from_env()
    if client is None:
        raise RuntimeError("未配置 WECHAT_DOWNLOAD_API_BASE_URL，无法直接读取 wechat-download-api。")
    raw_contents = client.fetch_subscription_articles(
        account_limit=int(os.getenv("WECHAT_REWRITE_SUBSCRIPTION_ACCOUNT_LIMIT", "0")),
        page_size=max(20, min(100, int(limit or 50))),
        article_keywords=None,
        max_age_days=int(os.getenv("WECHAT_REWRITE_FALLBACK_MAX_AGE_DAYS", "4")),
        articles_per_account=max(1, int(os.getenv("WECHAT_REWRITE_ARTICLES_PER_ACCOUNT", "3"))),
    )
    items = [getattr(raw, "raw_payload", {}) for raw in raw_contents]
    return {
        "items": items,
        "summary": {"download_article_count": len(items), "source": "wechat-download-api"},
        "cached": False,
        "source": "wechat-download-api",
    }


def normalize_article(item: dict) -> dict:
    reads = _int(item.get("reads") or item.get("readCount") or _nested_metric(item, "reads"))
    likes = _int(item.get("likes") or item.get("likeCount") or _nested_metric(item, "likes"))
    comments = _int(item.get("comments") or item.get("commentCount") or _nested_metric(item, "comments"))
    hotness = _float(item.get("ai_hot_score") or item.get("hotness_score") or item.get("totalScore") or 0)
    return {
        "id": str(item.get("content_id") or item.get("id") or item.get("url") or item.get("title") or ""),
        "title": str(item.get("title") or ""),
        "author": str(item.get("author") or item.get("userName") or "未知"),
        "url": item.get("url") or item.get("oriUrl") or "",
        "publicTime": item.get("published_at") or item.get("publicTime") or "",
        "clicksCount": reads,
        "readCount": reads,
        "likeCount": likes,
        "commentCount": comments,
        "watchCount": 0,
        "totalScore": round(min(15.0, hotness / 7 if hotness > 15 else hotness), 2),
        "relevanceScore": round(min(10.0, hotness / 10), 2),
        "hotScore": round(min(3.0, reads / 50000), 2),
        "timeScore": 2.0,
        "summary": item.get("hot_reason") or item.get("readiness_detail") or item.get("summary") or item.get("text") or "",
        "category": item.get("hot_badge") or item.get("knowledge_badge") or item.get("light") or "",
        "accountId": _account_id(item),
        "userName": str(item.get("author") or item.get("userName") or "未知"),
        "oriUrl": item.get("url") or item.get("oriUrl") or "",
    }


def filter_articles(items: list[dict], keyword: str = "", limit: int = 20) -> list[dict]:
    keywords = _expanded_keywords(keyword)
    articles = [normalize_article(item) for item in items]
    if keywords:
        articles = [article for article in articles if _matches_keywords(article, keywords)]
    articles.sort(key=lambda item: (item["clicksCount"], item["totalScore"], item["publicTime"]), reverse=True)
    return articles[: max(1, int(limit or 20))]


def build_search_payload(
    keyword: str = "",
    *,
    refresh: bool = False,
    max_items: int = 20,
    hot_rank: bool = False,
    source: str = "auto",
) -> dict:
    resolved_source = _resolve_source(source, hot_rank=hot_rank)
    data = _load_source_payload(resolved_source, refresh=refresh, limit=max_items)
    items = data.get("items") or []
    articles = filter_articles(items, keyword, max_items)
    latest = filter_articles(items, "", max_items)
    return {
        "keyword": keyword,
        "source": _source_label(resolved_source, data),
        "sourceMode": resolved_source,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "articles": articles,
        "latestHotArticles": latest,
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
    parser = argparse.ArgumentParser(description="读取 langgraph-study 本地公众号数据")
    parser.add_argument("--keyword", default="", help="按标题、作者或摘要关键词过滤，多个关键词用英文逗号分隔")
    parser.add_argument("--max-items", "--limit", type=int, default=20)
    parser.add_argument("--refresh", action="store_true", help="强制刷新本地候选数据")
    parser.add_argument("--source", choices=SOURCE_CHOICES, default="feed" if default_hot_rank else "auto")
    parser.add_argument("--output-format", choices=["json", "markdown", "html"], default="json")
    parser.add_argument("--output", help="HTML 输出路径")
    parser.add_argument("--type", default="", help="兼容 wechat-10w-hot 的分类参数，会映射为关键词过滤")
    parser.add_argument("--start-date", "--start_date", default="", help="兼容参数，本地候选接口会忽略具体日期")
    parser.add_argument("--end-date", "--end_date", default="", help="兼容参数，本地候选接口会忽略具体日期")
    parser.add_argument("--mode", default="preview", help="兼容参数")
    parser.add_argument("--hot-rank", action="store_true", default=False, help="使用 /workflow/rewrite/hot-candidates 高热榜接口")
    args = parser.parse_args(argv)

    keyword = args.keyword or ("" if args.type in TOTAL_TYPES else args.type)
    source = "hot" if args.hot_rank else args.source
    payload = build_search_payload(keyword, refresh=args.refresh, max_items=args.max_items, source=source)
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


def _load_source_payload(source: str, *, refresh: bool, limit: int) -> dict:
    if source == "auto":
        errors: list[str] = []
        for candidate_source in ("feed", "hot", "cache", "download"):
            try:
                data = _load_source_payload(candidate_source, refresh=refresh if candidate_source == "feed" else False, limit=limit)
            except RuntimeError as exc:
                errors.append(f"{candidate_source}:{exc}")
                continue
            if data.get("items"):
                data.setdefault("summary", {})["auto_source"] = candidate_source
                return data
        return {"items": [], "summary": {"errors": errors}, "source": "auto"}
    if source == "download":
        return fetch_download_articles(limit=limit)
    endpoint = {
        "cache": "/workflow/rewrite/candidates",
        "hot": "/workflow/rewrite/hot-candidates",
        "feed": "/workflow/wechat/articles",
    }[source]
    return fetch_local_endpoint(endpoint, refresh=refresh, cache_only=not refresh, limit=limit)


def _resolve_source(source: str, *, hot_rank: bool) -> str:
    if hot_rank:
        return "hot"
    return source if source in SOURCE_CHOICES else "auto"


def _source_label(source: str, data: dict) -> str:
    label = {
        "auto": "langgraph-study local auto",
        "cache": "langgraph-study rewrite candidates cache",
        "feed": "langgraph-study local /workflow/wechat/articles",
        "hot": "langgraph-study local /workflow/rewrite/hot-candidates",
        "download": "wechat-download-api direct",
    }.get(source, source)
    auto_source = (data.get("summary") or {}).get("auto_source")
    return f"{label} / {auto_source}" if auto_source else label


def _expanded_keywords(keyword: str) -> list[str]:
    raw_parts = [part.strip() for part in str(keyword or "").split(",") if part.strip()]
    expanded: list[str] = []
    for part in raw_parts:
        if part in TOTAL_TYPES:
            continue
        mapped = CATEGORY_KEYWORDS.get(part, part)
        expanded.extend(item.strip() for item in mapped.split(",") if item.strip())
    seen: set[str] = set()
    result: list[str] = []
    for item in expanded:
        lowered = item.lower()
        if lowered not in seen:
            seen.add(lowered)
            result.append(lowered)
    return result


def _matches_keywords(article: dict, keywords: list[str]) -> bool:
    searchable = f"{article['title']} {article['author']} {article['summary']} {article.get('category', '')}".lower()
    return any(keyword in searchable for keyword in keywords)


def _nested_metric(item: dict, key: str) -> object:
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    return metrics.get(key)


def _account_id(item: dict) -> str:
    account = item.get("account") if isinstance(item.get("account"), dict) else {}
    return str(account.get("fakeid") or item.get("accountId") or "")


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


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
