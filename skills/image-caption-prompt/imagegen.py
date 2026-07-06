#!/usr/bin/env python3
"""
Qwen / DashScope image generator.

只调用千问/通义万相 DashScope 图片生成接口。

Usage:
    python3 imagegen.py "提示词"
    python3 imagegen.py "公众号封面图，AI Agent 工作流，干净科技风" --size 1024x1024
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def find_project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = find_project_root()
DEFAULT_OUTPUT_DIR = Path("~/Downloads/QwenImages").expanduser()

DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_IMAGE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")
IMAGE_CREATE_PATH = os.getenv("DASHSCOPE_IMAGE_CREATE_PATH", "/services/aigc/text2image/image-synthesis")
IMAGE_EDIT_PATH = os.getenv("DASHSCOPE_IMAGE_EDIT_PATH", "/services/aigc/multimodal-generation/generation")
TASK_QUERY_PATH = os.getenv("DASHSCOPE_TASK_QUERY_PATH", "/tasks/{task_id}")
DEFAULT_MODEL = os.getenv("DASHSCOPE_IMAGE_MODEL", "wan2.2-t2i-flash")
DEFAULT_EDIT_MODEL = os.getenv("DASHSCOPE_IMAGE_EDIT_MODEL", "wan2.7-image")

POLL_INTERVAL_SECONDS = float(os.getenv("DASHSCOPE_IMAGE_POLL_INTERVAL_SECONDS", "3"))
POLL_TIMEOUT_SECONDS = int(os.getenv("DASHSCOPE_IMAGE_POLL_TIMEOUT_SECONDS", "180"))

ALLOWED_SIZES = {
    "1024x1024",
    "1024x1536",
    "1536x1024",
    "1792x1024",
    "1024x1792",
    "1440x1440",
    "1440x810",
    "810x1440",
}


def load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_api_key(cli_api_key: str | None) -> str:
    api_key = (
        cli_api_key
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("QWEN_API_KEY")
        or ""
    ).strip()
    if not api_key:
        raise ValueError("缺少 API Key。请传入 --api-key，或在 .env 中配置 QWEN_API_KEY / DASHSCOPE_API_KEY。")
    return api_key


def endpoint(path: str) -> str:
    return urljoin(f"{DASHSCOPE_BASE_URL.rstrip('/')}/", path.lstrip("/"))


def headers(api_key: str, async_call: bool = False) -> dict[str, str]:
    result = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if async_call:
        result["X-DashScope-Async"] = "enable"
    return result


def validate_args(args: argparse.Namespace) -> None:
    prompt = args.prompt.strip()
    if not prompt:
        raise ValueError("提示词不能为空。")
    if len(prompt) > 500:
        raise ValueError("提示词不能超过 500 字。")
    if args.size not in ALLOWED_SIZES:
        allowed = ", ".join(sorted(ALLOWED_SIZES))
        raise ValueError(f"不支持的尺寸：{args.size}。可用尺寸：{allowed}")
    if not 1 <= args.count <= 4:
        raise ValueError("--count 建议设置为 1-4。")


def dashscope_size(size: str) -> str:
    return size.replace("x", "*")


def create_task(args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    payload = {
        "model": args.model,
        "input": {
            "prompt": args.prompt.strip(),
        },
        "parameters": {
            "size": dashscope_size(args.size),
            "n": args.count,
            "prompt_extend": args.prompt_extend,
            "watermark": args.watermark,
        },
    }
    if args.negative_prompt:
        payload["parameters"]["negative_prompt"] = args.negative_prompt

    return request_json(
        endpoint(IMAGE_CREATE_PATH),
        method="POST",
        api_key=api_key,
        payload=payload,
        timeout=60,
        async_call=True,
    )


def create_edit(args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    payload = {
        "model": args.edit_model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": args.reference_image},
                        {"text": args.prompt.strip()},
                    ],
                }
            ]
        },
        "parameters": {
            "size": dashscope_size(args.size),
            "n": args.count,
            "watermark": args.watermark,
        },
    }
    return request_json(
        endpoint(IMAGE_EDIT_PATH),
        method="POST",
        api_key=api_key,
        payload=payload,
        timeout=180,
    )


def query_task(task_id: str, api_key: str) -> dict[str, Any]:
    path = TASK_QUERY_PATH.format(task_id=task_id)
    return request_json(endpoint(path), method="GET", api_key=api_key, timeout=30)


def request_json(
    url: str,
    *,
    method: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    timeout: int,
    async_call: bool = False,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers=headers(api_key, async_call=async_call), method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = response.status
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DashScope API 错误 HTTP {exc.code}: {detail[:1000]}") from exc
    except URLError as exc:
        raise RuntimeError(f"DashScope 请求失败：{exc}") from exc
    return parse_json_response(body, status_code=status_code)


def parse_json_response(body: str, *, status_code: int) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DashScope 返回了非 JSON 响应：HTTP {status_code}") from exc

    if status_code >= 400:
        raise RuntimeError(f"DashScope API 错误 HTTP {status_code}: {json.dumps(payload, ensure_ascii=False)}")
    if not isinstance(payload, dict):
        raise RuntimeError("DashScope 返回结构不是 JSON 对象。")
    return payload


def extract_task_id(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    if isinstance(output, dict):
        task_id = output.get("task_id") or output.get("taskId")
        if isinstance(task_id, str) and task_id:
            return task_id
    task_id = payload.get("task_id") or payload.get("taskId")
    if isinstance(task_id, str) and task_id:
        return task_id
    raise RuntimeError(f"DashScope 响应中没有 task_id：{json.dumps(payload, ensure_ascii=False)}")


def task_status(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    if isinstance(output, dict):
        return str(output.get("task_status") or output.get("status") or "").upper()
    return str(payload.get("task_status") or payload.get("status") or "").upper()


def extract_results(payload: dict[str, Any]) -> list[dict[str, str]]:
    output = payload.get("output")
    if not isinstance(output, dict):
        return []
    results = output.get("results")
    if not isinstance(results, list):
        return []

    images: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        b64_json = item.get("b64_json") or item.get("base64")
        if isinstance(url, str) and url:
            images.append({"url": url})
        elif isinstance(b64_json, str) and b64_json:
            images.append({"b64_json": b64_json})
    return images


def extract_images_recursive(payload: Any) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            image_value = value.get("url") or value.get("image")
            b64_json = value.get("b64_json") or value.get("base64")
            if isinstance(image_value, str) and image_value.startswith(("http://", "https://")):
                images.append({"url": image_value})
            elif isinstance(b64_json, str) and b64_json:
                images.append({"b64_json": b64_json})
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for image in images:
        key = image.get("url") or image.get("b64_json") or ""
        if key and key not in seen:
            seen.add(key)
            deduped.append(image)
    return deduped


def wait_for_task(task_id: str, api_key: str) -> dict[str, Any]:
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = query_task(task_id, api_key)
        status = task_status(latest)
        if status == "SUCCEEDED":
            return latest
        if status in {"FAILED", "CANCELED", "UNKNOWN"}:
            raise RuntimeError(f"图片生成任务失败：{json.dumps(latest, ensure_ascii=False)}")
        print(f"[imagegen] task={task_id} status={status or 'PENDING'}，等待中...", file=sys.stderr)
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"图片生成任务 {task_id} 超过 {POLL_TIMEOUT_SECONDS}s 仍未完成。")


def save_images(images: list[dict[str, str]], output_dir: Path, prefix: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    timestamp = int(time.time())
    for index, image in enumerate(images, start=1):
        path = output_dir / f"{prefix}_{timestamp}_{index}.png"
        if "url" in image:
            path.write_bytes(request_bytes(image["url"], timeout=90))
        else:
            path.write_bytes(base64.b64decode(image["b64_json"]))
        saved.append(path)
    return saved


def request_bytes(url: str, *, timeout: int) -> bytes:
    request = Request(url, headers={"Accept": "image/*"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(f"图片下载失败 HTTP {exc.code}: {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"图片下载失败：{exc}") from exc


def run(args: argparse.Namespace) -> int:
    load_dotenv()
    validate_args(args)
    api_key = get_api_key(args.api_key)

    if args.reference_image:
        result = create_edit(args, api_key)
        print(json.dumps({"edit_response": result}, ensure_ascii=False, indent=2))
        if args.no_download:
            return 0
        images = extract_images_recursive(result)
        if not images:
            raise RuntimeError("图片编辑完成，但未找到图片 URL 或 base64 结果。")
        saved = save_images(images, Path(args.output_dir).expanduser(), args.prefix)
        for path in saved:
            print(path)
        return 0

    created = create_task(args, api_key)
    task_id = extract_task_id(created)
    print(json.dumps({"task_id": task_id, "create_response": created}, ensure_ascii=False, indent=2))

    if args.no_download:
        return 0

    result = wait_for_task(task_id, api_key)
    images = extract_results(result)
    if not images:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise RuntimeError("任务完成，但未找到图片 URL 或 base64 结果。")

    saved = save_images(images, Path(args.output_dir).expanduser(), args.prefix)
    for path in saved:
        print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate images with Qwen / DashScope Wan text-to-image models.")
    parser.add_argument("prompt", help="图片提示词，最多 500 字。")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"DashScope 图片模型，默认 {DEFAULT_MODEL}。")
    parser.add_argument("--edit-model", default=DEFAULT_EDIT_MODEL, help=f"DashScope 图片编辑模型，默认 {DEFAULT_EDIT_MODEL}。")
    parser.add_argument("--reference-image", default="", help="可选：原文图片 URL。传入后使用图片编辑模型做换风格重绘。")
    parser.add_argument("--size", default="1024x1024", choices=sorted(ALLOWED_SIZES))
    parser.add_argument("-n", "--count", type=int, default=1, help="生成数量，建议 1-4。")
    parser.add_argument("--negative-prompt", default="", help="反向提示词。")
    parser.add_argument("--no-prompt-extend", dest="prompt_extend", action="store_false", help="关闭提示词智能扩写。")
    parser.set_defaults(prompt_extend=True)
    parser.add_argument("--watermark", action="store_true", help="开启水印。")
    parser.add_argument("-o", "--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--prefix", default="qwen_image")
    parser.add_argument("--no-download", action="store_true", help="只提交任务并打印 task_id，不等待下载。")
    parser.add_argument("--api-key", help="DashScope API Key。默认读取 DASHSCOPE_API_KEY 或 QWEN_API_KEY。")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as exc:
        print(f"[imagegen] error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
