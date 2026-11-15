"""Bounded ports of GenOffice media-protocols/search APIs; no desktop CLI fallback."""

import base64
import binascii
import json
from io import BytesIO
from urllib.parse import quote, urlsplit

from PIL import Image

from .provider_catalog import MEDIA
from .provider_http import ProviderHTTP
from .repository import OfficeError

MAX_MEDIA_BYTES = 20 * 1024 * 1024
MAX_MEDIA_ITEMS = 4


def invalid(message):
    return OfficeError("office_provider_input_invalid", message, 422)


def text(value, maximum=16000):
    return value[:maximum] if isinstance(value, str) else ""


def public_link(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


class ProviderRuntime:
    def __init__(self, http=None):
        self.http = http or ProviderHTTP()

    async def _json(self, method, url, **kwargs):
        raw, _ = await self.http.request(method, url, **kwargs)
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, UnicodeDecodeError):
            raise OfficeError(
                "office_provider_response_invalid", "提供商未返回有效 JSON 对象。", 502
            ) from None

    async def load_media(self, urls):
        if not isinstance(urls, list) or not 1 <= len(urls) <= MAX_MEDIA_ITEMS:
            raise invalid("每次请选择 1–4 个图片或视频文件。")
        media, total = [], 0
        for url in urls:
            if not isinstance(url, str):
                raise invalid("媒体地址无效。")
            if url.startswith("data:"):
                if len(url) > MAX_MEDIA_BYTES * 4 // 3 + 256:
                    raise invalid("媒体总大小不得超过 20 MiB。")
                try:
                    header, encoded = url.split(",", 1)
                    if not header.endswith(";base64"):
                        raise ValueError
                    content = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise invalid("媒体数据编码无效。") from None
            else:
                if len(url) > 4096:
                    raise invalid("媒体地址过长。")
                content, _ = await self.http.request("GET", url, max_bytes=MAX_MEDIA_BYTES - total)
            total += len(content)
            if total > MAX_MEDIA_BYTES:
                raise invalid("媒体总大小不得超过 20 MiB。")
            # Route on actual signatures, never on URL extensions or claimed MIME.
            if len(content) >= 12 and content[4:8] == b"ftyp":
                mime = "video/mp4"
            elif content.startswith(b"\x1aE\xdf\xa3") and b"webm" in content[:4096]:
                mime = "video/webm"
            else:
                try:
                    with Image.open(BytesIO(content)) as image:
                        if image.width * image.height > 25_000_000:
                            raise ValueError
                        mime = {
                            "PNG": "image/png",
                            "JPEG": "image/jpeg",
                            "WEBP": "image/webp",
                            "GIF": "image/gif",
                        }[image.format]
                        image.verify()
                except Exception:
                    raise invalid("仅支持有效 PNG/JPEG/WebP/GIF 图片及 MP4/WebM 视频。") from None
            media.append((mime, base64.b64encode(content).decode()))
        return media

    async def analyze(self, config, key, media, requirements):
        if not isinstance(requirements, str) or not 1 <= len(requirements.strip()) <= 8000:
            raise invalid("分析要求须为 1–8000 字符。")
        meta = MEDIA[config["provider"]]
        if any(m.startswith("video/") for m, _ in media) and not meta["video"]:
            raise invalid("此提供商不支持视频分析。")
        base, model = config["baseUrl"], config["model"]
        if meta["protocol"] == "gemini":
            data = await self._json(
                "POST",
                base + "/models/" + quote(model, safe="") + ":generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"text": requirements},
                                *[
                                    {"inline_data": {"mime_type": mime, "data": encoded}}
                                    for mime, encoded in media
                                ],
                            ],
                        }
                    ],
                    "generationConfig": {"maxOutputTokens": 4096},
                },
            )
            try:
                answer = "".join(
                    text(p.get("text"))
                    for p in data["candidates"][0]["content"]["parts"]
                    if isinstance(p, dict)
                )
            except (KeyError, IndexError, TypeError):
                answer = ""
        else:
            parts = [{"type": "text", "text": requirements}]
            for mime, encoded in media:
                kind = "video_url" if mime.startswith("video/") else "image_url"
                parts.append({"type": kind, kind: {"url": f"data:{mime};base64,{encoded}"}})
            data = await self._json(
                "POST",
                base + "/chat/completions",
                headers={"Authorization": "Bearer " + key},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": parts}],
                },
            )
            try:
                answer = data["choices"][0]["message"]["content"]
                if isinstance(answer, list):
                    answer = "".join(text(p.get("text")) for p in answer if isinstance(p, dict))
            except (KeyError, IndexError, TypeError):
                answer = ""
        if not isinstance(answer, str) or not answer.strip():
            raise OfficeError("office_provider_empty", "提供商未返回分析内容。", 502)
        return {
            "text": text(answer),
            "provider": config["provider"],
            "model": model,
            "external": True,
        }

    async def search(self, config, key, query, limit):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
            raise invalid("搜索词须为 1–2000 字符。")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise invalid("结果数量须为 1–20。")
        provider, base = config["provider"], config["baseUrl"]
        method, path, headers, params = "POST", "/search", {}, None
        if provider == "serper":
            headers, body = {"X-API-KEY": key}, {"q": query, "num": limit}
        elif provider == "tavily":
            body = {"api_key": key, "query": query, "max_results": limit, "include_answer": True}
        elif provider == "exa":
            headers, body = (
                {"x-api-key": key},
                {
                    "query": query,
                    "numResults": limit,
                    "contents": {"text": {"maxCharacters": 2000}},
                },
            )
        elif provider == "parallel":
            path, headers, body = (
                "/v1/search",
                {"x-api-key": key, "parallel-beta": "search-extract-2025-10-10"},
                {"objective": query, "mode": "one-shot"},
            )
        elif provider == "firecrawl":
            path, headers, body = (
                "/v2/search",
                {"Authorization": "Bearer " + key},
                {"query": query, "limit": limit},
            )
        elif provider == "keenable":
            path, headers, body = (
                "/v1/search",
                {"X-API-Key": key, "X-Keenable-Title": "GenOffice"},
                {"query": query, "max_results": limit},
            )
        elif provider == "serply":
            method, path, headers, params, body = (
                "GET",
                "/v1/search",
                {"X-Api-Key": key, "User-Agent": "genoffice"},
                {"q": query},
                None,
            )
        elif provider == "searchapi":
            method, path, params, body = (
                "GET",
                "/api/v1/search",
                {"engine": "google", "q": query},
                None,
            )
        else:
            raise invalid("不支持的搜索提供商。")
        if provider == "searchapi":
            headers = {"Authorization": "Bearer " + key, "User-Agent": "genoffice"}
        data = await self._json(method, base + path, headers=headers, json=body, params=params)
        if provider == "serper":
            raw = data.get("organic", [])
        elif provider in ("searchapi", "serply"):
            raw = data.get("organic_results", data.get("results", []))
        elif provider == "firecrawl":
            nested = data.get("data", {})
            raw = (
                (nested.get("web") or nested.get("news") or []) if isinstance(nested, dict) else []
            )
        else:
            raw = data.get("results", [])
        if not isinstance(raw, list):
            raise OfficeError("office_provider_response_invalid", "搜索结果格式无效。", 502)
        results = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = item.get("url", item.get("link"))
            if not public_link(url):
                continue
            snippet = (
                item.get("snippet")
                or item.get("content")
                or item.get("text")
                or item.get("description")
                or item.get("summary")
            )
            if provider == "parallel":
                snippet = "\n".join(x for x in item.get("excerpts", []) if isinstance(x, str))
            results.append(
                {
                    "title": text(item.get("title"), 500),
                    "url": text(url, 4096),
                    "snippet": text(snippet, 2000),
                }
            )
            if len(results) >= limit:
                break
        if "error" in data or data.get("success") is False:
            raise OfficeError(
                "office_provider_rejected", "搜索提供商返回失败，请检查密钥和配额。", 502
            )
        return {
            "results": results,
            "answer": text(data.get("answer"), 4000),
            "method": provider,
            "external": True,
        }
