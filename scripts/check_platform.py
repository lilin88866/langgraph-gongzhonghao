"""Check local platform prerequisites for langgraph-study.

This script is intentionally read-only. It reports what is available and what
will fall back at runtime on macOS, Windows/WSL2, and Linux.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
VIDEO_RENDERER_DIR = ROOT_DIR / "video-renderer"


def main() -> None:
    print(f"Platform: {platform.platform()}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"Project: {ROOT_DIR}")
    print()

    checks = [
        _check_python_package("fastapi", "FastAPI server"),
        _check_python_package("uvicorn", "Uvicorn server"),
        _check_python_package("PIL", "Pillow video fallback"),
        _check_python_package("edge_tts", "Edge TTS voiceover"),
        _check_python_package("imageio_ffmpeg", "Bundled ffmpeg fallback"),
        _check_command("docker", ["docker", "--version"], "Docker / Docker Desktop"),
        _check_command("node", ["node", "--version"], "Node.js for Remotion"),
        _check_command("npm", ["npm", "--version"], "npm for dependency installs"),
        _check_remotion_cli(),
        _check_ffmpeg(),
        _check_remotion_project(),
        _check_ollama(),
        _check_remotion_glibc(),
    ]

    width = max(len(item.name) for item in checks)
    for item in checks:
        marker = "OK" if item.ok else "WARN"
        print(f"[{marker}] {item.name:<{width}}  {item.detail}")


class CheckResult:
    def __init__(self, name: str, ok: bool, detail: str) -> None:
        self.name = name
        self.ok = ok
        self.detail = detail


def _check_python_package(module_name: str, label: str) -> CheckResult:
    if importlib.util.find_spec(module_name) is not None:
        return CheckResult(label, True, f"Python module '{module_name}' is installed.")
    return CheckResult(label, False, f"Missing Python module '{module_name}'.")


def _check_command(name: str, command: list[str], label: str) -> CheckResult:
    executable = _which(name)
    if executable is None:
        return CheckResult(label, False, f"Command '{name}' is not on PATH.")
    command = [str(executable), *command[1:]]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult(label, False, str(exc))
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    detail = output[0] if output else f"{name} found."
    return CheckResult(label, completed.returncode == 0, detail)


def _which(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    venv_dir = Path(sys.executable).resolve().parent
    candidates = [venv_dir / name]
    if platform.system().lower() == "windows":
        candidates.extend([venv_dir / f"{name}.exe", venv_dir / f"{name}.cmd"])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _check_ffmpeg() -> CheckResult:
    if importlib.util.find_spec("imageio_ffmpeg") is not None:
        return CheckResult("ffmpeg", True, "imageio-ffmpeg is installed.")
    return _check_command("ffmpeg", ["ffmpeg", "-version"], "ffmpeg")


def _check_remotion_project() -> CheckResult:
    package_json = VIDEO_RENDERER_DIR / "package.json"
    node_modules = VIDEO_RENDERER_DIR / "node_modules"
    if not package_json.exists():
        return CheckResult("Remotion project", False, "video-renderer/package.json is missing.")
    if not node_modules.exists():
        return CheckResult("Remotion project", False, "Run 'npm install' in video-renderer.")
    return CheckResult("Remotion project", True, "video-renderer dependencies are installed.")


def _check_remotion_cli() -> CheckResult:
    node = _which("node")
    local_cli = VIDEO_RENDERER_DIR / "node_modules" / ".bin" / "remotion"
    if node and local_cli.exists():
        try:
            completed = subprocess.run(
                [str(local_cli), "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                env={**os.environ, "PATH": f"{Path(node).parent}{os.pathsep}{os.environ.get('PATH', '')}"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CheckResult("Remotion CLI", False, str(exc))
        output = (completed.stdout or completed.stderr or "").strip().splitlines()
        detail = output[0] if output else "local Remotion CLI found."
        combined = f"{completed.stdout}\n{completed.stderr}"
        ok = completed.returncode == 0 or "@remotion/cli" in combined or "glibc" in combined.lower()
        return CheckResult("Remotion CLI", ok, detail)
    return _check_command("npx", ["npx", "remotion", "--version"], "Remotion CLI")


def _check_ollama() -> CheckResult:
    try:
        with urlopen("http://localhost:11434/api/tags", timeout=3) as response:
            return CheckResult("Ollama endpoint", response.status < 500, "http://localhost:11434 is reachable.")
    except URLError as exc:
        return CheckResult("Ollama endpoint", False, f"Not reachable: {exc.reason}")
    except TimeoutError:
        return CheckResult("Ollama endpoint", False, "Timed out.")


def _check_remotion_glibc() -> CheckResult:
    if platform.system().lower() != "linux":
        return CheckResult("Remotion glibc", True, "Not applicable outside Linux.")
    libc_name, libc_version = platform.libc_ver()
    if libc_name.lower() != "glibc" or not libc_version:
        return CheckResult("Remotion glibc", False, "Could not detect glibc version.")
    current = _version_tuple(libc_version)
    required = _version_tuple("2.31")
    if current >= required:
        return CheckResult("Remotion glibc", True, f"glibc {libc_version} >= 2.31.")
    if shutil.which("docker") is not None:
        image = os.getenv("VIDEO_RENDER_REMOTION_DOCKER_IMAGE", "mcr.microsoft.com/playwright:v1.49.1-jammy")
        return CheckResult("Remotion glibc", True, f"glibc {libc_version} < 2.31; Remotion render will use Docker image {image}.")
    return CheckResult("Remotion glibc", False, f"glibc {libc_version} < 2.31; Remotion render will fall back.")


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split(".") if part.isdigit())


if __name__ == "__main__":
    main()
