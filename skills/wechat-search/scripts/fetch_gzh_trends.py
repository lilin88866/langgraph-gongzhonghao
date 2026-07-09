#!/usr/bin/env python3
"""Local wrapper for WeChat candidate search.

This project version does not use external provider keys or third-party APIs. It
reads `/workflow/rewrite/candidates` from the local langgraph-study server.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills"))

from local_wechat_feed import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
