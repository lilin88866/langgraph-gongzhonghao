"""Start external services and the auto-reloading development API server."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def main() -> None:
    os.chdir(ROOT_DIR)
    _ensure_project_env()
    _load_project_env()
    _start_ollama()
    _start_wechat_download_api()
    _ensure_server_dependencies()
    refresher = _start_wechat_refresher()
    try:
        _start_uvicorn()
    finally:
        if refresher is not None:
            refresher.terminate()


def _ensure_project_env() -> None:
    env_file = ROOT_DIR / ".env"
    env_example = ROOT_DIR / ".env.example"
    if not env_file.exists():
        shutil.copyfile(env_example, env_file)


def _load_project_env() -> None:
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), _strip_quotes(value.strip()))


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _start_wechat_download_api() -> None:
    subprocess.run(
        [sys.executable, str(ROOT_DIR / "scripts" / "start_wechat_download_api.py")],
        check=True,
    )


def _start_ollama() -> None:
    if os.getenv("QWEN_FALLBACK_AUTO_START", "1").lower() in {"0", "false", "no"}:
        print("Ollama auto start is disabled by QWEN_FALLBACK_AUTO_START=0")
        return
    if not _is_local_ollama_fallback():
        return

    command = [sys.executable, str(ROOT_DIR / "scripts" / "start_ollama_docker.py")]
    model = os.getenv("QWEN_FALLBACK_MODEL")
    if model:
        command.extend(["--model", model])
    if os.getenv("QWEN_FALLBACK_AUTO_PULL", "1").lower() in {"0", "false", "no"}:
        command.append("--skip-pull")

    print("Starting local Ollama fallback model")
    subprocess.run(command, check=True)


def _is_local_ollama_fallback() -> bool:
    base_url = os.getenv("QWEN_FALLBACK_BASE_URL", "")
    return "localhost:11434" in base_url or "127.0.0.1:11434" in base_url


def _ensure_server_dependencies() -> None:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Missing server dependencies. Install them with: "
            "python -m pip install -e '.[server]'"
        ) from exc


def _start_wechat_refresher() -> subprocess.Popen | None:
    auto_refresh = os.getenv("WECHAT_AUTO_REFRESH", "1").lower() not in {"0", "false", "no"}
    if not auto_refresh:
        print("WeChat auto refresh is disabled by WECHAT_AUTO_REFRESH=0")
        return None

    interval = os.getenv("WECHAT_REFRESH_INTERVAL_SECONDS", "7200")
    print(f"Starting WeChat auto refresh scheduler every {interval} seconds")
    return subprocess.Popen(
        [sys.executable, str(ROOT_DIR / "scripts" / "refresh_wechat_downloads.py")],
        cwd=ROOT_DIR,
    )


def _start_uvicorn() -> None:
    host = os.getenv("LANGGRAPH_SERVER_HOST", "0.0.0.0")
    port = os.getenv("LANGGRAPH_SERVER_PORT", "8000")
    env = os.environ.copy()
    env.setdefault("WECHAT_DOWNLOAD_API_AUTO_START", "0")
    env.setdefault("QWEN_FALLBACK_AUTO_START", "0")
    venv_bin = Path(sys.executable).resolve().parent
    env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"

    print(f"Starting langgraph-study server at http://{host}:{port}")
    print("Auto reload watches app/, scripts/, and external/.")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.server:app",
            "--host",
            host,
            "--port",
            port,
            "--reload",
            "--reload-dir",
            "app",
            "--reload-dir",
            "scripts",
            "--reload-dir",
            "external",
            "--reload-exclude",
            "external/ChinaTextbook/**",
            "--timeout-graceful-shutdown",
            "5",
        ],
        cwd=ROOT_DIR,
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
