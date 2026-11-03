from __future__ import annotations

import base64
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from loguru import logger

from ..reporting.models import ReportingError
from .service import ReportEditorContext, ReportEditorSession

_MAX_PROMPT_CHARS = 1_000
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MAX_IMAGE_CANDIDATES = 8
_CANDIDATE_TTL = timedelta(minutes=20)
_DASHSCOPE_IMAGE_HOSTS = {"dashscope.aliyuncs.com", "token-plan.cn-beijing.maas.aliyuncs.com"}
_PUBLIC_PROVIDER_CODES = {
    "InvalidParameter", "InvalidApiKey", "AccessDenied", "ModelNotFound",
    "Throttling", "Throttling.RateQuota", "Throttling.AllocationQuota",
    "Arrearage", "DataInspectionFailed", "InternalError", "ServiceUnavailable",
}


@dataclass
class _ImageCandidate:
    candidate_id: str
    report_id: str
    revision: int
    user_id: str
    context_sha256: str
    created_at: datetime
    content: bytes
    media_type: str
    extension: str


class ReportSlidesImageService:
    """Generate identity-bound image assets for explicit insertion into a slide."""

    def __init__(
        self,
        slides: Any,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 120,
    ) -> None:
        self.slides = slides
        self.api_key = api_key.strip() if isinstance(api_key, str) else ""
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.client = client
        self.timeout_seconds = timeout_seconds
        self._candidates: dict[str, _ImageCandidate] = {}

    async def generate_candidate(
        self, session: ReportEditorSession, prompt: str
    ) -> dict[str, str]:
        context = await self.slides.context_for_session(session)
        normalized = prompt.strip() if isinstance(prompt, str) else ""
        if not normalized:
            raise ReportingError("report_slides_image_prompt_required", "请描述需要生成的配图。")
        if len(normalized) > _MAX_PROMPT_CHARS:
            raise ReportingError("report_slides_image_prompt_too_large", "配图要求过长，请缩短后重试。")
        if not self.api_key or not self.model or not self.base_url:
            raise ReportingError("report_slides_image_unavailable", "AI 配图服务尚未配置。")
        try:
            content, media_type, extension = await self._generate_image(normalized)
        except Exception as error:  # noqa: BLE001 - image failures leave the PPTX untouched
            reason = _image_failure_reason(error)
            logger.warning(
                "report_slides_image_failed report_id={} revision={} error_type={} reason={}",
                context.report_id,
                context.revision,
                type(error).__name__,
                reason,
            )
            raise ReportingError(
                "report_slides_image_failed", f"AI 配图生成失败：{reason}，当前幻灯片未改变。"
            ) from None

        self._prune_candidates()
        candidate_id = uuid4().hex
        self._candidates[candidate_id] = _ImageCandidate(
            candidate_id=candidate_id,
            report_id=context.report_id,
            revision=context.revision,
            user_id=context.scope["userId"],
            context_sha256=context.digest(),
            created_at=datetime.now(UTC),
            content=content,
            media_type=media_type,
            extension=extension,
        )
        return {
            "candidateId": candidate_id,
            "mediaType": media_type,
            "previewDataUrl": f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}",
        }

    async def resolve_for_session(
        self, session: ReportEditorSession, edits: Any
    ) -> list[dict[str, Any]]:
        context: ReportEditorContext = await self.slides.context_for_session(session)
        if not isinstance(edits, list) or len(edits) > _MAX_IMAGE_CANDIDATES:
            raise ReportingError("report_slides_image_edit_invalid", "配图候选数量无效。")
        if not edits:
            return []
        deck = await self.slides.deck_for_session(session)
        size = deck.get("size")
        slides = deck.get("slides")
        if not isinstance(size, dict) or not isinstance(slides, list):
            raise ReportingError("report_slides_image_edit_invalid", "幻灯片尺寸无法读取。")
        width = float(size["cx"]) / 9525
        height = float(size["cy"]) / 9525
        slide_indices = {slide.get("slideIndex") for slide in slides if isinstance(slide, dict)}
        result: list[dict[str, Any]] = []
        used: set[str] = set()
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {"candidateId", "slideIndex", "geometry"}:
                raise ReportingError("report_slides_image_edit_invalid", "配图候选无效。")
            candidate_id = edit["candidateId"]
            slide_index = edit["slideIndex"]
            geometry = edit["geometry"]
            if (
                not isinstance(candidate_id, str)
                or candidate_id in used
                or not isinstance(slide_index, int)
                or isinstance(slide_index, bool)
                or slide_index not in slide_indices
                or not isinstance(geometry, dict)
                or set(geometry) != {"x", "y", "width", "height"}
                or any(
                    not isinstance(geometry[key], (int, float))
                    or isinstance(geometry[key], bool)
                    or not math.isfinite(float(geometry[key]))
                    for key in ("x", "y", "width", "height")
                )
            ):
                raise ReportingError("report_slides_image_edit_invalid", "配图候选或页面信息无效。")
            x, y, w, h = (float(geometry[key]) for key in ("x", "y", "width", "height"))
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
                raise ReportingError("report_slides_image_geometry_invalid", "配图位置或大小无效。")
            candidate = self._authorized_candidate(context, candidate_id)
            used.add(candidate_id)
            result.append({
                "candidateId": candidate_id,
                "slideIndex": slide_index,
                "geometry": {key: round(float(geometry[key]), 2) for key in ("x", "y", "width", "height")},
                "bytes": candidate.content,
                "extension": candidate.extension,
                "mediaType": candidate.media_type,
            })
        return result

    async def discard_candidates(
        self, session: ReportEditorSession, candidate_ids: list[str]
    ) -> None:
        context: ReportEditorContext = await self.slides.context_for_session(session)
        for candidate_id in candidate_ids:
            self._authorized_candidate(context, candidate_id)
        for candidate_id in candidate_ids:
            self._candidates.pop(candidate_id, None)

    def _authorized_candidate(self, context: ReportEditorContext, candidate_id: str) -> _ImageCandidate:
        candidate = self._candidates.get(candidate_id)
        if (
            candidate is None
            or candidate.report_id != context.report_id
            or candidate.revision != context.revision
            or candidate.user_id != context.scope["userId"]
            or not secrets.compare_digest(candidate.context_sha256, context.digest())
        ):
            raise ReportingError("report_slides_image_candidate_expired", "图片候选已失效，请重新生成。")
        return candidate

    async def _generate_image(self, prompt: str) -> tuple[bytes, str, str]:
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False)
        try:
            base = urlsplit(self.base_url)
            native = base.hostname in _DASHSCOPE_IMAGE_HOSTS
            endpoint = (
                base._replace(path="/api/v1/services/aigc/multimodal-generation/generation", query="", fragment="").geturl()
                if native else f"{self.base_url}/images/generations"
            )
            payload = (
                {
                    "model": self.model,
                    "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
                    "parameters": {"size": "1024*1024", "n": 1},
                }
                if native else
                {"model": self.model, "prompt": prompt, "n": 1, "size": "1024*1024", "response_format": "url"}
            )
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            if native:
                choices = body.get("output", {}).get("choices", [])
                content = choices[0].get("message", {}).get("content", []) if choices else []
                image_url = next((item["image"] for item in content if isinstance(item, dict) and "image" in item), None)
            else:
                data = body.get("data")
                image_url = data[0].get("url") if isinstance(data, list) and data and isinstance(data[0], dict) else None
            parsed = urlsplit(image_url) if isinstance(image_url, str) else None
            if (
                parsed is None
                or parsed.scheme != "https"
                or not parsed.hostname
                or not parsed.hostname.endswith(".aliyuncs.com")
            ):
                raise ValueError("image_url_untrusted")
            async with client.stream("GET", image_url, timeout=self.timeout_seconds) as image_response:
                image_response.raise_for_status()
                length = image_response.headers.get("content-length")
                if length and int(length) > _MAX_IMAGE_BYTES:
                    raise ValueError("image_too_large")
                content = bytearray()
                async for chunk in image_response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_IMAGE_BYTES:
                        raise ValueError("image_too_large")
                media_type, extension = _image_type(bytes(content), image_response.headers.get("content-type", ""))
                return bytes(content), media_type, extension
        finally:
            if own_client:
                await client.aclose()

    def _prune_candidates(self) -> None:
        cutoff = datetime.now(UTC) - _CANDIDATE_TTL
        for candidate_id, candidate in tuple(self._candidates.items()):
            if candidate.created_at < cutoff:
                self._candidates.pop(candidate_id, None)


def _image_failure_reason(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        reason = f"图片服务返回 HTTP {error.response.status_code}"
        try:
            body = error.response.json()
        except (ValueError, httpx.ResponseNotRead):
            body = {}
        code = body.get("code") if isinstance(body, dict) else None
        if isinstance(code, str) and code in _PUBLIC_PROVIDER_CODES:
            reason += f"（{code}）"
        return reason
    if isinstance(error, httpx.TimeoutException):
        return "图片服务请求超时"
    if isinstance(error, httpx.RequestError):
        return "图片服务连接失败"
    return "图片服务未返回可用的图片"


def _image_type(content: bytes, declared_type: str) -> tuple[str, str]:
    if content.startswith(b"\x89PNG\r\n\x1a\n") and declared_type.lower().split(";", 1)[0] in {"image/png", "application/octet-stream"}:
        return "image/png", "png"
    if content.startswith(b"\xff\xd8\xff") and declared_type.lower().split(";", 1)[0] in {"image/jpeg", "image/jpg", "application/octet-stream"}:
        return "image/jpeg", "jpg"
    raise ValueError("image_type_unsupported")
