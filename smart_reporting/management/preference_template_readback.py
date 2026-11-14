"""DOCX模板声明区的独立读取；不复用通用末尾落款marker或生成模板V。"""

from io import BytesIO
from zipfile import ZipFile

from lxml import etree

from ..preferences.markdown_adapter import strip_signature
from ..reporting.delivery.template_body_readback import expected_body_text, read_template_body
from .preference_template_preflight import template_signature

_NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
_W = '{' + _NS['w'] + '}'
_SPACE = '{http://www.w3.org/XML/1998/namespace}space'


def _parts(content):
    with ZipFile(BytesIO(content)) as package:
        members = package.infolist()
        if (len(members) > 10000 or len({item.filename for item in members}) != len(members)
            or sum(item.file_size for item in members) > 200 * 1024 * 1024):
            raise ValueError('template package exceeds readback limits')
        return {item.filename: package.read(item) for item in members}


def _xml(content):
    return etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))


def _slots(root):
    all_slots = root.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_signature"]]', namespaces=_NS)
    legal = [slot for slot in all_slots if slot.getparent().tag in {_W + 'body', _W + 'tc'}
        and not slot.xpath('ancestor::w:sdt', namespaces=_NS)]
    return legal if len(all_slots) == len(legal) == 1 else []


def _outside_declared(original, actual, values):
    """比较ZIP部件和同XML非声明子树；仅允许明确占位符文字变化。"""
    if original.keys() != actual.keys():
        return False
    for name, before in original.items():
        after = actual[name]
        if before == after:
            continue
        if not (name == 'word/document.xml' or name.startswith(('word/header', 'word/footer'))
            and name.endswith('.xml')):
            return False
        left, right = _xml(before), _xml(after)
        if name == 'word/document.xml':
            left_slots, right_slots = _slots(left), _slots(right)
            if not left_slots or not right_slots:
                return False
            for slot in (left_slots[0], right_slots[0]):
                content = slot.find(_W + 'sdtContent')
                if content is None:
                    return False
                for child in list(content):
                    content.remove(child)
        left_paragraphs = left.xpath('.//w:p', namespaces=_NS)
        right_paragraphs = right.xpath('.//w:p', namespaces=_NS)
        if len(left_paragraphs) != len(right_paragraphs):
            return False
        for old, new in zip(left_paragraphs, right_paragraphs, strict=True):
            old_text = ''.join(old.xpath('.//w:t/text()', namespaces=_NS))
            if not any('{{' + key + '}}' in old_text for key in values):
                continue
            expected = old_text
            for key, value in values.items():
                expected = expected.replace('{{' + key + '}}', value)
            if ''.join(new.xpath('.//w:t/text()', namespaces=_NS)) != expected:
                return False
            # 填充器只改文本节点和必要的xml:space，其他run/段落属性仍须相同。
            for paragraph in (old, new):
                for text in paragraph.xpath('.//w:t', namespaces=_NS):
                    text.text = ''
                    text.attrib.pop(_SPACE, None)
        if etree.tostring(left, method='c14n') != etree.tostring(right, method='c14n'):
            return False
    return True


def _body_slot(root):
    controls = root.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]', namespaces=_NS)
    placeholders = [p for p in root.xpath('.//w:p[not(ancestor::w:sdt)]', namespaces=_NS)
        if ''.join(p.xpath('.//w:t/text()', namespaces=_NS)).strip() == '{{report_content}}']
    targets = controls + placeholders
    if (len(targets) != 1 or targets[0].getparent().tag not in {_W + 'body', _W + 'tc'}
        or targets[0].xpath('ancestor::w:sdt|.//w:sectPr', namespaces=_NS)):
        return None
    return targets[0]


def _entry_key(node):
    return (node.tag, node.get(_W + 'styleId'), node.get(_W + 'numId'), node.get(_W + 'abstractNumId'),
        node.get('Id'), node.get('PartName'), node.get('Extension'))


def _dependency_preserved(before, after, allowed):
    left, right = _xml(before), _xml(after)
    if dict(left.attrib) != dict(right.attrib):
        return False
    old, new = {_entry_key(node): node for node in left}, {_entry_key(node): node for node in right}
    if len(old) != len(left) or len(new) != len(right):
        return False
    for key, node in old.items():
        if key not in new or etree.tostring(node, method='c14n') != etree.tostring(new[key], method='c14n'):
            return False
    return all(allowed(node) for key, node in new.items() if key not in old)


def _outside_rich(original, actual, values, scope):
    """仅允许独立reader实际消费的正文依赖；原条目和声明外XML不能豁免。"""
    media = set(scope.get('mediaParts', []))
    if any(name not in actual for name in original):
        return False
    if any(name not in media and name != 'word/numbering.xml' for name in actual.keys() - original.keys()):
        return False
    # 新定义即使没有改原条目，也可能激活模板原先悬空的样式引用。
    old_styles = _xml(original['word/styles.xml'])
    old_ids = {node.get(_W + 'styleId') for node in old_styles.findall(_W + 'style')}
    new_ids = {node.get(_W + 'styleId') for node in _xml(actual['word/styles.xml']).findall(_W + 'style')} - old_ids
    old_document = _xml(original['word/document.xml'])
    slot = _body_slot(old_document)
    if slot is None:
        return False
    slot.getparent().remove(slot)
    before_names = {node.get(_W + 'name') for name, raw in original.items()
        if name == 'word/document.xml' or name.startswith(('word/header', 'word/footer')) and name.endswith('.xml')
        for node in _xml(raw).iter(_W + 'bookmarkStart')}
    added_names = {node.get(_W + 'name') for name, raw in actual.items()
        if name == 'word/document.xml' or name.startswith(('word/header', 'word/footer')) and name.endswith('.xml')
        for node in _xml(raw).iter(_W + 'bookmarkStart')} - before_names
    original_anchor_roots = [old_document, *(_xml(raw) for name, raw in original.items()
        if name.startswith(('word/header', 'word/footer')) and name.endswith('.xml'))]
    dangling_anchors = {node.get(_W + 'anchor') for root in original_anchor_roots
        for node in root.iter(_W + 'hyperlink')} - before_names
    if added_names & dangling_anchors:
        return False
    roots = [old_styles, old_document, *(_xml(raw) for name, raw in original.items()
        if name.startswith(('word/header', 'word/footer')) and name.endswith('.xml'))]
    references = {node.get(_W + 'val') for root in roots for node in root.iter()
        if node.tag in {_W + key for key in ('pStyle', 'rStyle', 'tblStyle', 'basedOn', 'link', 'next')}}
    if (references - old_ids) & new_ids:
        return False
    numbering = b'<w:numbering xmlns:w="' + _NS['w'].encode() + b'"/>'
    old_numbering = _xml(original.get('word/numbering.xml', numbering))
    new_numbering = _xml(actual.get('word/numbering.xml', numbering))
    for definition, reference in (('num', 'numId'), ('abstractNum', 'abstractNumId')):
        old_ids = {node.get(_W + reference) for node in old_numbering.findall(_W + definition)}
        new_ids = {node.get(_W + reference) for node in new_numbering.findall(_W + definition)} - old_ids
        targets = [old_numbering] if reference == 'abstractNumId' else roots
        references = {node.get(_W + 'val') for root in targets for node in root.iter(_W + reference)}
        if (references - old_ids) & new_ids:
            return False
    empty_rels = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    old_ids = {node.get('Id') for node in _xml(original.get('word/_rels/document.xml.rels', empty_rels))}
    new_ids = {node.get('Id') for node in _xml(actual.get('word/_rels/document.xml.rels', empty_rels))} - old_ids
    relation_ns = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    references = {node.get(relation_ns + key) for node in old_document.iter() for key in ('id', 'embed', 'link')}
    if (references - old_ids) & new_ids:
        return False
    comparisons = dict(actual)
    for name, after in actual.items():
        if original.get(name) == after:
            continue
        before = original.get(name)
        if name in media and before is None:
            continue
        if name == 'word/styles.xml':
            def allowed(node):
                return node.get(_W + 'styleId') in scope['styleIds']
        elif name == 'word/numbering.xml':
            def allowed(node):
                return ((node.tag == _W + 'num' and node.get(_W + 'numId') in scope['numberingIds'])
                    or (node.tag == _W + 'abstractNum' and node.get(_W + 'abstractNumId') in scope['abstractNumberingIds']))
            if before is None:
                before = b'<w:numbering xmlns:w="' + _NS['w'].encode() + b'"/>'
        elif name == 'word/_rels/document.xml.rels':
            def allowed(node):
                return node.get('Id') in scope['relationshipIds']
        elif name == '[Content_Types].xml':
            def allowed(node):
                return (node.get('PartName', '').lstrip('/') in media
                    or (node.get('PartName') == '/word/numbering.xml' and scope['numberingIds'])
                    or any(path.endswith('.' + str(node.get('Extension'))) for path in media))
        else:
            continue
        if before is None or not _dependency_preserved(before, after, allowed):
            return False
        # 在后续原模板比较中仅擦除已逐条核验的合法追加依赖。
        if name in original:
            comparisons[name] = original[name]
        else:
            comparisons.pop(name)
    for name in media - original.keys():
        comparisons.pop(name, None)
    if original.keys() != comparisons.keys():
        return False
    left, right = _xml(original['word/document.xml']), _xml(comparisons['word/document.xml'])
    if scope.get('titleReused'):
        title = right.find(_W + 'body')
        for index in scope['titleParagraphPath']:
            title = title[index]
        for node in title.xpath('./w:bookmarkStart|./w:bookmarkEnd', namespaces=_NS):
            if node.get(_W + 'id') in scope['titleBookmarkIds']:
                title.remove(node)
    source_slot, actual_slot = _body_slot(left), _body_slot(right)
    if source_slot is None or actual_slot is None:
        return False
    if source_slot.tag == _W + 'sdt':
        # 既有SDT的属性/声明保留；只允许其内容区变化。
        for slot in (source_slot, actual_slot):
            body = slot.find(_W + 'sdtContent')
            if body is None:
                return False
            for child in list(body):
                body.remove(child)
    else:
        for slot in (source_slot, actual_slot):
            slot.getparent().replace(slot, etree.Element(_W + 'p'))
    original = {**original, 'word/document.xml': etree.tostring(left)}
    comparisons['word/document.xml'] = etree.tostring(right)
    return _outside_declared(original, comparisons, {'report_title': values['report_title']})


def _body_sample(text, markdown):
    compact, position = ''.join(text.split()), 0
    for line in expected_body_text(markdown).splitlines():
        expected = ''.join(line.split())
        if not expected:
            continue
        offset = compact.find(expected, position)
        if offset < 0:
            return False
        position = offset + len(expected)
    return True


def read_template_document(content, format, resolved, frozen, original, *, body_resources=None):
    checks, issues = [], []
    expected = template_signature(resolved, frozen)
    lines = [expected['signer'], expected['date'], *expected['description'].splitlines()]
    detail = {'status': 'incomplete', 'signature': {'status': 'unverified'},
        'outsideDeclaredTargets': {'status': 'unverified'}, 'layoutValidation': 'unverified'}

    def check(path, actual, target, *, coverage='complete'):
        checks.append({'path': format + '.' + path if path else None, 'passed': actual == target,
            'actual': actual, 'expected': target, 'coverage': coverage,
            'message': '模板实际内容与冻结草稿匹配。' if actual == target else '模板实际内容与冻结草稿不一致。'})

    if format == 'word':
        detail['body'] = read_template_body(content, frozen['markdown'], body_resources or {},
            original=original, report_title=frozen['state']['_documentContext']['title'])
        issues.extend(detail['body']['issues'])
        before, after = _parts(original), _parts(content)
        source_root, root = _xml(before['word/document.xml']), _xml(after['word/document.xml'])
        text = ''.join(root.xpath('.//w:t/text()', namespaces=_NS))
        source_slots, actual_slots = _slots(source_root), _slots(root)
        if source_slots and actual_slots:
            block = actual_slots[0].find(_W + 'sdtContent')
            dynamic_fields = block is not None and bool(block.xpath('.//w:fldSimple|.//w:fldChar|.//w:instrText', namespaces=_NS))
            valid = (block is not None and bool(len(block))
                and all(child.tag == _W + 'p' for child in block)
                and not dynamic_fields
                and not block.xpath('.//w:vanish[not(@w:val="0" or @w:val="false")]|'
                    './/w:webHidden[not(@w:val="0" or @w:val="false")]|.//w:drawing|.//w:object', namespaces=_NS))
            if dynamic_fields:
                issues.append({'code': 'management_preference_template_signature_dynamic_field',
                    'message': '模板落款声明区包含动态域，缓存文字不能证明完整署名、日期和说明；实际文件仍保留。'})
            actual = [''.join(p.xpath('.//w:t/text()', namespaces=_NS)) for p in block] if valid else []
            check('common.signer', actual[0] if actual else None, lines[0])
            check('common.dateFormat', actual[1] if len(actual) > 1 else None, lines[1])
            check('signature.description', actual[2:] if valid else None, lines[2:])
            detail['signature'] = {'status': 'passed' if actual == lines else 'failed',
                'declaration': 'report_signature_sdt', 'coverage': 'complete'}
            values = {'report_title': frozen['state']['_documentContext']['title'],
                'report_content': strip_signature(frozen['markdown'])}
            preserved = (_outside_rich(before, after, values, detail['body']['scope'])
                if detail['body']['status'] == 'passed' and detail['body']['coverage'] == 'complete'
                else _outside_declared(before, after, values))
            detail['outsideDeclaredTargets'] = {'status': 'passed' if preserved else 'failed',
                'coverage': 'complete', 'scope': 'package_parts_and_same_xml_outside_declared_targets'}
            check(None, preserved, True)
        else:
            issues.append({'code': 'management_preference_template_signature_unverified',
                'message': '当前模板没有唯一可独立定位的合法SDT落款声明；整段槽或正文尾部回退已生成，位置及未声明样例仍需复核。'})
    else:
        from pypdf import PdfReader

        pdf = PdfReader(BytesIO(content))
        text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
        try:
            matches = _body_sample(text, frozen['markdown'])
            detail['body'] = {'status': 'sampled' if matches else 'failed', 'coverage': 'sample', 'issues': []}
            check(None, matches, True, coverage='sample')
        except ValueError:
            detail['body'] = {'status': 'unverified', 'coverage': 'unverified', 'issues': [{
                'code': 'management_preference_template_body_unverified',
                'message': '冻结正文含未支持的语义节点，PDF可见文字未作完整推定。'}]}
            issues.extend(detail['body']['issues'])
        check(None, len(pdf.pages) > 0, True, coverage='sample')
        issues.append({'code': 'management_preference_template_signature_unverified',
            'message': '模板PDF仅完成实际可见文字片段读取，尚未证明声明区域、样例清理或全页布局。'})
    compact = ''.join(text.split())
    values_to_sample = [frozen['state']['_documentContext']['title']]
    if format == 'word':
        if detail['body']['status'] == 'passed':
            check(None, True, True)
        else:
            values_to_sample.append(strip_signature(frozen['markdown']))
            if detail['body']['status'] == 'failed':
                check(None, False, True)
    for value in values_to_sample:
        check(None, ''.join(value.split()) in compact, True, coverage='sample')
    if detail['signature']['status'] == 'unverified':
        for path, value in zip(('common.signer', 'common.dateFormat', 'signature.description'),
            (expected['signer'], expected['date'], expected['description']), strict=True):
            check(path, ''.join(value.split()) in compact, True, coverage='sample')
    if any(not item['passed'] for item in checks):
        detail['status'] = 'failed'
    return {'status': 'failed' if detail['status'] == 'failed' else 'passed', 'checks': checks,
        'templateReadback': detail, 'issues': issues}
