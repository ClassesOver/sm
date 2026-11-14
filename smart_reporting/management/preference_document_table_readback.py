"""独立读取受控表题身份；原生对象证据与PDF文字抽样分开。"""

import json
import re
from collections import Counter
from hashlib import sha256

from docx.oxml.ns import qn
from markdown_it import MarkdownIt

_PREFIX = 'tblcap_'
WORD_TABLE_CAPTION_EVIDENCE = 'word_native_table_captions_v1'
_UNPROVEN = {qn('w:' + name) for name in (
    'ins', 'del', 'moveFrom', 'moveTo', 'pPrChange', 'rPrChange', 'tblPrChange', 'tblGridChange',
    'tblPrExChange', 'trPrChange', 'tcPrChange', 'cellIns', 'cellDel', 'cellMerge', 'permStart', 'permEnd')}


def _caption_visible(document, node):
    """保守核验文本和依赖样式；无法解析或含隐藏声明时不授予完整证据。"""
    styles = document.styles.element

    def visible(properties):
        return not any(item.tag in _UNPROVEN or (
            item.tag in {qn('w:vanish'), qn('w:webHidden'), qn('w:specVanish')}
            and item.get(qn('w:val')) not in ('0', 'false', 'off'))
            for props in properties for item in props.iter())

    def chain(identity, kind):
        seen, properties = set(), []
        while identity:
            matches = [item for item in styles.findall(qn('w:style')) if item.get(qn('w:styleId')) == identity]
            if identity in seen or len(matches) != 1 or matches[0].get(qn('w:type')) != kind:
                return None
            seen.add(identity)
            properties.append(matches[0])
            bases = matches[0].findall(qn('w:basedOn'))
            if len(bases) > 1 or bases and not bases[0].get(qn('w:val')):
                return None
            identity = bases[0].get(qn('w:val')) if bases else None
        return properties

    def selected(properties, tag, kind):
        references = properties.findall(qn('w:' + tag)) if properties is not None else []
        if references:
            if len(references) != 1 or not references[0].get(qn('w:val')):
                return None
            return chain(references[0].get(qn('w:val')), kind)
        defaults = [item for item in styles.findall(qn('w:style'))
            if item.get(qn('w:type')) == kind and item.get(qn('w:default')) in ('1', 'true', 'on')]
        if len(defaults) > 1:
            return None
        if defaults and not defaults[0].get(qn('w:styleId')):
            return None
        return chain(defaults[0].get(qn('w:styleId')), kind) if defaults else []

    defaults = styles.findall(qn('w:docDefaults'))
    if len(node.findall(qn('w:pPr'))) > 1 or any(
        len(run.findall(qn('w:rPr'))) > 1 for run in node.xpath('.//w:r')):
        return False
    paragraph = selected(node.find(qn('w:pPr')), 'pStyle', 'paragraph')
    if len(defaults) > 1 or paragraph is None or not visible([node, *defaults, *paragraph]):
        return False
    for run in node.xpath('.//w:r[w:t]'):
        character = selected(run.find(qn('w:rPr')), 'rStyle', 'character')
        if character is None or not visible(character):
            return False
    return True


def _bookmark_name(table_id):
    return _PREFIX + sha256(table_id.encode()).hexdigest()[:24]


def expected_table_captions(frozen, numbered):
    """由已核原始来源独立解析预期；不读取生成器的表题计划/回执。"""
    from bs4 import BeautifulSoup

    from ..reporting.delivery.report_runtime.table_captions import validate_table_caption_input

    parser = MarkdownIt('commonmark', {'html': False}).enable('table')
    tokens = parser.parse(frozen['markdown'])
    openings = [(index, re.fullmatch(r'\[\[table:([^\]\r\n]+)\]\]', tokens[index + 1].content))
        for index, token in enumerate(tokens[:-1]) if token.type == 'paragraph_open' and token.level == 0
        and tokens[index + 1].type == 'inline']
    openings = [(index, match[1]) for index, match in openings if match]
    if not openings:
        return {'status': 'not_exercised', 'expected': [], 'issues': []}
    value = frozen.get('tableCaptionInput')
    try:
        raw = value['markdownText'].encode('utf-8')
        if raw.decode().replace('\r\n', '\n').replace('\r', '\n') != frozen['markdown']:
            raise ValueError('frozen markdown differs from raw source')
        source = validate_table_caption_input(value, raw)
        if source['status'] != 'verified':
            raise ValueError('unverified table caption input')
        table_records = {item['tableId']: item for item in json.loads(value['traceIndexText'])['tables']}
    except Exception:
        return {'status': 'unverified', 'expected': [], 'issues': [{
            'code': 'management_preference_table_caption_source_unverified',
            'message': '表题缺少与当前冻结正文一致的实际来源身份；未据普通正文猜测编号。'}]}
    counts = Counter(table_id for _, table_id in openings)
    expected, unknown = [], []
    for index, table_id in openings:
        title = source['captions'].get(table_id)
        if not title:
            origin = table_records.get(table_id, {}).get('originMarkdown')
            if isinstance(origin, str) and origin.startswith('[[table:' + table_id + ']]'):
                continue
            unknown.append(table_id)
            continue
        previous = tokens[index - 3] if index >= 3 else None
        inline = tokens[index - 2] if index >= 3 else None
        if (counts[table_id] != 1 or previous is None or previous.type != 'paragraph_open'
            or previous.level != 0 or inline.type != 'inline' or inline.content != title
            or previous.map[1] + 1 != tokens[index].map[0]):
            unknown.append(table_id)
            continue
        text = BeautifulSoup(parser.renderInline(title), 'html.parser').get_text()
        expected.append({'tableId': table_id, 'text': (f'表 {len(expected) + 1}：' if numbered else '') + text})
    issues = [{'code': 'management_preference_table_caption_unverified',
        'message': '部分表题未能逐一绑定登记原题和实际表格：' + '、'.join(unknown)}] if unknown else []
    return {'status': 'unverified' if unknown else 'verified' if expected else 'not_exercised',
        'expected': expected, 'issues': issues}


def check_word_table_captions(document, expected, check):
    """逐一读取原生书签、Caption段及直接相邻的真实表格。"""
    if not expected:
        return {'status': 'unverified', 'expectedCount': 0, 'coverage': 'unverified'}
    body = document.element.body
    all_markers = body.xpath('.//w:bookmarkStart[starts-with(@w:name, "tblcap_")]')
    starts_by_id = Counter(item.get(qn('w:id')) for item in body.xpath('.//w:bookmarkStart'))
    ends_by_id = Counter(item.get(qn('w:id')) for item in body.xpath('.//w:bookmarkEnd'))
    protected = any(item.get(qn('w:enforcement')) not in ('0', 'false', 'off')
        for item in document.settings.element.findall(qn('w:documentProtection')))
    actual = []
    for paragraph in document.paragraphs:
        node = paragraph._p
        starts = node.xpath('./w:bookmarkStart[starts-with(@w:name, "tblcap_")]')
        if not starts:
            continue
        start = starts[0]
        ends = node.xpath('./w:bookmarkEnd')
        matching = [end for end in ends if end.get(qn('w:id')) == start.get(qn('w:id'))]
        identity = start.get(qn('w:id'))
        bounded = (isinstance(identity, str) and re.fullmatch(r'0|[1-9][0-9]*', identity) is not None
            and starts_by_id[identity] == ends_by_id[identity] == 1
            and len(starts) == len(matching) == 1 and node.index(start) < node.index(matching[0]))
        if bounded:
            outside = list(node)[:node.index(start)] + list(node)[node.index(matching[0]) + 1:]
            bounded = not any(next(part.iter(qn('w:t')), None) is not None for part in outside)
        following = node.getnext()
        style = paragraph.style
        visible = not protected and _caption_visible(document, node)
        adjacent = (following is not None and following.tag == qn('w:tbl')
            and not any(item.tag in _UNPROVEN for item in following.iter()))
        static = not node.xpath('.//w:fldChar | .//w:instrText | .//w:fldSimple')
        actual.append([start.get(qn('w:name')), paragraph.text,
            style.style_id == 'Caption', adjacent,
            bounded, visible, static])
    wanted = [[_bookmark_name(item['tableId']), item['text'], True, True, True, True, True] for item in expected]
    valid = len(all_markers) == len(actual) == len(wanted) and actual == wanted
    check('tables.captionNumbering', [len(all_markers), actual], [len(wanted), wanted], coverage='complete',
        evidence_kind=WORD_TABLE_CAPTION_EVIDENCE,
        evidence_objects={'expectedCaptions': len(wanted), 'nativeCaptions': len(all_markers),
            'checkedCaptions': len(actual)},
        message='全部受控表题的原生身份、文本、顺序及相邻表格已逐一核验。')
    return {'status': 'passed' if valid else 'failed', 'expectedCount': len(wanted),
        'actualCount': len(all_markers), 'coverage': 'complete'}


def check_pdf_table_captions(text, expected, check):
    """PDF只核逐行文字顺序/数量，不将它提升为原生结构证据。"""
    if not expected:
        return {'status': 'unverified', 'expectedCount': 0, 'coverage': 'unverified'}
    lines = [''.join(line.split()) for line in text.splitlines() if line.strip()]
    wanted = [''.join(item['text'].split()) for item in expected]
    selected = []
    index = 0
    while index < len(lines):
        candidate = lines[index]
        if any(candidate.startswith(caption) or caption.startswith(candidate) for caption in wanted):
            while (index + 1 < len(lines) and
                any(caption.startswith(candidate) and caption != candidate for caption in wanted)):
                index += 1
                candidate += lines[index]
            selected.append(candidate)
        index += 1
    if (len(selected) > len(wanted) and Counter(selected) >= Counter(wanted)
        and all(value in wanted for value in selected)):
        return {'status': 'unverified', 'expectedCount': len(wanted), 'coverage': 'unverified', 'issues': [{
            'code': 'management_preference_pdf_table_caption_ambiguous',
            'message': 'PDF含与未编号表题相同的额外文字，无法独立区分普通正文和重复表题；保留文件，编号仍未核验。'}]}
    check('tables.captionNumbering', selected, wanted, coverage='sample',
        message='PDF可见表题文字及顺序抽样；未证明表题身份锚、相邻表格或全部页布局。')
    return {'status': 'sampled' if selected == wanted else 'failed',
        'expectedCount': len(wanted), 'coverage': 'sample'}


def read_table_captions(native, format, numbered, frozen, check):
    """来源不完整时保留具体原因，已知片段也不能代表整个字段通过。"""
    source = expected_table_captions(frozen, numbered)
    if not source['expected']:
        return {'status': source['status'], 'sourceStatus': source['status'], 'expectedCount': 0, 'coverage': 'unverified',
            'issues': source['issues']}

    def scoped_check(path, actual, expected, **kwargs):
        if source['status'] != 'verified':
            kwargs['coverage'] = 'sample'
            kwargs.pop('evidence_kind', None)
            kwargs.pop('evidence_objects', None)
        elif 'evidence_objects' in kwargs:
            kwargs['evidence_objects']['sourceStatus'] = source['status']
        check(path, actual, expected, **kwargs)

    result = (check_word_table_captions(native, source['expected'], scoped_check) if format == 'word'
        else check_pdf_table_captions(native, source['expected'], scoped_check))
    if source['status'] != 'verified' and result['status'] != 'failed':
        result.update(status='unverified', coverage='unverified')
    return {**result, 'sourceStatus': source['status'], 'issues': [*source['issues'], *result.get('issues', [])]}
