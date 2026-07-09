#!/usr/bin/env python3
"""Local wrapper for hot WeChat articles.

The original upstream skill used a third-party 10w+ API. In langgraph-study we
use the local rewrite candidates produced from the configured wechat-download-api
service, sorted by reads and hotness score.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills"))

from local_wechat_feed import hot_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(hot_main())
