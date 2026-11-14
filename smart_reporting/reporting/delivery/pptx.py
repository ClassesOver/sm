from __future__ import annotations

import hashlib
import json
import posixpath
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger
from PIL import Image
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
    image_derivations: tuple[dict[str, object], ...] = ()


def _picture_shapes(presentation):
    for slide_index, slide in enumerate(presentation.slides, 1):
        for shape in slide.shapes:
            if shape.shape_type == 13:
                yield slide_index, shape


def _apply_chart_image_dpi(path: Path, chart_images: tuple[dict[str, object], ...], maximum_dpi: int):
    """Downsample chart picture objects by slide and source identity, keeping source parts intact."""
    warnings = []
    presentation = Presentation(str(path))
    targets = {}
    emu_per_inch = 914400
    for item in chart_images:
        slide_index = item.get('slide')
        expected_sha = item.get('sourceSha256')
        if not isinstance(slide_index, int) or not isinstance(expected_sha, str):
            warnings.append({'code': 'pptx_chart_image_dpi_binding_invalid',
                'message': '图表图片缺少原生幻灯片或来源身份绑定，未调整图片。'})
            continue
        if slide_index < 1 or slide_index > len(presentation.slides):
            warnings.append({'code': 'pptx_chart_image_dpi_binding_missing',
                'message': '图表图片绑定的幻灯片不存在，未调整图片。', 'page': slide_index})
            continue
        pictures = [shape for shape in presentation.slides[slide_index - 1].shapes if shape.shape_type == 13]
        matches = [shape for shape in pictures if hashlib.sha256(shape.image.blob).hexdigest() == expected_sha]
        if len(matches) != 1:
            warnings.append({'code': 'pptx_chart_image_dpi_binding_ambiguous',
                'message': '图表图片无法唯一绑定到原生图片对象，未调整图片。', 'page': slide_index})
            continue
        shape = matches[0]
        relation_id = shape._element.blipFill.blip.rEmbed
        source_part = str(shape.part.related_part(relation_id).partname).lstrip('/')
        identity = (slide_index, shape.shape_id)
        targets[identity] = {'slide': slide_index, 'shape': shape, 'sourceSha256': expected_sha,
            'sourcePart': source_part, 'relationId': relation_id}

    by_source_part = {}
    for identity, target in targets.items():
        by_source_part.setdefault(target['sourcePart'], set()).add(identity)
    for slide_index, shape in _picture_shapes(presentation):
        relation_id = shape._element.blipFill.blip.rEmbed
        part_name = str(shape.part.related_part(relation_id).partname).lstrip('/')
        target_ids = by_source_part.get(part_name)
        if target_ids and (slide_index, shape.shape_id) not in target_ids:
            for identity in target_ids:
                targets.pop(identity, None)
            warnings.append({'code': 'pptx_chart_image_dpi_shared_media',
                'message': '圖表來源媒體還被其他圖片對象使用，為保留其他對象未調整此來源。',
                'page': slide_index})

    from io import BytesIO

    additions = {}
    relation_updates = {}
    with zipfile.ZipFile(path) as source_package:
        occupied = set(source_package.namelist())
    for identity, target in targets.items():
        shape = target['shape']
        source_part = target['sourcePart']
        source_blob = shape.image.blob
        try:
            with Image.open(BytesIO(source_blob)) as image:
                if image.format not in {'PNG', 'JPEG'}:
                    raise ValueError('unsupported_image_format')
                source_size = image.size
                target_width = min(source_size[0], max(1, int(maximum_dpi * shape.width / emu_per_inch)))
                target_height = min(source_size[1], max(1, int(maximum_dpi * shape.height / emu_per_inch)))
                scale = min(1.0, target_width / source_size[0], target_height / source_size[1])
                output_blob = source_blob
                if scale < 1:
                    target_size = (max(1, int(source_size[0] * scale)), max(1, int(source_size[1] * scale)))
                    derived = image.resize(target_size, Image.Resampling.LANCZOS)
                    output = BytesIO()
                    options = {'optimize': True}
                    if image.format == 'JPEG':
                        options.update(quality=95, subsampling=0)
                    derived.save(output, format=image.format, **options)
                    output_blob = output.getvalue()
        except (OSError, ValueError):
            warnings.append({'code': 'pptx_chart_image_dpi_unsupported',
                'message': '图表图片格式无法安全派生，保留来源并提示复核。', 'page': target['slide']})
            continue
        if output_blob == source_blob:
            continue
        suffix = Path(source_part).suffix
        base = Path(source_part).stem
        derived_part = f'ppt/media/{base}-chart-dpi-{hashlib.sha256(output_blob).hexdigest()[:12]}{suffix}'
        serial = 1
        candidate = derived_part
        while candidate in occupied:
            candidate = f'ppt/media/{base}-chart-dpi-{hashlib.sha256(output_blob).hexdigest()[:12]}-{serial}{suffix}'
            serial += 1
        derived_part = candidate
        occupied.add(derived_part)
        additions[derived_part] = output_blob
        rels_name = posixpath.join(posixpath.dirname(str(shape.part.partname).lstrip('/')), '_rels',
            posixpath.basename(str(shape.part.partname)) + '.rels')
        relation_updates.setdefault(rels_name, {})[target['relationId']] = posixpath.relpath(
            '/' + derived_part, '/' + posixpath.dirname(str(shape.part.partname).lstrip('/')))

    if additions:
        ET.register_namespace('', 'http://schemas.openxmlformats.org/package/2006/relationships')
        with tempfile.NamedTemporaryFile(prefix='pptx-image-dpi-', suffix='.pptx', dir=path.parent, delete=False) as temp:
            temporary_path = Path(temp.name)
        try:
            with zipfile.ZipFile(path, 'r') as source, zipfile.ZipFile(temporary_path, 'w') as target_zip:
                for item in source.infolist():
                    content = source.read(item.filename)
                    updates = relation_updates.get(item.filename)
                    if updates:
                        root = ET.fromstring(content)
                        for relation in root:
                            if relation.attrib.get('Id') in updates:
                                relation.set('Target', updates[relation.attrib['Id']])
                        content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                    target_zip.writestr(item, content)
                for part_name, content in additions.items():
                    target_zip.writestr(part_name, content)
            with zipfile.ZipFile(temporary_path) as candidate:
                if candidate.testzip() is not None:
                    raise ValueError('pptx_image_dpi_package_invalid')
            Presentation(str(temporary_path))
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)

    actual = Presentation(str(path))
    records = []
    actual_by_identity = {(slide_index, shape.shape_id): shape for slide_index, shape in _picture_shapes(actual)}
    with zipfile.ZipFile(path, 'r') as package:
        for identity, target in targets.items():
            shape = actual_by_identity.get(identity)
            if shape is None:
                warnings.append({'code': 'pptx_chart_image_dpi_readback_missing',
                    'message': '图表图片对象在重新读取的 PPTX 中缺失。', 'page': target['slide']})
                continue
            embedded_part = str(shape.part.related_part(shape._element.blipFill.blip.rEmbed).partname).lstrip('/')
            source_part = target['sourcePart']
            source_blob = package.read(source_part)
            if hashlib.sha256(source_blob).hexdigest() != target['sourceSha256']:
                warnings.append({'code': 'pptx_chart_image_dpi_source_changed',
                    'message': 'PPTX 内冻结图表来源媒体身份发生变化。', 'page': target['slide']})
                continue
            image_blob = shape.image.blob
            with Image.open(BytesIO(image_blob)) as embedded:
                width, height = embedded.size
            dpi_x = width * emu_per_inch / shape.width
            dpi_y = height * emu_per_inch / shape.height
            records.append({
                'slide': target['slide'], 'shapeId': shape.shape_id,
                'sourcePart': source_part, 'sourceSha256': target['sourceSha256'],
                'embeddedPart': embedded_part, 'embeddedSha256': hashlib.sha256(image_blob).hexdigest(),
                'pixelWidth': width, 'pixelHeight': height,
                'extentWidthEmu': shape.width, 'extentHeightEmu': shape.height,
                'effectiveDpiX': round(dpi_x, 3), 'effectiveDpiY': round(dpi_y, 3),
                'withinLimit': dpi_x <= maximum_dpi + 0.01 and dpi_y <= maximum_dpi + 0.01,
            })
    return tuple(records), tuple(warnings)


def build_editable_pptx(
    *,
    output_path: Path,
    title: str,
    period: str,
    theme: PptxTheme,
    slides: tuple[dict[str, object], ...],
    preferences: dict[str, object] | None = None, generated_date: str | None = None,
) -> PptxBuildResult:
    if theme not in {"executive", "clinical", "modern"}:
        raise ValueError("pptx_theme_invalid")
    if not title.strip() or not slides:
        raise ValueError("pptx_content_invalid")
    normalized = []
    table_issues = []
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
        from .pptx_tables import normalize_slide_table

        tables = []
        table_input = slide.get('tables', [])
        if not isinstance(table_input, list):
            table_issues.append({'code': 'pptx_table_input_invalid',
                'message': '受控表格清单无效，已保留其他内容。'})
            table_input = []
        for table in table_input:
            try:
                tables.append(normalize_slide_table(table))
            except (ValueError, TypeError):
                table_issues.append({'code': 'pptx_table_input_invalid',
                    'message': '受控表格结构或来源身份无效，已跳过该表并保留其他内容。'})
        normalized.append({
            "title": slide_title,
            "bullets": bullets,
            "evidenceIds": evidence_ids,
            **({"chartPath": chart_path} if isinstance(chart_path, str) else {}),
            **({'tables': tables} if tables else {}),
        })

    engine_preferences = None
    if preferences is not None:
        from ...preferences.slides_adapter import prepare_slides

        engine_preferences = prepare_slides(preferences, title=title, period=period,
            generated_date=generated_date, filename=output_path.name, slide_count=len(normalized) + 2)
        theme = preferences["theme"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="report-pptx-") as temporary:
        input_path = Path(temporary) / "input.json"
        input_path.write_text(json.dumps({
            "output": str(output_path.resolve()),
            "title": title,
            "period": period,
            "theme": theme,
            "slides": normalized,
            "preferences": engine_preferences,
        }, ensure_ascii=False), encoding="utf-8")
        process = run_bridge("slides", "build-pptx", input_path)
        if process.returncode:
            raise RuntimeError(f"pptx_engine_failed: {process.stderr[-2000:]}")
        try:
            receipt = last_json_line(process.stdout)
        except ValueError as error:
            raise RuntimeError("pptx_engine_receipt_invalid") from error

    content = output_path.read_bytes()
    image_derivations = ()
    image_dpi_warnings = ()
    if preferences is not None:
        charts = preferences.get('charts', {})
        maximum_dpi = charts.get('imageDpi', charts.get('image_dpi', 150)) if isinstance(charts, dict) else 150
        if isinstance(maximum_dpi, int) and not isinstance(maximum_dpi, bool):
            chart_images = receipt.get('chartImages')
            if any(page.get('chartPath') for page in normalized) and not isinstance(chart_images, list):
                image_dpi_warnings = ({'code': 'pptx_chart_image_dpi_receipt_missing',
                    'message': 'PPTX 构建桥接未返回图表对象身份，未调整来源图片。'},)
            else:
                chart_images = tuple(item for item in chart_images or () if isinstance(item, dict))
                try:
                    image_derivations, image_dpi_warnings = _apply_chart_image_dpi(
                        output_path, chart_images, maximum_dpi,
                    )
                except Exception as error:
                    logger.warning('pptx_chart_image_dpi_failed error_type={}', type(error).__name__)
                    image_dpi_warnings = ({'code': 'pptx_chart_image_dpi_readback_failed',
                        'message': '图表图像 DPI 处理或回读未完成，已保留 PPTX 并提示复核。'},)
            content = output_path.read_bytes()
    identity = hashlib.sha256(content).hexdigest()
    if not content or re.fullmatch(SHA256_PATTERN, identity) is None:
        raise RuntimeError("pptx_identity_unavailable")
    presentation = Presentation(str(output_path))
    actual_count = len(presentation.slides)
    expected_count = len(normalized) + (2 if preferences is not None else 1)
    if (receipt.get('slideCount') != actual_count or actual_count < expected_count
            or preferences is None and not any(page.get('tables') for page in normalized)
            and actual_count != expected_count):
        raise RuntimeError("pptx_slide_count_invalid")
    return PptxBuildResult(
        path=output_path.as_posix(),
        size=len(content),
        sha256=identity,
        slide_count=len(presentation.slides),
        issues=(*table_issues, *receipt.get("issues", ()), *image_dpi_warnings, *(
            ({'code': 'pptx_chart_image_dpi_readback_incomplete',
              'message': '部分冻结图表未能从 PPTX 原生图片对象回读 DPI。'} ,)
            if preferences is not None and len(image_derivations) != len(receipt.get('chartImages', ()))
            else ()
        ), *(
            ({'code': 'pptx_chart_image_dpi_exceeded',
              'message': '部分图表图片的实际有效 DPI 仍高于维护上限。'},)
            if any(not item['withinLimit'] for item in image_derivations)
            else ()
        )),
        image_derivations=image_derivations,
    )
