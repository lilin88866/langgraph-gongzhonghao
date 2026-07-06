import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.tools.api import SUPPORTING_SKILL_NAMES, WechatRewriteSkill


class WechatRewriteSkillTest(unittest.TestCase):
    def test_loads_keywords_from_skill_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir)
            assets_dir = skill_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "platform-rules.md").write_text(
                """# 公众号文案改写规则

## 公众号

### Keyword
1. 指南：XX指南
2. 教程：XX教程
3. 解析：XX解析
""",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"WECHAT_REWRITE_SKILL_DIR": str(skill_dir)}, clear=True):
                skill = WechatRewriteSkill.from_env()

        self.assertEqual(skill.keywords[:3], ["指南", "教程", "解析"])
        self.assertEqual(skill.choose_keywords("AI 教程和趋势解析", limit=2), ["教程", "解析"])
        self.assertIn("教程", skill.tags_for("AI 热点", "AI 教程"))

    def test_build_task_prompt_contains_source_article_fields(self) -> None:
        skill = WechatRewriteSkill(
            skill_dir=Path("/tmp/skill"),
            rules="## 公众号\n规则",
            keywords=["指南", "教程"],
            workflow_rules="### title-generator\n标题生成\n\n### wechat-prohibited-word\n风险检查",
        )

        prompt = skill.build_task_prompt(
            {
                "title": "Claude 提示词指南",
                "text": "一份可以直接抄的 CLAUDE.md。",
                "author": "爱AI的大刘",
                "url": "https://mp.weixin.qq.com/s/demo",
                "metrics": {"reads": 12000, "likes": 300, "hotness_score": 91.0},
            }
        )

        self.assertIn("标题：Claude 提示词指南", prompt)
        self.assertIn("作者/公众号：爱AI的大刘", prompt)
        self.assertIn("原文链接：https://mp.weixin.qq.com/s/demo", prompt)
        self.assertIn("阅读 12000", prompt)
        self.assertIn("热度 91.0", prompt)
        self.assertIn("一份可以直接抄的 CLAUDE.md。", prompt)
        self.assertIn("title-generator", prompt)
        self.assertIn("wechat-prohibited-word", prompt)
        self.assertIn("### 标题候选", prompt)
        self.assertIn("### 来源与复核提醒", prompt)
        self.assertIn("### 配图建议", prompt)
        self.assertIn("### 发布风险自查", prompt)
        self.assertIn("保留原文的版式骨架", prompt)
        self.assertIn("相似度尽量低于 30%", prompt)
        self.assertIn("AI 知识型/讲解型订阅号", prompt)
        self.assertIn("是什么、为什么重要、普通人怎么理解", prompt)
        self.assertIn("配图占位卡片", prompt)
        self.assertIn("不要只在文末列配图建议", prompt)
        self.assertIn("模型迁移工作流", prompt)

    def test_default_loads_project_local_supporting_skills(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            skill = WechatRewriteSkill.from_env()

        self.assertTrue(str(skill.skill_dir).endswith("langgraph-study/skills/wechat-rewrite"))
        for skill_name in SUPPORTING_SKILL_NAMES:
            self.assertIn(skill_name, skill.workflow_rules)
        self.assertLess(len(skill.workflow_rules), 2500)


if __name__ == "__main__":
    unittest.main()
