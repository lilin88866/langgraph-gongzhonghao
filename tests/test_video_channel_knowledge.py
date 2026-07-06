import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agents.video_channel_knowledge import (
    EducationKnowledgeSourceAgent,
    VideoComplianceCheckAgent,
)
from app.schemas.hotspot import VideoChannelScript
from app.tools.video_render import (
    StoryboardClip,
    _safe_display_text,
    _scene_image_prompt,
    _storyboard_clips,
    _visual_summary,
    _paste_scene_image,
    _remotion_props,
    _remove_production_placeholders,
    _try_generate_scene_images,
    _try_render_with_remotion,
    _try_render_tts_by_clip,
)


class VideoChannelKnowledgeTest(unittest.TestCase):
    def test_education_source_agent_normalizes_manual_knowledge(self) -> None:
        state = {
            "video_source": {
                "title": "为什么分数除法要乘倒数",
                "subject": "数学",
                "grade_or_level": "小学",
                "source_url": "https://example.edu/fraction",
                "raw_text": "分数除法可以理解为求一个数里面有几个分数单位。常见误区是只背公式。",
            }
        }

        update = EducationKnowledgeSourceAgent().invoke(state)

        knowledge = update["education_knowledge"]
        self.assertEqual(knowledge.title, "为什么分数除法要乘倒数")
        self.assertEqual(knowledge.subject, "数学")
        self.assertEqual(knowledge.grade_or_level, "小学")
        self.assertEqual(update["review_flags"], ["video_source_too_short"])
        self.assertTrue(knowledge.key_points)

    def test_video_compliance_flags_missing_source_url(self) -> None:
        state = EducationKnowledgeSourceAgent().invoke(
            {
                "video_source": {
                    "title": "一个知识点",
                    "raw_text": "内容较短",
                }
            }
        )
        state["video_channel_script"] = VideoChannelScript(
            title="一个知识点",
            cover_text="知识点",
            hook="",
            voiceover="这是一个知识点讲解。",
            storyboard_markdown="",
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )
        update = VideoComplianceCheckAgent().invoke(state)

        self.assertTrue(update["human_review_required"])
        self.assertIn("video_source_missing_url", update["review_flags"])

    def test_scene_image_prompt_uses_storyboard_visual_description(self) -> None:
        script = VideoChannelScript(
            title="为什么分数除法要乘倒数？一分钟讲透",
            cover_text="分数除法为何乘倒数",
            hook="死记硬背可不行！",
            voiceover="分数除法的本质，是求一个数里面包含多少个这样的分数单位。",
            storyboard_markdown="",
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )
        clip = StoryboardClip(
            start=0,
            end=3,
            visual="老师出镜，手持一个苹果和一把刀，表情带有疑问。",
            voiceover="为什么除以一个数，等于乘它的倒数？",
            subtitle="分数除法为什么乘倒数？",
        )

        prompt = _scene_image_prompt(script, clip, index=1)

        self.assertIn("老师出镜", prompt)
        self.assertIn("苹果", prompt)
        self.assertIn("分数除法为什么乘倒数", prompt)
        self.assertIn("伪中文", prompt)
        self.assertIn("乱码", prompt)
        self.assertIn("只能使用清晰简体中文", prompt)
        self.assertNotIn("镜头编号", prompt.split("要求：")[0])
        self.assertLessEqual(len(prompt), 500)

    def test_safe_display_text_keeps_only_simplified_chinese_math_text(self) -> None:
        text = _safe_display_text("1 ÷ 1/2 = 2 ABC ａｂｃ 繁體 한글 �� 分数除法", limit=80)

        self.assertIn("分数除法", text)
        self.assertIn("1÷1/2=2", text.replace(" ", ""))
        self.assertNotIn("ABC", text)
        self.assertNotIn("한글", text)

    def test_safe_display_text_preserves_science_formula_symbols(self) -> None:
        text = _safe_display_text("F1=F2=kq²/r²=0.144N，F=2F1cos30°=0.25N", limit=100)

        self.assertIn("F1=F2=kq²/r²=0.144N", text)
        self.assertIn("F=2F1cos30°=0.25N", text)

    def test_storyboard_parser_accepts_tab_separated_rows(self) -> None:
        script = VideoChannelScript(
            title="为什么分数除法要乘倒数？一分钟讲透",
            cover_text="分数除法为何乘倒数",
            hook="",
            voiceover="",
            storyboard_markdown=(
                "时间\t画面\t口播\t屏幕字幕\n"
                "0-3s\t老师出镜，手持一个苹果。\t先看一个苹果。\t分数除法为什么乘倒数？\n"
                "3-10s\t白板动画，出现核心概念大字。\t本质是求包含多少个单位。\t本质：包含多少个单位\n"
            ),
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )

        clips = _storyboard_clips(script)

        self.assertEqual(len(clips), 2)
        self.assertIn("老师出镜", clips[0].visual)
        self.assertIn("白板动画", clips[1].visual)

    def test_storyboard_parser_accepts_markdown_items(self) -> None:
        script = VideoChannelScript(
            title="为什么分数除法要乘倒数？一分钟讲透",
            cover_text="分数除法为何乘倒数",
            hook="",
            voiceover="",
            storyboard_markdown=(
                "1. 时间：0-3s\n"
                "   画面：老师出镜，手持一个苹果。\n"
                "   口播：先看一个苹果。\n"
                "   屏幕字幕：分数除法为什么乘倒数？\n\n"
                "2. 时间：3-10s\n"
                "   画面：白板动画，出现核心概念大字。\n"
                "   口播：本质是求包含多少个单位。\n"
                "   屏幕字幕：本质：包含多少个单位\n"
            ),
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )

        clips = _storyboard_clips(script)

        self.assertEqual(len(clips), 2)
        self.assertIn("老师出镜", clips[0].visual)
        self.assertEqual(clips[1].subtitle, "本质：包含多少个单位")

    def test_storyboard_clips_have_minimum_duration(self) -> None:
        script = VideoChannelScript(
            title="为什么分数除法要乘倒数？一分钟讲透",
            cover_text="分数除法为何乘倒数",
            hook="",
            voiceover="",
            storyboard_markdown="| 时间 | 画面 | 口播 | 屏幕字幕 |\n|---|---|---|---|\n| 0-1s | 苹果切开 | 第一句 | 第一条字幕 |",
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )

        with patch.dict(os.environ, {"VIDEO_RENDER_MIN_CLIP_SECONDS": "4.5"}):
            clips = _storyboard_clips(script)

        self.assertGreaterEqual(clips[0].duration, 4.5)

    def test_storyboard_parser_keeps_all_rows_by_default(self) -> None:
        rows = "\n".join(
            f"| {index}-{index + 1}s | 第{index}个画面 | 第{index}句口播 | 第{index}条字幕 |"
            for index in range(15)
        )
        script = VideoChannelScript(
            title="长分镜视频",
            cover_text="长分镜视频",
            hook="",
            voiceover="",
            storyboard_markdown=f"| 时间 | 画面 | 口播 | 屏幕字幕 |\n|---|---|---|---|\n{rows}",
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )

        clips = _storyboard_clips(script)

        self.assertEqual(len(clips), 15)
        self.assertIn("第14个画面", clips[-1].visual)

    def test_fallback_clips_do_not_use_production_placeholder_text(self) -> None:
        script = VideoChannelScript(
            title="无分镜视频",
            cover_text="无分镜视频",
            hook="",
            voiceover="第一句解释知识点。第二句举例说明。",
            storyboard_markdown="",
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )

        clips = _storyboard_clips(script)

        self.assertTrue(clips)
        self.assertNotIn("知识点字幕卡", clips[0].visual)
        self.assertNotIn("知识点字幕卡", _visual_summary("第 6 张知识点字幕卡"))

    def test_storyboard_placeholder_visuals_are_replaced_for_every_clip(self) -> None:
        rows = "\n".join(
            f"| {index}-{index + 1}s | 第 {index} 张知识点字幕卡 | 第{index}句口播 | 第{index}条字幕 |"
            for index in range(1, 7)
        )
        script = VideoChannelScript(
            title="占位符分镜视频",
            cover_text="占位符分镜视频",
            hook="",
            voiceover="",
            storyboard_markdown=f"| 时间 | 画面 | 口播 | 屏幕字幕 |\n|---|---|---|---|\n{rows}",
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )

        clips = _storyboard_clips(script)

        self.assertEqual(len(clips), 6)
        self.assertTrue(all("知识点字幕卡" not in clip.visual for clip in clips))
        self.assertIn("第6条字幕", clips[-1].visual)

    def test_remove_production_placeholders_handles_compact_forms(self) -> None:
        self.assertEqual(_remove_production_placeholders("第6张知识点字幕卡"), "")
        self.assertEqual(_remove_production_placeholders("第 六 张 知识点 字幕卡"), "")

    def test_clip_tts_disabled_keeps_original_timing(self) -> None:
        clips = [
            StoryboardClip(start=0, end=3, visual="苹果切开", voiceover="第一句", subtitle="第一句"),
            StoryboardClip(start=3, end=10, visual="白板讲解", voiceover="第二句", subtitle="第二句"),
        ]

        with patch.dict(os.environ, {"VIDEO_TTS_ENABLED": "0"}):
            ok, synced = _try_render_tts_by_clip(
                clips,
                Path("/tmp/voice.m4a"),
                job_dir=Path("/tmp"),
                ffmpeg="ffmpeg",
                warnings=[],
            )

        self.assertFalse(ok)
        self.assertEqual([clip.end for clip in synced], [3, 10])

    def test_scene_image_generation_uses_dashscope_supported_vertical_size(self) -> None:
        script = VideoChannelScript(
            title="为什么分数除法要乘倒数？一分钟讲透",
            cover_text="分数除法为何乘倒数",
            hook="",
            voiceover="",
            storyboard_markdown="",
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )
        clip = StoryboardClip(start=0, end=3, visual="苹果切开", voiceover="第一句", subtitle="第一句")
        completed = __import__("subprocess").CompletedProcess(args=[], returncode=1, stdout="", stderr="mock failure")

        with (
            patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fake-key"}),
            patch("app.tools.video_render.subprocess.run", return_value=completed) as run,
        ):
            _try_generate_scene_images(script, [clip, clip], Path("/tmp/video-test"), [])

        self.assertEqual(run.call_count, 2)
        command = run.call_args.args[0]
        self.assertIn("810x1440", command)
        self.assertNotIn("1024x1792", command)

    def test_scene_image_is_sanitized_as_background(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            scene_path = Path(temp_dir) / "scene.png"
            Image.new("RGB", (810, 1440), "#102030").save(scene_path)
            canvas = Image.new("RGB", (1080, 1920), "#ffffff")

            _paste_scene_image(canvas, scene_path, box=(85, 315, 995, 1400), warnings=[])

            self.assertNotEqual(canvas.getpixel((100, 330)), (255, 255, 255))

    def test_remotion_props_export_storyboard_clips(self) -> None:
        script = VideoChannelScript(
            title="为什么分数除法要乘倒数？一分钟讲透",
            cover_text="分数除法为何乘倒数",
            hook="",
            voiceover="",
            storyboard_markdown="",
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )
        clips = [
            StoryboardClip(start=0, end=4.5, visual="苹果切开", voiceover="第一句", subtitle="第一条字幕", scene_type="physics_field", scene_phase="conditions"),
            StoryboardClip(start=4.5, end=9, visual="白板讲解", voiceover="第二句", subtitle="第二条字幕"),
        ]

        props = _remotion_props(script, clips, audio_src="jobs/video_a/voice.m4a", scene_images=["jobs/video_a/scene.png", None])

        self.assertEqual(props["coverText"], "分数除法为何乘倒数")
        self.assertEqual(props["totalDurationSeconds"], 9)
        self.assertEqual(len(props["clips"]), 2)
        self.assertEqual(props["clips"][0]["sceneImage"], "jobs/video_a/scene.png")
        self.assertEqual(props["clips"][1]["subtitle"], "第二条字幕")
        self.assertEqual(props["clips"][0]["sceneType"], "physics_field")
        self.assertEqual(props["clips"][0]["scenePhase"], "conditions")

    def test_remotion_timeline_marks_subject_specific_animation_scene(self) -> None:
        from app.server import _remotion_timeline_from_solution

        chemistry = _remotion_timeline_from_solution(
            "化学反应速率",
            "某反应中，2 min 内反应物浓度从 1.0 mol/L 变为 0.6 mol/L，计算平均反应速率。",
            ["平均反应速率 v = Δc / Δt。"],
        )
        math = _remotion_timeline_from_solution(
            "二次函数图像",
            "已知抛物线 y=x²-2x+1，求顶点并说明图像变化。",
            ["配方得到 y=(x-1)²，顶点为 (1,0)。"],
        )
        biology = _remotion_timeline_from_solution(
            "细胞有丝分裂",
            "观察细胞有丝分裂过程，说明染色体变化。",
            ["染色体复制后平均分配到两个子细胞。"],
        )
        physics = _remotion_timeline_from_solution(
            "圆周运动受力分析",
            "小球做圆周运动，绳的拉力和重力合力提供向心力。",
            ["受力分解得到 T sinθ = m v² / r。"],
        )
        charge = _remotion_timeline_from_solution(
            "库仑定律",
            "真空中有三个带正电的点电荷，求它们各自所受的静电力。",
            ["根据库仑定律，点电荷 q3 共受到 F1 和 F2 两个力的作用。"],
        )

        self.assertEqual(chemistry[0].scene_type, "chemistry_reaction")
        self.assertEqual(math[0].scene_type, "math_graph")
        self.assertEqual(biology[0].scene_type, "biology_process")
        self.assertEqual(physics[0].scene_type, "physics_force")
        self.assertEqual(charge[0].scene_type, "physics_charge")
        self.assertEqual([clip.scene_phase for clip in physics[:4]], ["intro", "question", "conditions", "model"])

    def test_remotion_timeline_voiceover_does_not_read_full_question(self) -> None:
        from app.server import _remotion_timeline_from_solution

        question = (
            "一个带电粒子以速度 v 垂直进入匀强磁场，磁感应强度为 B，"
            "粒子电荷量为 q、质量为 m，求粒子做圆周运动的半径和周期。"
        )

        clips = _remotion_timeline_from_solution(
            "带电粒子在磁场中的运动",
            question,
            ["洛伦兹力提供向心力：qvB = mv² / r。", "所以半径 r = mv / qB，周期 T = 2πm / qB。"],
        )
        voiceover = "\n".join(clip.voiceover for clip in clips)

        self.assertTrue(all(clip.scene_type == "physics_field" for clip in clips))
        self.assertEqual([clip.scene_phase for clip in clips[:4]], ["intro", "question", "conditions", "model"])
        self.assertNotIn("题目是", voiceover)
        self.assertNotIn(question[:40], voiceover)
        self.assertNotIn("先从题图读信息", voiceover)
        self.assertNotIn("已知条件", voiceover)
        self.assertNotIn("关键条件", voiceover)
        self.assertIn("带电粒子进入磁场", voiceover)
        self.assertIn("洛伦兹力提供向心力", voiceover)

    def test_remotion_timeline_voiceover_does_not_read_solution_steps(self) -> None:
        from app.server import _remotion_timeline_from_solution

        solution = [
            "先定位教材知识点：本题围绕“高中物理静电感应教材例题”展开，依据教材片段进行解释。",
            "复核要求：发布前需要人工核对教材页码、题目表述和解答过程是否与教材一致。",
            "根据库仑定律，点电荷 q3 共受到 F1 和 F2 两个力的作用。",
            "F ＝ 2 F1 cos 30°＝ 0.25 N。",
        ]

        clips = _remotion_timeline_from_solution(
            "库仑定律",
            "真空中有三个带正电的点电荷，求它们各自所受的静电力。",
            solution,
        )
        voiceover = "\n".join(clip.voiceover for clip in clips)

        self.assertNotIn("先定位教材知识点", voiceover)
        self.assertNotIn("复核要求", voiceover)
        self.assertIn("根据库仑定律", voiceover)
        self.assertIn("0.25 N", voiceover)

    def test_remotion_timeline_stays_under_one_minute(self) -> None:
        from app.server import _remotion_timeline_from_solution

        clips = _remotion_timeline_from_solution(
            "库仑定律",
            "真空中有三个带正电的点电荷，它们固定在边长为 50 cm 的等边三角形的三个顶点上，求它们各自所受的静电力。",
            [
                "根据库仑定律，点电荷 q3 共受到 F1 和 F2 两个力的作用。",
                "其中 q1=q2=q3=q，每两个点电荷之间的距离 r 都相同。",
                "根据平行四边形定则可得 F = 2F1 cos30° = 0.25 N。",
                "方向沿 q1 与 q2 连线的垂直平分线向外。",
            ],
        )

        self.assertLessEqual(clips[-1].end, 60)
        self.assertLessEqual(sum(1 for clip in clips if clip.scene_phase == "solve"), 3)

    def test_timeline_visuals_are_aligned_with_voiceover(self) -> None:
        from app.server import _remotion_timeline_from_solution

        clips = _remotion_timeline_from_solution(
            "库仑定律",
            "真空中有三个带正电的点电荷，求它们各自所受的静电力。",
            [
                "根据库仑定律，点电荷 q3 共受到 F1 和 F2 两个力的作用。",
                "F1=F2=kq²/r²=0.144N。",
                "根据平行四边形定则可得 F=2F1cos30°=0.25N。",
            ],
        )

        for clip in clips:
            self.assertIn("口播", clip.visual)
            self.assertIn(clip.voiceover[:12], clip.visual)

    def test_important_formulas_are_written_into_video_fields(self) -> None:
        from app.server import _remotion_timeline_from_solution

        clips = _remotion_timeline_from_solution(
            "库仑定律",
            "真空中有三个带正电的点电荷，求它们各自所受的静电力。",
            [
                "根据库仑定律，点电荷 q3 共受到 F1 和 F2 两个力的作用。",
                "F1=F2=kq²/r²=0.144N。",
                "根据平行四边形定则可得 F=2F1cos30°=0.25N。",
            ],
        )
        visible_text = "\n".join(clip.subtitle for clip in clips)

        self.assertIn("F1=F2=kq²/r²=0.144N", visible_text)
        self.assertIn("F=2F1cos30°=0.25N", visible_text)

    def test_static_induction_timeline_uses_dynamic_diagram_annotations(self) -> None:
        from app.server import _remotion_timeline_from_solution

        clips = _remotion_timeline_from_solution(
            "静电感应",
            "当带正电的带电体靠近验电器导体棒时，说明近端和远端电荷分布，并解释金属箔片为什么张开。",
            [
                "带电体靠近导体时，导体中的自由电子向靠近带电体的一端移动。",
                "靠近带电体的一端感应出负电荷，远端因缺少电子而带正电。",
                "金属箔片带同种电荷相互排斥，所以箔片张开。",
            ],
        )
        voiceover = "\n".join(clip.voiceover for clip in clips)
        visual = "\n".join(clip.visual for clip in clips)

        self.assertTrue(all(clip.scene_type == "physics_field" for clip in clips))
        self.assertIn("自由电子", voiceover)
        self.assertIn("箔片张开", voiceover)
        self.assertIn("题图", visual)
        self.assertIn("标注", visual)
        self.assertNotIn("屏幕上显示", voiceover)

    def test_remotion_render_falls_back_without_node(self) -> None:
        script = VideoChannelScript(
            title="测试",
            cover_text="测试",
            hook="",
            voiceover="",
            storyboard_markdown="",
            cover_prompt="",
            publish_copy="",
            hashtags=[],
            source_review=[],
            risk_flags=[],
        )
        warnings: list[str] = []
        with patch("app.tools.video_render.shutil.which", return_value=None):
            result = _try_render_with_remotion(
                script,
                [StoryboardClip(start=0, end=4.5, visual="苹果切开", voiceover="第一句", subtitle="第一条字幕")],
                audio_path=Path("/tmp/missing.m4a"),
                scene_images=[],
                job_dir=Path("/tmp/video_x"),
                warnings=warnings,
            )

        self.assertIsNone(result)
        self.assertTrue(any("node/remotion CLI" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
