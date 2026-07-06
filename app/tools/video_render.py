"""Render Video Channel scripts into preview MP4 drafts."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.hotspot import VideoChannelScript


@dataclass(slots=True)
class VideoRenderResult:
    video_path: Path
    audio_path: Path
    subtitles_path: Path
    frame_paths: list[Path]
    warnings: list[str]
    duration_seconds: float


@dataclass(slots=True)
class StoryboardClip:
    start: float
    end: float
    visual: str
    voiceover: str
    subtitle: str
    scene_type: str = "concept"
    scene_phase: str = "explain"

    @property
    def duration(self) -> float:
        return max(1.0, self.end - self.start)


def render_video_draft(script: VideoChannelScript, output_dir: Path, *, require_remotion: bool = False) -> VideoRenderResult:
    """Render a simple 9:16 MP4 draft from a generated script.

    The MVP intentionally uses static subtitle cards rather than complex motion graphics.
    It keeps the workflow reliable while preserving the later path to replace each card
    with generated images or animation.
    """

    return _render_video_from_clips(script, _storyboard_clips(script), output_dir, require_remotion=require_remotion)


def render_remotion_timeline_draft(
    script: VideoChannelScript,
    clips: list[StoryboardClip],
    output_dir: Path,
    *,
    require_remotion: bool = False,
) -> VideoRenderResult:
    """Render directly from structured Remotion timeline clips, without parsing storyboard markdown."""

    if not clips:
        raise RuntimeError("缺少 Remotion timeline clips，无法生成视频。")
    return _render_video_from_clips(script, clips, output_dir, require_remotion=require_remotion)


def _render_video_from_clips(
    script: VideoChannelScript,
    clips: list[StoryboardClip],
    output_dir: Path,
    *,
    require_remotion: bool,
) -> VideoRenderResult:
    _require_module("PIL", "缺少 Pillow，请安装可选依赖：pip install pillow")
    if require_remotion:
        remotion_blocker = _remotion_unavailable_reason()
        if remotion_blocker is not None:
            raise RuntimeError(f"当前任务要求使用 Remotion skill 生成视频，但 Remotion 环境不可用：{remotion_blocker}")
    ffmpeg = _ffmpeg_exe()
    output_dir = output_dir.resolve()
    job_dir = output_dir / _job_name(script)
    frame_dir = job_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    audio_path = job_dir / "voice.m4a"
    audio_ready, synced_clips = _try_render_tts_by_clip(clips, audio_path, job_dir=job_dir, ffmpeg=ffmpeg, warnings=warnings)
    if audio_ready:
        clips = synced_clips
    scene_images = _try_generate_scene_images(script, clips, job_dir, warnings)
    frame_paths = _render_frames(script, clips, frame_dir, warnings, scene_images=scene_images)
    if not any(scene_images):
        warnings.append("当前视频草稿使用模板化分镜画面；配置 DashScope 图片 API 后可按每条分镜逐镜头出图。")
    subtitles_path = job_dir / "subtitles.srt"
    _write_srt(clips, subtitles_path)

    duration_seconds = sum(clip.duration for clip in clips)
    if not audio_ready:
        audio_path = job_dir / "silent.m4a"
        _render_silent_audio(ffmpeg, audio_path, duration_seconds)

    remotion_video_path = _try_render_with_remotion(
        script,
        clips,
        audio_path=audio_path,
        scene_images=scene_images,
        job_dir=job_dir,
        warnings=warnings,
    )
    if remotion_video_path is not None:
        return VideoRenderResult(
            video_path=remotion_video_path,
            audio_path=audio_path,
            subtitles_path=subtitles_path,
            frame_paths=[path for path in scene_images if path is not None],
            warnings=warnings,
            duration_seconds=duration_seconds,
        )
    if require_remotion:
        detail = "；".join(warnings) or "Remotion skill 未返回可用视频文件。"
        raise RuntimeError(f"当前任务要求使用 Remotion skill 生成视频，但 Remotion 渲染未成功：{detail}")

    concat_path = job_dir / "frames.txt"
    _write_concat_file(frame_paths, clips, concat_path)
    video_path = job_dir / "video-narrated.mp4"
    _run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-i",
            str(audio_path),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(video_path),
        ]
    )
    return VideoRenderResult(
        video_path=video_path,
        audio_path=audio_path,
        subtitles_path=subtitles_path,
        frame_paths=frame_paths,
        warnings=warnings,
        duration_seconds=duration_seconds,
    )


def _require_module(module_name: str, message: str) -> None:
    if importlib.util.find_spec(module_name) is None:
        raise RuntimeError(message)


def _ffmpeg_exe() -> str:
    if importlib.util.find_spec("imageio_ffmpeg") is not None:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    from shutil import which

    ffmpeg = which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    raise RuntimeError("缺少 ffmpeg，请安装 imageio-ffmpeg 或系统 ffmpeg。")


def _job_name(script: VideoChannelScript) -> str:
    seed = f"{script.title}\n{script.voiceover}\n{time.time_ns()}".encode("utf-8")
    return f"video_{hashlib.sha1(seed).hexdigest()[:12]}"


def _storyboard_clips(script: VideoChannelScript) -> list[StoryboardClip]:
    rows = _markdown_table_rows(script.storyboard_markdown)
    clips: list[StoryboardClip] = []
    cursor = 0.0
    min_clip_seconds = float(os.getenv("VIDEO_RENDER_MIN_CLIP_SECONDS", "4.5"))
    for row in rows:
        if len(row) < 4 or row[0] == "时间":
            continue
        start, end = _parse_time_range(row[0], fallback_start=cursor)
        if end <= start:
            end = start + min_clip_seconds
        elif end - start < min_clip_seconds:
            end = start + min_clip_seconds
        cursor = end
        clips.append(
            StoryboardClip(
                start=start,
                end=end,
                visual=_visual_text_or_fallback(row[1], fallback=f"{row[3]} {row[2]}"),
                voiceover=_clean_cell(row[2]),
                subtitle=_clean_cell(row[3]),
            )
        )
    if clips:
        max_clips = int(os.getenv("VIDEO_RENDER_MAX_CLIPS", "0"))
        return clips[:max_clips] if max_clips > 0 else clips
    return _fallback_clips(script)


def _markdown_table_rows(markdown: str) -> list[list[str]]:
    rows: list[list[str]] = []
    rows.extend(_markdown_storyboard_rows(markdown))
    rows.extend(_html_table_rows(markdown))
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        cells: list[str] = []
        if line.startswith("|") and line.endswith("|"):
            cells = [_clean_cell(cell) for cell in line.strip("|").split("|")]
        elif "\t" in line:
            cells = [_clean_cell(cell) for cell in line.split("\t")]
        elif re.match(r"^\d+\s*[-到]\s*\d+\s*s?\s+", line, flags=re.IGNORECASE):
            cells = _loose_storyboard_cells(line)
        if not cells:
            continue
        if cells and all(set(cell) <= {"-"} for cell in cells):
            continue
        rows.append(cells)
    return rows


def _markdown_storyboard_rows(markdown: str) -> list[list[str]]:
    rows: list[list[str]] = []
    current: dict[str, str] = {}

    def flush() -> None:
        if current.get("time") and (current.get("visual") or current.get("voiceover") or current.get("subtitle")):
            rows.append(
                [
                    current.get("time", ""),
                    current.get("visual", ""),
                    current.get("voiceover", ""),
                    current.get("subtitle", ""),
                ]
            )
        current.clear()

    field_pattern = re.compile(r"^(?:[-*]\s*)?(时间|画面|口播|屏幕字幕|字幕)\s*[：:]\s*(.+)$")
    item_time_pattern = re.compile(r"^\s*(?:\d+[.、)]\s*)?时间\s*[：:]\s*(.+)$")
    for raw_line in markdown.splitlines():
        line = _clean_cell(raw_line).strip()
        if not line:
            continue
        time_match = item_time_pattern.match(line)
        if time_match:
            flush()
            current["time"] = time_match.group(1).strip()
            continue
        field_match = field_pattern.match(line)
        if not field_match:
            continue
        field_name, value = field_match.group(1), field_match.group(2).strip()
        key = {
            "时间": "time",
            "画面": "visual",
            "口播": "voiceover",
            "屏幕字幕": "subtitle",
            "字幕": "subtitle",
        }[field_name]
        if key == "time" and current:
            flush()
        current[key] = value
    flush()
    return rows


def _html_table_rows(markdown: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", markdown, flags=re.IGNORECASE | re.DOTALL):
        row_html = row_match.group(1)
        cells = [
            _plain_text(cell_match.group(1))
            for cell_match in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.IGNORECASE | re.DOTALL)
        ]
        if cells:
            rows.append(cells)
    return rows


def _loose_storyboard_cells(line: str) -> list[str]:
    match = re.match(r"^(\d+\s*[-到]\s*\d+\s*s?)\s+(.+)$", line, flags=re.IGNORECASE)
    if not match:
        return []
    time_range = match.group(1)
    rest = match.group(2)
    parts = [item for item in re.split(r"\s{2,}", rest) if item.strip()]
    if len(parts) >= 3:
        return [time_range, parts[0], parts[1], " ".join(parts[2:])]
    return []


def _parse_time_range(value: str, *, fallback_start: float) -> tuple[float, float]:
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", value)]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if len(numbers) == 1:
        return fallback_start, max(fallback_start + 1, numbers[0])
    return fallback_start, fallback_start + 8


def _fallback_clips(script: VideoChannelScript) -> list[StoryboardClip]:
    chunks = _wrap_text(script.voiceover, max_chars=38)[:8] or [script.title]
    duration = max(5.0, min(9.0, 60 / max(1, len(chunks))))
    clips = []
    cursor = 0.0
    for index, chunk in enumerate(chunks, start=1):
        clips.append(
            StoryboardClip(
                start=cursor,
                end=cursor + duration,
                visual=chunk,
                voiceover=chunk,
                subtitle=chunk,
            )
        )
        cursor += duration
    return clips


def _render_frames(
    script: VideoChannelScript,
    clips: list[StoryboardClip],
    frame_dir: Path,
    warnings: list[str],
    *,
    scene_images: list[Path | None] | None = None,
) -> list[Path]:
    from PIL import Image, ImageDraw, ImageFont

    font_path = _font_path()
    if not font_path:
        warnings.append("未找到中文字体，字幕卡文字可能无法正确显示。")
    title_font = _load_font(ImageFont, font_path, 58)
    body_font = _load_font(ImageFont, font_path, 38)
    small_font = _load_font(ImageFont, font_path, 30)

    frame_paths: list[Path] = []
    for index, clip in enumerate(clips, start=1):
        scene_image = scene_images[index - 1] if scene_images and index - 1 < len(scene_images) else None
        image = Image.new("RGB", (1080, 1920), "#f8fafc")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((70, 90, 1010, 245), radius=34, fill="#2563eb")
        draw.text((110, 128), _safe_display_text(script.cover_text or script.title, limit=16), fill="white", font=title_font)
        draw.rounded_rectangle((70, 300, 1010, 1415), radius=42, fill="#ffffff", outline="#d9e2ef", width=3)
        if scene_image is not None and scene_image.exists():
            _paste_scene_image(image, scene_image, box=(85, 315, 995, 1400), warnings=warnings)
        _draw_scene(draw, clip, body_font=body_font, small_font=small_font)
        frame_path = frame_dir / f"frame_{index:03d}.png"
        image.save(frame_path)
        frame_paths.append(frame_path)
    return frame_paths


def _try_generate_scene_images(
    script: VideoChannelScript,
    clips: list[StoryboardClip],
    job_dir: Path,
    warnings: list[str],
) -> list[Path | None]:
    if os.getenv("VIDEO_RENDER_SCENE_IMAGES", "1").lower() in {"0", "false", "no"}:
        warnings.append("已跳过逐分镜图片生成，使用模板画面。")
        return [None for _ in clips]
    if not (os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")):
        warnings.append("未检测到 DASHSCOPE_API_KEY / QWEN_API_KEY，使用模板画面。")
        return [None for _ in clips]

    project_root = Path(__file__).resolve().parents[2]
    imagegen = project_root / "skills" / "image-caption-prompt" / "imagegen.py"
    if not imagegen.exists():
        warnings.append("未找到 imagegen.py，使用模板画面。")
        return [None for _ in clips]

    scene_dir = job_dir / "scene_images"
    scene_dir.mkdir(parents=True, exist_ok=True)
    limit = int(os.getenv("VIDEO_RENDER_SCENE_IMAGE_LIMIT", "0"))
    timeout = int(os.getenv("VIDEO_RENDER_SCENE_IMAGE_TIMEOUT_SECONDS", "240"))
    image_size = os.getenv("VIDEO_RENDER_SCENE_IMAGE_SIZE", "810x1440")
    results: list[Path | None] = []
    for index, clip in enumerate(clips, start=1):
        if limit > 0 and index > limit:
            results.append(None)
            continue
        prompt = _scene_image_prompt(script, clip, index=index)
        command = [
            sys.executable,
            str(imagegen),
            prompt,
            "--size",
            image_size,
            "--count",
            "1",
            "--output-dir",
            str(scene_dir),
            "--prefix",
            f"scene_{index:02d}",
            "--negative-prompt",
            _scene_image_negative_prompt(),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            warnings.append(f"第 {index} 个分镜图片生成失败，已使用模板画面：{exc}")
            results.append(None)
            continue
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            warnings.append(f"第 {index} 个分镜图片生成失败，已使用模板画面：{detail[-180:]}")
            results.append(None)
            continue
        image_path = _first_generated_image(completed.stdout)
        if image_path is None:
            warnings.append(f"第 {index} 个分镜未返回图片路径，已使用模板画面。")
        results.append(image_path)
    if any(results):
        warnings.append("已按分镜画面描述逐镜头生成图片；图片文字已淡化，最终可见文字由程序叠加为简体中文。")
    return results


def _try_render_with_remotion(
    script: VideoChannelScript,
    clips: list[StoryboardClip],
    *,
    audio_path: Path,
    scene_images: list[Path | None],
    job_dir: Path,
    warnings: list[str],
) -> Path | None:
    project_root = Path(__file__).resolve().parents[2]
    renderer_dir = project_root / "video-renderer"
    blocker = _remotion_unavailable_reason()
    if blocker is not None:
        warnings.append(f"{blocker}，已回退 ffmpeg 静态帧渲染。")
        return None

    job_name = job_dir.name
    public_job_dir = renderer_dir / "public" / "jobs" / job_name
    public_job_dir.mkdir(parents=True, exist_ok=True)
    public_audio = public_job_dir / audio_path.name
    shutil.copy2(audio_path, public_audio)
    public_scene_images: list[str | None] = []
    for index, image_path in enumerate(scene_images, start=1):
        if image_path is None or not image_path.exists():
            public_scene_images.append(None)
            continue
        target = public_job_dir / f"scene_{index:03d}{image_path.suffix.lower()}"
        shutil.copy2(image_path, target)
        public_scene_images.append(f"jobs/{job_name}/{target.name}")

    props_path = job_dir / "remotion-props.json"
    props_path.write_text(
        json.dumps(
            _remotion_props(
                script,
                clips,
                audio_src=f"jobs/{job_name}/{public_audio.name}",
                scene_images=public_scene_images,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output_path = job_dir / "video-remotion-narrated.mp4"
    command, cwd, env = _remotion_render_command(renderer_dir, output_path, props_path, warnings)
    try:
        subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=int(os.getenv("VIDEO_RENDER_REMOTION_TIMEOUT_SECONDS", "600")), check=True)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        warnings.append(f"Remotion 3.0 渲染失败，已回退 ffmpeg 静态帧渲染：{_clean_subprocess_error(exc)}")
        return None
    warnings.append("已使用 Remotion 3.0 渲染 React 分镜、字幕、音频和转场。")
    return output_path if output_path.exists() else None


def _remotion_unavailable_reason() -> str | None:
    if os.getenv("VIDEO_RENDER_ENGINE", "remotion").lower() not in {"remotion", "auto"}:
        return "已按配置跳过 Remotion"
    project_root = Path(__file__).resolve().parents[2]
    renderer_dir = project_root / "video-renderer"
    if not renderer_dir.exists():
        return "未找到 video-renderer"
    if not (renderer_dir / "node_modules").exists():
        return "video-renderer 依赖未安装，请在 video-renderer 目录执行 npm install"
    if _host_glibc_too_old() and shutil.which("docker") is not None:
        return None
    if _local_remotion_command(renderer_dir) is None:
        return "未检测到可用的 node/remotion CLI"
    if _host_glibc_too_old():
        glibc_version = _glibc_version() or "unknown"
        min_glibc = os.getenv("VIDEO_RENDER_REMOTION_MIN_GLIBC", "2.31")
        return f"当前 glibc {glibc_version} 低于 Remotion 渲染要求 {min_glibc}，且未检测到 Docker"
    return None


def _remotion_render_command(renderer_dir: Path, output_path: Path, props_path: Path, warnings: list[str]) -> tuple[list[str], Path, dict[str, str] | None]:
    project_root = Path(__file__).resolve().parents[2]
    if _host_glibc_too_old() and shutil.which("docker") is not None:
        image = os.getenv("VIDEO_RENDER_REMOTION_DOCKER_IMAGE", "mcr.microsoft.com/playwright:v1.49.1-jammy")
        warnings.append(f"宿主机 glibc 不满足 Remotion 要求，已改用 Docker 镜像 {image} 运行 Remotion skill。")
        return (
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{project_root}:/workspace",
                "-w",
                "/workspace/video-renderer",
                image,
                "./node_modules/.bin/remotion",
                "render",
                "src/index.ts",
                "ProblemSolving3DVideo",
                f"/workspace/{output_path.relative_to(project_root)}",
                "--props",
                f"/workspace/{props_path.relative_to(project_root)}",
                "--log",
                "error",
            ],
            project_root,
            None,
        )
    local_command = _local_remotion_command(renderer_dir)
    if local_command is None:
        raise RuntimeError("未检测到可用的 node/remotion CLI")
    env = os.environ.copy()
    venv_bin = Path(sys.executable).resolve().parent
    env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    return (
        [
            *local_command,
            "render",
            "src/index.ts",
            "ProblemSolving3DVideo",
            str(output_path.resolve()),
            "--props",
            str(props_path.resolve()),
            "--log",
            "error",
        ],
        renderer_dir,
        env,
    )


def _local_remotion_command(renderer_dir: Path) -> list[str] | None:
    node = shutil.which("node")
    if node is None:
        return None
    remotion_bin = renderer_dir / "node_modules" / ".bin" / "remotion"
    if remotion_bin.exists():
        return [str(remotion_bin)]
    cli = renderer_dir / "node_modules" / "@remotion" / "cli" / "dist" / "index.js"
    if cli.exists():
        return [node, str(cli)]
    return None


def _host_glibc_too_old() -> bool:
    glibc_version = _glibc_version()
    if glibc_version is None:
        return False
    min_glibc = os.getenv("VIDEO_RENDER_REMOTION_MIN_GLIBC", "2.31")
    return _version_tuple(glibc_version) < _version_tuple(min_glibc)


def _remotion_props(
    script: VideoChannelScript,
    clips: list[StoryboardClip],
    *,
    audio_src: str,
    scene_images: list[str | None],
) -> dict[str, Any]:
    return {
        "title": _safe_display_text(script.title, limit=32),
        "coverText": _safe_display_text(script.cover_text or script.title, limit=18),
        "audioSrc": audio_src,
        "totalDurationSeconds": sum(clip.duration for clip in clips),
        "clips": [
            {
                "start": clip.start,
                "end": clip.end,
                "visual": _safe_display_text(clip.visual, limit=80),
                "voiceover": _safe_display_text(clip.voiceover, limit=120),
                "subtitle": _safe_display_text(clip.subtitle or clip.voiceover, limit=80),
                "sceneImage": scene_images[index] if index < len(scene_images) else None,
                "sceneType": re.sub(r"[^a-z0-9_-]", "", (clip.scene_type or "concept").lower()) or "concept",
                "scenePhase": re.sub(r"[^a-z0-9_-]", "", (clip.scene_phase or "explain").lower()) or "explain",
            }
            for index, clip in enumerate(clips)
        ],
    }


def _glibc_version() -> str | None:
    libc_name, libc_version = platform.libc_ver()
    if libc_name.lower() != "glibc" or not libc_version:
        return None
    return libc_version


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


def _scene_image_prompt(script: VideoChannelScript, clip: StoryboardClip, *, index: int) -> str:
    caption = _safe_visible_caption(clip.subtitle or clip.voiceover or script.cover_text)
    prompt = f"""K12科教短视频竖屏镜头图，9:16，适合小学/初中/高中知识讲解。
视频标题：{script.title}
第{index}个镜头画面：{clip.visual}
本镜头口播：{clip.voiceover}
本镜头字幕：{clip.subtitle}
要求：画面必须严格表现“第{index}个镜头画面”的内容；图片主体尽量不要生成任何文字，文字会由程序后期叠加；如果画面必须出现文字，只能使用清晰简体中文，且只允许出现这句：{caption}；不要出现其他文字、伪中文、乱码、英文字母、繁体字、拼音、分镜表、镜头编号、制作说明或UI界面；优先用课堂板书、简洁动画、实物示意和数学图形表现。"""
    return _limit_text(prompt.replace("\n", " "), 500)


def _scene_image_negative_prompt() -> str:
    return (
        "伪中文、乱码字、乱码字母、假汉字、无意义符号、英文字母、英文单词、拼音、繁体字、"
        "日文、韩文、错别字、错误公式、制作说明、分镜编号、镜头编号、字幕条、UI界面、低清晰度、变形手指"
    )


def _safe_visible_caption(value: str) -> str:
    cleaned = _safe_science_text(value)
    cleaned = re.sub(r"\s+", "", cleaned)
    return _limit_text(cleaned or "知识点讲解", 18)


def _safe_display_text(value: str, *, limit: int) -> str:
    cleaned = _safe_science_text(value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return _limit_text(cleaned or "知识点讲解", limit)


def _safe_science_text(value: str) -> str:
    text = _clean_cell(value)
    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"占位{len(protected) - 1}位占"

    token_pattern = r"(?:mol/\(L·min\)|mol/L|rad/s|mL|min|H2O|CO2|NaCl|NH4Cl|Ba\(OH\)2)"
    text = re.sub(token_pattern, protect, text)
    text = re.sub(r"[^\u4e00-\u9fff0-9πvcmtgosTLFqkrNBUEI＋+×÷=＝·./\-^Δθ²³₁₂₃₄₅₆₇₈₉₀°？?，。：“”《》、()（） ]", "", text)
    for index, token in enumerate(protected):
        text = text.replace(f"占位{index}位占", token)
    return text


def _first_generated_image(output: str) -> Path | None:
    for raw_line in output.splitlines():
        value = raw_line.strip()
        if not value:
            continue
        path = Path(value)
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and path.exists():
            return path
    return None


def _paste_scene_image(image: Any, scene_image: Path, *, box: tuple[int, int, int, int], warnings: list[str]) -> None:
    from PIL import Image, ImageEnhance, ImageFilter

    try:
        with Image.open(scene_image) as raw:
            frame = raw.convert("RGB")
            x1, y1, x2, y2 = box
            width = x2 - x1
            height = y2 - y1
            frame_ratio = frame.width / frame.height
            target_ratio = width / height
            if frame_ratio > target_ratio:
                new_width = int(frame.height * target_ratio)
                left = (frame.width - new_width) // 2
                frame = frame.crop((left, 0, left + new_width, frame.height))
            else:
                new_height = int(frame.width / target_ratio)
                top = (frame.height - new_height) // 2
                frame = frame.crop((0, top, frame.width, top + new_height))
            frame = frame.resize((width, height)).filter(ImageFilter.GaussianBlur(radius=7))
            frame = ImageEnhance.Color(frame).enhance(0.45)
            frame = ImageEnhance.Brightness(frame).enhance(1.18)
            image.paste(frame, (x1, y1))
            overlay = Image.new("RGBA", (width, height), (255, 255, 255, 165))
            image.paste(overlay, (x1, y1), overlay)
    except OSError as exc:
        warnings.append(f"分镜图片读取失败，已保留空白画面：{exc}")


def _draw_scene(draw: Any, clip: StoryboardClip, *, body_font: Any, small_font: Any) -> None:
    combined = f"{clip.visual}\n{clip.subtitle}\n{clip.voiceover}"
    area = (110, 365, 970, 1335)
    if any(keyword in combined for keyword in ("苹果", "切成", "圆", "1/2", "二分之一")):
        _draw_fraction_scene(draw, area, body_font=body_font, small_font=small_font)
    elif any(keyword in combined for keyword in ("算式", "公式", "计算", "代入", "=", "＝", "箭头")):
        _draw_formula_scene(draw, area, clip, body_font=body_font, small_font=small_font)
    elif any(keyword in combined for keyword in ("白板", "板书", "口诀", "总结")):
        _draw_whiteboard_scene(draw, area, clip, body_font=body_font, small_font=small_font)
    elif any(keyword in combined for keyword in ("老师", "出镜", "手持", "讲解")):
        _draw_teacher_scene(draw, area, clip, body_font=body_font, small_font=small_font)
    else:
        _draw_custom_visual_scene(draw, area, clip, body_font=body_font, small_font=small_font)


def _draw_fraction_scene(draw: Any, area: tuple[int, int, int, int], *, body_font: Any, small_font: Any) -> None:
    x1, y1, x2, y2 = area
    cx = (x1 + x2) // 2
    cy = y1 + 210
    radius = 150
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill="#ef4444", outline="#991b1b", width=6)
    draw.line((cx, cy - radius, cx, cy + radius), fill="white", width=10)
    draw.pieslice((cx - radius, cy - radius, cx + radius, cy + radius), 90, 270, fill="#f97316", outline="#991b1b", width=4)
    draw.pieslice((cx - radius, cy - radius, cx + radius, cy + radius), 270, 90, fill="#ef4444", outline="#991b1b", width=4)
    draw.text((x1 + 80, y1 + 30), "1 个整体", fill="#0f172a", font=body_font)
    draw.text((cx - 185, cy + 175), "1/2", fill="#0f172a", font=body_font)
    draw.text((cx + 110, cy + 175), "1/2", fill="#0f172a", font=body_font)
    draw.rounded_rectangle((x1 + 150, y2 - 90, x2 - 150, y2 - 20), radius=20, fill="#fee2e2")
    draw.text((x1 + 205, y2 - 82), "1 里面有 2 个二分之一", fill="#991b1b", font=small_font)


def _draw_formula_scene(
    draw: Any,
    area: tuple[int, int, int, int],
    clip: StoryboardClip,
    *,
    body_font: Any,
    small_font: Any,
) -> None:
    x1, y1, x2, y2 = area
    main_text = _visual_summary(clip.subtitle or clip.voiceover or clip.visual)
    detail_text = _visual_summary(clip.visual or clip.voiceover)
    draw.rounded_rectangle((x1 + 40, y1 + 70, x2 - 40, y1 + 210), radius=28, fill="#eff6ff", outline="#93c5fd", width=4)
    _draw_wrapped(draw, main_text, (x1 + 90, y1 + 105), body_font, "#1d4ed8", max_chars=14)
    draw.line((x1 + 250, y1 + 285, x2 - 250, y1 + 285), fill="#2563eb", width=8)
    draw.polygon([(x2 - 250, y1 + 285), (x2 - 285, y1 + 265), (x2 - 285, y1 + 305)], fill="#2563eb")
    draw.rounded_rectangle((x1 + 40, y1 + 350, x2 - 40, y1 + 490), radius=28, fill="#ecfdf5", outline="#86efac", width=4)
    _draw_wrapped(draw, detail_text, (x1 + 90, y1 + 385), body_font, "#166534", max_chars=14)
    draw.text((x1 + 300, y1 + 250), "条件", fill="#334155", font=small_font)
    draw.text((x1 + 515, y1 + 250), "结论", fill="#334155", font=small_font)
    draw.rounded_rectangle((x1 + 300, y1 + 555, x2 - 300, y1 + 625), radius=18, fill="#fef3c7")
    draw.text((x1 + 345, y1 + 563), "按步骤计算", fill="#92400e", font=small_font)


def _draw_whiteboard_scene(
    draw: Any,
    area: tuple[int, int, int, int],
    clip: StoryboardClip,
    *,
    body_font: Any,
    small_font: Any,
) -> None:
    x1, y1, x2, y2 = area
    draw.rounded_rectangle((x1 + 45, y1 + 20, x2 - 45, y2 - 30), radius=28, fill="#f8fafc", outline="#94a3b8", width=6)
    title = _visual_summary(clip.subtitle or clip.visual or clip.voiceover)
    draw.text((x1 + 105, y1 + 75), _limit_text(title, 12), fill="#0f172a", font=body_font)
    items = _visual_bullets(clip)
    colors = ["#dbeafe", "#dcfce7", "#fef3c7"]
    for index, item in enumerate(items):
        top = y1 + 165 + index * 105
        draw.rounded_rectangle((x1 + 120, top, x2 - 120, top + 72), radius=20, fill=colors[index])
        draw.text((x1 + 170, top + 16), _limit_text(item, 18), fill="#111827", font=small_font)


def _draw_teacher_scene(
    draw: Any,
    area: tuple[int, int, int, int],
    clip: StoryboardClip,
    *,
    body_font: Any,
    small_font: Any,
) -> None:
    x1, y1, x2, y2 = area
    head = (x1 + 90, y1 + 80, x1 + 230, y1 + 220)
    draw.ellipse(head, fill="#fde68a", outline="#92400e", width=4)
    draw.rounded_rectangle((x1 + 115, y1 + 230, x1 + 205, y1 + 430), radius=30, fill="#60a5fa")
    draw.line((x1 + 120, y1 + 285, x1 + 45, y1 + 350), fill="#1d4ed8", width=10)
    draw.line((x1 + 200, y1 + 285, x1 + 310, y1 + 350), fill="#1d4ed8", width=10)
    draw.rounded_rectangle((x1 + 330, y1 + 55, x2 - 50, y1 + 310), radius=30, fill="#ffffff", outline="#bfdbfe", width=4)
    _draw_wrapped(draw, _visual_summary(clip.voiceover or clip.subtitle), (x1 + 370, y1 + 95), body_font, "#0f172a", max_chars=13)
    draw.rounded_rectangle((x1 + 330, y1 + 360, x2 - 50, y1 + 470), radius=22, fill="#fee2e2")
    draw.text((x1 + 370, y1 + 390), "先读题，再分析", fill="#991b1b", font=small_font)


def _draw_concept_scene(draw: Any, area: tuple[int, int, int, int], *, body_font: Any, small_font: Any) -> None:
    x1, y1, x2, _ = area
    labels = ["定义", "例子", "误区", "回顾"]
    for index, label in enumerate(labels):
        left = x1 + 60 + index * 205
        draw.rounded_rectangle((left, y1 + 170, left + 150, y1 + 270), radius=24, fill="#dbeafe", outline="#60a5fa", width=3)
        draw.text((left + 38, y1 + 198), label, fill="#1d4ed8", font=small_font)
        if index < len(labels) - 1:
            draw.line((left + 155, y1 + 220, left + 200, y1 + 220), fill="#2563eb", width=6)
            draw.polygon([(left + 200, y1 + 220), (left + 178, y1 + 208), (left + 178, y1 + 232)], fill="#2563eb")
    draw.text((x1 + 180, y1 + 370), "一个小知识点，按四步讲清楚", fill="#334155", font=body_font)


def _draw_custom_visual_scene(
    draw: Any,
    area: tuple[int, int, int, int],
    clip: StoryboardClip,
    *,
    body_font: Any,
    small_font: Any,
) -> None:
    x1, y1, x2, y2 = area
    draw.rounded_rectangle((x1 + 55, y1 + 45, x2 - 55, y2 - 95), radius=36, fill="#f8fafc", outline="#bfdbfe", width=5)
    draw.rounded_rectangle((x1 + 110, y1 + 105, x2 - 110, y1 + 250), radius=28, fill="#dbeafe")
    main_text = _visual_summary(clip.visual or clip.subtitle or clip.voiceover)
    _draw_wrapped(draw, main_text, (x1 + 145, y1 + 138), body_font, "#1d4ed8", max_chars=12, line_gap=14)
    draw.line((x1 + 210, y1 + 360, x2 - 210, y1 + 360), fill="#2563eb", width=8)
    draw.polygon([(x2 - 210, y1 + 360), (x2 - 245, y1 + 340), (x2 - 245, y1 + 380)], fill="#2563eb")
    draw.rounded_rectangle((x1 + 110, y1 + 455, x2 - 110, y1 + 630), radius=28, fill="#ecfdf5")
    _draw_wrapped(draw, _visual_summary(clip.subtitle or clip.voiceover), (x1 + 145, y1 + 492), small_font, "#166534", max_chars=18)
    draw.ellipse((x1 + 355, y2 - 250, x1 + 505, y2 - 100), fill="#fef3c7", outline="#f59e0b", width=5)
    draw.ellipse((x1 + 530, y2 - 250, x1 + 680, y2 - 100), fill="#fee2e2", outline="#ef4444", width=5)


def _visual_summary(value: str) -> str:
    cleaned = _clean_cell(value)
    cleaned = re.sub(r"（.*?）|\(.*?\)", "", cleaned)
    cleaned = re.sub(r"[。；;，,].*$", "", cleaned)
    return _limit_text(cleaned or "知识点画面", 36)


def _visual_bullets(clip: StoryboardClip) -> list[str]:
    text = _clean_cell(f"{clip.subtitle}。{clip.voiceover}。{clip.visual}")
    candidates = [
        item.strip(" ：:，,。；;")
        for item in re.split(r"[。；;]\s*|\n+", text)
        if item.strip(" ：:，,。；;")
    ]
    bullets: list[str] = []
    for item in candidates:
        summary = _visual_summary(item)
        if summary and summary not in bullets:
            bullets.append(summary)
        if len(bullets) >= 3:
            break
    while len(bullets) < 3:
        bullets.append(["本题条件", "本题公式", "本题答案"][len(bullets)])
    return bullets


def _font_path() -> str | None:
    candidates = [
        os.getenv("VIDEO_RENDER_FONT_PATH"),
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _load_font(image_font: Any, font_path: str | None, size: int) -> Any:
    if font_path:
        try:
            return image_font.truetype(font_path, size=size)
        except OSError:
            pass
    return image_font.load_default()


def _draw_wrapped(
    draw: Any,
    text: str,
    xy: tuple[int, int],
    font: Any,
    fill: str,
    *,
    max_chars: int,
    line_gap: int = 10,
) -> None:
    x, y = xy
    for line in _wrap_text(text, max_chars=max_chars):
        draw.text((x, y), line, fill=fill, font=font)
        bbox = draw.textbbox((x, y), line, font=font)
        y += (bbox[3] - bbox[1]) + line_gap


def _wrap_text(text: str, *, max_chars: int) -> list[str]:
    cleaned = re.sub(r"\s+", " ", _clean_cell(text))
    if not cleaned:
        return []
    lines: list[str] = []
    buffer = ""
    for char in cleaned:
        buffer += char
        if len(buffer) >= max_chars or char in "。！？；，":
            lines.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        lines.append(buffer.strip())
    return lines


def _write_srt(clips: list[StoryboardClip], path: Path) -> None:
    chunks = []
    for index, clip in enumerate(clips, start=1):
        subtitle = _safe_display_text(clip.subtitle or clip.voiceover, limit=80)
        chunks.append(
            f"{index}\n{_srt_time(clip.start)} --> {_srt_time(clip.end)}\n{subtitle}\n"
        )
    path.write_text("\n".join(chunks), encoding="utf-8")


def _srt_time(seconds: float) -> str:
    millis = int(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _try_render_tts_by_clip(
    clips: list[StoryboardClip],
    output_path: Path,
    *,
    job_dir: Path,
    ffmpeg: str,
    warnings: list[str],
) -> tuple[bool, list[StoryboardClip]]:
    if os.getenv("VIDEO_TTS_ENABLED", "1").lower() in {"0", "false", "no"}:
        warnings.append("已跳过 TTS，使用静音音轨。")
        return False, clips
    voice_tts = Path(__file__).resolve().parents[2] / "skills" / "voice-tts" / "voice_tts.py"
    if voice_tts.exists():
        try:
            return _try_render_voice_tts_by_clip(clips, output_path, job_dir=job_dir, ffmpeg=ffmpeg, voice_tts=voice_tts, warnings=warnings)
        except Exception as exc:  # pragma: no cover - depends on external TTS service
            warnings.append(f"voice-tts 生成失败，使用静音音轨：{exc}")
            return False, clips
    if importlib.util.find_spec("edge_tts") is None:
        warnings.append("未安装 edge-tts，使用静音音轨。")
        return False, clips
    try:
        import edge_tts

        voice = os.getenv("VIDEO_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
        audio_dir = job_dir / "audio_segments"
        audio_dir.mkdir(parents=True, exist_ok=True)
        segment_paths: list[Path] = []
        synced_clips: list[StoryboardClip] = []
        cursor = 0.0
        min_clip_seconds = float(os.getenv("VIDEO_RENDER_MIN_CLIP_SECONDS", "4.5"))
        clip_padding_seconds = float(os.getenv("VIDEO_RENDER_CLIP_PADDING_SECONDS", "0.8"))
        for index, clip in enumerate(clips, start=1):
            segment_path = audio_dir / f"voice_{index:03d}.mp3"
            text = clip.voiceover or clip.subtitle
            communicate = edge_tts.Communicate(text, voice=voice)
            asyncio.run(communicate.save(str(segment_path)))
            audio_duration = max(_audio_duration_seconds(ffmpeg, segment_path), 0.8)
            duration = max(audio_duration + clip_padding_seconds, min_clip_seconds, clip.duration)
            segment_paths.append(segment_path)
            synced_clips.append(
                StoryboardClip(
                    start=cursor,
                    end=cursor + duration,
                    visual=clip.visual,
                    voiceover=clip.voiceover,
                    subtitle=clip.subtitle,
                    scene_type=clip.scene_type,
                    scene_phase=clip.scene_phase,
                )
            )
            cursor += duration
        _concat_audio_segments(ffmpeg, segment_paths, output_path)
        warnings.append("已按每条分镜逐段生成口播音频，并用真实音频时长同步字幕和画面。")
        return output_path.exists() and output_path.stat().st_size > 0, synced_clips
    except Exception as exc:  # pragma: no cover - depends on external TTS service
        warnings.append(f"TTS 生成失败，使用静音音轨：{exc}")
        return False, clips


def _try_render_voice_tts_by_clip(
    clips: list[StoryboardClip],
    output_path: Path,
    *,
    job_dir: Path,
    ffmpeg: str,
    voice_tts: Path,
    warnings: list[str],
) -> tuple[bool, list[StoryboardClip]]:
    audio_dir = job_dir / "audio_segments"
    audio_dir.mkdir(parents=True, exist_ok=True)
    text_dir = job_dir / "tts_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    synced_clips: list[StoryboardClip] = []
    cursor = 0.0
    min_clip_seconds = float(os.getenv("VIDEO_RENDER_MIN_CLIP_SECONDS", "4.5"))
    clip_padding_seconds = float(os.getenv("VIDEO_RENDER_CLIP_PADDING_SECONDS", "0.8"))
    for index, clip in enumerate(clips, start=1):
        text_path = text_dir / f"voice_{index:03d}.txt"
        segment_path = audio_dir / f"voice_{index:03d}.mp3"
        text_path.write_text(clip.voiceover or clip.subtitle or "知识点讲解", encoding="utf-8")
        command = [
            sys.executable,
            str(voice_tts),
            str(text_path),
            "--output",
            str(segment_path),
            "--fallback-edge-tts",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=int(os.getenv("VIDEO_TTS_TIMEOUT_SECONDS", "180")), check=False)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown voice-tts error").strip()
            raise RuntimeError(detail[-500:])
        audio_duration = max(_audio_duration_seconds(ffmpeg, segment_path), 0.8)
        duration = max(audio_duration + clip_padding_seconds, min_clip_seconds, clip.duration)
        segment_paths.append(segment_path)
        synced_clips.append(
            StoryboardClip(
                start=cursor,
                end=cursor + duration,
                visual=clip.visual,
                voiceover=clip.voiceover,
                subtitle=clip.subtitle,
                scene_type=clip.scene_type,
                scene_phase=clip.scene_phase,
            )
        )
        cursor += duration
    _concat_audio_segments(ffmpeg, segment_paths, output_path)
    warnings.append("已使用 voice-tts skill 生成口播音频，并同步字幕和画面。")
    return output_path.exists() and output_path.stat().st_size > 0, synced_clips


def _audio_duration_seconds(ffmpeg: str, path: Path) -> float:
    command = [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(path),
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    output = f"{completed.stderr}\n{completed.stdout}"
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not match:
        return 0.0
    hours = float(match.group(1))
    minutes = float(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def _concat_audio_segments(ffmpeg: str, segment_paths: list[Path], output_path: Path) -> None:
    concat_path = output_path.with_suffix(".txt")
    concat_path.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in segment_paths) + "\n",
        encoding="utf-8",
    )
    _run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c:a",
            "aac",
            str(output_path),
        ]
    )


def _render_silent_audio(ffmpeg: str, path: Path, duration_seconds: float) -> None:
    _run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            f"{max(1.0, duration_seconds):.2f}",
            "-c:a",
            "aac",
            str(path),
        ]
    )


def _write_concat_file(frame_paths: list[Path], clips: list[StoryboardClip], path: Path) -> None:
    lines: list[str] = []
    for frame_path, clip in zip(frame_paths, clips, strict=False):
        lines.append(f"file '{frame_path.resolve().as_posix()}'")
        lines.append(f"duration {clip.duration:.2f}")
    if frame_paths:
        lines.append(f"file '{frame_paths[-1].resolve().as_posix()}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_ffmpeg(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown ffmpeg error").strip()
        raise RuntimeError(f"视频合成失败：{detail[-800:]}")


def _clean_subprocess_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        detail = exc.stderr or exc.stdout or str(exc)
    elif isinstance(exc, subprocess.TimeoutExpired):
        detail = f"timeout after {exc.timeout}s"
    else:
        detail = str(exc)
    return re.sub(r"\s+", " ", detail.strip())[-800:]


def _clean_cell(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", str(value), flags=re.IGNORECASE)
    return _remove_production_placeholders(text).strip()


def _visual_text_or_fallback(value: str, *, fallback: str) -> str:
    cleaned = _clean_cell(value)
    if cleaned:
        return cleaned
    return _clean_cell(fallback) or "知识点画面"


def _remove_production_placeholders(value: str) -> str:
    text = str(value)
    number = r"(?:\d+|[一二三四五六七八九十]+)"
    patterns = [
        rf"第\s*{number}\s*张\s*知识点\s*字幕卡",
        rf"第\s*{number}\s*个\s*知识点\s*字幕卡",
        rf"知识点\s*字幕卡",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text)
    return re.sub(r"\s+", " ", text).strip()


def _plain_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return _clean_cell(text)


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[:limit]}…"


def _limit_text(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]
