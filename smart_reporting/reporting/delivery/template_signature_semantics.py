"""从完整 DOCX 上下文绑定经外部消歧确认的安全原生段落，不猜署名措辞。"""

from hashlib import sha256
from io import BytesIO
from xml.parsers import expat
from zipfile import BadZipFile, ZipFile

from lxml import etree

from .template_body_readback import _package
from .templates import _PLACEHOLDER

_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_NS = {'w': _W}
_WQ = '{' + _W + '}'
_P_PROPERTIES = {'jc', 'spacing', 'ind', 'keepNext', 'keepLines', 'widowControl', 'contextualSpacing',
    'bidi', 'textAlignment', 'outlineLvl', 'shd', 'pBdr', 'top', 'left', 'bottom', 'right', 'between', 'bar'}
_R_PROPERTIES = {'rFonts', 'b', 'bCs', 'i', 'iCs', 'u', 'strike', 'dstrike', 'color', 'sz', 'szCs',
    'highlight', 'vertAlign', 'lang', 'spacing', 'kern', 'position', 'caps', 'smallCaps', 'rtl', 'cs'}
_STYLE_HAZARDS = {'vanish', 'webHidden', 'specVanish', 'numPr', 'sectPr', 'pageBreakBefore'}
_STYLE_METADATA = {'name', 'aliases', 'basedOn', 'next', 'link', 'uiPriority', 'qFormat', 'semiHidden',
    'unhideWhenUsed', 'rsid', 'autoRedefine', 'locked', 'personal', 'personalCompose', 'personalReply'}
_RANGE_MARKERS = {_WQ + name for name in ('bookmarkStart', 'bookmarkEnd', 'commentRangeStart', 'commentRangeEnd',
    'moveFromRangeStart', 'moveFromRangeEnd', 'moveToRangeStart', 'moveToRangeEnd', 'permStart', 'permEnd',
    'customXmlInsRangeStart', 'customXmlInsRangeEnd', 'customXmlDelRangeStart', 'customXmlDelRangeEnd',
    'customXmlMoveFromRangeStart', 'customXmlMoveFromRangeEnd', 'customXmlMoveToRangeStart', 'customXmlMoveToRangeEnd')}


def _xml(raw):
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError('模板 XML 不允许 DTD 或实体声明')
    return root


def _text(block):
    pieces = []
    for node in block.iter():
        if node.tag in {_WQ + name for name in ('t', 'instrText', 'delText')}:
            pieces.append(node.text or '')
        elif node.tag == _WQ + 'tab':
            pieces.append('\t')
        elif node.tag in {_WQ + 'br', _WQ + 'cr'}:
            pieces.append('\n')
    return ''.join(pieces)


def _safe_default_style(parts, styles):
    if 'word/settings.xml' in parts:
        settings = _xml(parts['word/settings.xml'])
        if settings.find('.//w:documentProtection', _NS) is not None:
            return False
    if styles is None:
        return True
    defaults = styles.find('w:docDefaults', _NS)
    if defaults is not None and any(node.tag in {_WQ + name for name in _STYLE_HAZARDS} for node in defaults.iter()):
        return False
    indexed = {node.get(_WQ + 'styleId'): node for node in styles.findall('w:style', _NS)}
    for node in styles.findall('w:style', _NS):
        if node.get(_WQ + 'default') not in {'1', 'true', 'on'} or node.get(_WQ + 'type') not in {'paragraph', 'character'}:
            continue
        seen = set()
        while node is not None:
            identity = node.get(_WQ + 'styleId')
            if identity in seen or any(child.tag in {_WQ + name for name in _STYLE_HAZARDS} for child in node.iter()):
                return False
            seen.add(identity)
            parent = node.find('w:basedOn', _NS)
            node = indexed.get(parent.get(_WQ + 'val')) if parent is not None else None
    return True


def _safe_properties(properties, allowed, styles, reference=None):
    names = allowed | ({reference} if reference else set())
    descendants = [node for node in properties.iter() if node is not properties]
    if any(node.tag not in {_WQ + name for name in names} for node in descendants):
        return False
    if reference:
        references = [node for node in descendants if node.tag == _WQ + reference]
        if len(references) > 1 or any(node.getparent() is not properties or len(node)
                or not _safe_style_reference(styles, node.get(_WQ + 'val'),
                    'paragraph' if reference == 'pStyle' else 'character') for node in references):
            return False
    return True


def _safe_style_reference(styles, identity, kind):
    """完整检查父样式及关联样式；合法双向link不等同basedOn循环。"""
    pending, checked = [(identity, kind)], set()
    while pending:
        current, expected = pending.pop()
        ancestry = set()
        while current:
            if current in ancestry:
                return False
            ancestry.add(current)
            key = (current, expected)
            if key in checked:
                break
            matches = styles.get(current, ())
            if len(matches) != 1 or matches[0].get(_WQ + 'type') != expected:
                return False
            node = matches[0]
            if any(child.tag not in {_WQ + name for name in _STYLE_METADATA | {'pPr', 'rPr'}} for child in node):
                return False
            for name, allowed in (('pPr', _P_PROPERTIES), ('rPr', _R_PROPERTIES)):
                properties = node.findall(_WQ + name)
                if len(properties) > 1 or any(not _safe_properties(prop, allowed, styles) for prop in properties):
                    return False
            parent, linked = node.findall(_WQ + 'basedOn'), node.findall(_WQ + 'link')
            if len(parent) > 1 or len(linked) > 1:
                return False
            if any(not item.get(_WQ + 'val') or len(item) for item in [*parent, *linked]):
                return False
            if linked:
                pending.append((linked[0].get(_WQ + 'val'), 'character' if expected == 'paragraph' else 'paragraph'))
            checked.add(key)
            current = parent[0].get(_WQ + 'val') if parent else None
    return bool(identity)


def _eligible(block, styles):
    if block.tag != _WQ + 'p' or not _text(block).strip() or _PLACEHOLDER.search(_text(block)):
        return False
    for child in block:
        if child.tag == _WQ + 'pPr':
            if not _safe_properties(child, _P_PROPERTIES, styles, 'pStyle'):
                return False
        elif child.tag == _WQ + 'r':
            for run_child in child:
                if run_child.tag == _WQ + 'rPr':
                    if not _safe_properties(run_child, _R_PROPERTIES, styles, 'rStyle'):
                        return False
                elif run_child.tag != _WQ + 't' or len(run_child):
                    return False
        else:
            return False
    return True


def _inspect(raw):
    try:
        parts = _package(raw)
        root = _xml(parts['word/document.xml'])
        bodies = root.findall('w:body', _NS)
        if root.tag != _WQ + 'document' or len(bodies) != 1:
            raise ValueError('模板必须包含唯一正文')
        body = bodies[0]
        if len(body) > 400:
            raise ValueError('模板正文超过 400 块，不能截断语义上下文')
        declared = False
        for name, content in parts.items():
            if not name.startswith('word/') or not name.endswith('.xml'):
                continue
            part = root if name == 'word/document.xml' else _xml(content)
            if part.xpath('.//w:sdtPr/w:tag[@w:val="report_signature"]', namespaces=_NS):
                declared = True
            if any(_text(paragraph).strip() == '{{report_signature}}' for paragraph in part.iter(_WQ + 'p')):
                declared = True
        styles = _xml(parts['word/styles.xml']) if 'word/styles.xml' in parts else None
        indexed = {}
        if styles is not None:
            for style in styles.findall('w:style', _NS):
                indexed.setdefault(style.get(_WQ + 'styleId'), []).append(style)
        default_safe = _safe_default_style(parts, styles) and not any(node.tag in _RANGE_MARKERS for node in body.iter())
        blocks = []
        total = 0
        for index, block in enumerate(body):
            text = _text(block)
            total += len(text)
            if total > 60000:
                raise ValueError('模板正文超过 60000 字，不能截断语义上下文')
            block_digest = sha256(etree.tostring(block, with_tail=False)).hexdigest()
            blocks.append({'blockId': f'body:{index}:{block_digest}', 'text': text,
                'eligible': default_safe and _eligible(block, indexed)})
        return parts, root, body, {'version': 1, 'templateSha256': sha256(raw).hexdigest(),
            'declared': declared, 'blocks': blocks}
    except (BadZipFile, etree.XMLSyntaxError, KeyError, TypeError, RuntimeError) as error:
        raise ValueError('模板包或 XML 无法安全读取') from error


def inspect_signature_candidates(raw):
    """完整列出正文直接子块；复杂原生对象只作为只读上下文。"""
    return _inspect(raw)[3]


def _paragraph_spans(document):
    """使用标准 XML 解析器的字节位置，避免重新序列化改变未选 XML。"""
    encoding = 'UTF-16' if document.startswith((b'\xff\xfe', b'\xfe\xff', b'<\x00', b'\x00<')) else None
    parser = expat.ParserCreate(encoding=encoding, namespace_separator='}')
    stack, spans = [], {}
    index = -1
    start = None

    def opened(name, _attributes):
        nonlocal index, start
        if len(stack) == 2 and stack[-1] == _W + '}body':
            index += 1
            start = parser.CurrentByteIndex
        stack.append(name)

    def closed(name):
        if len(stack) == 3 and stack[-2] == _W + '}body' and name == _W + '}p':
            spans[index] = (start, parser.CurrentByteIndex)
        stack.pop()

    def context_node(*_args):
        nonlocal index
        if len(stack) == 2 and stack[-1] == _W + '}body':
            index += 1

    parser.StartElementHandler, parser.EndElementHandler = opened, closed
    parser.CommentHandler = context_node
    parser.ProcessingInstructionHandler = context_node
    parser.Parse(document, True)
    return spans


def bind_semantic_signature_slot(raw, record):
    """仅将同模板、逐字证据匹配的连续安全段落原样包入一个声明槽。"""
    parts, root, _body, view = _inspect(raw)
    if (not isinstance(record, dict) or type(record.get('version')) is not int or record['version'] != 1
            or record.get('templateSha256') != view['templateSha256'] or record.get('status') != 'resolved'
            or view['declared']):
        raise ValueError('语义选区身份、状态或既有声明不允许绑定')
    identities, evidence = record.get('blockIds'), record.get('evidence')
    if (not isinstance(identities, list) or not 1 <= len(identities) <= 12
            or not all(isinstance(identity, str) for identity in identities) or len(set(identities)) != len(identities)
            or not isinstance(evidence, list) or len(evidence) != len(identities)):
        raise ValueError('语义选区必须是唯一非空且有完整证据的段落组')
    indexes = {block['blockId']: index for index, block in enumerate(view['blocks'])}
    positions = [indexes.get(identity, -1) for identity in identities]
    if positions[0] < 0 or positions != list(range(positions[0], positions[0] + len(positions))):
        raise ValueError('语义选区必须按正文顺序连续且属于当前模板')
    for identity, position, proof in zip(identities, positions, evidence, strict=True):
        block = view['blocks'][position]
        if (not block['eligible'] or not isinstance(proof, dict) or proof.get('blockId') != identity
                or proof.get('text') != block['text']):
            raise ValueError('语义选区包含保护段落或原文证据不匹配')
    document = parts['word/document.xml']
    encoding = root.getroottree().docinfo.encoding or 'UTF-8'
    if encoding.upper().replace('-', '') == 'UTF16':
        encoding = 'utf-16-le' if document.startswith(b'\xff\xfe') or document.startswith(b'<\x00') else 'utf-16-be'
    spans = _paragraph_spans(document)
    start, closing = spans[positions[0]][0], spans[positions[-1]][1]
    delimiter = '>'.encode(encoding)
    end = document.find(delimiter, closing) + len(delimiter)
    if end < closing + len(delimiter):
        raise ValueError('语义选区 XML 边界无法安全定位')
    prefix = next((name for name, uri in _body.nsmap.items() if name and uri == _W), None)
    declaration = ''
    if prefix is None:
        prefix = 'srSignature'
        namespaces = {name for node in root.iter() if isinstance(node.tag, str) for name in node.nsmap}
        while prefix in namespaces:
            prefix += '_'
        declaration = f' xmlns:{prefix}="{_W}"'
    opening = f'<{prefix}:sdt{declaration}><{prefix}:sdtPr><{prefix}:tag {prefix}:val="report_signature"/></{prefix}:sdtPr><{prefix}:sdtContent>'
    ending = f'</{prefix}:sdtContent></{prefix}:sdt>'
    edited = document[:start] + opening.encode(encoding) + document[start:end] + ending.encode(encoding) + document[end:]
    _xml(edited)
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(output, 'w') as target:
        target.comment = source.comment
        for member in source.infolist():
            target.writestr(member, edited if member.filename == 'word/document.xml' else parts[member.filename])
    prepared = output.getvalue()
    return prepared, {'templateSha256': view['templateSha256'], 'preparedTemplateSha256': sha256(prepared).hexdigest(),
        'selectedBlockIds': list(identities), 'status': 'resolved'}
