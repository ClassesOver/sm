from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..reporting.models import ReportingError


def render_pptx_tree(content: bytes) -> dict[str, Any]:
    """只在已核验的 PPTX bytes 上运行冻结版本的静态 RenderTree builder。"""
    engine = Path(os.environ.get(
        "AGENT_REPORTING_SLIDES_ENGINE_DIR",
        Path(__file__).parents[1] / "reporting" / "slides_engine",
    ))
    with tempfile.TemporaryDirectory(prefix="report-slides-render-") as directory:
        root = Path(directory)
        source = root / "source.pptx"
        source.write_bytes(content)
        request = root / "request.json"
        request.write_text(json.dumps({"input": str(source)}), encoding="utf-8")
        result = subprocess.run(
            ["node_modules/.bin/tsx", "bridge/render-pptx.ts", str(request)],
            cwd=engine, capture_output=True, text=True, check=False, timeout=120,
        )
        if result.returncode:
            raise ReportingError("report_slides_render_failed", result.stderr[-2000:] or "幻灯片画布载入失败。")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ReportingError("report_slides_render_invalid", "幻灯片画布数据无效。") from error


_MAX_SLIDE_EDITS = 500
_MAX_SLIDE_EDIT_TEXT = 20_000
_GEOMETRY_KEYS = {"x", "y", "width", "height"}


def validate_slide_edits(edits: Any) -> list[dict[str, Any]]:
    """即时预览与保存共用的对象修改校验，避免预览接受、保存拒绝。"""
    if not isinstance(edits, list) or len(edits) > _MAX_SLIDE_EDITS:
        raise ReportingError("report_slides_edit_invalid", "幻灯片修改内容无效。")
    for edit in edits:
        if (
            not isinstance(edit, dict)
            or not set(edit).issubset({"slideIndex", "elementId", "text", "geometry"})
            or not ({"text", "geometry"} & set(edit))
            or not isinstance(edit.get("slideIndex"), int)
            or isinstance(edit.get("slideIndex"), bool)
            or edit["slideIndex"] < 0
            or not isinstance(edit.get("elementId"), str)
            or not edit["elementId"]
            or ("text" in edit and (not isinstance(edit["text"], str) or len(edit["text"]) > _MAX_SLIDE_EDIT_TEXT))
        ):
            raise ReportingError("report_slides_edit_invalid", "幻灯片修改内容无效。")
        if "geometry" in edit:
            geometry = edit["geometry"]
            if (
                not isinstance(geometry, dict)
                or set(geometry) != _GEOMETRY_KEYS
                or any(
                    not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or value < 0 or value > 100_000
                    for value in geometry.values()
                )
                or geometry["width"] <= 0 or geometry["height"] <= 0
            ):
                raise ReportingError("report_slides_edit_invalid", "幻灯片对象位置无效。")
    return edits


def validate_preview_edits(payload: Any, expected_sha256: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("expectedSha256") != expected_sha256:
        raise ReportingError("report_slides_conflict", "PPTX 已发生变化，请重新载入。")
    return validate_slide_edits(payload.get("edits"))
