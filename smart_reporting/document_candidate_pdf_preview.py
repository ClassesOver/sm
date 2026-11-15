"""Read-only PDF annotation candidate preview using PyMuPDF.

The preview contains page geometry and intersecting text for human review.
It does not write annotations, edit PDF bytes, or accept candidates.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
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
        self._lock = asyncio.Lock()
        self._tasks: dict[str, tuple[DocumentScope, str, dict[str, Any]]] = {}

    async def prepare(self, request: DocumentCandidateRequest) -> str:
        async with self._lock:
            return await self._prepare_locked(request)

    async def _prepare_locked(self, request: DocumentCandidateRequest) -> str:
        validate_pdf_selection(request.selection)
        task_id = hashlib.sha256(json.dumps([
            request.scope.channel, request.scope.grant, request.scope.document_id,
            request.scope.revision, request.scope.source_sha256, request.request_id,
        ]).encode()).hexdigest()
        fingerprint = hashlib.sha256(json.dumps([
            request.instruction, request.selection,
        ], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        existing = self._tasks.get(task_id)
        if existing is not None and (existing[0] != request.scope or existing[1] != fingerprint):
            raise ValueError("document_request_id_conflict")
        source = await self._load_source(request.scope)
        if hashlib.sha256(source).hexdigest() != request.scope.source_sha256:
            raise PermissionError("document_source_changed")
        if existing is not None:
            return task_id
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
                # Selection rectangles use rendered (rotated) page geometry,
                # while PyMuPDF text extraction expects unrotated page space.
                # Derotate the clip to avoid showing unrelated/missing context.
                words = page.get_text("words", clip=rect * page.derotation_matrix)
                changes.append({
                    "page": page_index, "rect": list(item["rect"]),
                    "note": item["note"],
                    "context": " ".join(str(word[4]) for word in words)[:2000],
                })
        # PDF parsing and text extraction may take time; verify the exact
        # source again before publishing a candidate receipt.
        if hashlib.sha256(await self._load_source(request.scope)).hexdigest() != request.scope.source_sha256:
            raise PermissionError("document_source_changed")
        self._tasks[task_id] = (request.scope, fingerprint, {
            "taskId": task_id, "status": "preview_ready",
            "accepted": False, "changes": changes,
        })
        return task_id

    async def status(self, scope: DocumentScope, task_id: str) -> dict[str, Any]:
        entry = self._tasks.get(task_id)
        if entry is None or entry[0] != scope:
            raise PermissionError("document_task_not_accessible")
        source = await self._load_source(scope)
        if hashlib.sha256(source).hexdigest() != scope.source_sha256:
            raise PermissionError("document_source_changed")
        return deepcopy(entry[2])
