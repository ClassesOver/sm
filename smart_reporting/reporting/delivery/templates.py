"""同格式 Office 模板的局部占位符填充；只接受调用方已冻结的内容。"""

from __future__ import annotations

import io
import re
import subprocess
import zipfile
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from lxml import etree

from .office_engine import libreoffice_to_pdf

_PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}


@dataclass(frozen=True)
class TemplateFillResult:
    content: bytes
    issues: tuple[dict[str, Any], ...]
    modified_parts: tuple[str, ...]
    signature_binding: dict[str, Any] | None = None
    body_binding: dict[str, Any] | None = None


def _fill_text_nodes(nodes: list[Any], values: Mapping[str, str]) -> bool:
    """反向替换跨 run 占位符，保留未命中的文字及原 run 格式。"""
    texts = [node.text or "" for node in nodes]
    combined = "".join(texts)
    matches = [match for match in _PLACEHOLDER.finditer(combined) if match.group(1) in values]
    starts, offset = [], 0
    for text in texts:
        starts.append(offset)
        offset += len(text)
    for match in reversed(matches):
        first = next(index for index, text in enumerate(texts)
            if starts[index] <= match.start() < starts[index] + len(text))
        last = next(index for index, text in enumerate(texts)
            if starts[index] < match.end() <= starts[index] + len(text))
        prefix = texts[first][:match.start() - starts[first]]
        suffix = texts[last][match.end() - starts[last]:]
        replacement = values[match.group(1)]
        if first == last:
            texts[first] = prefix + replacement + suffix
        else:
            texts[first] = prefix + replacement
            for index in range(first + 1, last):
                texts[index] = ""
            texts[last] = suffix
    if matches:
        for node, text in zip(nodes, texts, strict=True):
            node.text = text
            if text.startswith(" ") or text.endswith(" "):
                node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return bool(matches)


def _text_groups(root: Any, template_format: str) -> list[list[Any]]:
    if template_format == "docx":
        return [paragraph.xpath(".//w:t", namespaces=_NAMESPACES)
            for paragraph in root.xpath(".//w:p", namespaces=_NAMESPACES)]
    if template_format == "pptx":
        return [paragraph.xpath(".//a:t", namespaces=_NAMESPACES)
            for paragraph in root.xpath(".//a:p", namespaces=_NAMESPACES)]
    return [container.xpath(".//s:t", namespaces=_NAMESPACES)
        for container in root.xpath(".//s:si | .//s:is", namespaces=_NAMESPACES)]


def _supported_part(name: str, template_format: str) -> bool:
    if template_format == "docx":
        return name == "word/document.xml" or bool(re.fullmatch(r"word/(?:header|footer)\d+\.xml", name))
    if template_format == "pptx":
        return bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", name))
    return name == "xl/sharedStrings.xml" or bool(re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))


def _bind_docx_signature(root: Any, signature: Mapping[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """仅绑定明确声明的正文落款位置；其余模板文字不作语义猜测。"""
    namespace = "{" + _NAMESPACES["w"] + "}"
    unusable = root.xpath(
        './/w:sdt[w:sdtPr/w:tag[@w:val="report_signature"] and '
        '(not(parent::w:body or parent::w:tc) or ancestor::w:sdt)]', namespaces=_NAMESPACES)
    targets = root.xpath(
        './/w:sdt[(parent::w:body or parent::w:tc) and not(ancestor::w:sdt) '
        'and w:sdtPr/w:tag[@w:val="report_signature"]]/w:sdtContent'
        ' | .//w:p[not(ancestor::w:sdt) and not(.//w:sdt)]', namespaces=_NAMESPACES)
    targets = [target for target in targets if target.tag == namespace + 'sdtContent'
        or ''.join(target.xpath('.//w:t/text()', namespaces=_NAMESPACES)).strip() == '{{report_signature}}']
    unusable = [node for node in unusable if not any(target in node.iterancestors() for target in targets)]
    issues = []
    if unusable:
        issues.append({'code': 'report_template_signature_slot_unusable',
            'message': '模板落款声明不是可独立排版的正文块，已保留原文并使用合法正文位置，请复核模板。'})
    if len(targets) > 1:
        issues.append({'code': 'report_template_signature_multiple_slots',
            'message': '模板声明了多个正文落款位置，已保留首个声明并清除其余重复落款，需复核布局。'})
        for duplicate in targets[1:]:
            duplicate.getparent().remove(duplicate)
        targets = targets[:1]
    lines = [signature['signer'], signature['date'], *signature.get('description', '').splitlines()]
    target = targets[0] if targets else None
    is_control = target is not None and target.tag == namespace + 'sdtContent'
    sample = (target.find(namespace + 'p') if is_control else target) if target is not None else None
    properties = sample.find(namespace + 'pPr') if sample is not None else None
    run_properties = sample.find('.//' + namespace + 'rPr') if sample is not None else None
    paragraphs = []
    for index, line in enumerate(lines):
        paragraph = etree.Element(namespace + 'p')
        props = deepcopy(properties) if properties is not None else etree.Element(namespace + 'pPr')
        for existing in list(props):
            if existing.tag in {namespace + 'keepNext', namespace + 'keepLines'}:
                props.remove(existing)
        if properties is None:
            align = etree.SubElement(props, namespace + 'jc')
            align.set(namespace + 'val', 'right')
        etree.SubElement(props, namespace + 'keepLines')
        if index < len(lines) - 1:
            etree.SubElement(props, namespace + 'keepNext')
        paragraph.append(props)
        run = etree.SubElement(paragraph, namespace + 'r')
        if run_properties is not None:
            run.append(deepcopy(run_properties))
        text = etree.SubElement(run, namespace + 't')
        text.text = line
        text.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        paragraphs.append(paragraph)
    if is_control:
        for child in list(target):
            target.remove(child)
        target.extend(paragraphs)
    elif target is not None:
        parent = target.getparent()
        position = parent.index(target)
        parent.remove(target)
        for offset, paragraph in enumerate(paragraphs):
            parent.insert(position + offset, paragraph)
    else:
        body = root.find(namespace + 'body')
        section = body.find(namespace + 'sectPr')
        position = body.index(section) if section is not None else len(body)
        for offset, paragraph in enumerate(paragraphs):
            body.insert(position + offset, paragraph)
    return issues, {'placement': 'declared_template_slot' if target is not None else 'body_end',
        'layoutSource': 'template' if target is not None else 'generated_fallback',
        'templateSampleStatus': 'preserved_for_review' if unusable else 'replaced' if target is not None else 'no_declared_slot'}


def _workbook_signature_clips(content: bytes, sheet_name: str, column: str, top: int, lines: list[str]) -> bool:
    """沿用工作簿字体实测方式，仅拒绝可证实放不下的不换行落款。"""
    from openpyxl import load_workbook
    from PIL import ImageFont

    workbook = load_workbook(io.BytesIO(content))
    sheet = workbook[sheet_name]
    width = sheet.sheet_format.defaultColWidth or 8.43
    column_index = sheet[f'{column}{top}'].column
    dimension = next((item for item in sheet.column_dimensions.values()
        if item.min <= column_index <= item.max), None)
    if dimension is not None:
        if dimension.hidden:
            return True
        width = dimension.width
    fonts = {}

    def measured_font(font):
        face = (font.name or 'Calibri') + (':style=Bold' if font.bold else '')
        key = (face, font.sz or 11)
        if key not in fonts:
            path = subprocess.run(['fc-match', '-f', '%{file}', face],
                capture_output=True, text=True, check=True).stdout
            fonts[key] = ImageFont.truetype(path, round(key[1] * 4))
        return fonts[key]

    # Excel 列宽以默认字体的 0 字形计量，减去单元格内边距。
    available = width * measured_font(workbook._fonts[0]).getlength('0') / 4 - 4
    for offset, line in enumerate(lines):
        cell = sheet[f'{column}{top + offset}']
        if not cell.alignment.wrap_text and not cell.alignment.shrink_to_fit:
            if measured_font(cell.font).getlength(line) / 4 > available:
                return True
    return False


def _append_workbook_signature(content: bytes, signature: Mapping[str, str]) -> tuple[bytes, str, list[dict[str, Any]], dict[str, Any]]:
    """复用引擎追加原生说明页，仅修改新增页，保留业务公式及其缓存。"""
    from .xlsx import inspect_workbook, patch_workbook

    model = inspect_workbook(content)
    issues = []
    declared = [entry for entry in model.get('definedNames', []) if entry['name'].casefold() == 'report_signature']
    sample_status = 'preserved_for_review' if declared else 'no_declared_slot'
    if declared:
        try:
            from openpyxl.utils.cell import get_column_letter, range_boundaries

            reference = declared[0]['refersTo']
            match = re.fullmatch(r"(?:'((?:[^']|'')+)'|([^!]+))!(\$?[A-Z]+\$?[1-9][0-9]*)(?::(\$?[A-Z]+\$?[1-9][0-9]*))?", reference)
            if len(declared) != 1 or match is None:
                raise ValueError('模板落款命名区域必须指向单一有效区域')
            name = (match[1] or match[2]).replace("''", "'")
            left, top, right, bottom = range_boundaries(match[3] + ':' + (match[4] or match[3]))
            lines = [signature['signer'], signature['date'], *signature.get('description', '').splitlines()]
            sheet = next((sheet for sheet in model['sheets'] if sheet['name'] == name), None)
            if sheet is None or right != left or bottom - top + 1 < len(lines) or bottom - top > 100:
                raise ValueError('模板落款命名区域需为足够容纳署名、日期和说明的单列区域')
            column = match[3].replace('$', '').rstrip('0123456789')
            if any(sheet['cells'].get(f'{column}{row}', {}).get('formula') for row in range(top, bottom + 1)):
                raise ValueError('模板落款命名区域不得覆盖公式')
            edits = [{'sheetName': name, 'row': row - 1, 'column': left - 1, 'writeValue': True,
                'cell': {'value': lines[row - top] if row - top < len(lines) else None}}
                for row in range(top, bottom + 1)]
            # 保留原打印范围并扩至落款；没有范围时包含所有已用列，不能裁掉业务内容。
            print_left, print_top, print_right, print_bottom = range_boundaries(
                sheet.get('printArea') or sheet.get('dimension') or 'A1')
            print_area = (f'{get_column_letter(min(print_left, left))}{min(print_top, top)}:'
                f'{get_column_letter(max(print_right, right))}{max(print_bottom, bottom)}')
            operations = [{'kind': 'applyCellEdits', 'edits': edits},
                {'kind': 'applyPageSetups', 'setups': [{'sheetName': name, 'printArea': print_area}]}]
            try:
                clips = _workbook_signature_clips(content, name, column, top, lines)
            except (OSError, subprocess.SubprocessError):
                issues.append({'code': 'report_template_signature_measurement_unavailable',
                    'message': '模板落款字体测量不可用，未确认原区域容量，已保留原区域并新增独立落款说明页；原样例署名和日期可能仍在，请复核模板。'})
            else:
                if clips:
                    issues.append({'code': 'report_template_signature_range_small',
                        'message': '模板落款区域列宽不足以显示当前署名或日期，已清除该处样例并使用独立落款说明页，业务列宽保持不变。'})
                    content = patch_workbook(content, [{'kind': 'applyCellEdits', 'edits': [
                        {**edit, 'cell': {'value': None}} for edit in edits]}])
                    sample_status = 'cleared'
                else:
                    return patch_workbook(content, operations), name, issues, {
                        'placement': 'declared_named_range', 'layoutSource': 'template',
                        'templateSampleStatus': 'replaced', 'sheetName': name, 'cellRange': reference}
        except ValueError:
            issues.append({'code': 'report_template_signature_range_unusable',
                'message': '模板落款命名区域无法安全使用，已保留原区域并新增独立落款说明页，请复核模板。'})
    names = [sheet['name'] for sheet in model['sheets']]
    occupied = {name.casefold() for name in names}
    name, suffix = '报告落款', 2
    while name.casefold() in occupied:
        name, suffix = f'报告落款{suffix}', suffix + 1
    lines = ['报告落款', signature['signer'], signature['date'], *signature.get('description', '').splitlines()]
    operations = [
        {'kind': 'applySheetEdits', 'plan': {'renames': [], 'removals': [],
            'additions': [{'name': name}], 'order': [*names, name]}},
        {'kind': 'applyCellEdits', 'edits': [{'sheetName': name, 'row': index, 'column': 0,
            'writeValue': True, 'cell': {'value': line}, 'style': {'fontFamily': 'Noto Sans CJK SC',
                'fontSize': 14 if index == 0 else 11, 'bold': index == 0,
                'horizontalAlignment': 'right', 'wrapText': True}}
            for index, line in enumerate(lines)]},
        {'kind': 'applyColumnWidths', 'sheetName': name, 'entries': [{'index': 0, 'widthChars': 65}]},
        {'kind': 'applyRowHeights', 'sheetName': name,
            'entries': [{'index': index, 'heightPoints': 36} for index in range(len(lines))]},
        {'kind': 'applyPageSetups', 'setups': [{'sheetName': name, 'paperSize': 9,
            'orientation': 'portrait', 'fitToPage': True, 'fitToWidth': 1, 'fitToHeight': 1,
            'printArea': f'A1:A{len(lines)}'}]},
    ]
    return patch_workbook(content, operations), name, issues, {
        'placement': 'signature_sheet', 'layoutSource': 'generated_fallback',
        'templateSampleStatus': sample_status, 'sheetName': name, 'cellRange': f'A1:A{len(lines)}'}


def fill_report_template(
    template: bytes,
    *,
    template_format: str,
    delivery_format: str,
    values: Mapping[str, str],
    signature: Mapping[str, str] | None = None,
    body_resources: Mapping[str, bytes] | None = None,
) -> TemplateFillResult:
    """复制模板并更新 ``{{name}}``；PDF 只通过现有 Office 转换生成。

    占位符的值必须来自服务端冻结的成稿或数据库结果，本函数不从模板取数。
    未支持的 Office 对象原样保留并告警，不声称任意对象无损编辑。
    """
    if template_format not in {"docx", "xlsx", "pptx"}:
        raise ValueError("模板填充仅支持 DOCX、XLSX、PPTX")
    if delivery_format not in {template_format, "pdf"}:
        raise ValueError("Office 交付必须使用同格式模板")
    if any(not isinstance(value, str) for value in values.values()):
        raise ValueError("模板值必须是已冻结的文本")
    if signature is not None:
        if (template_format not in {'docx', 'xlsx', 'pptx'} or not signature.get('signer', '').strip()
                or not signature.get('date', '').strip() or any(not isinstance(value, str) for value in signature.values())):
            raise ValueError("模板落款需要支持的 Office 格式、署名和冻结日期")
        from ...preferences.markdown_adapter import strip_signature

        values = {**values, 'report_content': strip_signature(values.get('report_content', ''))}
    modified, issues, unresolved = [], [], set()
    signature_binding = None
    body_binding = None
    if template_format == 'docx' and 'report_content' in values:
        from .template_body import project_docx_body

        projected = project_docx_body(template, values['report_content'], body_resources or {},
            report_title=values.get('report_title'))
        template = projected.content
        body_binding = projected.binding
        modified.extend(projected.modified_parts)
        issues.extend(projected.issues)
    if signature is not None and template_format == 'pptx':
        from .template_slides import bind_slide_signature

        template, slide_parts, signature_issues, signature_binding = bind_slide_signature(template, signature)
        modified.extend(slide_parts)
        issues.extend(signature_issues)
    output = io.BytesIO()
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with zipfile.ZipFile(io.BytesIO(template)) as source, zipfile.ZipFile(output, "w") as target:
        members = source.infolist()
        if len(members) > 10000 or sum(member.file_size for member in members) > 200 * 1024 * 1024:
            raise ValueError("模板展开内容超过限制")
        for member in members:
            content = source.read(member)
            if _supported_part(member.filename, template_format):
                root = etree.fromstring(content, parser)
                signature_bound = signature is not None and member.filename == 'word/document.xml'
                groups = _text_groups(root, template_format)
                if template_format == 'docx' and body_binding and body_binding['status'] == 'projected':
                    groups = [nodes for nodes in groups if not any(node.xpath(
                        'ancestor::w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]', namespaces=_NAMESPACES) for node in nodes)]
                if signature_bound:
                    signature_issues, signature_binding = _bind_docx_signature(root, signature)
                    issues.extend(signature_issues)
                    groups = [nodes for nodes in groups if nodes and root in nodes[0].iterancestors()
                        and not any(node.xpath('ancestor::w:sdt[w:sdtPr/w:tag[@w:val="report_signature"]]',
                            namespaces=_NAMESPACES) for node in nodes)]
                if signature is not None and template_format == 'pptx':
                    groups = [nodes for nodes in groups if nodes and not any(
                        ancestor.tag.endswith('}sp') and ancestor.xpath('.//*[local-name()="cNvPr"][@name="report_signature"]')
                        for ancestor in nodes[0].iterancestors())] if groups else []
                changed = signature_bound
                for nodes in groups:
                    changed = _fill_text_nodes(nodes, values) or changed
                    unresolved.update(match.group(1) for match in _PLACEHOLDER.finditer(
                        "".join(node.text or "" for node in nodes)))
                if changed:
                    content = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                    modified.append(member.filename)
            elif member.filename.endswith(".xml") and b"{{" in content:
                issues.append({"code": "report_template_unsupported_object",
                    "message": "模板非正文对象中的占位符未修改。", "part": member.filename})
            target.writestr(member, content)
    if unresolved:
        issues.insert(0, {"code": "report_template_unresolved_placeholder",
            "message": "模板占位符缺少已冻结的内容，已保留原值。", "placeholders": sorted(unresolved)})
    if not modified and not unresolved:
        issues.append({"code": "report_template_no_target",
            "message": "模板没有可更新的文本占位符，需人工核对模板内容。"})
    content = output.getvalue()
    if signature is not None and template_format == 'xlsx':
        content, sheet_name, signature_issues, signature_binding = _append_workbook_signature(content, signature)
        issues.extend(signature_issues)
        modified.append('worksheet:' + sheet_name)
    if delivery_format == "pdf":
        content = libreoffice_to_pdf(content, suffix=f".{template_format}", timeout=120)
    if signature_binding is not None:
        signature_binding.update(undeclaredSamples='not_assessed',
            issueCodes=[issue['code'] for issue in issues if issue['code'].startswith('report_template_signature_')])
    return TemplateFillResult(content=content, issues=tuple(issues), modified_parts=tuple(modified),
        signature_binding=signature_binding, body_binding=body_binding)
