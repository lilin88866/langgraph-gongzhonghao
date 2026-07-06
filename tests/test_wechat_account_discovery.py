import os
import unittest
from unittest.mock import patch

from app.agents.wechat_account_discovery import WechatAccountDiscoveryAgent
from app.agents.wechat_account_discovery import _auto_subscribe_enabled, _discovery_queries, _search_limit
from app.schemas.hotspot import ApiDimension, HotspotTask, Platform


class FakeAccountClient:
    def __init__(self) -> None:
        self.subscribed_accounts: list[dict] = []

    def search_accounts(self, query: str, *, limit: int = 10) -> list[dict]:
        return [
            {
                "id": "fake_ai",
                "author": "Claude AI 前沿",
                "title": "Claude AI 前沿",
                "text": "关注 agent 和人工智能",
                "account": {"fakeid": "fake_ai", "nickname": "Claude AI 前沿", "alias": "claude-ai"},
            },
            {
                "id": "fake_food",
                "author": "杭州美食",
                "title": "杭州美食",
                "text": "本地生活",
                "account": {"fakeid": "fake_food", "nickname": "杭州美食", "alias": "food"},
            },
        ][:limit]

    def subscribe_account(self, account: dict) -> bool:
        self.subscribed_accounts.append(account)
        return True


class WechatAccountDiscoveryAgentTest(unittest.TestCase):
    def test_agent_filters_ai_related_accounts_without_default_subscribe(self) -> None:
        client = FakeAccountClient()
        task = HotspotTask(
            objective="发现 AI 热点",
            keywords=["AI"],
            platforms=[Platform.WECHAT],
            dimensions=[ApiDimension.SEARCH_QUERY],
        )

        with patch.dict(os.environ, {"WECHAT_ACCOUNT_DISCOVERY_LIMIT": "5"}, clear=True):
            update = WechatAccountDiscoveryAgent(client).invoke({"task": task})

        accounts = update["wechat_accounts"]
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].nickname, "Claude AI 前沿")
        self.assertFalse(accounts[0].subscribed)
        self.assertEqual(len(client.subscribed_accounts), 0)
        self.assertEqual(update["quality_flags"], [])
        self.assertIn("wechat_accounts_discovered:1", update["quality_info"])

    def test_agent_subscribes_only_when_enabled(self) -> None:
        client = FakeAccountClient()
        task = HotspotTask(
            objective="发现 AI 热点",
            keywords=["AI"],
            platforms=[Platform.WECHAT],
            dimensions=[ApiDimension.SEARCH_QUERY],
        )

        with patch.dict(os.environ, {"WECHAT_ACCOUNT_AUTO_SUBSCRIBE": "1", "WECHAT_ACCOUNT_DISCOVERY_LIMIT": "5"}, clear=True):
            update = WechatAccountDiscoveryAgent(client).invoke({"task": task})

        accounts = update["wechat_accounts"]
        self.assertTrue(accounts[0].subscribed)
        self.assertEqual(len(client.subscribed_accounts), 1)

    def test_default_discovery_queries_cover_many_ai_account_topics(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            queries = _discovery_queries(["AI"])

        self.assertEqual(_search_limit(), 20)
        self.assertIn("DeepSeek", queries)
        self.assertIn("AI编程", queries)
        self.assertIn("MCP", queries)
        self.assertIn("LangGraph", queries)
        self.assertIn("LangChain", queries)
        self.assertIn("loop", queries)
        self.assertIn("promot", queries)
        self.assertIn("DevOps", queries)
        self.assertIn("Jenkins", queries)
        self.assertIn("GitHub", queries)
        self.assertNotIn("CDDevops", queries)

    def test_auto_subscribe_defaults_to_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(_auto_subscribe_enabled())

        with patch.dict(os.environ, {"WECHAT_ACCOUNT_AUTO_SUBSCRIBE": "1"}, clear=True):
            self.assertTrue(_auto_subscribe_enabled())


if __name__ == "__main__":
    unittest.main()
