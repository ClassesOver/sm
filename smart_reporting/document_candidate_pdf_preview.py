"""Read-only PDF annotation candidate preview using PyMuPDF.

The preview contains page geometry and intersecting text for human review.
It does not write annotations, edit PDF bytes, or accept candidates.
"""
from __future__ import annotations

import hashlib
import io
from collections.abc import Awaitable, Callable
from typing import Any

import fitz

from .document_candidate_contract import DocumentCandidateRequest, DocumentScope
from .document_candidate_pdf_targets import validate_pdf_selection


class PdfAnnotationPreviewEngine:
    def __init__(
        self,
        load_source: Callable[[DocumentScope], Awaitable[bytes]],
        propose: Callable[[DocumentCandidateRequest], Awaitable[tuple[dict[str, Any], ...]]],
    ) -> None:
        self._load_source = load_source
        self._propose = propose

    async def prepare(self, request: DocumentCandidateRequest) -> dict[str, Any]:
        validate_pdf_selection(request.selection)
        source = await self._load_source(request.scope)
        if hashlib.sha256(source).hexdigest() != request.scope.source_sha256:
            raise PermissionError("document_source_changed")
        proposals = await self._propose(request)
        if not proposals or len(proposals) > 100:
            raise ValueError("pdf_annotations_invalid")
        allowed = {
            (target["page"], tuple(target["rect"])) for target in request.selection
        }
        seen: set[tuple[int, tuple[float, ...]]] = set()
        for item in proposals:
            if not isinstance(item, dict) or set(item) != {"page", "rect", "note"}:
                raise ValueError("pdf_annotation_invalid")
            validate_pdf_selection(({"page": item["page"], "rect": item["rect"]},))
            key = (item["page"], tuple(item["rect"]))
            if key not in allowed or key in seen:
                raise ValueError("pdf_annotation_target_unapproved")
            seen.add(key)
            note = item["note"]
            if not isinstance(note, str) or not note.strip() or len(note) > 2000:
                raise ValueError("pdf_annotation_note_invalid")
        if hashlib.sha256(await self._load_source(request.scope)).hexdigest() != request.scope.source_sha256:
            raise PermissionError("document_source_changed")
        changes = []
        with fitz.open(stream=source, filetype="pdf") as document:
            if document.needs_pass:
                raise ValueError("pdf_password_required")
            for item in proposals:
                page_index = item["page"]
                if page_index >= len(document):
                    raise ValueError("pdf_page_out_of_bounds")
                page = document[page_index]
                x0, y0, x1, y1 = item["rect"]
                bounds = page.rect
                rect = fitz.Rect(
                    bounds.x0 + x0 * bounds.width, bounds.y0 + y0 * bounds.height,
                    bounds.x0 + x1 * bounds.width, bounds.y0 + y1 * bounds.height,
                )
                words = page.get_text("words", clip=rect)
                changes.append({
                    "page": page_index, "rect": list(item["rect"]),
                    "note": item["note"],
                    "context": " ".join(str(word[4]) for word in words)[:2000],
                })
        return {"status": "preview_ready", "accepted": False, "changes": changes}
