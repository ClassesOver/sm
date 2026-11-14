"""PPTX 原生引擎调用与结构编辑校验，供 Office 与旧幻灯片编辑器共用。"""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..reporting.delivery.office_engine import (
    OfficeConversionError,
    last_json_line,
    libreoffice_to_pdf,
    run_bridge,
)
from ..reporting.models import ReportingError

_SLIDE_ANIMATION_EFFECTS = {
    "appear", "fade", "flyIn", "wipe", "wipeDown", "splitIn", "bounce", "flipIn", "zoom",
    "pulse", "spin", "grow", "teeter", "disappear", "fadeOut", "flyOut", "wipeOut", "shrink",
    "zoomOut", "motionPath", "mediaPlay", "mediaPause", "mediaStop",
}
_SLIDE_ANIMATION_TRIGGERS = {"onClick", "withPrev", "afterPrev"}
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MAX_STRUCTURE_EDITS = 200


def _slide_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _number(value: Any, minimum: float, maximum: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and minimum <= value <= maximum
    )


def _validate_structure_edits(payload: dict[str, Any]) -> tuple[list[Any], list[Any], list[Any]]:
    """页面背景、新增文本框（含水印）和删除对象；引擎按原页序号再次核验目标。"""
    backgrounds = payload.get("backgrounds", [])
    text_boxes = payload.get("textBoxes", [])
    deletions = payload.get("deletions", [])
    if (
        not isinstance(backgrounds, list) or len(backgrounds) > _MAX_STRUCTURE_EDITS
        or any(
            not isinstance(item, dict)
            or set(item) != {"slideIndex", "color"}
            or not _slide_index(item["slideIndex"])
            or not isinstance(item["color"], str)
            or not _HEX_COLOR.match(item["color"])
            for item in backgrounds
        )
    ):
        raise ReportingError("report_slides_edit_invalid", "页面背景内容无效。")
    if len({item["slideIndex"] for item in backgrounds}) != len(backgrounds):
        raise ReportingError("report_slides_edit_invalid", "同一页面只能设置一次背景。")
    optional = {"fontSize", "fontFamily", "color", "bold", "rotation", "field", "italic", "outline", "wordArt", "equation"}
    if (
        not isinstance(text_boxes, list) or len(text_boxes) > _MAX_STRUCTURE_EDITS
        or any(
            not isinstance(item, dict)
            or not {"slideIndex", "text", "geometry"}.issubset(item)
            or not set(item).issubset({"slideIndex", "text", "geometry", *optional})
            or not _slide_index(item["slideIndex"])
            or not isinstance(item["text"], str)
            or len(item["text"]) > 20_000
            or not isinstance(item["geometry"], dict)
            or set(item["geometry"]) != {"x", "y", "width", "height"}
            or not all(_number(item["geometry"][key], 0, 100_000) for key in ("x", "y"))
            or not all(_number(item["geometry"][key], 1, 100_000) for key in ("width", "height"))
            or ("fontSize" in item and not _number(item["fontSize"], 1, 400))
            or ("fontFamily" in item and (
                not isinstance(item["fontFamily"], str)
                or not item["fontFamily"].strip()
                or len(item["fontFamily"]) > 200
            ))
            or ("color" in item and (not isinstance(item["color"], str) or not _HEX_COLOR.match(item["color"])))
            or ("bold" in item and not isinstance(item["bold"], bool))
            or ("rotation" in item and not _number(item["rotation"], -360, 360))
            or ("field" in item and item["field"] not in {"slidenum", "datetime1"})
            or any(key in item and not isinstance(item[key], bool) for key in ("italic", "wordArt", "equation"))
            or ("outline" in item and (not isinstance(item["outline"], dict) or set(item["outline"]) != {"color", "widthEmu"}
                or not isinstance(item["outline"]["color"], str) or not _HEX_COLOR.match(item["outline"]["color"])
                or not isinstance(item["outline"]["widthEmu"], int) or isinstance(item["outline"]["widthEmu"], bool) or not 1 <= item["outline"]["widthEmu"] <= 254000))
            for item in text_boxes
        )
    ):
        raise ReportingError("report_slides_edit_invalid", "新增文本框内容无效。")
    if (
        not isinstance(deletions, list) or len(deletions) > _MAX_STRUCTURE_EDITS
        or any(
            not isinstance(item, dict)
            or set(item) != {"slideIndex", "elementId"}
            or not _slide_index(item["slideIndex"])
            or not isinstance(item["elementId"], str)
            or not item["elementId"]
            for item in deletions
        )
    ):
        raise ReportingError("report_slides_edit_invalid", "删除对象内容无效。")
    deleted = {(item["slideIndex"], item["elementId"]) for item in deletions}
    if len(deleted) != len(deletions):
        raise ReportingError("report_slides_edit_invalid", "删除对象重复。")
    pending = [*payload.get("edits", []), *payload.get("animations", [])]
    if any(
        isinstance(item, dict) and (item.get("slideIndex"), item.get("elementId")) in deleted
        for item in pending
    ):
        raise ReportingError("report_slides_edit_invalid", "已删除的对象不能同时修改或添加动画。")
    return backgrounds, text_boxes, deletions




class PptxEngine:
    """PPTX 引擎桥接：检查、编辑与预览渲染。"""

    @staticmethod
    def _run_engine(
        content: bytes,
        action: str,
        *,
        edits: list[dict[str, Any]] | None = None,
        order: list[int] | None = None,
        new_slides: list[dict[str, Any]] | None = None,
        deleted_slides: list[int] | None = None,
        reset_layouts: list[int] | None = None,
        shapes: list[dict[str, Any]] | None = None,
        tables: list[dict[str, Any]] | None = None,
        shape_styles: list[dict[str, Any]] | None = None,
        shape_kinds: list[dict[str, Any]] | None = None,
        sections: list[dict[str, Any]] | None = None,
        header_footer: dict[str, Any] | None = None,
        table_cells: list[dict[str, Any]] | None = None,
        table_styles: list[dict[str, Any]] | None = None,
        table_structures: list[dict[str, Any]] | None = None,
        charts: list[dict[str, Any]] | None = None,
        smart_arts: list[dict[str, Any]] | None = None,
        animation_sequences: list[dict[str, Any]] | None = None,
        theme: str | None = None,
        slide_size: dict[str, int] | None = None,
        images: list[dict[str, Any]] | None = None,
        native_images: list[dict[str, Any]] | None = None,
        zoom_insertions: list[dict[str, Any]] | None = None,
        media_insertions: list[dict[str, Any]] | None = None,
        model_insertions: list[dict[str, Any]] | None = None,
        model_views: list[dict[str, Any]] | None = None,
        picture_replacements: list[dict[str, Any]] | None = None,
        picture_crops: list[dict[str, Any]] | None = None,
        picture_opacities: list[dict[str, Any]] | None = None,
        element_orders: list[dict[str, Any]] | None = None,
        group_edits: list[dict[str, Any]] | None = None,
        notes_edits: list[dict[str, Any]] | None = None,
        master_text_edits: list[dict[str, Any]] | None = None,
        master_element_edits: list[dict[str, Any]] | None = None,
        link_edits: list[dict[str, Any]] | None = None,
        clipboard_pastes: list[dict[str, Any]] | None = None,
        chart_edits: list[dict[str, Any]] | None = None,
        hidden_slides: list[dict[str, Any]] | None = None,
        comment_edits: list[dict[str, Any]] | None = None,
        transitions: list[dict[str, Any]] | None = None,
        animations: list[dict[str, Any]] | None = None,
        slide_layouts: list[dict[str, Any]] | None = None,
        backgrounds: list[dict[str, Any]] | None = None,
        background_images: list[dict[str, Any]] | None = None,
        custom_shows: list[dict[str, Any]] | None = None,
        background_image_reuses: list[dict[str, Any]] | None = None,
        background_gradients: list[dict[str, Any]] | None = None,
        background_resets: list[int] | None = None,
        background_graphics: list[dict[str, Any]] | None = None,
        text_boxes: list[dict[str, Any]] | None = None,
        deletions: list[dict[str, Any]] | None = None,
        paragraph_formatting: list[dict[str, Any]] | None = None,
    ) -> Any:
        with tempfile.TemporaryDirectory(prefix="report-slides-edit-") as directory:
            root = Path(directory)
            source_path = root / "source.pptx"
            source_path.write_bytes(content)
            request_path = root / "request.json"
            request: dict[str, Any] = {"action": action, "input": str(source_path)}
            output_path = root / "output.pptx"
            if action == "edit":
                request.update({"output": str(output_path), "edits": edits or [], "order": order})
                if new_slides:
                    request["newSlides"] = new_slides
                if deleted_slides:
                    request["deletedSlides"] = deleted_slides
                if reset_layouts:
                    request["resetLayouts"] = reset_layouts
                if shapes:
                    request["shapes"] = shapes
                if tables:
                    request["tables"] = tables
                if shape_styles:
                    request["shapeStyles"] = shape_styles
                if shape_kinds:
                    request["shapeKinds"] = shape_kinds
                if sections:
                    request["sections"] = sections
                if header_footer is not None:
                    request["headerFooter"] = header_footer
                if table_structures:
                    request["tableStructures"] = table_structures
                if master_text_edits:
                    request["masterTextEdits"] = master_text_edits
                if master_element_edits:
                    request["masterElementEdits"] = master_element_edits
                if table_styles:
                    request["tableStyles"] = table_styles
                if table_cells:
                    request["tableCells"] = table_cells
                if charts:
                    request["charts"] = charts
                if smart_arts:
                    request["smartArts"] = smart_arts
                if animation_sequences:
                    request["animationSequences"] = animation_sequences
                if theme is not None:
                    request["theme"] = theme
                if slide_size is not None:
                    request["slideSize"] = slide_size
                if images:
                    import base64

                    request["images"] = [
                        {
                            "slideIndex": image["slideIndex"],
                            "bytesBase64": base64.b64encode(image["bytes"]).decode("ascii"),
                            "extension": image["extension"],
                            "geometry": image["geometry"],
                            "descr": "AI 生成配图",
                        }
                        for image in images
                    ]
                if native_images:
                    request["nativeImages"] = native_images
                if zoom_insertions:
                    request["zoomInsertions"] = zoom_insertions
                if model_insertions:
                    request["modelInsertions"] = model_insertions
                if model_views:
                    request["modelViews"] = model_views
                if media_insertions:
                    request["mediaInsertions"] = media_insertions
                if picture_replacements:
                    request["pictureReplacements"] = picture_replacements
                if group_edits:
                    request["groupEdits"] = group_edits
                if notes_edits:
                    request["notesEdits"] = notes_edits
                if link_edits:
                    request["linkEdits"] = link_edits
                if clipboard_pastes:
                    request["clipboardPastes"] = clipboard_pastes
                if element_orders:
                    request["elementOrders"] = element_orders
                if picture_crops:
                    request["pictureCrops"] = picture_crops
                if picture_opacities:
                    request["pictureOpacities"] = picture_opacities
                if chart_edits:
                    request["chartEdits"] = chart_edits
                if hidden_slides:
                    request["hiddenSlides"] = hidden_slides
                if comment_edits:
                    request["commentEdits"] = comment_edits
                    # 固定宿主标签，不接收客户端作者冒认，也不宣称账号协作身份。
                    request["commentAuthor"] = "用户"
                if transitions:
                    request["transitions"] = transitions
                if animations:
                    request["animations"] = animations
                if slide_layouts:
                    request["slideLayouts"] = slide_layouts
                if backgrounds:
                    request["backgrounds"] = backgrounds
                if custom_shows is not None:
                    request["customShows"] = custom_shows
                if background_image_reuses:
                    request["backgroundImageReuses"] = background_image_reuses
                if background_images:
                    request["backgroundImages"] = background_images
                if background_gradients:
                    request["backgroundGradients"] = background_gradients
                if background_resets:
                    request["backgroundResets"] = background_resets
                if background_graphics:
                    request["backgroundGraphics"] = background_graphics
                if text_boxes:
                    request["textBoxes"] = text_boxes
                if deletions:
                    request["deletions"] = deletions
                if paragraph_formatting:
                    request["paragraphFormatting"] = paragraph_formatting
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            process = run_bridge("slides", "edit-pptx", request_path)
            if process.returncode:
                raise ReportingError(
                    "report_slides_engine_failed", process.stderr[-2000:] or "PPTX 编辑失败。"
                )
            try:
                receipt = last_json_line(process.stdout)
            except ValueError as error:
                raise ReportingError("report_slides_engine_receipt_invalid", "PPTX 引擎回执无效。") from error
            if action == "edit":
                return {"bytes": output_path.read_bytes(), "issues": receipt.get("issues", [])}
            return receipt

    @staticmethod
    def _render_pdf(content: bytes) -> bytes:
        try:
            return libreoffice_to_pdf(content, suffix=".pptx", timeout=90)
        except (OfficeConversionError, subprocess.TimeoutExpired) as error:
            raise ReportingError("report_slides_preview_failed", "幻灯片预览暂不可用。") from error
