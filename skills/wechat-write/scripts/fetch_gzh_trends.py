#!/usr/bin/env python3
"""Local wrapper for WeChat writing reference candidates."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills"))

from local_wechat_feed import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
