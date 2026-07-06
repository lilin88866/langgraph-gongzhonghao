"""Start Ollama through Docker for the local rewrite model."""

from __future__ import annotations

import argparse
import subprocess
import sys


CONTAINER_NAME = "ollama"
IMAGE = "ollama/ollama"
MODEL = "qwen2.5:7b"


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Docker Ollama and optionally pull the rewrite model.")
    parser.add_argument("--model", default=MODEL, help="Model to pull inside Ollama.")
    parser.add_argument("--skip-pull", action="store_true", help="Only start the container; do not pull the model.")
    args = parser.parse_args()

    _ensure_docker()
    if _container_exists(CONTAINER_NAME):
        _run(["docker", "start", CONTAINER_NAME])
    else:
        _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                CONTAINER_NAME,
                "-p",
                "11434:11434",
                "-v",
                "ollama:/root/.ollama",
                IMAGE,
            ]
        )

    if not args.skip_pull:
        _run(["docker", "exec", CONTAINER_NAME, "ollama", "pull", args.model])

    print("Ollama Docker is ready at http://localhost:11434")


def _ensure_docker() -> None:
    try:
        _run(["docker", "--version"], capture=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit("Docker is not available. Install/start Docker first.") from exc


def _container_exists(name: str) -> bool:
    result = _run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture=True,
    )
    return name in result.stdout.splitlines()


def _run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command))
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout)
        sys.exit(exc.returncode)
