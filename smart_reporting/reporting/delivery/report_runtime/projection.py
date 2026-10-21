"""Versioned identity for the actual Markdown consumed by PDF and Word.

This receipt authenticates a deterministic rendering projection when recomputed
against current inputs. It is not an assertion proof or an assertion signature.
The frozen source Markdown and its projected presentation always keep separate
identities, even when a summary or amount formatter copies an existing value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .markdown import (
    _normalize_cjk_strong_markers,
    align_numeric_table_columns,
    collapse_repeated_values,
    compact_single_column_tables,
    insert_executive_summary,
    readable_large_amounts,
    relocate_server_tables,
)
from .pdf import _pdf_markdown

PROJECTION_VERSION = "report-markdown/1"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True)
class ProjectionStage:
    name: str
    source_sha256: str
    markdown_sha256: str

    def receipt(self) -> dict[str, str]:
        return {
            "name": self.name,
            "sourceSha256": self.source_sha256,
            "markdownSha256": self.markdown_sha256,
        }


@dataclass(frozen=True)
class RenderProjection:
    markdown: str
    _citation_presentations_json: bytes
    _trace_source_render_json: bytes
    source_sha256: str
    source_size: int
    normalized_source_sha256: str
    context_sha256: str
    stages: tuple[ProjectionStage, ...]

    @property
    def citation_presentations(self) -> list[dict[str, Any]]:
        return json.loads(self._citation_presentations_json)

    @property
    def trace_source_render(self) -> dict[str, Any]:
        return json.loads(self._trace_source_render_json)

    @property
    def receipt(self) -> dict[str, Any]:
        # Return a fresh JSON value: consumer annotations cannot mutate identity.
        value = {
            "version": PROJECTION_VERSION,
            "scope": "render_markdown",
            "sourceSha256": self.source_sha256,
            "sourceSize": self.source_size,
            "normalizedSourceSha256": self.normalized_source_sha256,
            "contextSha256": self.context_sha256,
            "markdownSha256": _sha256(self.markdown.encode("utf-8")),
            "presentationSha256": _sha256(
                _json(
                    {
                        "citations": self.citation_presentations,
                        "traceSources": self.trace_source_render,
                    }
                )
            ),
            "stages": [stage.receipt() for stage in self.stages],
            # Source assertion support cannot be inherited by a changed sentence.
            "semanticSupportReused": False,
        }
        return {**value, "projectionSha256": _sha256(_json(value))}


def build_render_projection(
    source: bytes | str,
    sections: Sequence[Mapping[str, Any]],
    *,
    citation_presentations: Any = None,
    include_sources: bool = False,
    trace_sources: Any = None,
) -> RenderProjection:
    """Run the complete text pipeline once, for both output formats.

    Bytes preserve the real frozen file identity. Universal-newline conversion
    matches the previous ``Path.read_text`` behavior without confusing raw-byte
    identity with normalized source text. Caller-supplied strings identify their
    exact UTF-8 bytes; disk consumers should pass bytes.
    """
    raw = source.encode("utf-8") if isinstance(source, str) else source
    markdown = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    normalized_hash = _sha256(markdown.encode("utf-8"))
    # Snapshot inputs so an appendix normalizer cannot mutate caller state or
    # change the meaning of contextSha256 after the receipt is created.
    context_raw = _json(
        {
            "sections": sections,
            "citationPresentations": citation_presentations,
            "includeSources": include_sources,
            "traceSources": trace_sources,
        }
    )
    context = json.loads(context_raw)
    stages: list[ProjectionStage] = []

    def apply(name: str, transform: Callable[[str], str]) -> None:
        nonlocal markdown
        before = _sha256(markdown.encode("utf-8"))
        markdown = transform(markdown)
        stages.append(ProjectionStage(name, before, _sha256(markdown.encode("utf-8"))))

    apply("relocate_server_tables/1", relocate_server_tables)
    apply("compact_single_column_tables/1", compact_single_column_tables)
    apply(
        "insert_executive_summary/1",
        lambda text: insert_executive_summary(text, context["sections"]),
    )
    apply("collapse_repeated_values/1", collapse_repeated_values)
    apply("readable_large_amounts/1", readable_large_amounts)
    apply("align_numeric_table_columns/1", align_numeric_table_columns)
    before = _sha256(markdown.encode("utf-8"))
    markdown, citations, trace = _pdf_markdown(
        markdown,
        context["citationPresentations"],
        include_sources=context["includeSources"],
        trace_sources=context["traceSources"],
    )
    stages.append(
        ProjectionStage("source_presentations/1", before, _sha256(markdown.encode("utf-8")))
    )
    apply("normalize_cjk_strong_markers/1", _normalize_cjk_strong_markers)
    return RenderProjection(
        markdown=markdown,
        _citation_presentations_json=_json(citations),
        _trace_source_render_json=_json(trace),
        source_sha256=_sha256(raw),
        source_size=len(raw),
        normalized_source_sha256=normalized_hash,
        context_sha256=_sha256(context_raw),
        stages=tuple(stages),
    )


def verify_render_projection(
    receipt: Any,
    source: bytes | str,
    sections: Sequence[Mapping[str, Any]],
    *,
    citation_presentations: Any = None,
    include_sources: bool = False,
    trace_sources: Any = None,
) -> dict[str, str]:
    """Return a soft, bounded result; missing/legacy/invalid receipts never pass."""
    if not isinstance(receipt, Mapping):
        return {"status": "unknown", "scope": "render_markdown", "reason": "projection_unavailable"}
    if receipt.get("version") != PROJECTION_VERSION:
        return {
            "status": "unknown",
            "scope": "render_markdown",
            "reason": "projection_rule_unavailable",
        }
    try:
        current = build_render_projection(
            source,
            sections,
            citation_presentations=citation_presentations,
            include_sources=include_sources,
            trace_sources=trace_sources,
        ).receipt
        if receipt == current:
            return {
                "status": "verified",
                "scope": "render_markdown",
                "reason": "projection_recomputed",
            }
        reason = (
            "projection_source_changed"
            if receipt.get("sourceSha256") != current["sourceSha256"]
            else "projection_context_changed"
            if receipt.get("contextSha256") != current["contextSha256"]
            else "projection_receipt_changed"
        )
    except Exception:
        reason = "projection_check_failed"
    return {"status": "unknown", "scope": "render_markdown", "reason": reason}
