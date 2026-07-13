import os
import unittest
from unittest.mock import patch

from app.agents.platform_collection import PlatformCollectionAgent
from app.agents.wechat_download_collection import WechatDownloadCollectionAgent
from app.schemas.hotspot import ApiDimension, HotspotTask, Platform, SourcePlan, WechatAccountCandidate
from app.tools.client_factory import build_content_clients
from app.tools.wechat_download_api import WechatDownloadApiClient


class FakeWechatDownloadApiClient(WechatDownloadApiClient):
    def __init__(
        self,
        *,
        get_responses: dict[str, list[object]] | None = None,
        post_responses: dict[str, list[object]] | None = None,
        failing_get_paths: set[str] | None = None,
    ) -> None:
        super().__init__(base_url="http://wechat.local")
        self.get_responses = get_responses or {}
        self.post_responses = post_responses or {}
        self.failing_get_paths = failing_get_paths or set()
        self.get_calls: list[tuple[str, dict[str, object]]] = []
        self.post_calls: list[tuple[str, dict[str, object]]] = []

    def _get_json(self, path: str, query: dict[str, object]) -> object:
        self.get_calls.append((path, query))
        if path in self.failing_get_paths:
            raise RuntimeError(f"forced failure for {path}")
        return self.get_responses[path].pop(0)

    def _post_json(self, path: str, payload: dict[str, object], **kwargs: object) -> object:
        self.post_calls.append((path, payload))
        return self.post_responses[path].pop(0)


class WechatDownloadApiClientTest(unittest.TestCase):
    def test_account_search_maps_fakeid_and_profile_fields(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/public/searchbiz": [
                    {
                        "list": [
                            {
                                "fakeid": "fake_123",
                                "nickname": "AI 前沿",
                                "alias": "ai-frontier",
                                "round_head_img": "https://img.example/avatar.png",
                            }
                        ]
                    }
                ]
            }
        )
        plan = SourcePlan(platform=Platform.WECHAT, dimension=ApiDimension.ACCOUNT_INFO, query="AI")

        [raw] = client.fetch(plan)

        self.assertEqual(raw.platform, Platform.WECHAT)
        self.assertEqual(raw.source_api, "wechat-download-api")
        self.assertEqual(raw.raw_payload["id"], "fake_123")
        self.assertEqual(raw.raw_payload["title"], "AI 前沿")
        self.assertEqual(raw.raw_payload["media_type"], "account")
        self.assertEqual(raw.raw_payload["account"]["alias"], "ai-frontier")

    def test_search_query_discovers_fakeid_and_maps_nested_article_list(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/public/searchbiz": [
                    {"data": {"list": [{"fakeid": "fake_123", "nickname": "AI 前沿"}]}}
                ],
                "/api/public/articles/search": [
                    {
                        "data": {
                            "app_msg_list": [
                                {
                                    "appmsgid": "msg_1",
                                    "title": "AI Agent 产品观察",
                                    "link": "https://mp.weixin.qq.com/s/msg_1",
                                    "plain_content": "智能体产品正在升温",
                                    "publish_time": "2026-06-17",
                                    "read_count": "1024",
                                    "like_count": "88",
                                }
                            ]
                        }
                    }
                ],
            }
        )
        plan = SourcePlan(platform=Platform.WECHAT, dimension=ApiDimension.SEARCH_QUERY, query="AI Agent", page_size=10)

        [raw] = client.fetch(plan)

        self.assertEqual(client.get_calls[0][0], "/api/public/searchbiz")
        self.assertEqual(client.get_calls[1][0], "/api/public/articles/search")
        self.assertEqual(client.get_calls[1][1]["fakeid"], "fake_123")
        self.assertEqual(raw.raw_payload["id"], "msg_1")
        self.assertEqual(raw.raw_payload["title"], "AI Agent 产品观察")
        self.assertEqual(raw.raw_payload["text"], "智能体产品正在升温")
        self.assertEqual(raw.raw_payload["url"], "https://mp.weixin.qq.com/s/msg_1")
        self.assertEqual(raw.raw_payload["metrics"]["reads"], 1024)
        self.assertEqual(raw.raw_payload["account"]["fakeid"], "fake_123")

    def test_article_title_does_not_fallback_to_subscription_query(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/public/articles/search": [
                    {
                        "list": [
                            {
                                "aid": "article_without_title",
                                "link": "https://mp.weixin.qq.com/s/no-title",
                                "plain_content": "AI Agent 实践指南。",
                            }
                        ]
                    }
                ],
            }
        )
        client.default_fakeids = ["fake_123"]
        plan = SourcePlan(platform=Platform.WECHAT, dimension=ApiDimension.SEARCH_QUERY, query="AI 前沿", page_size=10)

        [raw] = client.fetch(plan)

        self.assertEqual(raw.raw_payload["title"], "")
        self.assertNotEqual(raw.raw_payload["title"], "AI 前沿")

    def test_article_metrics_accept_wechat_stat_field_variants(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/public/articles/search": [
                    {
                        "data": {
                            "app_msg_list": [
                                {
                                    "appmsgid": "msg_1",
                                    "title": "AI Agent 产品观察",
                                    "link": "https://mp.weixin.qq.com/s/msg_1",
                                    "plain_content": "智能体产品正在升温",
                                    "publish_time": "2026-06-17",
                                    "appmsgstat": {
                                        "read_num": "10万+",
                                        "like_num": "1.2万",
                                        "comment_count": "345",
                                    },
                                }
                            ]
                        }
                    }
                ],
            }
        )
        client.default_fakeids = ["fake_123"]
        plan = SourcePlan(platform=Platform.WECHAT, dimension=ApiDimension.SEARCH_QUERY, query="AI Agent", page_size=10)

        [raw] = client.fetch(plan)

        self.assertEqual(raw.raw_payload["metrics"]["reads"], 100000)
        self.assertEqual(raw.raw_payload["metrics"]["likes"], 12000)
        self.assertEqual(raw.raw_payload["metrics"]["comments"], 345)

    def test_search_query_backfills_account_name_from_discovered_fakeid(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/public/searchbiz": [
                    {"list": [{"fakeid": "fake_123", "nickname": "AI 前沿"}]}
                ],
                "/api/public/articles/search": [
                    {
                        "list": [
                            {
                                "aid": "article_1",
                                "title": "AI 热点",
                                "link": "https://mp.weixin.qq.com/s/article_1",
                                "author": "",
                            }
                        ]
                    }
                ],
            }
        )
        plan = SourcePlan(platform=Platform.WECHAT, dimension=ApiDimension.SEARCH_QUERY, query="AI")

        [raw] = client.fetch(plan)

        self.assertEqual(raw.raw_payload["author"], "AI 前沿")
        self.assertEqual(raw.raw_payload["account"]["nickname"], "AI 前沿")

    def test_search_query_falls_back_to_articles_keyword_endpoint(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/public/articles": [
                    {
                        "appmsg_list": [
                            {
                                "msgid": "msg_2",
                                "title": "大模型应用案例",
                                "link": "https://mp.weixin.qq.com/s/msg_2",
                            }
                        ]
                    }
                ]
            },
            failing_get_paths={"/api/public/articles/search"},
        )
        client.default_fakeids = ["fake_456"]
        plan = SourcePlan(platform=Platform.WECHAT, dimension=ApiDimension.SEARCH_QUERY, query="大模型")

        [raw] = client.fetch(plan)

        self.assertEqual(client.get_calls[0][0], "/api/public/articles/search")
        self.assertEqual(client.get_calls[1][0], "/api/public/articles")
        self.assertEqual(client.get_calls[1][1]["keyword"], "大模型")
        self.assertEqual(raw.raw_payload["id"], "msg_2")

    def test_article_detail_unwraps_data_payload(self) -> None:
        client = FakeWechatDownloadApiClient(
            post_responses={
                "/api/article": [
                    {
                        "data": {
                            "title": "AI 产品深度分析",
                            "url": "https://mp.weixin.qq.com/s/detail",
                            "content": "完整正文",
                            "source_nickname": "AI 前沿",
                        }
                    }
                ]
            }
        )
        plan = SourcePlan(
            platform=Platform.WECHAT,
            dimension=ApiDimension.ARTICLE_DETAIL,
            metadata={"url": "https://mp.weixin.qq.com/s/detail"},
        )

        [raw] = client.fetch(plan)

        self.assertEqual(client.post_calls, [("/api/article", {"url": "https://mp.weixin.qq.com/s/detail"})])
        self.assertEqual(raw.raw_payload["title"], "AI 产品深度分析")
        self.assertEqual(raw.raw_payload["author"], "AI 前沿")
        self.assertEqual(raw.raw_payload["text"], "完整正文")

    def test_article_detail_strips_html_content(self) -> None:
        client = FakeWechatDownloadApiClient(
            post_responses={
                "/api/article": [
                    {
                        "data": {
                            "title": "Claude 提示词指南",
                            "url": "https://mp.weixin.qq.com/s/detail",
                            "content": (
                                '<p>第一段<br />第二段</p>'
                                '<img data-src="//mmbiz.qpic.cn/demo.jpg">'
                                "<section><code>CLAUDE.md</code></section>"
                            ),
                            "cover": "https://mmbiz.qpic.cn/cover.jpg",
                            "source_nickname": "AI 前沿",
                        }
                    }
                ]
            }
        )
        plan = SourcePlan(
            platform=Platform.WECHAT,
            dimension=ApiDimension.ARTICLE_DETAIL,
            metadata={"url": "https://mp.weixin.qq.com/s/detail"},
        )

        [raw] = client.fetch(plan)

        self.assertEqual(raw.raw_payload["text"], "第一段\n第二段\nCLAUDE.md")
        self.assertEqual(
            raw.raw_payload["image_urls"],
            ["https://mmbiz.qpic.cn/cover.jpg", "https://mmbiz.qpic.cn/demo.jpg"],
        )
        self.assertIn("<img", raw.raw_payload["html"])

    def test_factory_uses_wechat_download_provider_when_configured(self) -> None:
        env = {
            "CONTENT_API_REQUIRE_REAL": "1",
            "WECHAT_PROVIDER": "wechat_download",
            "WECHAT_DOWNLOAD_API_BASE_URL": "http://localhost:5000",
        }
        with patch.dict(os.environ, env, clear=True):
            clients = build_content_clients([Platform.WECHAT])

        self.assertIsInstance(clients[Platform.WECHAT], WechatDownloadApiClient)

    def test_timeout_is_reported_as_runtime_error(self) -> None:
        client = WechatDownloadApiClient(base_url="http://wechat.example")

        with patch("app.tools.wechat_download_api.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(RuntimeError, "request timed out"):
                client.check_health()

    def test_subscribe_account_posts_rss_subscription_payload(self) -> None:
        client = FakeWechatDownloadApiClient(
            post_responses={
                "/api/rss/subscribe": [{"success": True}]
            }
        )
        account = {
            "id": "fake_123",
            "author": "AI 前沿",
            "account": {
                "fakeid": "fake_123",
                "nickname": "AI 前沿",
                "alias": "ai-frontier",
                "avatar": "https://img.example/avatar.png",
            },
        }

        subscribed = client.subscribe_account(account)

        self.assertTrue(subscribed)
        self.assertEqual(
            client.post_calls,
            [
                (
                    "/api/rss/subscribe",
                    {
                        "fakeid": "fake_123",
                        "nickname": "AI 前沿",
                        "alias": "ai-frontier",
                        "head_img": "https://img.example/avatar.png",
                    },
                )
            ],
        )

    def test_subscription_fetch_excludes_red_fox_accounts_before_article_requests(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/rss/subscriptions": [
                    {
                        "list": [
                            {"fakeid": "abcdefghijkl=", "nickname": "红狐 AI"},
                            {"fakeid": "mnopqrstuvwx=", "nickname": "AI 前沿"},
                        ]
                    }
                ],
                "/api/public/articles": [
                    {"list": []},
                ],
            }
        )

        with patch.dict(os.environ, {"WECHAT_ARTICLE_LIST_CACHE": "0"}):
            client.fetch_subscription_articles(account_limit=0)

        article_calls = [call for call in client.get_calls if call[0] == "/api/public/articles"]
        self.assertEqual(len(article_calls), 1)
        self.assertEqual(article_calls[0][1]["fakeid"], "mnopqrstuvwx=")


class WechatDownloadCollectionAgentTest(unittest.TestCase):
    def test_agent_collects_only_wechat_source_plans(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/health": [{"status": "ok"}],
                "/api/public/articles": [
                    {
                        "list": [
                            {
                                "msgid": "msg_3",
                                "title": "微信 Agent 测试",
                                "link": "https://mp.weixin.qq.com/s/msg_3",
                            }
                        ]
                    }
                ],
            }
        )
        agent = WechatDownloadCollectionAgent(client)
        state = {
            "source_plans": [
                SourcePlan(platform=Platform.WECHAT, dimension=ApiDimension.WORK_LIST, account_id="fake_789"),
                SourcePlan(platform=Platform.DOUYIN, dimension=ApiDimension.SEARCH_QUERY, query="AI"),
            ]
        }

        update = agent.invoke(state)

        self.assertEqual(update["quality_flags"], [])
        self.assertEqual(len(update["raw_contents"]), 1)
        self.assertEqual(update["raw_contents"][0].raw_payload["id"], "msg_3")
        self.assertEqual(client.get_calls[0][0], "/api/health")
        self.assertEqual(client.get_calls[1][0], "/api/public/articles")

    def test_platform_collection_delegates_wechat_download_provider_to_agent(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/public/articles": [
                    {
                        "list": [
                            {
                                "msgid": "msg_4",
                                "title": "委托微信 Agent",
                                "link": "https://mp.weixin.qq.com/s/msg_4",
                            }
                        ]
                    }
                ],
            }
        )
        wechat_agent = WechatDownloadCollectionAgent(client, check_health=False)
        platform_agent = PlatformCollectionAgent(clients={}, wechat_agent=wechat_agent)
        state = {
            "task": HotspotTask(
                objective="验证微信 Agent 委托",
                keywords=["AI"],
                platforms=[Platform.WECHAT],
                dimensions=[ApiDimension.WORK_LIST],
            ),
            "source_plans": [
                SourcePlan(platform=Platform.WECHAT, dimension=ApiDimension.WORK_LIST, account_id="fake_789")
            ],
        }

        with patch.dict(os.environ, {"WECHAT_PROVIDER": "wechat_download"}, clear=True):
            update = platform_agent.invoke(state)

        self.assertEqual(update["quality_flags"], [])
        self.assertEqual(len(update["raw_contents"]), 1)
        self.assertEqual(update["raw_contents"][0].raw_payload["title"], "委托微信 Agent")

    def test_agent_collects_articles_from_discovered_wechat_accounts(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/health": [{"status": "ok"}],
                "/api/public/articles": [
                    {
                        "data": {
                            "articles": [
                                {
                                    "aid": "article_5",
                                    "title": "自动订阅账号文章",
                                    "link": "https://mp.weixin.qq.com/s/article_5",
                                    "author": "",
                                }
                            ]
                        }
                    }
                ],
            }
        )
        agent = WechatDownloadCollectionAgent(client)
        state = {
            "task": HotspotTask(
                objective="验证自动发现公众号文章采集",
                keywords=["AI"],
                platforms=[Platform.WECHAT],
                dimensions=[ApiDimension.WORK_LIST],
                max_items_per_platform=5,
            ),
            "source_plans": [],
            "wechat_accounts": [
                WechatAccountCandidate(
                    fakeid="fake_discovered",
                    nickname="AI 前沿",
                    alias=None,
                    relevance_score=0.8,
                    matched_keywords=["AI"],
                    subscribed=True,
                    reason="测试",
                )
            ],
        }

        update = agent.invoke(state)

        self.assertEqual(client.get_calls[1][0], "/api/public/articles")
        self.assertEqual(client.get_calls[1][1]["fakeid"], "fake_discovered")
        self.assertEqual(client.get_calls[1][1]["count"], 5)
        self.assertEqual(update["raw_contents"][0].raw_payload["author"], "AI 前沿")

    def test_discovered_account_collection_respects_limit(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/public/articles": [
                    {"list": [{"msgid": "msg_1", "title": "第一篇"}]},
                ],
            }
        )
        agent = WechatDownloadCollectionAgent(client, check_health=False)
        state = {
            "source_plans": [],
            "wechat_accounts": [
                WechatAccountCandidate(
                    fakeid="fake_1",
                    nickname="账号一",
                    alias=None,
                    relevance_score=0.8,
                    matched_keywords=["AI"],
                    subscribed=True,
                    reason="测试",
                ),
                WechatAccountCandidate(
                    fakeid="fake_2",
                    nickname="账号二",
                    alias=None,
                    relevance_score=0.8,
                    matched_keywords=["AI"],
                    subscribed=True,
                    reason="测试",
                ),
            ],
        }

        with patch.dict(os.environ, {"WECHAT_COLLECTION_DISCOVERED_ACCOUNT_LIMIT": "1"}, clear=True):
            update = agent.invoke(state)

        self.assertEqual(len(update["raw_contents"]), 1)
        self.assertEqual(len([call for call in client.get_calls if call[0] == "/api/public/articles"]), 1)
        self.assertEqual(client.get_calls[0][1]["fakeid"], "fake_1")

    def test_discovered_accounts_skip_slow_search_plans_by_default(self) -> None:
        client = FakeWechatDownloadApiClient(
            get_responses={
                "/api/public/articles": [
                    {"list": [{"msgid": "msg_1", "title": "订阅号文章"}]},
                ],
            }
        )
        agent = WechatDownloadCollectionAgent(client, check_health=False)
        state = {
            "source_plans": [
                SourcePlan(platform=Platform.WECHAT, dimension=ApiDimension.SEARCH_QUERY, query="AI")
            ],
            "wechat_accounts": [
                WechatAccountCandidate(
                    fakeid="fake_1",
                    nickname="账号一",
                    alias=None,
                    relevance_score=0.8,
                    matched_keywords=["AI"],
                    subscribed=True,
                    reason="测试",
                )
            ],
        }

        with patch.dict(os.environ, {}, clear=True):
            update = agent.invoke(state)

        self.assertEqual(len(update["raw_contents"]), 1)
        self.assertEqual([call[0] for call in client.get_calls], ["/api/public/articles"])


if __name__ == "__main__":
    unittest.main()
