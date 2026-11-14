"""受控 PDF 静态图像派生；调用方须先核实图表产物身份。"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from PIL import Image


@dataclass(frozen=True)
class ChartImageSource:
    chart_id: str
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class DerivedChartImage:
    chart_id: str
    source_path: str
    source_sha256: str
    derived_sha256: str
    media_type: str
    width: int
    height: int
    data: bytes


def verify_chart_image_sources(
    workspace: Path,
    charts: list[dict[str, object]],
    allowed_images: set[Path],
) -> dict[Path, ChartImageSource]:
    """仅返回与正式清单身份一致且已由 Markdown 引用的图表文件。"""
    root = workspace.resolve()
    allowed = {path.resolve() for path in allowed_images}
    verified: dict[Path, ChartImageSource] = {}
    for item in charts:
        chart_id = item.get("chartId")
        path_value, size, digest = item.get("path"), item.get("size"), item.get("sha256")
        if (
            not isinstance(chart_id, str)
            or not chart_id
            or not isinstance(path_value, str)
            or not isinstance(size, int)
            or not isinstance(digest, str)
        ):
            continue
        relative = PurePosixPath(path_value)
        if "\\" in path_value or relative.is_absolute() or ".." in relative.parts:
            continue
        path = root.joinpath(*relative.parts).resolve()
        if path not in allowed or not path.is_file():
            continue
        content = path.read_bytes()
        actual_digest = hashlib.sha256(content).hexdigest()
        if len(content) != size or actual_digest != digest:
            continue
        verified[path] = ChartImageSource(chart_id, path_value, size, digest)
    return verified


def derive_chart_image(
    path: Path,
    source: ChartImageSource,
    *,
    display_width_css_px: float,
    display_height_css_px: float,
    target_dpi: int,
) -> DerivedChartImage | None:
    """按显示框限制过高像素；不改源文件，也不放大低清图。"""
    if target_dpi < 1 or display_width_css_px <= 0 or display_height_css_px <= 0:
        return None
    original = path.read_bytes()
    source_sha256 = hashlib.sha256(original).hexdigest()
    if source_sha256 != source.sha256 or len(original) != source.size:
        return None
    try:
        with Image.open(io.BytesIO(original)) as image:
            image.load()
            original_width, original_height = image.size
            max_width = max(1, math.floor(display_width_css_px * target_dpi / 96))
            max_height = max(1, math.floor(display_height_css_px * target_dpi / 96))
            if original_width <= max_width and original_height <= max_height:
                return None
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            if image.mode in {"RGB", "L"}:
                image.save(output, format="PNG", optimize=False)
                media_type = "image/png"
            else:
                image.convert("RGBA").save(output, format="PNG", optimize=False)
                media_type = "image/png"
            data = output.getvalue()
    except (OSError, ValueError):
        return None
    with Image.open(io.BytesIO(data)) as derived:
        width, height = derived.size
    return DerivedChartImage(
        chart_id=source.chart_id,
        source_path=source.path,
        source_sha256=source_sha256,
        derived_sha256=hashlib.sha256(data).hexdigest(),
        media_type=media_type,
        width=width,
        height=height,
        data=data,
    )


def mark_chart_images(
    body_html: str,
    source_paths: dict[str, Path],
    verified: dict[Path, ChartImageSource],
) -> str:
    """Add an internal identity marker only to uniquely resolved chart images."""
    by_path: dict[Path, list[str]] = {}
    for src, path in source_paths.items():
        if path.resolve() in verified:
            by_path.setdefault(path.resolve(), []).append(src)
    markers = {
        src: verified[path.resolve()].chart_id
        for path, sources in by_path.items()
        if len(sources) == 1
        for src in sources
    }

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        src_match = re.search(r"\bsrc\s*=\s*(['\"])(.*?)\1", tag, re.IGNORECASE | re.DOTALL)
        if src_match is None:
            return tag
        source = html.unescape(src_match.group(2))
        chart_id = markers.get(source)
        if chart_id is None:
            return tag
        safe_id = html.escape(chart_id, quote=True)
        slash = re.search(r"\s*/>$", tag)
        at = slash.start() if slash else len(tag) - 1
        return tag[:at] + f' data-pdf-chart-id="{safe_id}"' + tag[at:]

    return re.sub(r"<img\b[^>]*>", replace, body_html, flags=re.IGNORECASE | re.DOTALL)


def chart_image_boxes(document: object) -> dict[str, list[tuple[float, float]]]:
    """Read WeasyPrint's laid-out CSS image boxes before output resampling."""
    from weasyprint.formatting_structure.boxes import ReplacedBox

    found: dict[str, list[tuple[float, float]]] = {}
    for page in getattr(document, "pages", ()):
        page_box = getattr(page, "_page_box", None)
        if page_box is None:
            continue
        for box in page_box.descendants():
            element = getattr(box, "element", None)
            if element is None:
                continue
            chart_id = element.get("data-pdf-chart-id")
            if chart_id and isinstance(box, ReplacedBox):
                size = (float(box.width), float(box.height))
                if size[0] > 0 and size[1] > 0:
                    found.setdefault(chart_id, []).append(size)
    return found


def apply_chart_derivatives(
    body_html: str,
    derivatives: dict[str, DerivedChartImage],
    boxes: dict[str, list[tuple[float, float]]],
) -> str:
    """Replace PDF-only chart bytes while locking each original display box."""
    positions: dict[str, int] = {}

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        id_match = re.search(r"\bdata-pdf-chart-id\s*=\s*(['\"])(.*?)\1", tag, re.IGNORECASE)
        if id_match is None:
            return tag
        chart_id = html.unescape(id_match.group(2))
        derived = derivatives.get(chart_id)
        dimensions = boxes.get(chart_id, [])
        if derived is None or not dimensions:
            return tag
        index = positions.get(chart_id, 0)
        positions[chart_id] = index + 1
        if index >= len(dimensions):
            return tag
        width, height = dimensions[index]
        uri = f"data:{derived.media_type};base64,{base64.b64encode(derived.data).decode('ascii')}"
        src_match = re.search(r"\bsrc\s*=\s*(['\"])(.*?)\1", tag, re.IGNORECASE | re.DOTALL)
        if src_match is None:
            return tag
        tag = tag[:src_match.start(2)] + html.escape(uri, quote=True) + tag[src_match.end(2):]
        style_match = re.search(r"\bstyle\s*=\s*(['\"])(.*?)\1", tag, re.IGNORECASE | re.DOTALL)
        locked_style = f"width:{width:.6f}px;height:{height:.6f}px"
        if style_match is None:
            slash = re.search(r"\s*/>$", tag)
            at = slash.start() if slash else len(tag) - 1
            return tag[:at] + f' style="{locked_style}"' + tag[at:]
        prior = style_match.group(2).strip().rstrip(";")
        style = f"{prior};{locked_style}" if prior else locked_style
        return tag[:style_match.start(2)] + html.escape(style, quote=True) + tag[style_match.end(2):]

    return re.sub(r"<img\b[^>]*>", replace, body_html, flags=re.IGNORECASE | re.DOTALL)


def read_pdf_chart_dpi(pdf_path: Path, derivatives: dict[str, DerivedChartImage]) -> dict[str, list[dict[str, float]]]:
    """Independently match chart pixels in PDF XObjects and read each draw matrix."""
    import base64
    from hashlib import md5

    from pypdf import PdfReader
    from pypdf.generic import ContentStream

    expected: dict[str, str] = {}
    for chart_id, item in derivatives.items():
        uri = f"data:{item.media_type};base64,{base64.b64encode(item.data).decode('ascii')}"
        expected["/i" + md5(uri.encode(), usedforsecurity=False).hexdigest()] = chart_id
    result: dict[str, list[dict[str, float]]] = {chart_id: [] for chart_id in derivatives}
    reader = PdfReader(str(pdf_path))
    identity = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def compose(left, right):
        a, b, c, d, e, f = left
        g, h, i, j, k, m = right
        return (
            a * g + c * h, b * g + d * h,
            a * i + c * j, b * i + d * j,
            a * k + c * m + e, b * k + d * m + f,
        )

    def read_stream(stream, resources, initial_ctm, active_forms):
        resources = resources.get_object()
        xobjects = resources.get("/XObject", {}).get_object()
        content = ContentStream(stream, reader)
        ctm = initial_ctm
        stack = []
        for operands, operator in content.operations:
            if operator == b"q":
                stack.append(ctm)
            elif operator == b"Q":
                if stack:
                    ctm = stack.pop()
            elif operator == b"cm" and len(operands) == 6:
                ctm = compose(ctm, tuple(float(value) for value in operands))
            elif operator == b"Do" and operands:
                name = str(operands[0])
                reference = xobjects.get(name)
                if reference is None:
                    continue
                xobject = reference.get_object()
                subtype = xobject.get("/Subtype")
                if subtype == "/Form":
                    ref_id = (reference.idnum, reference.generation)
                    if ref_id in active_forms:
                        continue
                    form_matrix = tuple(float(value) for value in xobject.get("/Matrix", identity))
                    form_ctm = compose(ctm, form_matrix)
                    form_resources = xobject.get("/Resources") or resources
                    read_stream(xobject, form_resources, form_ctm, active_forms | {ref_id})
                    continue
                if subtype != "/Image":
                    continue
                chart_id = expected.get(name)
                if chart_id is None:
                    chart_id = next((value for base, value in expected.items()
                        if name.startswith(base) and name[len(base):].isdigit()), None)
                if chart_id is None:
                    continue
                a, b, c, d, _, _ = ctm
                width_pt = math.hypot(a, b)
                height_pt = math.hypot(c, d)
                pixel_width, pixel_height = int(xobject["/Width"]), int(xobject["/Height"])
                if width_pt <= 0 or height_pt <= 0:
                    continue
                result[chart_id].append({
                    "widthDpi": pixel_width * 72 / width_pt,
                    "heightDpi": pixel_height * 72 / height_pt,
                    "pixelWidth": float(pixel_width),
                    "pixelHeight": float(pixel_height),
                })

    for page in reader.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        stream = page.get_contents()
        if stream is not None:
            read_stream(stream, resources, identity, set())
    return result
