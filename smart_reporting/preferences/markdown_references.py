"""引用展示可还原为原始标记；不隐藏身份、不从正文推断来源。"""
import base64
import binascii
import html
import re

from markdown_it import MarkdownIt

_CITATION = re.compile(r'\[\[citation:([A-Za-z0-9_.:-]{1,128})\]\]')
_REFERENCE = re.compile(
    r'<span data-report-md-reference="v1" data-number="(?P<number>[1-9]\d{0,3})" '
    r'data-label="(?P<label>[A-Za-z0-9+/=]+)" hidden>'
    r'(?P<marker>\[\[citation:(?P<id>[A-Za-z0-9_.:-]{1,128})\]\])</span>'
    r'(?P<display><abbr title="[^"\r\n]*">[^<\r\n]*</abbr>)?')


def _display(number: int, label: str) -> str:
    return '<abbr title="' + html.escape(label, quote=True) + r'">\[来源 ' + f'{number:03d}' + r'\]</abbr>'


def reference_matches(markdown: str):
    """只识别生成器的完整结构；手改编号/标题或损坏内容原样保留。"""
    for match in _REFERENCE.finditer(markdown):
        try:
            label = base64.b64decode(match['label'], validate=True).decode('utf-8')
        except (binascii.Error, UnicodeDecodeError):
            continue
        if not 1 <= len(label) <= 200 or any(ord(char) < 32 for char in label):
            continue
        if match['display'] is not None:
            display = _display(int(match['number']), label)
            # v1早期产物未转义方括号；保留还原兼容，新生成统一阻止引用式链接捕获。
            if match['display'] not in {display, display.replace(r'\[', '[').replace(r'\]', ']')}:
                continue
        elif markdown[match.end():].startswith('<abbr'):
            continue
        yield match, label


def _active_matches(markdown: str):
    from ..reporting.trace.markdown_body import trace_body

    matches = list(reference_matches(markdown))
    if not matches:
        return []
    traced = trace_body(markdown)
    return [(match, label) for match, label in matches
        if traced[match.start('marker'):match.end('marker')] == match['marker']]


def restore_reference_markers(markdown: str) -> str:
    for match, _label in reversed(_active_matches(markdown)):
        markdown = markdown[:match.start()] + match['marker'] + markdown[match.end():]
    return markdown


def reference_presentations(markdown: str) -> list[dict] | None:
    values = {match['id']: {'citationId': match['id'], 'label': label, 'coverageItems': []}
        for match, label in _active_matches(markdown)}
    return list(values.values()) or None


def _citation_matches(markdown: str):
    """复用行内解析器的源位置，链接目标、图片替代文字与HTML属性不作引用。"""
    parser = MarkdownIt('commonmark', {'html': True}).enable('table')
    document_environment = {}
    tokens = parser.parse(markdown, document_environment)
    offsets = [0]
    for line in markdown.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))

    def citation(state, silent):
        # 静默探测必须保留原生括号计数，否则会让外层合法链接误判为普通文本。
        if silent or state.linkLevel or state.src != state.env['source']:
            return False
        match = _CITATION.match(state.src, state.pos)
        if match is None:
            return False
        state.env['positions'].append(state.pos)
        state.pending += match[0]
        state.pos = match.end()
        return True

    parser.inline.ruler.before('link', 'report_reference', citation)
    positions = set()
    for token in tokens:
        if token.type != 'inline' or not token.map:
            continue
        start, end = (offsets[index] for index in token.map)
        source = markdown[start:end]
        environment = {**document_environment, 'source': source, 'positions': []}
        parser.inline.parse(source, parser, environment, [])
        positions.update(start + position for position in environment['positions'])
    return [_CITATION.match(markdown, position) for position in sorted(positions)]


def apply_reference_preferences(markdown: str, visible: bool, presentations: list[dict] | None = None) -> str:
    from ..reporting.delivery.report_runtime.pdf import _normalize_citation_presentations
    from ..reporting.trace.markdown_body import trace_body

    recovered = {match['id']: {'label': label, 'number': int(match['number'])}
        for match, label in _active_matches(markdown)}
    if presentations is None and not recovered:
        return markdown
    markdown = restore_reference_markers(markdown)
    traced = trace_body(markdown)
    citations = [match for match in _citation_matches(markdown)
        if traced[match.start():match.end()] == match[0]]
    if presentations is not None:
        registered = {item.get('citationId') for item in presentations if isinstance(item, dict)}
        ids = tuple(dict.fromkeys(match[1] for match in citations if match[1] in registered))
        normalized = _normalize_citation_presentations(presentations, ids)
        recovered = {item['citationId']: {'label': item['label'], 'number': index}
            for index, item in enumerate(normalized, 1)}
    # 不把损坏或手改的旧包装内标记再次嵌套包装。
    protected = [match.span() for match in re.finditer(
        r'<span\b[^>\r\n]*\bdata-report-md-reference=[^>\r\n]*>[^\r\n]*?(?:</span>|$)', markdown, re.M)]
    matches = [match for match in citations if match[1] in recovered
        and not any(start <= match.start() < end for start, end in protected)]
    for match in reversed(matches):
        value = recovered[match[1]]
        encoded = base64.b64encode(value['label'].encode()).decode('ascii')
        wrapper = ('<span data-report-md-reference="v1" data-number="' + str(value['number']) +
            '" data-label="' + encoded + '" hidden>' + match[0] + '</span>')
        if visible:
            wrapper += _display(value['number'], value['label'])
        markdown = markdown[:match.start()] + wrapper + markdown[match.end():]
    return markdown
