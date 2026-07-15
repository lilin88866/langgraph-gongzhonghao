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
                "source_outline": "原文段落骨架（必须按顺序覆盖）：\n1. 提示词背景\n   - 先讲 CLAUDE.md 的使用场景。",
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
        self.assertIn("### 发布风险自查", prompt)
        self.assertIn("确定性原文骨架", prompt)
        self.assertIn("必须先沿“确定性原文骨架”逐段润色", prompt)
        self.assertIn("正文里禁止出现任何内部实现标签、系统说明或失败兜底说明", prompt)
        self.assertIn("先讲 CLAUDE.md 的使用场景", prompt)
        self.assertIn("相似度目标区间是 20%-25%", prompt)
        self.assertIn("AI 知识型/讲解型订阅号", prompt)
        self.assertIn("LLM 只负责表达润色", prompt)
        self.assertIn("配图占位卡片", prompt)
        self.assertIn("不要只在文末列配图建议", prompt)
        self.assertIn("按正文长度估算插入 1 个", prompt)
        self.assertIn("禁止照抄", prompt)
        self.assertIn("根据原文当前段落生成的具体主题", prompt)
        self.assertIn("参考原图", prompt)
        self.assertNotIn("模型迁移工作流", prompt)
        self.assertNotIn("长期评估 -> 灰度上线 -> Prompt 调优 -> 全面切换", prompt)

    def test_build_task_prompt_uses_source_image_count(self) -> None:
        skill = WechatRewriteSkill(
            skill_dir=Path("/tmp/skill"),
            rules="## 公众号\n规则",
            keywords=["指南"],
        )

        prompt = skill.build_task_prompt(
            {
                "title": "Agent 图解",
                "text": "Agent 工作流说明。",
                "source_image_count": 4,
            }
        )

        self.assertIn("原文检测到 4 张配图", prompt)
        self.assertIn("必须对应插入 4 个“配图占位卡片”", prompt)
        self.assertNotIn("直接插入 1-3 个", prompt)

    def test_build_task_prompt_allows_no_inline_images_when_source_has_none(self) -> None:
        skill = WechatRewriteSkill(
            skill_dir=Path("/tmp/skill"),
            rules="## 公众号\n规则",
            keywords=["指南"],
        )

        prompt = skill.build_task_prompt(
            {
                "title": "Agent 纯文字解析",
                "text": "Agent 工作流说明。",
                "source_image_count": 0,
            }
        )

        self.assertIn("原文未检测到正文配图", prompt)
        self.assertIn("正文配图占位卡片可不插入", prompt)

    def test_build_task_prompt_detects_images_from_raw_payload(self) -> None:
        skill = WechatRewriteSkill(
            skill_dir=Path("/tmp/skill"),
            rules="## 公众号\n规则",
            keywords=["指南"],
        )

        prompt = skill.build_task_prompt(
            {
                "title": "Agent 图解",
                "text": "Agent 工作流说明。",
                "raw_payload": {
                    "article": {
                        "image_urls": [
                            "https://mmbiz.qpic.cn/one",
                            "https://mmbiz.qpic.cn/two",
                        ]
                    }
                },
            }
        )

        self.assertIn("原文检测到 2 张配图", prompt)
        self.assertIn("必须对应插入 2 个“配图占位卡片”", prompt)
        self.assertIn("原文图片 1：https://mmbiz.qpic.cn/one", prompt)
        self.assertIn("原文图片 2：https://mmbiz.qpic.cn/two", prompt)
        self.assertIn("参考原图：原文图片 N / URL", prompt)

    def test_default_loads_project_local_supporting_skills(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            skill = WechatRewriteSkill.from_env()

        self.assertTrue(str(skill.skill_dir).endswith("langgraph-study/skills/wechat-rewrite"))
        for skill_name in SUPPORTING_SKILL_NAMES:
            self.assertIn(skill_name, skill.workflow_rules)
        self.assertLess(len(skill.workflow_rules), 2500)


if __name__ == "__main__":
    unittest.main()
