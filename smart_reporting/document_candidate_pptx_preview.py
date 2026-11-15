"""Read-only PowerPoint text candidate preview.

The host supplies authenticated PPTX bytes and proposed literal replacements.
This engine never saves, modifies, or accepts a presentation.
"""
from __future__ import annotations

import hashlib
import io
from collections.abc import Awaitable, Callable
from typing import Any

from pptx import Presentation

from .document_candidate_contract import DocumentCandidateRequest, DocumentScope
from .document_candidate_pptx_targets import validate_pptx_selection


class PptxTextPreviewEngine:
    def __init__(
        self,
        load_source: Callable[[DocumentScope], Awaitable[bytes]],
        propose: Callable[[DocumentCandidateRequest], Awaitable[tuple[dict[str, Any], ...]]],
    ) -> None:
        self._load_source = load_source
        self._propose = propose

    async def prepare(self, request: DocumentCandidateRequest) -> dict[str, Any]:
        validate_pptx_selection(request.selection)
        source = await self._load_source(request.scope)
        if hashlib.sha256(source).hexdigest() != request.scope.source_sha256:
            raise PermissionError("document_source_changed")
        operations = await self._propose(request)
        approved = {(item["slide_id"], item["shape_id"]) for item in request.selection}
        if not operations or len(operations) > 100:
            raise ValueError("pptx_operations_invalid")
        seen: set[tuple[int, int]] = set()
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) != {"slide_id", "shape_id", "text"}:
                raise ValueError("pptx_operation_invalid")
            validate_pptx_selection(({
                "slide_id": operation["slide_id"], "shape_id": operation["shape_id"],
            },))
            key = (operation["slide_id"], operation["shape_id"])
            if key not in approved or key in seen:
                raise ValueError("pptx_operation_target_unapproved")
            seen.add(key)
            text = operation["text"]
            if not isinstance(text, str) or len(text) > 10000 or any(ord(c) < 32 and c not in "\n\t" for c in text):
                raise ValueError("pptx_text_invalid")
        if hashlib.sha256(await self._load_source(request.scope)).hexdigest() != request.scope.source_sha256:
            raise PermissionError("document_source_changed")
        presentation = Presentation(io.BytesIO(source))
        shapes = {
            (slide.slide_id, shape.shape_id): shape
            for slide in presentation.slides for shape in slide.shapes
        }
        changes = []
        for operation in operations:
            key = (operation["slide_id"], operation["shape_id"])
            shape = shapes.get(key)
            if shape is None or not shape.has_text_frame or shape.has_table or shape.has_chart:
                raise ValueError("pptx_preview_target_unsupported")
            changes.append({
                "slide_id": key[0], "shape_id": key[1],
                "before": shape.text, "after": operation["text"],
            })
        return {"status": "preview_ready", "accepted": False, "changes": changes}
