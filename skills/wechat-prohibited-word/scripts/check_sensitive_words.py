#!/usr/bin/env python3
"""Prepare Qwen input for WeChat publishing risk checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


MAX_TOTAL_LENGTH = 10000


def read_input(args: argparse.Namespace) -> str:
    if args.content:
        return args.content
    if args.file:
        return Path(args.file).read_text(encoding="utf-8", errors="replace")
    if args.url:
        return f"用户提供网页链接：{args.url}\n请先基于用户提供的页面摘要或正文进行检查。"
    return ""


def build_payload(content: str, extract_only: bool) -> dict:
    payload = {
        "provider": "qianwen",
        "task": "wechat_publish_risk_check",
        "content": content,
        "length": len(content),
    }
    if extract_only:
        return payload
    payload["analysis_instruction"] = (
        "请使用千问检查公众号发布风险，重点关注夸大承诺、绝对化用语、"
        "未验证数据、医疗金融法律风险、版权肖像风险和标题误导。"
    )
    payload["expected_output"] = [
        "风险等级",
        "必须修改",
        "建议修改",
        "可以保留",
        "发布前复核清单",
    ]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Qwen input for WeChat risk check.")
    parser.add_argument("--content", default="", help="待检查文本。")
    parser.add_argument("--file", default="", help="待检查文本文件。")
    parser.add_argument("--url", default="", help="网页链接，需配合用户提供正文或摘要。")
    parser.add_argument("--extract-only", action="store_true", help="仅输出提取文本。")
    parser.add_argument("--pretty", action="store_true", help="格式化输出 JSON。")
    args = parser.parse_args()

    content = read_input(args).strip()
    if not content:
        raise SystemExit("请通过 --content、--file 或 --url 提供待检查内容。")
    if len(content) > MAX_TOTAL_LENGTH:
        raise SystemExit(f"内容过长（{len(content)} 字），请分批检查。")

    payload = build_payload(content, args.extract_only)
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
