"""Check the local Ollama/OpenAI-compatible rewrite model configuration."""

from __future__ import annotations

from app.config.env import load_dotenv
from app.tools.qwen_rewrite_client import QwenRewriteClient


def main() -> None:
    load_dotenv()
    client = QwenRewriteClient.from_env()
    if client is None:
        raise SystemExit("Model is not configured. Set QWEN_API_KEY/QWEN_BASE_URL/QWEN_MODEL in .env.")

    print(f"Checking model: {client.model}")
    print(f"Base URL: {client.base_url}")
    try:
        result = client.rewrite("请只回答：Ollama OK")
    except RuntimeError as exc:
        raise SystemExit(f"Model check failed: {exc}") from exc
    print(result)


if __name__ == "__main__":
    main()
