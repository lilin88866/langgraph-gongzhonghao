#!/usr/bin/env python3
"""Local WeChat account analyzer for langgraph-study."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills"))

from local_wechat_feed import build_search_payload  # noqa: E402


def analyze_account(account: str, *, refresh: bool = False) -> dict:
    payload = build_search_payload(account, refresh=refresh, max_items=100)
    articles = payload.get("articles") or []
    if not articles:
        fallback = build_search_payload("", refresh=refresh, max_items=100).get("articles") or []
        articles = [item for item in fallback if account in item.get("author", "") or account in item.get("title", "")]
    total_reads = sum(int(item.get("clicksCount") or 0) for item in articles)
    total_likes = sum(int(item.get("likeCount") or 0) for item in articles)
    total_comments = sum(int(item.get("commentCount") or 0) for item in articles)
    count = len(articles)
    avg_reads = round(total_reads / count) if count else 0
    interaction_rate = round((total_likes + total_comments) / max(total_reads, 1) * 100, 2) if count else 0
    score = min(100, round(avg_reads / 1000 + interaction_rate * 2 + min(count, 10) * 3, 1))
    return {
        "account": account,
        "article_count": count,
        "avg_reads": avg_reads,
        "total_reads": total_reads,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "interaction_rate": interaction_rate,
        "score": score,
        "grade": grade(score),
        "articles": articles[:10],
        "source": "langgraph-study local wechat-download-api",
    }


def grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "E"


def print_report(result: dict) -> None:
    print(f"# 公众号账号本地诊断：{result['account']}")
    print()
    print("## 一、账号信息")
    print(f"- 数据来源：{result['source']}")
    print(f"- 候选文章数：{result['article_count']}")
    print()
    print("## 二、综合评分")
    print(f"- 综合评分：{result['score']} / 100")
    print(f"- 评级：{result['grade']}")
    print(f"- 平均阅读：{result['avg_reads']}")
    print(f"- 互动率：{result['interaction_rate']}%")
    print()
    print("## 三、近期待选文章数据")
    print("| 标题 | 阅读 | 点赞 | 评论 | 链接 |")
    print("| --- | ---: | ---: | ---: | --- |")
    for article in result["articles"]:
        print(
            f"| {article.get('title', '').replace('|', ' ')} | "
            f"{article.get('clicksCount', 0)} | {article.get('likeCount', 0)} | "
            f"{article.get('commentCount', 0)} | {article.get('url', '')} |"
        )
    print()
    print("## 四、优化建议")
    if result["article_count"] == 0:
        print("- 当前本地候选里没有匹配文章，请先在 `/workflow/rewrite` 手动更新订阅号文章。")
    elif result["avg_reads"] < 5000:
        print("- 优先优化标题钩子和选题聚焦度，挑选读者收益更明确的主题。")
    else:
        print("- 保持当前高阅读选题方向，继续沉淀可复用标题和结构模板。")
    print("- 发布前仍需人工复核事实、版权、图片和合规风险。")
    print()
    print("## 五、行业对标分析")
    print("- 本地版只基于当前工程候选文章做轻量诊断，不使用外部指数。")


def main() -> int:
    parser = argparse.ArgumentParser(description="本地公众号账号诊断")
    parser.add_argument("account", nargs="?", default="")
    parser.add_argument("--account", dest="account_option", default="")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    account = args.account_option or args.account
    if not account:
        print("请提供公众号名称，例如：python scripts/wechat_analyzer.py AI前沿", file=sys.stderr)
        return 2
    result = analyze_account(account, refresh=args.refresh)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
