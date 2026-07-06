"""Generate narration audio with Volcengine TTS.

When --fallback-edge-tts is passed and Volcengine credentials are missing, this
script uses edge-tts for local preview audio.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ENDPOINT = "https://openspeech.bytedance.com/api/v1/tts"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate voiceover audio.")
    parser.add_argument("text_file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fallback-edge-tts", action="store_true")
    args = parser.parse_args()

    text = args.text_file.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit("text file is empty")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if _has_volcengine_config():
        _volcengine_tts(text, args.output)
        print(args.output)
        return

    if args.fallback_edge_tts:
        asyncio.run(_edge_tts(text, args.output))
        print(args.output)
        return

    raise SystemExit(
        "missing Volcengine TTS config. Set VOLCENGINE_TTS_APP_ID and "
        "VOLCENGINE_TTS_ACCESS_TOKEN, or pass --fallback-edge-tts for preview audio."
    )


def _has_volcengine_config() -> bool:
    return bool(os.getenv("VOLCENGINE_TTS_APP_ID") and os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN"))


def _volcengine_tts(text: str, output_path: Path) -> None:
    app_id = os.environ["VOLCENGINE_TTS_APP_ID"]
    token = os.environ["VOLCENGINE_TTS_ACCESS_TOKEN"]
    endpoint = os.getenv("VOLCENGINE_TTS_ENDPOINT", DEFAULT_ENDPOINT)
    payload = {
        "app": {
            "appid": app_id,
            "token": token,
            "cluster": os.getenv("VOLCENGINE_TTS_CLUSTER", "volcano_tts"),
        },
        "user": {"uid": os.getenv("VOLCENGINE_TTS_UID", "langgraph-study")},
        "audio": {
            "voice_type": os.getenv("VOLCENGINE_TTS_VOICE_TYPE", "BV001_streaming"),
            "encoding": os.getenv("VOLCENGINE_TTS_ENCODING", "mp3"),
            "speed_ratio": float(os.getenv("VOLCENGINE_TTS_SPEED_RATIO", "1.0")),
        },
        "request": {
            "reqid": str(uuid.uuid4()),
            "text": text,
            "operation": "query",
        },
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer;{token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Volcengine TTS HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"Volcengine TTS request failed: {exc.reason}") from exc

    if result.get("code") not in {0, "0", None} and not result.get("data"):
        raise SystemExit(f"Volcengine TTS error: {json.dumps(result, ensure_ascii=False)}")
    audio_base64 = result.get("data")
    if not audio_base64:
        raise SystemExit(f"Volcengine TTS response missing audio data: {json.dumps(result, ensure_ascii=False)[:1000]}")
    output_path.write_bytes(base64.b64decode(audio_base64))


async def _edge_tts(text: str, output_path: Path) -> None:
    try:
        import edge_tts
    except ModuleNotFoundError as exc:
        raise SystemExit("edge-tts is not installed. Install video extras or configure Volcengine TTS.") from exc
    voice = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))


if __name__ == "__main__":
    main()
