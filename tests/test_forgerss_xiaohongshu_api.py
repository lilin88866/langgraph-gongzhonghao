import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.schemas.hotspot import ApiDimension, Platform, SourcePlan
from app.tools.client_factory import build_content_clients
from app.tools.forgerss_xiaohongshu_api import ForgeRSSXiaohongshuClient


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>小红书用户笔记</title>
    <item>
      <title>AI Agent 工具体验</title>
      <link>https://www.xiaohongshu.com/explore/note_1</link>
      <guid>note_1</guid>
      <dc:creator>小红书作者</dc:creator>
      <pubDate>Wed, 24 Jun 2026 02:00:00 GMT</pubDate>
      <description><![CDATA[<p>点赞: 88 评论: 12 收藏: 34</p>]]></description>
      <content:encoded><![CDATA[<p>这是一篇 AI Agent 小红书笔记。</p><p>包含工具体验和避坑清单。</p>]]></content:encoded>
      <media:content url="https://img.example/note.jpg" />
    </item>
  </channel>
</rss>
"""


class ForgeRSSXiaohongshuClientTest(unittest.TestCase):
    def test_reads_forgerss_xiaohongshu_feed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            feed_file = Path(temp_dir) / "feed_xiaohongshu_user.xml"
            feed_file.write_text(RSS_SAMPLE, encoding="utf-8")
            client = ForgeRSSXiaohongshuClient(feed_file=str(feed_file))

            [raw] = client.fetch(
                SourcePlan(
                    platform=Platform.XIAOHONGSHU,
                    dimension=ApiDimension.WORK_LIST,
                    query="AI Agent",
                    page_size=10,
                )
            )

        self.assertEqual(raw.platform, Platform.XIAOHONGSHU)
        self.assertEqual(raw.source_api, "forgerss-xiaohongshu-rss")
        self.assertEqual(raw.raw_payload["id"], "note_1")
        self.assertEqual(raw.raw_payload["author"], "小红书作者")
        self.assertEqual(raw.raw_payload["title"], "AI Agent 工具体验")
        self.assertIn("工具体验", raw.raw_payload["text"])
        self.assertEqual(raw.raw_payload["metrics"]["likes"], 88)
        self.assertEqual(raw.raw_payload["metrics"]["comments"], 12)
        self.assertEqual(raw.raw_payload["metrics"]["saves"], 34)
        self.assertEqual(raw.raw_payload["media_urls"], ["https://img.example/note.jpg"])

    def test_factory_uses_forgerss_provider_for_xiaohongshu(self) -> None:
        env = {
            "CONTENT_API_REQUIRE_REAL": "1",
            "XIAOHONGSHU_PROVIDER": "forgerss",
            "XIAOHONGSHU_FORGERSS_FEED_FILE": "/tmp/feed_xiaohongshu_user.xml",
        }
        with patch.dict(os.environ, env, clear=True):
            clients = build_content_clients([Platform.XIAOHONGSHU])

        self.assertIsInstance(clients[Platform.XIAOHONGSHU], ForgeRSSXiaohongshuClient)


if __name__ == "__main__":
    unittest.main()
