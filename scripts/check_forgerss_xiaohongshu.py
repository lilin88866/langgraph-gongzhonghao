"""Check ForgeRSS Xiaohongshu login state and generated feed path."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT_DIR / "external" / "ForgeRSS"
VENV_PYTHON = SERVICE_DIR / ".venv" / "bin" / "python"
FEED_FILE = SERVICE_DIR / "feeds" / "feed_xiaohongshu_user.xml"


def main() -> None:
    if not (SERVICE_DIR / "scripts" / "run_single.py").exists():
        raise SystemExit(f"ForgeRSS is not installed at {SERVICE_DIR}. Run: python scripts/setup_forgerss.py")
    python_bin = str(VENV_PYTHON if VENV_PYTHON.exists() else "python")
    test_script = SERVICE_DIR / "tools" / "test_login_check.py"
    if test_script.exists():
        subprocess.run([python_bin, str(test_script), "xiaohongshu"], cwd=SERVICE_DIR, check=True)
    else:
        print("ForgeRSS login checker not found; skipped login check.")

    if FEED_FILE.exists():
        print(f"Feed exists: {FEED_FILE}")
        print(f"Size: {FEED_FILE.stat().st_size} bytes")
    else:
        print(f"Feed not found yet: {FEED_FILE}")
        print("Generate it with: python scripts/run_forgerss_xiaohongshu.py")


if __name__ == "__main__":
    main()
