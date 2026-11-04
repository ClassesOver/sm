from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pptx import Presentation

from ..contract import SHA256_PATTERN
from .office_engine import last_json_line, run_bridge

PptxTheme = Literal["executive", "clinical", "modern"]


@dataclass(frozen=True)
class PptxBuildResult:
    path: str
    size: int
    sha256: str
    slide_count: int
    issues: tuple[dict[str, object], ...]


def build_editable_pptx(
    *,
    output_path: Path,
    title: str,
    period: str,
    theme: PptxTheme,
    slides: tuple[dict[str, object], ...],
) -> PptxBuildResult:
    if theme not in {"executive", "clinical", "modern"}:
        raise ValueError("pptx_theme_invalid")
    if not title.strip() or not slides:
        raise ValueError("pptx_content_invalid")
    normalized = []
    for slide in slides:
        slide_title = slide.get("title")
        bullets = slide.get("bullets", [])
        evidence_ids = slide.get("evidenceIds", [])
        chart_path = slide.get("chartPath")
        if (
            not isinstance(slide_title, str)
            or not isinstance(bullets, list)
            or not isinstance(evidence_ids, list)
        ):
            raise ValueError("pptx_slide_invalid")
        if not all(isinstance(item, str) for item in [*bullets, *evidence_ids]):
            raise ValueError("pptx_slide_invalid")
        normalized.append({
            "title": slide_title,
            "bullets": bullets,
            "evidenceIds": evidence_ids,
            **({"chartPath": chart_path} if isinstance(chart_path, str) else {}),
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="report-pptx-") as temporary:
        input_path = Path(temporary) / "input.json"
        input_path.write_text(json.dumps({
            "output": str(output_path.resolve()),
            "title": title,
            "period": period,
            "theme": theme,
            "slides": normalized,
        }, ensure_ascii=False), encoding="utf-8")
        process = run_bridge("slides", "build-pptx", input_path)
        if process.returncode:
            raise RuntimeError(f"pptx_engine_failed: {process.stderr[-2000:]}")
        try:
            receipt = last_json_line(process.stdout)
        except ValueError as error:
            raise RuntimeError("pptx_engine_receipt_invalid") from error

    content = output_path.read_bytes()
    identity = hashlib.sha256(content).hexdigest()
    if not content or re.fullmatch(SHA256_PATTERN, identity) is None:
        raise RuntimeError("pptx_identity_unavailable")
    presentation = Presentation(str(output_path))
    if len(presentation.slides) != len(normalized) + 1:
        raise RuntimeError("pptx_slide_count_invalid")
    return PptxBuildResult(
        path=output_path.as_posix(),
        size=len(content),
        sha256=identity,
        slide_count=len(presentation.slides),
        issues=tuple(receipt.get("issues", ())),
    )
