#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat-article-style/scripts/rewrite.py

公众号文案改写辅助脚本
用途：输出公众号改写规则，并生成供千问使用的改写任务说明。
只在本地整理千问改写任务说明。

用法：
  python rewrite.py prompt                  # 输出公众号改写规则 prompt
  python rewrite.py "<文案内容>"           # 生成千问改写任务说明
"""

import sys
import os
import re
from typing import Dict, Any

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_FILE = os.path.join(SCRIPT_DIR, '..', 'assets', 'platform-rules.md')

# ── 平台 ──────────────────────────────────────────────────────────────────────
PLATFORM = '公众号'

# ─────────────────────────────────────────────────────────────────────────────
# 规则提取
# ─────────────────────────────────────────────────────────────────────────────

def extract_platform_rules() -> str:
    """读取规则文件，提取公众号规则块。"""
    rules_path = os.path.normpath(RULES_FILE)
    if not os.path.exists(rules_path):
        print(f'❌ 规则文件不存在：{rules_path}', file=sys.stderr)
        sys.exit(1)

    with open(rules_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取公众号部分（从 ## 公众号 到文件末尾）
    match = re.search(r'^## 公众号\n(.*)', content, re.DOTALL | re.MULTILINE)
    if match:
        return '## 公众号\n' + match.group(1).strip()
    return ''


# ─────────────────────────────────────────────────────────────────────────────
# 千问改写任务：本地生成，不调用外部记录接口
# ─────────────────────────────────────────────────────────────────────────────

def report_rewrite(content: str) -> Dict[str, Any]:
    """
    保留函数名以兼容旧流程。现在只返回本地千问任务信息。
    """
    return {
        'ok': True,
        'provider': 'qianwen',
        'platform': PLATFORM,
        'content_length': len(content),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI 命令
# ─────────────────────────────────────────────────────────────────────────────

def cmd_prompt() -> None:
    """输出公众号改写规则 prompt。"""
    rules = extract_platform_rules()
    if not rules:
        print(f'\n❌ 规则文件中未找到公众号规则\n', file=sys.stderr)
        sys.exit(1)

    print(f'\n✅ 平台：{PLATFORM}\n')
    print('─' * 60)
    print('\n【System Prompt（供 AI 使用）】\n')
    print(rules)


def cmd_report(content: str) -> None:
    """生成千问改写任务说明。"""
    print(f'\n🧠 准备千问公众号改写任务…')
    result = report_rewrite(content)
    if result.get('ok'):
        print(f'✅ 已准备（provider={result.get("provider")}）')
        print('请将原文交给千问，并按公众号规则输出改写结果。')
    else:
        print(
            f'⚠️  准备失败：{result.get("error")}',
            file=sys.stderr
        )


def print_help() -> None:
    print(f"""
📝 公众号文案改写辅助脚本

用法：
  python rewrite.py prompt                    # 输出公众号改写规则 prompt
  python rewrite.py "<文案内容>"              # 生成千问改写任务说明

注意：
  不调用外部统计接口。实际改写由千问根据公众号规则完成。
""")


# ─────────────────────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ('-h', '--help'):
        print_help()
        sys.exit(0)

    first = args[0].lower()

    # ── prompt ──────────────────────────────────────────────────────────────
    if first == 'prompt':
        cmd_prompt()
        return

    # ── 上报记录 ────────────────────────────────────────────────────────────
    content = ' '.join(args)
    cmd_report(content)


if __name__ == '__main__':
    main()