"""Generate Xiaohongshu RSS feed using external ForgeRSS."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT_DIR / "external" / "ForgeRSS"
VENV_PYTHON = SERVICE_DIR / ".venv" / "bin" / "python"
FEED_FILE = SERVICE_DIR / "feeds" / "feed_xiaohongshu_user.xml"


def main() -> None:
    if not (SERVICE_DIR / "scripts" / "run_single.py").exists():
        raise SystemExit(f"ForgeRSS is not installed at {SERVICE_DIR}. Run: python scripts/setup_forgerss.py")
    xhs_user_id = os.getenv("XHS_USER_ID")
    if not xhs_user_id:
        raise SystemExit("Set XHS_USER_ID to a Xiaohongshu user id or profile URL.")

    max_items = os.getenv("XIAOHONGSHU_FORGERSS_MAX_ITEMS", os.getenv("MAX_ARTICLES", "10"))
    python_bin = str(VENV_PYTHON if VENV_PYTHON.exists() else "python")
    env = {**os.environ, "XHS_USER_ID": xhs_user_id}
    subprocess.run(
        [python_bin, "scripts/run_single.py", "xiaohongshu_user", "--max", max_items],
        cwd=SERVICE_DIR,
        env=env,
        check=True,
    )
    print(f"Generated feed: {FEED_FILE}")
    print("Use this in langgraph-study:")
    print("XIAOHONGSHU_PROVIDER=forgerss")
    print(f"XIAOHONGSHU_FORGERSS_FEED_FILE={FEED_FILE}")


if __name__ == "__main__":
    main()
