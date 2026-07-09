#!/usr/bin/env python3
"""Generate a local AI WeChat feed report for langgraph-study."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills"))

from local_wechat_feed import build_search_payload, print_markdown, write_html  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="生成本地 AI 公众号候选日报")
    parser.add_argument("--keywords", "--keyword", default="AI,人工智能,大模型,GPT,Agent")
    parser.add_argument("--count", "--max-items", type=int, default=50)
    parser.add_argument("--output-dir", default=str(Path.home() / "Downloads" / "QoderReports"))
    parser.add_argument("--no-open", action="store_true", help="兼容参数，本地脚本不自动打开浏览器")
    parser.add_argument("--refresh", action="store_true", help="强制刷新本地候选数据")
    parser.add_argument("--subscribe", action="store_true", help="兼容参数：请使用 /workflow/rewrite 手动更新")
    parser.add_argument("--unsubscribe", action="store_true", help="兼容参数：本地版不安装定时任务")
    parser.add_argument("--date", default="", help="兼容参数，本地候选接口忽略具体日期")
    args = parser.parse_args()

    payload = build_search_payload(args.keywords, refresh=args.refresh, max_items=args.count)
    print_markdown(payload)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "AI公众号候选日报.html"
    path = write_html(payload, str(output))
    print(f"\nHTML 日报：{path}")
    if args.subscribe:
        print("本地版不安装第三方定时任务；请在 /workflow/rewrite 使用“手动更新订阅号文章”。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
