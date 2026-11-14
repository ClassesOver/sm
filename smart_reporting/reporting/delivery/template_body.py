"""以成熟转换/合并库把冻结正文导入模板声明区；不导入 donor 页面布局。"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docxcompose.composer import Composer
from loguru import logger
from lxml import etree
from markdown_it import MarkdownIt
from PIL import Image

from .report_runtime.validation import MAX_IMAGE_BYTES, MAX_MARKDOWN_BYTES, MAX_TOTAL_IMAGE_BYTES

TEMPLATE_BODY_VERSION = 'template-body/4'
TEMPLATE_BODY_RESTORE_VERSIONS = ('template-body/3', 'template-body/2', 'template-body/1')
_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_MARKER = re.compile(r'\[\[(?:/?table|section|claim|citation|analysis):[^\]\r\n]+\]\]')


@dataclass(frozen=True)
class TemplateBodyResult:
    content: bytes
    issues: tuple
    modified_parts: tuple
    binding: dict


def _parts(content):
    with ZipFile(io.BytesIO(content)) as package:
        members = package.infolist()
        if (len(members) > 10000 or len({m.filename for m in members}) != len(members)
                or sum(m.file_size for m in members) > 200 * 1024 * 1024):
            raise ValueError('template package exceeds limits')
        return {m.filename: package.read(m) for m in members}


def _body_target(doc):
    controls = doc.element.body.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]')
    placeholders = [p for p in doc.element.body.xpath('.//w:p[not(ancestor::w:sdt)]')
        if ''.join(p.xpath('.//w:t/text()')).strip() == '{{report_content}}']
    if len(controls) + len(placeholders) != 1:
        raise ValueError('body declaration is missing or ambiguous')
    target = (controls or placeholders)[0]
    if (target.getparent().tag not in {_W + 'body', _W + 'tc'}
            or etree.XPath('ancestor::w:sdt | .//w:sectPr', namespaces={'w': _W[1:-1]})(target)):
        raise ValueError('body declaration is not an independent block')
    if controls and (target.find(_W + 'sdtContent') is None
        or etree.XPath('.//w:sdt', namespaces={'w': _W[1:-1]})(target)):
        raise ValueError('body control is not a simple block')
    return target


def _body_html(markdown, resources):
    from ...preferences.markdown_adapter import (
        strip_navigation,
        strip_signature,
        strip_table_preferences,
    )
    from ...preferences.markdown_captions import restore_image_captions
    from ...preferences.markdown_headings import restore_heading_levels
    from ...preferences.markdown_references import restore_reference_markers

    if len(markdown.encode('utf-8')) > MAX_MARKDOWN_BYTES:
        raise ValueError('body exceeds markdown limit')
    for transform in (strip_signature, restore_heading_levels, restore_reference_markers,
            strip_navigation, strip_table_preferences, restore_image_captions):
        markdown = transform(markdown)
    parser = MarkdownIt('commonmark', {'html': False}).enable('table')
    tokens = parser.parse(markdown)
    leading_title = None
    if (len(tokens) >= 3 and tokens[0].type == 'heading_open' and tokens[0].tag == 'h1'
        and tokens[1].type == 'inline' and all(child.type in {
            'text', 'code_inline', 'strong_open', 'strong_close', 'em_open', 'em_close'}
            for child in tokens[1].children or ())):
        leading_title = ''.join(child.content for child in tokens[1].children or ()
            if child.type in {'text', 'code_inline'})
    total = 0
    seen, images = {}, {}
    for token in tokens:
        for child in token.children or ():
            if child.type == 'text':
                child.content = _MARKER.sub('', child.content)
            elif child.type == 'image':
                source = child.attrGet('src') or ''
                raw = resources.get(source)
                if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_IMAGE_BYTES:
                    raise ValueError('body image is not a bounded frozen resource')
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in {'PNG', 'JPEG'}:
                        raise ValueError('body image must be static PNG/JPEG')
                    suffix = 'png' if image.format == 'PNG' else 'jpg'
                    image.verify()
                if source not in seen:
                    total += len(raw)
                    filename = f'body-image-{len(seen)}.{suffix}'
                    seen[source] = filename
                    images[filename] = raw
                if total > MAX_TOTAL_IMAGE_BYTES:
                    raise ValueError('body images exceed total limit')
                child.attrSet('src', seen[source])
            elif child.type == 'link_open':
                href = child.attrGet('href') or ''
                if not href.startswith('#'):
                    raise ValueError('body link is not a registered internal target')
    return parser.renderer.render(tokens, parser.options, {}), images, leading_title


def _declared_title(document, body_target):
    """仅复用正文前唯一、独立且纯文本的显式总标题槽。"""
    candidates = [p for p in document.element.body.xpath('.//w:p')
        if ''.join(p.xpath('.//w:t/text()')).strip() == '{{report_title}}']
    if len(candidates) != 1:
        return None
    title = candidates[0]
    body = document.element.body
    positions = {node: index for index, node in enumerate(body.iter())}
    if (title.getparent().tag not in {_W + 'body', _W + 'tc'}
        or positions[title] >= positions[body_target]
        or title.xpath('.//w:sectPr|.//w:numPr')
        or any(child.tag not in {_W + 'pPr', _W + 'r'} for child in title)
        or any(child.tag not in {_W + 'rPr', _W + 't'} for run in title.findall(_W + 'r') for child in run)):
        return None
    def hidden(node):
        return node is not None and any(child.tag in {_W + key for key in ('vanish', 'webHidden', 'specVanish')}
            and child.get(_W + 'val') not in {'0', 'false', 'off'} for child in node.iter())
    def revised(node):
        return node is not None and any(child.tag in {_W + key for key in (
            'del', 'ins', 'moveFrom', 'moveTo', 'pPrChange', 'rPrChange', 'tblPrChange',
            'tblGridChange', 'tblPrExChange', 'trPrChange', 'tcPrChange', 'cellDel', 'cellIns', 'cellMerge')}
            for child in node.iter())
    styles = document.styles.element
    if (hidden(title) or revised(title) or hidden(styles.find(_W + 'docDefaults'))
        or document.settings.element.xpath('.//w:documentProtection')):
        return None
    references = title.xpath('.//w:pStyle/@w:val|.//w:rStyle/@w:val')
    references += styles.xpath('./w:style[@w:default="1" or @w:default="true" or @w:default="on"]/@w:styleId')
    ancestor = title.getparent()
    while ancestor is not body:
        if ancestor is None or ancestor.tag not in {_W + 'tbl', _W + 'tr', _W + 'tc'}:
            return None
        properties = ancestor.find(ancestor.tag + 'Pr')
        if hidden(properties) or revised(properties):
            return None
        if ancestor.tag == _W + 'tc' and properties is not None and any(
            node.get(_W + 'val') != 'restart' for tag in ('vMerge', 'hMerge')
            for node in properties.findall(_W + tag)):
            return None
        if ancestor.tag == _W + 'tbl' and revised(ancestor.find(_W + 'tblGrid')):
            return None
        if ancestor.tag == _W + 'tr' and revised(ancestor.find(_W + 'tblPrEx')):
            return None
        if ancestor.tag == _W + 'tbl' and properties is not None:
            references += properties.xpath('./w:tblStyle/@w:val')
        ancestor = ancestor.getparent()
    for identity in references:
        ancestry = set()
        while identity:
            definitions = [node for node in styles.findall(_W + 'style') if node.get(_W + 'styleId') == identity]
            if identity in ancestry or len(definitions) != 1 or hidden(definitions[0]):
                return None
            ancestry.add(identity)
            parent = definitions[0].find(_W + 'basedOn')
            identity = parent.get(_W + 'val') if parent is not None else None
    return title


def _localize_heading_bookmarks(elements):
    """表格后的生成节范围在PDF导入时可能丢失；仅收束donor标题端点。"""
    moved = set()
    for start in [node for node in elements if node.tag == _W + 'bookmarkStart']:
        paragraph = start.getnext()
        ends = [node for element in elements for node in element.iter(_W + 'bookmarkEnd')
            if node.get(_W + 'id') == start.get(_W + 'id')]
        if paragraph is None or paragraph.tag != _W + 'p' or paragraph not in elements or len(ends) != 1:
            raise ValueError('generated heading bookmark has no complete native paragraph target')
        end = ends[0]
        for endpoint in (start, end):
            endpoint.getparent().remove(endpoint)
            moved.add(endpoint)
        paragraph.insert(1 if paragraph.find(_W + 'pPr') is not None else 0, start)
        paragraph.append(end)
    return [node for node in elements if node not in moved]


def _unique_import_ids(elements, original_parts):
    roots = [etree.fromstring(value) for name, value in original_parts.items()
        if name == 'word/document.xml' or re.fullmatch(r'word/(?:header|footer)\d+\.xml', name)]
    used_names = {node.get(_W + 'name') for root in roots for node in root.iter(_W + 'bookmarkStart')}
    used_names.update(node.get(_W + 'anchor') for root in roots for node in root.iter(_W + 'hyperlink')
        if node.get(_W + 'anchor') is not None)
    names = {}
    for element in elements:
        for node in element.iter(_W + 'bookmarkStart'):
            name = node.get(_W + 'name')
            if not name or name in names:
                raise ValueError('imported bookmark name is missing or ambiguous')
            candidate, suffix = name, 1
            while candidate in used_names:
                candidate = f'report_body_{suffix}'
                suffix += 1
            names[name] = candidate
            used_names.add(candidate)
            node.set(_W + 'name', candidate)
    for element in elements:
        for node in element.iter(_W + 'hyperlink'):
            anchor = node.get(_W + 'anchor')
            if anchor is not None:
                if anchor not in names:
                    raise ValueError('body hyperlink has no imported bookmark target')
                node.set(_W + 'anchor', names[anchor])
    for tag in ('bookmarkStart', 'docPr', 'cNvPr'):
        namespace = (_W if tag == 'bookmarkStart' else
            '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}' if tag == 'docPr' else
            '{http://schemas.openxmlformats.org/drawingml/2006/picture}')
        attr = _W + 'id' if tag == 'bookmarkStart' else 'id'
        used = {node.get(attr) for root in roots for node in root.iter(namespace + tag)}
        next_id = max((int(x) for x in used if x and x.isdigit()), default=0) + 1
        mapping = {}
        for element in elements:
            for node in element.iter(namespace + tag):
                mapping[node.get(attr)] = str(next_id)
                node.set(attr, str(next_id))
                next_id += 1
        if tag == 'bookmarkStart':
            for element in elements:
                for node in element.iter(_W + 'bookmarkEnd'):
                    node.set(_W + 'id', mapping[node.get(_W + 'id')])


def _bind_header_targets(document):
    """仅按Pandoc官方AST的精确原identifier绑定，不依赖Word私有编码。"""
    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    nodes = list(walk(document))
    targets = {}
    headers = [node for node in nodes if node.get('t') == 'Header']
    for index, header in enumerate(headers, 1):
        identifier = header['c'][1][0]
        if not identifier or identifier in targets:
            raise ValueError('body header identifier is missing or ambiguous')
        targets[identifier] = 'report_content_heading_' + str(index)
    for link in (node for node in nodes if node.get('t') == 'Link'):
        href = link['c'][-1][0]
        if not href.startswith('#') or unquote(href[1:]) not in targets:
            raise ValueError('body link has no unique local header target')
        link['c'][-1][0] = '#' + targets[unquote(href[1:])]
    for header in headers:
        header['c'][1][0] = targets[header['c'][1][0]]
    return document


def _append_dependency(original, merged, part):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    before, after = etree.fromstring(original, parser), etree.fromstring(merged, parser)
    if dict(before.attrib) != dict(after.attrib):
        raise ValueError('existing dependency root changed: ' + part)
    def key(node):
        return (node.tag, node.get(_W + 'styleId'), node.get(_W + 'numId'), node.get(_W + 'abstractNumId'),
            node.get('Id'), node.get('PartName'), node.get('Extension'))
    old = {key(node): node for node in before}
    actual = {key(node): node for node in after}
    if len(old) != len(before) or len(actual) != len(after):
        raise ValueError('ambiguous dependency entries: ' + part)
    for identity, node in old.items():
        if identity not in actual or etree.tostring(node, method='c14n') != etree.tostring(actual[identity], method='c14n'):
            raise ValueError('existing dependency entry changed: ' + part)
    for identity, node in actual.items():
        if identity not in old:
            before.append(deepcopy(node))
    return etree.tostring(before, encoding='UTF-8', xml_declaration=True, standalone=True)


def project_docx_body(template: bytes, markdown: str, resources, *, report_title=None) -> TemplateBodyResult:
    """失败只返回未投影原模板；调用方继续已有文字填充与非阻断交付。"""
    try:
        original = _parts(template)
        document = Document(io.BytesIO(template))
        target = _body_target(document)
        parent, index = target.getparent(), target.getparent().index(target)
        parent.remove(target)
        host_roots = [document.element, *(etree.fromstring(raw) for name, raw in original.items()
            if name == 'word/styles.xml' or re.fullmatch(r'word/(?:header|footer)\d+\.xml', name))]
        outside_styles = {node.get(_W + 'val') for root in host_roots for node in root.iter()
            if node.tag in {_W + tag for tag in ('pStyle', 'rStyle', 'tblStyle', 'basedOn', 'next', 'link')}}
        outside_numbers = {node.get(_W + 'val') for root in host_roots for node in root.iter(_W + 'numId')}
        relationship_namespace = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
        outside_relationships = {value for node in document.element.iter() for attr, value in node.attrib.items()
            if attr in {relationship_namespace + key for key in ('id', 'embed', 'link')}}
        original_numbering = (etree.fromstring(original['word/numbering.xml'])
            if 'word/numbering.xml' in original else None)
        abstract_references = ({node.get(_W + 'val') for node in original_numbering.iter(_W + 'abstractNumId')}
            if original_numbering is not None else set())
        parent.insert(index, target)
        html, images, leading_title = _body_html(markdown, resources)
        reuse_title = bool(report_title and leading_title == report_title and _declared_title(document, target) is not None)
        pandoc = shutil.which('pandoc')
        if not pandoc:
            raise ValueError('Pandoc is unavailable')
        with tempfile.TemporaryDirectory(prefix='template-body-') as directory:
            root = Path(directory)
            (root / 'template.docx').write_bytes(template)
            (root / 'body.html').write_text(html, encoding='utf-8')
            for filename, data in images.items():
                (root / filename).write_bytes(data)
            ast = subprocess.run([pandoc, '--from=html', '--to=json', 'body.html'],
                cwd=root, capture_output=True, check=True, timeout=120).stdout
            (root / 'body.json').write_text(json.dumps(_bind_header_targets(json.loads(ast)), ensure_ascii=False), encoding='utf-8')
            subprocess.run([pandoc, '--from=json', '--to=docx', '--reference-doc=template.docx',
                '--output=body.docx', 'body.json'], cwd=root, capture_output=True, check=True, timeout=120)
            donor = Document(root / 'body.docx')
        defined_styles = set(donor.styles.element.xpath('./w:style/@w:styleId'))
        missing_styles = set()
        for style in donor.element.body.xpath('.//w:pStyle|.//w:rStyle|.//w:tblStyle'):
            identity = style.get(_W + 'val')
            if identity not in defined_styles:
                missing_styles.add(identity)
        if missing_styles:
            # reference-doc 可缺少 Pandoc 自带的正文/列表/代码样式。
            # 仅补其官方默认定义及依赖；模板已有定义始终优先。
            defaults = subprocess.run([pandoc, '--print-default-data-file=reference.docx'],
                capture_output=True, check=True, timeout=30).stdout
            default_doc = Document(io.BytesIO(defaults))
            default_styles = {node.get(_W + 'styleId'): node for node in default_doc.styles.element}
            while missing_styles:
                identity = missing_styles.pop()
                if identity in defined_styles:
                    continue
                definition = default_styles.get(identity)
                if definition is None:
                    raise ValueError('body donor references an undefined style')
                donor.styles.element.append(deepcopy(definition))
                defined_styles.add(identity)
                missing_styles.update(node.get(_W + 'val') for node in definition
                    if node.tag in {_W + 'basedOn', _W + 'next', _W + 'link'}
                    and node.get(_W + 'val') not in defined_styles)
        if len(donor.sections) != 1 or donor.element.body.xpath('.//w:pPr/w:sectPr'):
            raise ValueError('body donor must not import page sections')
        existing = list(document.element.body)
        snapshots = [deepcopy(element) for element in existing]
        composer = Composer(document)
        composer.insert(composer.append_index(), donor)
        imported = [element for element in document.element.body if element not in existing]
        _unique_import_ids(imported, original)
        # Composer会全局重排对象ID；恢复所有宿主节点，再移动已映射的donor块。
        for element, snapshot in zip(existing, snapshots, strict=True):
            document.element.body.replace(element, snapshot)
        target = _body_target(document)
        if reuse_title:
            title = _declared_title(document, target)
            duplicate = next(node for node in imported if node.tag == _W + 'p')
            prefix = imported[:imported.index(duplicate)]
            starts = [*duplicate.findall(_W + 'bookmarkStart'),
                *(node for node in prefix if node.tag == _W + 'bookmarkStart')]
            ends = [node for element in imported for node in element.iter(_W + 'bookmarkEnd')
                if len(starts) == 1 and node.get(_W + 'id') == starts[0].get(_W + 'id')]
            if (title is None or duplicate.tag != _W + 'p' or len(starts) != 1 or len(ends) != 1
                or any(node.tag != _W + 'bookmarkStart' for node in prefix)
                or ''.join(duplicate.xpath('.//w:t/text()')) != report_title):
                raise ValueError('native title reuse cannot preserve the complete heading bookmark')
            position = 1 if title.find(_W + 'pPr') is not None else 0
            title.insert(position, deepcopy(starts[0]))
            title.append(deepcopy(ends[0]))
            for endpoint in (*starts, *ends):
                endpoint.getparent().remove(endpoint)
            duplicate.getparent().remove(duplicate)
            imported = [node for node in imported if node not in (*starts, *ends, duplicate)]
            if title.getparent().tag == _W + 'tc':
                imported = _localize_heading_bookmarks(imported)
        if target.tag == _W + 'p':
            control, props, tag, content = [OxmlElement(name) for name in ('w:sdt', 'w:sdtPr', 'w:tag', 'w:sdtContent')]
            tag.set(qn('w:val'), 'report_content')
            props.append(tag)
            control.extend((props, content))
            target.getparent().replace(target, control)
        else:
            content = target.find(_W + 'sdtContent')
            for child in list(content):
                content.remove(child)
        content.extend(imported)
        if len(content) and content[-1].tag == _W + 'tbl':
            content.append(OxmlElement('w:p'))
        output = io.BytesIO()
        composer.save(output)
        merged = _parts(output.getvalue())
        def definitions(parts, part, tag, attribute):
            if part not in parts:
                return set()
            return {node.get(attribute) for node in etree.fromstring(parts[part]).findall(tag)}
        for part, tag, attribute, references in (
            ('word/styles.xml', _W + 'style', _W + 'styleId', outside_styles),
            ('word/numbering.xml', _W + 'num', _W + 'numId', outside_numbers),
            ('word/numbering.xml', _W + 'abstractNum', _W + 'abstractNumId', abstract_references),
            ('word/_rels/document.xml.rels', '{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',
                'Id', outside_relationships),
        ):
            added = definitions(merged, part, tag, attribute) - definitions(original, part, tag, attribute)
            if added & references:
                raise ValueError('new body dependency would activate an unresolved outside template reference')
        parts = dict(original)
        for name in ('word/styles.xml', 'word/numbering.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'):
            if name in original and name in merged and original[name] != merged[name]:
                parts[name] = _append_dependency(original[name], merged[name], name)
        parts['word/document.xml'] = merged['word/document.xml']
        for name in merged.keys() - original.keys():
            if not name.startswith('word/media/') and name != 'word/numbering.xml':
                raise ValueError('unsupported new body dependency: ' + name)
            parts[name] = merged[name]
        modified = tuple(name for name, raw in parts.items() if original.get(name) != raw)
        output = io.BytesIO()
        with ZipFile(output, 'w') as package:
            for name, raw in parts.items():
                package.writestr(name, raw)
        return TemplateBodyResult(output.getvalue(), (), modified,
            {'version': TEMPLATE_BODY_VERSION, 'status': 'projected', 'scope': 'declared_body_native_blocks',
                'layoutValidation': 'unverified', 'titleReused': reuse_title})
    except Exception as error:
        logger.warning('report_template_body_projection_unavailable error_type={} reason={}', type(error).__name__, str(error)[:250])
        issue = {'code': 'report_template_body_projection_unavailable',
            'message': '模板正文声明、资源或富文档转换未能完整核验，已保留文字填充结果；富文档排版尚未通过。'}
        return TemplateBodyResult(template, (issue,), (), {'version': TEMPLATE_BODY_VERSION, 'status': 'unverified'})
