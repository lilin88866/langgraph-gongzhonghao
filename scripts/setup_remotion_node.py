"""Install Node/npm for the Remotion renderer inside the current Python venv."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
VENV_DIR = Path(sys.prefix)
VIDEO_RENDERER_DIR = ROOT_DIR / "video-renderer"


def main() -> None:
    _ensure_in_venv()
    _install_node_into_venv()
    _install_remotion_dependencies()
    print("Remotion Node/npm setup complete.")
    print(f"Node tools are in: {VENV_DIR / 'bin'}")


def _ensure_in_venv() -> None:
    if not (VENV_DIR / "pyvenv.cfg").exists():
        raise SystemExit("请先使用项目 .venv 运行：.venv/bin/python scripts/setup_remotion_node.py")


def _install_node_into_venv() -> None:
    command = [
        sys.executable,
        "-m",
        "nodeenv",
        "-p",
        "--force",
        "--node",
        os.getenv("REMOTION_NODE_VERSION", "20.11.1"),
        "--npm",
        os.getenv("REMOTION_NPM_VERSION", "10.2.4"),
    ]
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def _install_remotion_dependencies() -> None:
    if not VIDEO_RENDERER_DIR.exists():
        raise SystemExit("缺少 video-renderer 目录。")
    env = os.environ.copy()
    cache_dir = ROOT_DIR / ".cache" / "npm"
    tmp_dir = ROOT_DIR / ".cache" / "tmp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "HOME": str(ROOT_DIR),
            "TMPDIR": str(tmp_dir),
            "XDG_CACHE_HOME": str(ROOT_DIR / ".cache"),
            "npm_config_cache": str(cache_dir),
            "PATH": f"{VENV_DIR / 'bin'}{os.pathsep}{env.get('PATH', '')}",
        }
    )
    subprocess.run([str(VENV_DIR / "bin" / "npm"), "install"], cwd=VIDEO_RENDERER_DIR, env=env, check=True)


if __name__ == "__main__":
    main()
