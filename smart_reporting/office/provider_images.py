"""Pinned GenOffice text-to-image protocols; only validated PNG/JPEG bytes leave this adapter."""

import base64
import binascii
from io import BytesIO
from urllib.parse import quote

from PIL import Image

from .repository import OfficeError

MAX_IMAGE_BYTES = 6 * 1024 * 1024


def validate_image(content):
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise OfficeError("office_image_size_invalid", "生成图片为空或超过 6 MiB。", 502)
    try:
        with Image.open(BytesIO(content)) as image:
            if image.width * image.height > 25_000_000 or image.format not in ("PNG", "JPEG"):
                raise ValueError
            mime, extension = (
                ("image/png", "png") if image.format == "PNG" else ("image/jpeg", "jpg")
            )
            image.verify()
    except Exception:
        raise OfficeError("office_image_invalid", "提供商未返回有效 PNG/JPEG 图片。", 502) from None
    return content, mime, extension


async def generate_image(runtime, value, key, prompt):
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 1000:
        raise OfficeError("office_image_prompt_invalid", "生图要求须为 1–1000 字符。", 422)
    provider, base, model = value["provider"], value["baseUrl"], value["model"]
    headers = {"Authorization": "Bearer " + key}
    if provider == "gemini":
        endpoint = base + "/models/" + quote(model, safe="") + ":generateContent"
        headers = {"x-goog-api-key": key}
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
    elif provider == "qwen":
        for suffix in ("/compatible-mode/v1", "/api/v1"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        endpoint = base + "/api/v1/services/aigc/multimodal-generation/generation"
        body = {
            "model": model,
            "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
            "parameters": {"n": 1, "watermark": False},
        }
    else:
        endpoint = base + "/images/generations"
        body = {"model": model, "prompt": prompt, "n": 1}
        if provider in ("doubao", "xai"):
            body["response_format"] = "b64_json"
        if provider == "doubao":
            body.update(size="2K", watermark=False)
    data = await runtime._json(
        "POST", endpoint, headers=headers, json=body, max_bytes=9 * 1024 * 1024, timeout_seconds=600
    )
    encoded = url = None
    try:
        if provider == "gemini":
            for part in data["candidates"][0]["content"]["parts"]:
                inline = part.get("inlineData", part.get("inline_data", {}))
                if inline.get("data"):
                    encoded = inline["data"]
                    break
        elif provider == "qwen":
            if data.get("code"):
                raise ValueError
            url = next(
                item["image"]
                for item in data["output"]["choices"][0]["message"]["content"]
                if item.get("image")
            )
        else:
            item = data["data"][0]
            encoded = item.get("b64_json")
            url = item.get("url")
    except (KeyError, IndexError, TypeError, AttributeError, ValueError, StopIteration):
        raise OfficeError("office_image_response_invalid", "提供商未返回可用图片。", 502) from None
    if isinstance(encoded, str) and encoded:
        if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 8:
            raise OfficeError("office_image_size_invalid", "生成图片超过 6 MiB。", 502)
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise OfficeError("office_image_response_invalid", "图片编码无效。", 502) from None
    elif isinstance(url, str) and len(url) <= 4096:
        # Never reuse provider authorization headers when fetching the returned asset URL.
        content, _ = await runtime.http.request("GET", url, max_bytes=MAX_IMAGE_BYTES)
    else:
        raise OfficeError("office_image_response_invalid", "提供商未返回可用图片。", 502)
    return validate_image(content)
