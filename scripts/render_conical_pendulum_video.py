"""Render a narrated conical pendulum explainer video.

The Remotion component is the preferred production renderer. This script creates
a deterministic local MP4 draft with the same storyboard when Remotion is not
available in the current environment.
"""

from __future__ import annotations

import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT_DIR / "out"
WIDTH = 720
HEIGHT = 1280
FPS = 24

TITLE = "圆锥摆运动例题"
NARRATION = (
    "这道题来自人教版高中物理必修第二册第六章向心力的空中飞椅情境。"
    "小球做水平圆周运动时，绳子的拉力斜向上，重力竖直向下。"
    "竖直方向没有加速度，所以拉力的竖直分量平衡重力。"
    "水平方向的合力指向圆心，提供向心力。"
    "因此可以列出两个方程，拉力乘余弦角等于重力，拉力乘正弦角等于质量乘速度平方除以半径。"
    "两式相除，就能得到速度和角度的关系。"
)

EXAMPLE = {
    "source": {
        "repository": "https://github.com/TapXWorld/ChinaTextbook",
        "pdf": "高中/物理/人教版-人民教育出版社/普通高中教科书·物理必修 第二册.pdf",
        "pages": "PDF 第 32-33 页，教材页码第 27-28 页",
        "basis": "第六章“向心力”用空中飞椅说明：飞椅与人做圆周运动时，绳子斜向上方的拉力和重力的合力提供向心力。",
    },
    "question": (
        "一小球用长为 L 的轻绳悬挂，绕竖直轴做匀速圆周运动，轻绳与竖直方向夹角为 θ。"
        "已知小球质量为 m，重力加速度为 g，忽略空气阻力。求："
        "1. 绳中拉力 T；2. 小球做圆周运动的半径 r；3. 小球线速度 v。"
    ),
    "solution": [
        "受力分析：小球受到重力 mg 和绳的拉力 T。拉力可分解为竖直分量 T cosθ 和水平分量 T sinθ。",
        "竖直方向：小球高度不变，没有竖直加速度，所以 T cosθ = mg，得到 T = mg / cosθ。",
        "圆周半径：绳长为 L，与竖直方向夹角为 θ，所以 r = L sinθ。",
        "水平方向：水平合力提供向心力，T sinθ = m v² / r。",
        "代入 T = mg / cosθ 和 r = L sinθ，得 v² = g L sinθ tanθ，所以 v = √(g L sinθ tanθ)。",
        "物理含义：角度 θ 越大，圆周半径越大，需要的向心力越大，小球速度也越大。",
    ],
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    narration_path = OUT_DIR / "conical-pendulum-narration.txt"
    data_path = OUT_DIR / "conical-pendulum-example.json"
    audio_path = OUT_DIR / "conical-pendulum-narration.mp3"
    silent_path = OUT_DIR / "conical-pendulum.mp4"
    narrated_path = OUT_DIR / "conical-pendulum-narrated.mp4"

    narration_path.write_text(NARRATION, encoding="utf-8")
    _generate_audio(narration_path, audio_path)
    audio_duration = max(18.0, _audio_duration_seconds(audio_path) + 0.8)
    warnings: list[str] = []
    render_engine = _try_render_remotion(audio_path, narrated_path, audio_duration, warnings)
    if render_engine != "remotion":
        _render_silent_video(silent_path, audio_duration)
        _mux_audio(silent_path, audio_path, narrated_path)
        render_engine = "ffmpeg_fallback"

    payload = dict(EXAMPLE)
    payload["video"] = {
        "render_engine": render_engine,
        "duration_seconds": audio_duration,
        "narrated_video": str(narrated_path.relative_to(ROOT_DIR)),
        "silent_video": str(silent_path.relative_to(ROOT_DIR)),
        "warnings": warnings,
        "remotion_skill": "skills/video-remotion/SKILL.md",
        "remotion_composition": "ConicalPendulumVideo",
    }
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"example: {data_path}")
    print(f"silent_video: {silent_path}")
    print(f"narrated_video: {narrated_path}")
    print(f"render_engine: {render_engine}")
    print(f"duration_seconds: {audio_duration:.2f}")


def _generate_audio(text_path: Path, output_path: Path) -> None:
    command = [
        sys.executable,
        str(ROOT_DIR / "skills" / "voice-tts" / "voice_tts.py"),
        str(text_path),
        "--output",
        str(output_path),
        "--fallback-edge-tts",
    ]
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def _try_render_remotion(audio_path: Path, output_path: Path, duration_seconds: float, warnings: list[str]) -> str | None:
    if os.getenv("VIDEO_RENDER_ENGINE", "remotion").lower() not in {"remotion", "auto"}:
        warnings.append("已按配置跳过 Remotion，使用 ffmpeg/Pillow 生成圆锥摆草稿。")
        return None
    renderer_dir = ROOT_DIR / "video-renderer"
    if not renderer_dir.exists():
        warnings.append("未找到 video-renderer，使用 ffmpeg/Pillow 生成圆锥摆草稿。")
        return None
    npx = shutil.which("npx")
    if npx is None:
        warnings.append("未检测到 npx，无法调用 Remotion skill，使用 ffmpeg/Pillow 生成圆锥摆草稿。")
        return None
    if not (renderer_dir / "node_modules").exists():
        warnings.append("video-renderer 依赖未安装，需执行 npm install；本次使用 ffmpeg/Pillow 生成圆锥摆草稿。")
        return None
    glibc_version = _glibc_version()
    min_glibc = os.getenv("VIDEO_RENDER_REMOTION_MIN_GLIBC", "2.31")
    if glibc_version is not None and _version_tuple(glibc_version) < _version_tuple(min_glibc):
        warnings.append(f"当前 glibc {glibc_version} 低于 Remotion 渲染要求 {min_glibc}，使用 ffmpeg/Pillow 生成圆锥摆草稿。")
        return None

    public_job_dir = renderer_dir / "public" / "jobs" / "conical-pendulum"
    public_job_dir.mkdir(parents=True, exist_ok=True)
    public_audio = public_job_dir / audio_path.name
    shutil.copy2(audio_path, public_audio)
    props_path = OUT_DIR / "conical-pendulum-remotion-props.json"
    props_path.write_text(
        json.dumps(
            {
                "title": TITLE,
                "audioSrc": f"jobs/conical-pendulum/{public_audio.name}",
                "durationSeconds": duration_seconds,
                "narration": NARRATION,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    command = [
        npx,
        "remotion",
        "render",
        "src/index.ts",
        "ConicalPendulumVideo",
        str(output_path.resolve()),
        "--props",
        str(props_path.resolve()),
        "--log",
        "error",
    ]
    try:
        subprocess.run(command, cwd=renderer_dir, capture_output=True, text=True, timeout=int(os.getenv("VIDEO_RENDER_REMOTION_TIMEOUT_SECONDS", "600")), check=True)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        warnings.append(f"Remotion skill 渲染失败，使用 ffmpeg/Pillow 生成圆锥摆草稿：{_clean_subprocess_error(exc)}")
        return None
    warnings.append("已使用 Remotion skill 的 ConicalPendulumVideo 渲染 3D 动画、字幕和解说音。")
    return "remotion" if output_path.exists() else None


def _render_silent_video(output_path: Path, duration_seconds: float) -> None:
    ffmpeg = _ffmpeg_exe()
    command = [
        ffmpeg,
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    total_frames = max(1, math.ceil(duration_seconds * FPS))
    with subprocess.Popen(command, stdin=subprocess.PIPE) as process:
        if process.stdin is None:
            raise RuntimeError("ffmpeg stdin is unavailable")
        for frame in range(total_frames):
            image = _draw_frame(frame, total_frames)
            process.stdin.write(image.tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("ffmpeg video render failed")


def _draw_frame(frame: int, total_frames: int) -> Image.Image:
    progress = frame / max(1, total_frames - 1)
    image = Image.new("RGB", (WIDTH, HEIGHT), "#07111f")
    draw = ImageDraw.Draw(image, "RGBA")
    _draw_background(draw)

    title_font = _font(46)
    body_font = _font(27)
    small_font = _font(23)
    draw.text((WIDTH / 2, 64), TITLE, font=title_font, anchor="ma", fill="white")

    center = (WIDTH / 2, 285)
    orbit_center = (WIDTH / 2, 690)
    orbit_rx = 210
    orbit_ry = 72
    angle = progress * math.tau * 5.6
    x = orbit_center[0] + math.cos(angle) * orbit_rx
    z = math.sin(angle)
    y = orbit_center[1] + z * orbit_ry
    scale = 0.86 + (z + 1) * 0.11
    bob_r = int(44 * scale)

    draw.line((center[0], center[1], x, y), fill=(125, 211, 252, 230), width=5)
    draw.ellipse((center[0] - 7, center[1] - 7, center[0] + 7, center[1] + 7), fill=(224, 242, 254, 255))
    draw.ellipse(
        (orbit_center[0] - orbit_rx, orbit_center[1] - orbit_ry, orbit_center[0] + orbit_rx, orbit_center[1] + orbit_ry),
        outline=(147, 197, 253, 140),
        width=5,
    )
    draw.line((orbit_center[0], center[1], orbit_center[0], orbit_center[1] + 155), fill=(226, 232, 240, 80), width=4)

    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse((x - bob_r, y + 42, x + bob_r, y + 42 + bob_r * 0.45), fill=(0, 0, 0, 85))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    image = Image.alpha_composite(image.convert("RGBA"), shadow)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((x - bob_r, y - bob_r, x + bob_r, y + bob_r), fill=(249, 115, 22, 255), outline=(254, 215, 170, 255), width=4)
    draw.ellipse((x - bob_r * 0.45, y - bob_r * 0.55, x - bob_r * 0.05, y - bob_r * 0.15), fill=(254, 240, 138, 160))

    _arrow(draw, (x, y - 8), (center[0], center[1] + 80), "拉力", small_font, "#facc15")
    _arrow(draw, (x + 62, y), (x + 62, y + 142), "重力", small_font, "#f97316")
    _arrow(draw, (x, y + 88), (orbit_center[0], y + 88), "合力指向圆心", small_font, "#22c55e")

    panel_y = 880
    draw.rounded_rectangle((48, panel_y, WIDTH - 48, panel_y + 230), radius=26, fill=(15, 23, 42, 210), outline=(148, 163, 184, 120), width=2)
    lines = ["竖直方向：T cosθ = mg", "水平方向：T sinθ = m v² / r", "半径：r = L sinθ", "结论：v = √(g L sinθ tanθ)"]
    for index, line in enumerate(lines):
        draw.text((76, panel_y + 30 + index * 48), line, font=body_font, fill="white")

    caption = "绳子的拉力和重力的合力，始终指向圆心，提供向心力。"
    draw.rounded_rectangle((46, 1150, WIDTH - 46, 1238), radius=24, fill=(255, 255, 255, 238))
    draw.text((WIDTH / 2, 1194), caption, font=body_font, anchor="mm", fill="#0f172a")
    return image.convert("RGB")


def _draw_background(draw: ImageDraw.ImageDraw) -> None:
    for radius, alpha in [(260, 80), (470, 38), (650, 22)]:
        draw.ellipse((WIDTH / 2 - radius, 110 - radius, WIDTH / 2 + radius, 110 + radius), fill=(59, 130, 246, alpha))
    for y in range(0, HEIGHT, 44):
        alpha = max(8, 30 - y // 80)
        draw.line((0, y, WIDTH, y), fill=(148, 163, 184, alpha), width=1)


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float], label: str, font: ImageFont.ImageFont, color: str) -> None:
    fill = _hex_to_rgba(color, 235)
    draw.line((start[0], start[1], end[0], end[1]), fill=fill, width=5)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    arrow_len = 18
    for delta in (math.pi * 0.82, -math.pi * 0.82):
        point = (end[0] + math.cos(angle + delta) * arrow_len, end[1] + math.sin(angle + delta) * arrow_len)
        draw.line((end[0], end[1], point[0], point[1]), fill=fill, width=5)
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    draw.text((mid[0] + 8, mid[1] - 8), label, font=font, fill="white", stroke_width=2, stroke_fill="#0f172a")


def _mux_audio(video_path: Path, audio_path: Path, output_path: Path) -> None:
    command = [
        _ffmpeg_exe(),
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def _audio_duration_seconds(audio_path: Path) -> float:
    command = [_ffmpeg_exe(), "-i", str(audio_path), "-f", "null", "-"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", completed.stderr)
    if not match:
        return 18.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ModuleNotFoundError:
        return "ffmpeg"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _hex_to_rgba(value: str, alpha: int) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


def _glibc_version() -> str | None:
    libc_name, libc_version = platform.libc_ver()
    if libc_name.lower() != "glibc" or not libc_version:
        return None
    return libc_version


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


def _clean_subprocess_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        output = "\n".join(part for part in [exc.stderr, exc.stdout] if part)
        return output.strip()[-1200:] or str(exc)
    return str(exc)


if __name__ == "__main__":
    main()
