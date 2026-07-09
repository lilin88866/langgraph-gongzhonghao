#!/usr/bin/env python3
"""Local subscription helper for langgraph-study WeChat candidates."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills"))

from local_wechat_feed import build_search_payload, print_markdown, write_html  # noqa: E402


SUBSCRIPTIONS_FILE = ROOT / ".cache" / "local_gzh_subscriptions.json"
DEFAULT_CATEGORIES = {"竞对账号", "同类账号", "关注账号"}


def load_subscriptions() -> list[dict]:
    try:
        return json.loads(SUBSCRIPTIONS_FILE.read_text(encoding="utf-8")).get("subscriptions", [])
    except (OSError, json.JSONDecodeError):
        return []


def save_subscriptions(items: list[dict]) -> None:
    SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUBSCRIPTIONS_FILE.write_text(
        json.dumps({"updated_at": datetime.now().isoformat(timespec="seconds"), "subscriptions": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_subscription(name: str, account_id: str = "", category: str = "关注账号") -> None:
    items = load_subscriptions()
    if any(item.get("accountName") == name or (account_id and item.get("accountId") == account_id) for item in items):
        print(f"已订阅过：{name}")
        return
    items.append(
        {
            "accountName": name,
            "accountId": account_id,
            "category": category if category in DEFAULT_CATEGORIES else "关注账号",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    save_subscriptions(items)
    print(f"已添加订阅：{name}")


def remove_subscription(identifier: str) -> None:
    items = load_subscriptions()
    kept = [item for item in items if item.get("accountName") != identifier and item.get("accountId") != identifier]
    save_subscriptions(kept)
    print(f"已移除 {len(items) - len(kept)} 个订阅")


def list_subscriptions() -> None:
    items = load_subscriptions()
    if not items:
        print("暂无订阅。")
        return
    print("| 公众号 | ID | 分类 |")
    print("| --- | --- | --- |")
    for item in items:
        print(f"| {item.get('accountName', '')} | {item.get('accountId', '')} | {item.get('category', '')} |")


def fetch_or_report(args: argparse.Namespace, *, html: bool = False) -> None:
    keywords = ",".join(item.get("accountName", "") for item in load_subscriptions() if item.get("accountName"))
    if not keywords:
        keywords = args.keyword or ""
    payload = build_search_payload(keywords, refresh=args.refresh, max_items=args.max_items)
    print_markdown(payload)
    if html or not args.no_report:
        output_dir = Path(args.output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        path = write_html(payload, str(output_dir / "公众号订阅候选日报.html"))
        print(f"\nHTML 日报：{path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="本地公众号订阅追踪，不使用第三方外部密钥")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--max-items", type=int, default=50)
    parser.add_argument("--keyword", default="")
    parser.add_argument("--output-dir", default=str(Path.home() / "Downloads" / "QoderGzhReports"))
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--subscribe", action="store_true", help="兼容参数：请使用 /workflow/rewrite 手动更新")
    parser.add_argument("--unsubscribe", action="store_true", help="兼容参数：本地版不安装定时任务")
    subparsers = parser.add_subparsers(dest="command")

    add = subparsers.add_parser("add")
    add.add_argument("accountName")
    add.add_argument("--id", default="")
    add.add_argument("--category", default="关注账号")

    remove = subparsers.add_parser("remove")
    remove.add_argument("identifier")

    subparsers.add_parser("list")
    subparsers.add_parser("fetch")
    subparsers.add_parser("report")

    args = parser.parse_args()
    if args.command == "add":
        add_subscription(args.accountName, args.id, args.category)
    elif args.command == "remove":
        remove_subscription(args.identifier)
    elif args.command == "list":
        list_subscriptions()
    elif args.command == "report":
        fetch_or_report(args, html=True)
    else:
        fetch_or_report(args, html=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
