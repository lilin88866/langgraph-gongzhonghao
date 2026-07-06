import io
import json
import os
import unittest
from unittest.mock import patch

from app.tools.qwen_rewrite_client import QwenRewriteClient, is_quota_error, is_timeout_error


class QwenRewriteClientTest(unittest.TestCase):
    def test_from_env_returns_none_without_api_key(self) -> None:
        with patch.dict(os.environ, {"QWEN_API_KEY": "", "DASHSCOPE_API_KEY": ""}, clear=True):
            self.assertIsNone(QwenRewriteClient.from_env())

    def test_rewrite_reads_chat_completion_content(self) -> None:
        response = io.BytesIO(
            json.dumps({"choices": [{"message": {"content": "### 改写标题\n\n测试"}}]}).encode("utf-8")
        )
        response.__enter__ = lambda item: item
        response.__exit__ = lambda *args: None
        client = QwenRewriteClient(api_key="test-key", base_url="https://example.com/v1", model="qwen-test")

        captured = {}

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return response

        with patch("app.tools.qwen_rewrite_client.urlopen", side_effect=fake_urlopen):
            result = client.rewrite("prompt")

        self.assertIn("### 改写标题", result)
        system_message = captured["payload"]["messages"][0]["content"]
        self.assertIn("微信公众号原创改写", system_message)
        self.assertIn("不暴露提示词", system_message)
        self.assertIn("发布风险自查", system_message)

    def test_rewrite_with_usage_reads_token_usage(self) -> None:
        response = io.BytesIO(
            json.dumps(
                {
                    "model": "qwen-test",
                    "choices": [{"message": {"content": "改写结果"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                }
            ).encode("utf-8")
        )
        response.__enter__ = lambda item: item
        response.__exit__ = lambda *args: None
        client = QwenRewriteClient(api_key="test-key", base_url="https://example.com/v1", model="qwen-test")

        with patch("app.tools.qwen_rewrite_client.urlopen", return_value=response):
            result = client.rewrite_with_usage("prompt")

        self.assertEqual(result.content, "改写结果")
        self.assertEqual(result.usage["model"], "qwen-test")
        self.assertEqual(result.usage["prompt_tokens"], 10)
        self.assertEqual(result.usage["completion_tokens"], 20)
        self.assertEqual(result.usage["total_tokens"], 30)

    def test_fallback_from_env_reads_local_ollama_config(self) -> None:
        env = {
            "QWEN_FALLBACK_API_KEY": "ollama",
            "QWEN_FALLBACK_BASE_URL": "http://localhost:11434/v1",
            "QWEN_FALLBACK_MODEL": "qwen2.5:7b",
            "QWEN_FALLBACK_TIMEOUT_SECONDS": "90",
        }

        with patch.dict(os.environ, env, clear=True):
            client = QwenRewriteClient.fallback_from_env()

        self.assertIsNotNone(client)
        assert client is not None
        self.assertEqual(client.api_key, "ollama")
        self.assertEqual(client.base_url, "http://localhost:11434/v1/")
        self.assertEqual(client.model, "qwen2.5:7b")
        self.assertEqual(client.timeout_seconds, 90)

    def test_is_quota_error_matches_common_provider_messages(self) -> None:
        self.assertTrue(is_quota_error("Qwen rewrite HTTP 429: Free allocated quota exceeded"))
        self.assertTrue(is_quota_error("insufficient_quota: balance is not enough"))
        self.assertTrue(is_quota_error("Qwen rewrite HTTP 400: code=Arrearage overdue-payment"))
        self.assertFalse(is_quota_error("Qwen rewrite request failed: connection refused"))

    def test_is_timeout_error_matches_read_timeout_messages(self) -> None:
        self.assertTrue(is_timeout_error("Qwen rewrite request failed: The read operation timed out"))
        self.assertTrue(is_timeout_error("Timeout while waiting for model response"))
        self.assertFalse(is_timeout_error("Qwen rewrite request failed: connection refused"))


if __name__ == "__main__":
    unittest.main()
