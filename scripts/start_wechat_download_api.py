"""Start the external wechat-download-api Docker service."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT_DIR / "external" / "wechat-download-api"


def main() -> None:
    env_file = SERVICE_DIR / ".env"
    env_example = SERVICE_DIR / ".env.example"
    if not env_file.exists():
        shutil.copyfile(env_example, env_file)

    subprocess.run(["docker", "compose", "up", "-d"], cwd=SERVICE_DIR, check=True)

    print("wechat-download-api is starting at http://localhost:5000")
    print("Open http://localhost:5000/login.html and scan the QR code before running the workflow.")


if __name__ == "__main__":
    main()
