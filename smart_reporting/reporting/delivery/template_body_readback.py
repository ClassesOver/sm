"""从冻结Markdown和实际OOXML独立核验正文，不读取投影器回执。"""

import re
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import unquote
from zipfile import BadZipFile, ZipFile

from lxml import etree
from markdown_it import MarkdownIt
from PIL import Image

from ...preferences.markdown_adapter import (
    strip_navigation,
    strip_signature,
    strip_table_preferences,
)
from ...preferences.markdown_captions import restore_image_captions
from ...preferences.markdown_headings import restore_heading_levels
from ...preferences.markdown_references import restore_reference_markers

_NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
_W = '{' + _NS['w'] + '}'
_R = '{' + _NS['r'] + '}'
_MARKER = re.compile(r'\[\[(?:/?table|section|claim|citation|analysis):[^\]\r\n]+\]\]')


def _xml(raw):
    return etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))


def _package(content):
    with ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        if (len(entries) > 10000 or len({item.filename for item in entries}) != len(entries)
            or sum(item.file_size for item in entries) > 200 * 1024 * 1024):
            raise ValueError('invalid package limits or duplicate parts')
        return {item.filename: archive.read(item) for item in entries}


def _inline(token):
    text, images, links, offsets = [], [], [], []
    opened = None
    for child in token.children or []:
        if child.type in ('text', 'code_inline'):
            text.append(_MARKER.sub('', child.content) if child.type == 'text' else child.content)
        elif child.type == 'softbreak':
            text.append(' ')
        elif child.type == 'hardbreak':
            text.append('\n')
        elif child.type == 'image':
            images.append(child.attrGet('src'))
            offsets.append(len(''.join(text)))
        elif child.type == 'link_open':
            if opened is not None:
                raise ValueError('nested source hyperlink')
            opened = {'target': child.attrGet('href'), 'text': '', 'offset': len(''.join(text))}
            links.append(opened)
        elif child.type == 'link_close':
            if opened is None:
                raise ValueError('source hyperlink has no opening')
            opened['text'] = ''.join(text)[opened['offset']:]
            opened = None
        elif child.type not in ('strong_open', 'strong_close', 'em_open', 'em_close'):
            raise ValueError('unsupported inline node: ' + child.type)
    if opened is not None:
        raise ValueError('source hyperlink is not closed')
    return ''.join(text), images, links, offsets


def _expected(markdown):
    """解析全部源token；不复用生成器的HTML、块计划或关系映射。"""
    # 复用已核可逆来源解码；对象预期仍由本reader独立解析，不调用投影器。
    for restore in (strip_signature, restore_heading_levels, restore_reference_markers,
        strip_navigation, strip_table_preferences, restore_image_captions):
        markdown = restore(markdown)
    tokens = MarkdownIt('commonmark', {'html': False}).enable('table').parse(markdown)
    result, lists, index = [], [], 0
    while index < len(tokens):
        token = tokens[index]
        if token.type in ('bullet_list_open', 'ordered_list_open'):
            lists.append({'format': 'bullet' if token.type == 'bullet_list_open' else 'decimal',
                'start': int(token.attrGet('start') or 1), 'seen': False})
        elif token.type in ('bullet_list_close', 'ordered_list_close'):
            lists.pop()
        elif token.type in ('heading_open', 'paragraph_open'):
            text, images, links, offsets = _inline(tokens[index + 1])
            kind = 'heading' if token.type == 'heading_open' else 'list' if lists else 'paragraph'
            if text or images or links:
                result.append({'kind': kind, 'text': text, 'images': images, 'links': links, 'imageOffsets': offsets,
                    **({'level': int(token.tag[1:])} if kind == 'heading' else {}),
                    **({'level': len(lists) - 1, 'numbering': lists[-1]['format'],
                        **({'start': lists[-1]['start']} if lists[-1]['format'] == 'decimal' and not lists[-1]['seen'] else {})}
                        if kind == 'list' else {})})
                if kind == 'list':
                    lists[-1]['seen'] = True
            index += 2
        elif token.type == 'table_open':
            rows, row = [], None
            while tokens[index].type != 'table_close':
                item = tokens[index]
                if item.type == 'tr_open':
                    row = []
                    rows.append(row)
                elif item.type in ('th_open', 'td_open'):
                    text, images, links, _ = _inline(tokens[index + 1])
                    if images or links:
                        raise ValueError('table cell image or hyperlink not supported')
                    row.append(text)
                index += 1
            result.append({'kind': 'table', 'rows': rows})
        elif token.type in ('fence', 'code_block'):
            result.append({'kind': 'code', 'text': token.content.rstrip('\n'), 'images': [], 'links': [], 'imageOffsets': []})
        elif token.type not in ('list_item_open', 'list_item_close'):
            raise ValueError('unsupported block node: ' + token.type)
        index += 1
    return result


def expected_body_text(markdown):
    """PDF可见文字预期；仅供抽样，不能证明对象边界或布局。"""
    return '\n'.join('\n'.join('\t'.join(row) for row in item['rows']) if item['kind'] == 'table'
        else item['text'] for item in _expected(markdown))


def _value(node, local):
    child = node.find(_W + local) if node is not None else None
    return child.get(_W + 'val') if child is not None else None


def _style_chain(style_id, styles, used):
    seen = set()
    while style_id:
        if style_id in seen or style_id not in styles:
            raise ValueError('missing or cyclic style dependency')
        seen.add(style_id)
        used.add(style_id)
        style = styles[style_id]
        yield style
        style_id = _value(style, 'basedOn')


def _property(nodes, local):
    for node in nodes:
        value = node.find(_W + local) if node is not None else None
        if value is not None:
            return value.get(_W + 'val') not in ('0', 'false', 'off')
    return False


def _native_text(node, stop=None):
    text = ''
    for child in node.iter():
        if child == stop:
            break
        if child.tag == _W + 't':
            text += child.text or ''
        elif child.tag == _W + 'tab':
            text += '\t'
        elif child.tag in (_W + 'br', _W + 'cr'):
            text += '\n'
    return text


def _paragraph(paragraph, styles, default_style, defaults, numbering, scope, parts, resources):
    if any(child.tag not in {_W + name for name in ('pPr', 'r', 'hyperlink', 'bookmarkStart', 'bookmarkEnd')}
        for child in paragraph):
        raise ValueError('unsupported paragraph object')
    ppr = paragraph.find(_W + 'pPr')
    style_id = _value(ppr, 'pStyle') or default_style
    chain = list(_style_chain(style_id, styles, scope['styleIds'])) if style_id else []
    properties = [ppr, *(style.find(_W + 'pPr') for style in chain)]
    outline = next((_value(props, 'outlineLvl') for props in properties if _value(props, 'outlineLvl') is not None), None)
    level = int(outline) + 1 if outline is not None and int(outline) < 9 else None
    num = next((props.find(_W + 'numPr') for props in properties
        if props is not None and props.find(_W + 'numPr') is not None), None)
    kind = 'heading' if level else 'list' if num is not None else 'paragraph'
    result = {'kind': kind, 'text': '', 'images': [], 'links': [], 'imageOffsets': []}
    if level:
        result['level'] = level
    if num is not None:
        num_id, depth = _value(num, 'numId'), int(_value(num, 'ilvl') or '0')
        nums = numbering.findall(_W + 'num') if numbering is not None else []
        defined = [item for item in nums if item.get(_W + 'numId') == num_id]
        if len(defined) != 1:
            raise ValueError('missing or duplicate list numbering')
        abstract_id = _value(defined[0], 'abstractNumId')
        abstracts = [item for item in numbering.findall(_W + 'abstractNum') if item.get(_W + 'abstractNumId') == abstract_id]
        levels = abstracts[0].findall(_W + 'lvl') if len(abstracts) == 1 else []
        levels = [item for item in levels if item.get(_W + 'ilvl') == str(depth)]
        if len(levels) != 1:
            raise ValueError('missing or duplicate abstract list level')
        result.update(level=depth, numbering=_value(levels[0], 'numFmt'))
        identity = (num_id, depth)
        if result['numbering'] == 'decimal' and identity not in scope['_seenLists']:
            overrides = [entry for entry in defined[0].findall(_W + 'lvlOverride')
                if entry.get(_W + 'ilvl') == str(depth)]
            if len(overrides) > 1:
                raise ValueError('duplicate list start override')
            start = _value(overrides[0], 'startOverride') if overrides else None
            result['start'] = int(start or _value(levels[0], 'start') or '1')
        scope['_seenLists'].add(identity)
        scope['numberingIds'].add(num_id)
        scope['abstractNumberingIds'].add(abstract_id)
    relationships = scope['_relationships']
    for run in paragraph.xpath('.//w:r', namespaces=_NS):
        if any(child.tag not in {_W + name for name in ('rPr', 't', 'tab', 'br', 'cr', 'drawing', 'lastRenderedPageBreak')}
            for child in run):
            raise ValueError('unsupported run object')
        rpr = run.find(_W + 'rPr')
        rstyle = _value(rpr, 'rStyle')
        run_chain = list(_style_chain(rstyle, styles, scope['styleIds'])) if rstyle else []
        effective = [rpr, *(style.find(_W + 'rPr') for style in run_chain),
            *(style.find(_W + 'rPr') for style in chain), defaults]
        if any(_property(effective, name) for name in ('vanish', 'webHidden', 'specVanish')):
            raise ValueError('hidden body text or object')
        for child in run:
            if child.tag == _W + 't':
                result['text'] += child.text or ''
            elif child.tag == _W + 'tab':
                result['text'] += '\t'
            elif child.tag in (_W + 'br', _W + 'cr'):
                result['text'] += '\n'
    for picture in paragraph.xpath('.//a:blip', namespaces=_NS):
        relationship_id = picture.get(_R + 'embed')
        relation = relationships.get(relationship_id)
        if (picture.get(_R + 'link') or relation is None or relation.get('TargetMode') == 'External'
            or not relation.get('Type', '').endswith('/image')):
            raise ValueError('unverified body image relationship')
        target = relation.get('Target', '')
        path = PurePosixPath('word') / target
        if target.startswith('/') or '..' in path.parts or '\\' in target or str(path) not in parts:
            raise ValueError('missing or invalid image target')
        media = str(path)
        content_types = scope['_contentTypes']
        declared = next((entry.get('ContentType') for entry in content_types
            if entry.get('PartName') == '/' + media), None) or next((entry.get('ContentType') for entry in content_types
            if entry.get('Extension') == path.suffix.lstrip('.')), None)
        if declared not in ('image/png', 'image/jpeg'):
            raise ValueError('unverified static image content type')
        data = parts[media]
        with Image.open(BytesIO(data)) as image:
            if image.format not in ('PNG', 'JPEG') or declared != ('image/png' if image.format == 'PNG' else 'image/jpeg'):
                raise ValueError('image media differs from declared static type')
            image.verify()
        matched = [name for name, raw in resources.items() if raw == data]
        if not matched:
            raise ValueError('body image differs from frozen image bytes')
        result['images'].append(data)
        position = 0
        for node in paragraph.iter():
            if node == picture:
                break
            if node.tag == _W + 't':
                position += len(node.text or '')
            elif node.tag in (_W + 'tab', _W + 'br', _W + 'cr'):
                position += 1
        result['imageOffsets'].append(position)
        scope['relationshipIds'].add(relationship_id)
        scope['mediaParts'].add(media)
    for link in paragraph.xpath('.//w:hyperlink', namespaces=_NS):
        relationship_id = link.get(_R + 'id')
        anchor = link.get(_W + 'anchor')
        if any(child.tag not in {_W + 'r', _W + 'bookmarkStart', _W + 'bookmarkEnd'} for child in link):
            raise ValueError('unsupported hyperlink child')
        if anchor is not None:
            if not anchor or relationship_id is not None or link.get(_W + 'docLocation'):
                raise ValueError('local hyperlink has ambiguous target')
            target = {'anchor': anchor}
        else:
            relation = relationships.get(relationship_id)
            if relation is None or not relation.get('Type', '').endswith('/hyperlink'):
                raise ValueError('unverified hyperlink relationship')
            target = relation.get('Target')
            scope['relationshipIds'].add(relationship_id)
        result['links'].append({'target': target, 'text': _native_text(link),
            'offset': len(_native_text(paragraph, stop=link))})
    drawings = paragraph.xpath('.//w:drawing', namespaces=_NS)
    if (len(drawings) != len(result['images'])
        or any(len(node.xpath('.//a:blip', namespaces=_NS)) != 1 for node in drawings)):
        raise ValueError('drawing is not exactly one verified picture')
    return result


def _bookmarks(root, body):
    starts = root.xpath('.//w:bookmarkStart', namespaces=_NS)
    ends = root.xpath('.//w:bookmarkEnd', namespaces=_NS)
    ids = [node.get(_W + 'id') for node in starts]
    names = [node.get(_W + 'name') for node in starts]
    if (None in ids or None in names or len(set(ids)) != len(ids) or len(set(names)) != len(names)):
        raise ValueError('duplicate or incomplete bookmark identity')
    positions = {node: index for index, node in enumerate(root.iter())}
    for node in body.xpath('.//w:bookmarkStart|.//w:bookmarkEnd', namespaces=_NS):
        identity = node.get(_W + 'id')
        matching_starts = [item for item in starts if item.get(_W + 'id') == identity]
        matching_ends = [item for item in ends if item.get(_W + 'id') == identity]
        if (len(matching_starts) != 1 or len(matching_ends) != 1
            or body not in matching_starts[0].iterancestors() or body not in matching_ends[0].iterancestors()
            or positions[matching_starts[0]] >= positions[matching_ends[0]] or len(node)):
            raise ValueError('body bookmark is not a complete local ordered pair')


class _UnknownSourceAnchor(ValueError):
    """无法从支持范围内的冻结标题独立定位源目标。"""


def _source_anchor_targets(expected):
    targets = {}
    unknown_heading = False
    for index, block in enumerate(expected):
        if block['kind'] != 'heading':
            continue
        text = block['text']
        # 只核可无歧义解析的字词标题；标点/显式ID等复杂约定不猜测。
        if not text or not text[0].isalpha() or not re.fullmatch(r'[\w \t-]+', text):
            unknown_heading = True
            continue
        base = re.sub(r'\s+', '-', text).lower()
        candidate, suffix = base, 1
        while candidate in targets:
            candidate = base + '-' + str(suffix)
            suffix += 1
        targets[candidate] = index
    for block in expected:
        for link in block.get('links', []):
            target = link['target'] or ''
            if target.startswith('#') and (unknown_heading or unquote(target[1:]) not in targets or not link['text']):
                raise _UnknownSourceAnchor('冻结链接缺少可独立定位的简单标题目标：' + target)
    return targets


def _resolve_internal_links(expected, actual, body, nodes, source_targets, title=None):
    """按目标块身份对照，不把实际bookmark名字或writer重命名回执当源身份。"""
    positions = {node: index for index, node in enumerate(body.getroottree().getroot().iter())}
    regions = [body, *([title] if title is not None else [])]
    starts = {node.get(_W + 'name'): node for region in regions
        for node in region.xpath('.//w:bookmarkStart', namespaces=_NS)}
    ends = {node.get(_W + 'id'): node for region in regions
        for node in region.xpath('.//w:bookmarkEnd', namespaces=_NS)}
    evidence = []
    for block_index, (source, rendered) in enumerate(zip(expected, actual)):
        source_links, actual_links = source.get('links', []), rendered.get('links', [])
        if len(source_links) != len(actual_links):
            raise ValueError('native hyperlink count differs from source')
        for source_link, actual_link in zip(source_links, actual_links, strict=True):
            href = source_link['target'] or ''
            if not href.startswith('#'):
                continue
            target_index = source_targets[unquote(href[1:])]
            anchor = actual_link['target']
            if not isinstance(anchor, dict) or anchor.get('anchor') not in starts:
                raise ValueError('local hyperlink target is not a unique bookmark in this body slot')
            start = starts[anchor['anchor']]
            ending = ends[start.get(_W + 'id')]
            target_node = next((node for node in start.iterancestors() if node in nodes), None)
            if target_node is None:
                target_node = next((node for node in nodes if positions[node] > positions[start]), None)
            if (target_node is None or start.getparent() not in (body, target_node)
                or nodes.index(target_node) != target_index or target_index >= len(actual)
                or actual[target_index]['kind'] != 'heading'):
                raise ValueError('local hyperlink points to a different native heading block')
            original_target, native_target = expected[target_index], actual[target_index]
            texts = target_node.xpath('.//w:t', namespaces=_NS)
            if (not texts or positions[start] >= positions[texts[0]] or positions[ending] <= positions[texts[-1]]
                or original_target['text'] != native_target['text'] or original_target['level'] != native_target['level']):
                raise ValueError('local bookmark does not cover the corresponding full native heading')
            name = anchor['anchor']
            source_link['target'] = actual_link['target'] = {'headingBlock': target_index}
            evidence.append({'sourceBlock': block_index, 'sourceFragment': href, 'targetBlock': target_index,
                'targetText': original_target['text'], 'targetLevel': original_target['level'], 'actualBookmark': name})
    return evidence


def _visible_title_path(title, body, parts):
    """独立检查标题祖先与可见性；路径只由真实原生节点推导。"""
    if title.getparent().tag not in {_W + 'body', _W + 'tc'}:
        raise ValueError('title is not an independent native paragraph')
    settings = _xml(parts['word/settings.xml']) if 'word/settings.xml' in parts else None
    if settings is not None and settings.xpath('.//w:documentProtection', namespaces=_NS):
        raise ValueError('protected title cannot be reused')
    def hidden(node):
        return node is not None and any(item.tag in {_W + name for name in ('vanish', 'webHidden', 'specVanish')}
            and item.get(_W + 'val') not in {'0', 'false', 'off'} for item in node.iter())
    def revised(node):
        return node is not None and any(item.tag in {_W + name for name in (
            'del', 'ins', 'moveFrom', 'moveTo', 'pPrChange', 'rPrChange', 'tblPrChange',
            'tblGridChange', 'tblPrExChange', 'trPrChange', 'tcPrChange', 'cellDel', 'cellIns', 'cellMerge')}
            for item in node.iter())
    styles_root = _xml(parts['word/styles.xml'])
    definitions = styles_root.findall(_W + 'style')
    styles = {item.get(_W + 'styleId'): item for item in definitions}
    if (len(styles) != len(definitions) or hidden(title) or revised(title)
        or hidden(styles_root.find(_W + 'docDefaults'))):
        raise ValueError('title visibility or styles are ambiguous')
    references = title.xpath('.//w:pStyle/@w:val|.//w:rStyle/@w:val', namespaces=_NS)
    references.extend(item.get(_W + 'styleId') for item in definitions
        if item.get(_W + 'default') in {'1', 'true', 'on'})
    path, node = [], title
    while node is not body:
        parent = node.getparent()
        if parent is None or parent.tag not in {_W + name for name in ('body', 'tbl', 'tr', 'tc')}:
            raise ValueError('title has an opaque native ancestor')
        path.append(parent.index(node))
        properties = parent.find(parent.tag + 'Pr')
        if hidden(properties) or revised(properties):
            raise ValueError('title ancestor has hidden or revised properties')
        if parent.tag == _W + 'tc' and properties is not None and any(
            item.get(_W + 'val') != 'restart' for tag in ('vMerge', 'hMerge')
            for item in properties.findall(_W + tag)):
            raise ValueError('title is in a hidden merge continuation')
        if parent.tag == _W + 'tr' and revised(parent.find(_W + 'tblPrEx')):
            raise ValueError('title row has unresolved table property revisions')
        if parent.tag == _W + 'tbl':
            if revised(parent.find(_W + 'tblGrid')):
                raise ValueError('title table grid has unresolved revisions')
            style = _value(properties, 'tblStyle')
            if style:
                references.append(style)
        node = parent
    for identity in references:
        if any(hidden(style) for style in _style_chain(identity, styles, set())):
            raise ValueError('title has a hidden style dependency')
    return list(reversed(path))


def _original_title_path(original):
    """独立从原件确认显式总标题在正文声明之前，不消费writer回执。"""
    parts = _package(original)
    if ('word/settings.xml' in parts
        and _xml(parts['word/settings.xml']).xpath('.//w:documentProtection', namespaces=_NS)):
        return None
    root = _xml(parts['word/document.xml'])
    body = root.find(_W + 'body')
    candidates = [p for p in root.xpath('.//w:p', namespaces=_NS)
        if ''.join(p.xpath('.//w:t/text()', namespaces=_NS)).strip() == '{{report_title}}']
    slots = root.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]', namespaces=_NS)
    slots += [p for p in root.xpath('.//w:p[not(ancestor::w:sdt)]', namespaces=_NS)
        if ''.join(p.xpath('.//w:t/text()', namespaces=_NS)).strip() == '{{report_content}}']
    if len(candidates) != 1 or len(slots) != 1:
        return None
    title = candidates[0]
    positions = {node: index for index, node in enumerate(body.iter())}
    if (positions[title] >= positions[slots[0]]
        or title.xpath('.//w:sectPr|.//w:numPr', namespaces=_NS)
        or any(child.tag not in {_W + 'pPr', _W + 'r'} for child in title)
        or any(child.tag not in {_W + 'rPr', _W + 't'} for run in title.findall(_W + 'r') for child in run)):
        return None
    return _visible_title_path(title, body, parts)


def read_template_body(content, markdown, resources, *, original=None, report_title=None):
    """只信源token和实际声明区；完整原生覆盖不代表完整布局或字段V。"""
    def finish(status, message, scope=None):
        return {'status': status, 'coverage': 'complete' if status == 'passed' else 'unverified',
            'issues': [] if status == 'passed' else [{'code': 'report_template_body_' + status, 'message': message}],
            'scope': scope or {}}

    try:
        expected = _expected(markdown)
        source_targets = _source_anchor_targets(expected)
        if not expected:
            return finish('unverified', '冻结正文为空，未将空对象清单当作富正文通过。')
        resources = resources or {}
        for block in expected:
            for name in block.get('images', []):
                if name not in resources or not isinstance(resources[name], bytes):
                    return finish('unverified', '冻结正文引用的实际图片来源不完整：' + str(name))
        parts = _package(content)
        root = _xml(parts['word/document.xml'])
        slots = root.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]', namespaces=_NS)
        if (len(slots) != 1 or slots[0].getparent().tag not in (_W + 'body', _W + 'tc')
            or slots[0].xpath('ancestor::w:sdt', namespaces=_NS)):
            return finish('unverified', '正文没有唯一可独立定位的合法块级声明。')
        body = slots[0].find(_W + 'sdtContent')
        if body is None:
            return finish('failed', '实际正文声明没有内容区。')
        _bookmarks(root, body)
        if body.xpath('.//w:fldSimple|.//w:fldChar|.//w:instrText|.//w:del|.//w:moveFrom|'
            './/w:txbxContent|.//w:object|.//w:sdt|.//w:altChunk', namespaces=_NS):
            return finish('failed', '正文含动态域、隐藏替代位置或无法完整读取的原生对象。')
        styles_root = _xml(parts['word/styles.xml'])
        styles = {item.get(_W + 'styleId'): item for item in styles_root.findall(_W + 'style')}
        default_style = next((key for key, item in styles.items()
            if item.get(_W + 'type') == 'paragraph' and item.get(_W + 'default') == '1'), None)
        defaults = styles_root.find(_W + 'docDefaults/' + _W + 'rPrDefault/' + _W + 'rPr')
        numbering = _xml(parts['word/numbering.xml']) if 'word/numbering.xml' in parts else None
        rel_root = _xml(parts['word/_rels/document.xml.rels']) if 'word/_rels/document.xml.rels' in parts else []
        relationships = {item.get('Id'): item for item in rel_root}
        if len(relationships) != len(rel_root):
            raise ValueError('duplicate document relationship IDs')
        scope = {'bodyTag': 'report_content', 'relationshipIds': set(), 'mediaParts': set(),
            'styleIds': set(), 'numberingIds': set(), 'abstractNumberingIds': set(),
            '_relationships': relationships, '_contentTypes': _xml(parts['[Content_Types].xml']), '_seenLists': set()}
        actual, nodes = [], []
        for child in body:
            if child.tag in (_W + 'bookmarkStart', _W + 'bookmarkEnd'):
                continue
            if child.tag == _W + 'p':
                actual.append(_paragraph(child, styles, default_style, defaults, numbering, scope, parts, resources))
                nodes.append(child)
            elif child.tag == _W + 'tbl':
                if any(node.tag not in {_W + name for name in ('tblPr', 'tblGrid', 'tr')} for node in child):
                    raise ValueError('unsupported table object')
                if child.xpath('.//w:gridSpan|.//w:vMerge|.//w:tbl[ancestor::w:tbl]', namespaces=_NS):
                    raise ValueError('merged or nested table not independently supported')
                rows = []
                for row in child.findall(_W + 'tr'):
                    if any(node.tag not in {_W + 'trPr', _W + 'tc'} for node in row):
                        raise ValueError('unsupported table row object')
                    cells = []
                    for cell in row.findall(_W + 'tc'):
                        texts = []
                        for paragraph in cell:
                            if paragraph.tag == _W + 'tcPr':
                                continue
                            if paragraph.tag != _W + 'p':
                                raise ValueError('unsupported table cell object')
                            parsed = _paragraph(paragraph, styles, default_style, defaults, numbering, scope, parts, resources)
                            if parsed['images'] or parsed['links']:
                                raise ValueError('unsupported table cell image or hyperlink')
                            texts.append(parsed['text'])
                        cells.append('\n'.join(texts))
                    rows.append(cells)
                style_id = _value(child.find(_W + 'tblPr'), 'tblStyle')
                if style_id:
                    list(_style_chain(style_id, styles, scope['styleIds']))
                actual.append({'kind': 'table', 'rows': rows})
                nodes.append(child)
            else:
                raise ValueError('unsupported native body block')
        for block in expected:
            if 'images' in block:
                block['images'] = [resources[name] for name in block['images']]
        # Pandoc代码段在原生Word中仍是普通静态段落；本轮只证明内容和块边界。
        for block in expected:
            if block['kind'] == 'code':
                block['kind'] = 'paragraph'
        empty = {'kind': 'paragraph', 'text': '', 'images': [], 'links': [], 'imageOffsets': []}
        if (len(actual) >= 2 and actual[-1] == empty and actual[-2]['kind'] == 'table'
            and expected[-1]['kind'] == 'table'):
            actual.pop()
            nodes.pop()
        title = None
        if (original is not None and report_title and len(actual) + 1 == len(expected)
            and expected[0]['kind'] == 'heading' and expected[0]['level'] == 1
            and expected[0]['text'] == report_title and not expected[0]['images'] and not expected[0]['links']):
            title_path = _original_title_path(original)
            if title_path is not None:
                native_body = root.find(_W + 'body')
                title = native_body
                for index in title_path:
                    if index >= len(title):
                        raise ValueError('declared title position is missing')
                    title = title[index]
                if title.tag != _W + 'p' or _visible_title_path(title, native_body, parts) != title_path:
                    raise ValueError('declared title path is not an eligible native paragraph')
                _bookmarks(root, title)
                starts = title.xpath('./w:bookmarkStart', namespaces=_NS)
                ends = title.xpath('./w:bookmarkEnd', namespaces=_NS)
                children = [node for node in title if node.tag != _W + 'pPr']
                if (len(starts) != 1 or len(ends) != 1 or not starts[0].get(_W + 'id')
                    or not starts[0].get(_W + 'name') or children[0] is not starts[0] or children[-1] is not ends[0]):
                    raise ValueError('reused title requires one complete native bookmark pair around its text')
                parsed = _paragraph(title, styles, default_style, defaults, numbering, scope, parts, resources)
                if (parsed['kind'] not in ('paragraph', 'heading') or parsed['text'] != report_title
                    or parsed['images'] or parsed['links']):
                    raise ValueError('declared title does not contain the frozen total title')
                parsed.update(kind='heading', level=1)
                actual.insert(0, parsed)
                nodes.insert(0, title)
                scope.update(titleReused=True, titleParagraphPath=title_path,
                    titleBookmarkIds=title.xpath('.//w:bookmarkStart/@w:id', namespaces=_NS))
                if len(title_path) == 1:
                    scope['titleParagraphIndex'] = title_path[0]
        internal_links = _resolve_internal_links(expected, actual, body, nodes, source_targets, title)
        if actual != expected:
            return finish('failed', '实际正文全部块、顺序、表格原值或图片身份与冻结来源不一致。')
        public_scope = {key: sorted(value) if isinstance(value, set) else value
            for key, value in scope.items() if not key.startswith('_')}
        public_scope.update(blockCount=len(actual), tableCount=sum(item['kind'] == 'table' for item in actual),
            imageCount=sum(len(item.get('images', [])) for item in actual))
        if internal_links:
            public_scope.update(internalLinkCount=len(internal_links), internalLinkTargets=internal_links)
        return finish('passed', '', public_scope)
    except _UnknownSourceAnchor as error:
        return finish('unverified', str(error))
    except (ValueError, KeyError, TypeError, etree.XMLSyntaxError, OSError, BadZipFile) as error:
        return finish('failed', '实际富正文无法完整核验：' + str(error))
