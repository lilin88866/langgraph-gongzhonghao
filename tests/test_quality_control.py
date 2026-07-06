import unittest

from app.agents.quality_control import QualityControlAgent


class QualityControlAgentTest(unittest.TestCase):
    def test_information_flags_do_not_require_human_review(self) -> None:
        update = QualityControlAgent().invoke(
            {
                "trends": [object()],
                "quality_info": ["wechat_accounts_discovered:3"],
                "quality_flags": [],
            }
        )

        self.assertEqual(update["quality_info"], ["wechat_accounts_discovered:3"])
        self.assertEqual(update["review_flags"], [])
        self.assertFalse(update["human_review_required"])

    def test_fetch_failures_and_article_similarity_require_review(self) -> None:
        update = QualityControlAgent().invoke(
            {
                "trends": [object()],
                "quality_flags": ["fetch_failed:wechat:work_list:captcha"],
                "article_compliance": {"similarity": 62, "threshold": 40, "compliant": False},
            }
        )

        self.assertIn("fetch_failed:wechat:work_list:captcha", update["review_flags"])
        self.assertIn("article_similarity_too_high:62%", update["review_flags"])
        self.assertTrue(update["human_review_required"])


if __name__ == "__main__":
    unittest.main()
