"""Word chart image downsampling with native OOXML geometry readback."""

from __future__ import annotations

import hashlib
import math
import os
import posixpath
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from loguru import logger
from lxml import etree
from PIL import Image

_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}
_DPI_PER_EMU = 914400


def _media_target(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("word", target))


def _media_owners(entries: dict[str, bytes]) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for relationship_path, raw in entries.items():
        if not relationship_path.endswith(".rels") or "/_rels/" not in relationship_path:
            continue
        folder, filename = relationship_path.rsplit("/_rels/", 1)
        owner = posixpath.join(folder, filename.removesuffix(".rels"))
        try:
            relationships = etree.fromstring(raw)
        except etree.XMLSyntaxError:
            continue
        for relationship in relationships:
            if relationship.get("Type", "").rsplit("/", 1)[-1] == "image":
                target = _media_target(relationship.get("Target", ""))
                owners.setdefault(target, set()).add(owner)
    return owners


def _image_info(data: bytes) -> tuple[str, int, int] | None:
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG"}:
                return None
            return image.format, image.width, image.height
    except Exception:
        return None


def _derived_image(data: bytes, *, width: int, height: int, target_dpi: int) -> tuple[bytes, dict[str, Any]] | None:
    info = _image_info(data)
    if info is None:
        return None
    image_format, source_width, source_height = info
    maximum_width = max(1, math.floor(width / _DPI_PER_EMU * target_dpi))
    maximum_height = max(1, math.floor(height / _DPI_PER_EMU * target_dpi))
    scale = min(1.0, maximum_width / source_width, maximum_height / source_height)
    if scale >= 1:
        return None
    output_width = max(1, min(maximum_width, math.floor(source_width * scale)))
    output_height = max(1, min(maximum_height, math.floor(source_height * scale)))
    with Image.open(BytesIO(data)) as image:
        image.load()
        resized = image.resize((output_width, output_height), Image.Resampling.LANCZOS)
        output = BytesIO()
        save_options: dict[str, Any] = {}
        if image_format == "JPEG":
            if resized.mode not in {"RGB", "L"}:
                resized = resized.convert("RGB")
            save_options.update(quality=95, optimize=True)
        resized.save(output, format=image_format, **save_options)
    effective = {
        "x": round(output_width * 914400 / width, 3),
        "y": round(output_height * 914400 / height, 3),
    }
    return output.getvalue(), {
        "sourcePixels": {"width": source_width, "height": source_height},
        "outputPixels": {"width": output_width, "height": output_height},
        "effectiveDpi": effective,
    }


def apply_word_chart_image_dpi(
    path: Path,
    *,
    target_dpi: int,
    chart_source_sha256s: set[str],
) -> dict[str, Any]:
    """Create a separate media part per registered chart drawing; keep source parts intact."""
    if not chart_source_sha256s:
        return {"status": "unchanged", "images": [], "issues": []}
    with zipfile.ZipFile(path) as package:
        infos = {item.filename: item for item in package.infolist()}
        entries = {item.filename: package.read(item.filename) for item in infos.values()}
        document = etree.fromstring(entries["word/document.xml"])
        relationships = etree.fromstring(entries["word/_rels/document.xml.rels"])
        content_types = etree.fromstring(entries["[Content_Types].xml"])
        rel_by_id = {item.get("Id"): item for item in relationships}
        media_owners = _media_owners(entries)
        extents = [
            (node.get("cx"), node.get("cy"))
            for node in document.xpath(".//wp:inline/wp:extent | .//wp:anchor/wp:extent", namespaces=_NS)
        ]
        blips = document.xpath(".//a:blip[@r:embed]", namespaces=_NS)
        if len(blips) != len(extents):
            return {"status": "unchanged", "images": [], "issues": ["drawing_geometry_unreadable"]}

        image_rows: list[dict[str, Any]] = []
        issues: list[str] = []
        next_relation = 1
        for relationship in relationships:
            value = relationship.get("Id", "")
            if value.startswith("rId") and value[3:].isdigit():
                next_relation = max(next_relation, int(value[3:]) + 1)
        next_media = 1
        for name in entries:
            base = posixpath.basename(name)
            stem = base.rsplit(".", 1)[0]
            if name.startswith("word/media/") and stem.startswith("image"):
                suffix = stem.removeprefix("image")
                if suffix.isdigit():
                    next_media = max(next_media, int(suffix) + 1)

        for blip, (extent_width_raw, extent_height_raw) in zip(blips, extents, strict=True):
            relation_id = blip.get(f"{{{_NS['r']}}}embed")
            relation = rel_by_id.get(relation_id)
            if relation is None or relation.get("Type", "").rsplit("/", 1)[-1] != "image":
                continue
            source_part = _media_target(relation.get("Target", ""))
            source = entries.get(source_part)
            if source is None or hashlib.sha256(source).hexdigest() not in chart_source_sha256s:
                continue
            if media_owners.get(source_part, set()) - {"word/document.xml"}:
                issues.append("chart_media_reused_ambiguously")
                continue
            try:
                extent_width, extent_height = int(extent_width_raw), int(extent_height_raw)
            except (TypeError, ValueError):
                issues.append("drawing_geometry_unreadable")
                continue
            result = _derived_image(source, width=extent_width, height=extent_height, target_dpi=target_dpi)
            if result is None:
                if _image_info(source) is None:
                    issues.append("chart_image_format_not_supported")
                continue
            derived, measurement = result
            extension = source_part.rsplit(".", 1)[-1].lower()
            media_name = f"word/media/image-dpi-{next_media}.{extension}"
            while media_name in entries:
                next_media += 1
                media_name = f"word/media/image-dpi-{next_media}.{extension}"
            next_media += 1
            new_relation_id = f"rId{next_relation}"
            next_relation += 1
            target = posixpath.relpath(media_name, "word")
            etree.SubElement(relationships, f"{{{_NS['rel']}}}Relationship", {
                "Id": new_relation_id,
                "Type": relation.get("Type"),
                "Target": target,
            })
            blip.set(f"{{{_NS['r']}}}embed", new_relation_id)
            entries[media_name] = derived
            # 原包可能只有逐图片Override；新增部件必须独立登记，不能假定有扩展名Default。
            etree.SubElement(content_types, "{http://schemas.openxmlformats.org/package/2006/content-types}Override", {
                "PartName": "/" + media_name,
                "ContentType": "image/png" if _image_info(derived)[0] == "PNG" else "image/jpeg",
            })
            image_rows.append({
                "relationshipId": new_relation_id,
                "sourceSha256": hashlib.sha256(source).hexdigest(),
                "derivedSha256": hashlib.sha256(derived).hexdigest(),
                "extentEmu": {"width": extent_width, "height": extent_height},
                **measurement,
            })

        if not image_rows:
            return {"status": "unchanged", "images": [], "issues": sorted(set(issues))}
        entries["word/document.xml"] = etree.tostring(document, xml_declaration=True, encoding="UTF-8", standalone=True)
        entries["word/_rels/document.xml.rels"] = etree.tostring(relationships, xml_declaration=True,
            encoding="UTF-8", standalone=True)
        entries["[Content_Types].xml"] = etree.tostring(content_types, xml_declaration=True,
            encoding="UTF-8", standalone=True)

    fd, temporary_name = tempfile.mkstemp(prefix="word-image-dpi-", suffix=".docx", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for name, value in entries.items():
                package.writestr(infos.get(name, name), value)
        with zipfile.ZipFile(temporary) as package:
            if package.testzip() is not None:
                raise ValueError("generated Word package failed CRC readback")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = {"status": "applied", "images": image_rows, "issues": sorted(set(issues))}
    try:
        readback = read_word_chart_image_dpi(path)
    except Exception as error:
        logger.warning("report_word_chart_dpi_readback_failed error_type={}", type(error).__name__)
        return {**receipt, "status": "unverified",
            "issues": sorted(set([*receipt["issues"], "chart_image_dpi_readback_failed"]))}
    rows_by_relation = {item["relationshipId"]: item for item in readback}
    verified = verify_word_chart_image_dpi(path, receipt, readback=readback)
    actual_rows = []
    for item in image_rows:
        actual = rows_by_relation.get(item["relationshipId"])
        if actual is None:
            continue
        actual_rows.append({
            **actual,
            "sourceSha256": item["sourceSha256"],
            "derivedSha256": actual["mediaSha256"],
            "sourcePixels": item["sourcePixels"],
        })
    return {
        "status": "applied" if verified else "unverified",
        "images": actual_rows,
        "issues": sorted(set(issues + ([] if verified else ["chart_image_dpi_readback_mismatch"]))),
    }


def read_word_chart_image_dpi(path: Path) -> list[dict[str, Any]]:
    """Read every embedded Word picture's actual pixels and DrawingML physical extent."""
    with zipfile.ZipFile(path) as package:
        document = etree.fromstring(package.read("word/document.xml"))
        relationships = etree.fromstring(package.read("word/_rels/document.xml.rels"))
        rel_by_id = {item.get("Id"): item for item in relationships}
        blips = document.xpath(".//a:blip[@r:embed]", namespaces=_NS)
        extents = document.xpath(".//wp:inline/wp:extent | .//wp:anchor/wp:extent", namespaces=_NS)
        if len(blips) != len(extents):
            raise ValueError("Word picture drawing geometry is incomplete")
        rows: list[dict[str, Any]] = []
        for blip, extent in zip(blips, extents, strict=True):
            relation_id = blip.get(f"{{{_NS['r']}}}embed")
            relation = rel_by_id.get(relation_id)
            if relation is None or relation.get("Type", "").rsplit("/", 1)[-1] != "image":
                raise ValueError("Word picture image relationship is invalid")
            target = _media_target(relation.get("Target", ""))
            info = _image_info(package.read(target))
            if info is None:
                raise ValueError("Word picture image cannot be measured")
            _, pixel_width, pixel_height = info
            width, height = int(extent.get("cx")), int(extent.get("cy"))
            rows.append({
                "relationshipId": relation_id,
                "mediaSha256": hashlib.sha256(package.read(target)).hexdigest(),
                "outputPixels": {"width": pixel_width, "height": pixel_height},
                "extentEmu": {"width": width, "height": height},
                "effectiveDpi": {
                    "x": round(pixel_width * 914400 / width, 3),
                    "y": round(pixel_height * 914400 / height, 3),
                },
            })
        return rows


def verify_word_chart_image_dpi(
    path: Path, receipt: dict[str, Any], *, readback: list[dict[str, Any]] | None = None
) -> bool:
    """Bind each derivation receipt to the final package's media relation and source bytes."""
    if receipt.get("status") != "applied":
        return receipt.get("status") == "unchanged"
    try:
        with zipfile.ZipFile(path) as package:
            media_hashes = {
                hashlib.sha256(package.read(name)).hexdigest()
                for name in package.namelist()
                if name.startswith("word/media/") and not name.endswith("/")
            }
        rows = readback if readback is not None else read_word_chart_image_dpi(path)
        by_relation = {item["relationshipId"]: item for item in rows}
        derivations = receipt.get("images")
        return isinstance(derivations, list) and all(
            isinstance(item, dict)
            and item.get("sourceSha256") in media_hashes
            and (row := by_relation.get(item.get("relationshipId"))) is not None
            and row["mediaSha256"] == item.get("derivedSha256")
            and row["outputPixels"] == item.get("outputPixels")
            and row["extentEmu"] == item.get("extentEmu")
            and row["effectiveDpi"] == item.get("effectiveDpi")
            for item in derivations
        ) and len(derivations) == len(receipt.get("images", []))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return False
