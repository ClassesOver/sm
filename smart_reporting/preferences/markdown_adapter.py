"""标准 Markdown 语法偏好与服务端标记的末尾落款。"""
import base64
import binascii
import re
import string

from markdown_it import MarkdownIt

from .markdown_captions import apply_image_caption_preference
from .markdown_headings import (
    apply_heading_preferences,
    heading_presentations,
    restore_heading_levels,
)
from .markdown_references import (
    apply_reference_preferences,
    reference_presentations,
    restore_reference_markers,
)
from .workbook_adapter import displayed_date

START = '<!-- report-signature:v1 -->'
END = '<!-- /report-signature:v1 -->'
_SIGNATURE = re.compile(r'(?m)^<!-- report-signature:v1 -->\n[\s\S]*?^<!-- /report-signature:v1 -->[ \t]*\n?\s*\Z')


def strip_signature(markdown: str) -> str:
    match = _SIGNATURE.search(markdown)
    return markdown[:match.start()].rstrip() + '\n' if match else markdown


def _literal(value: str) -> str:
    return ''.join('\\' + char if char in string.punctuation else char for char in value)


def _table_html(source: str) -> str:
    parser = MarkdownIt('commonmark', {'html': True}).enable('table')
    tokens = parser.parse(source)
    if not tokens or tokens[0].type != 'table_open' or tokens[-1].type != 'table_close':
        return ''
    encoded = base64.b64encode(source.encode()).decode('ascii')
    return parser.renderer.render(tokens, parser.options, {}).replace(
        '<table>', '<table data-report-md-source="' + encoded + '">', 1)


def strip_table_preferences(markdown: str) -> str:
    """仅恢复与原表重新渲染完全一致的生成表格，拒绝使用漂移或伪造的隐藏源。"""
    lines = markdown.splitlines(keepends=True)
    tokens = MarkdownIt('commonmark', {'html': True}).parse(markdown)
    for token in reversed(tokens):
        if token.type != 'html_block' or token.level != 0 or not token.map:
            continue
        match = re.match(r'<table data-report-md-source="([A-Za-z0-9+/=]+)">\n', token.content)
        if not match:
            continue
        try:
            source = base64.b64decode(match.group(1), validate=True).decode('utf-8')
        except (binascii.Error, UnicodeDecodeError):
            continue
        start, end = token.map
        if token.content == _table_html(source) and end < len(lines) and lines[end] == '\n':
            lines[start:end + 1] = [source]
    return ''.join(lines)


def _tables(markdown: str, preferences: dict) -> str:
    markdown = strip_table_preferences(markdown)
    if preferences['tableStyle'] != 'html':
        return markdown
    lines = markdown.splitlines(keepends=True)
    tokens = MarkdownIt('commonmark', {'html': True}).enable('table').parse(markdown)
    for token in reversed(tokens):
        if token.type == 'table_open' and token.level == 0 and token.map:
            start, end = token.map
            lines[start:end] = [_table_html(''.join(lines[start:end])) + '\n']
    return ''.join(lines)


def strip_navigation(markdown: str) -> str:
    """只移除解析器确认的生成目录及锚点，代码中的同名标记保留。"""
    lines = markdown.splitlines(keepends=True)
    blocks = [token for token in MarkdownIt('commonmark', {'html': True}).parse(markdown)
        if token.type == 'html_block' and token.level == 0 and token.map]
    removed = set()
    opened = None
    for token in blocks:
        value = token.content.strip()
        start, end = token.map
        if value == '<!-- report-md-toc:v1 -->':
            opened = start
        elif value == '<!-- /report-md-toc:v1 -->' and opened is not None:
            removed.update(range(opened, end + (end < len(lines) and not lines[end].strip())))
            opened = None
        elif re.fullmatch(r'<!-- report-md-anchor:v1 --><a id="report-md-heading-\d+"></a>', value):
            removed.update(range(start, end + (end < len(lines) and not lines[end].strip())))
    return ''.join(line for index, line in enumerate(lines) if index not in removed)


def _navigation(markdown: str, preferences: dict) -> str:
    markdown = strip_navigation(markdown)
    if not preferences['toc']:
        return markdown
    lines = markdown.splitlines(keepends=True)
    tokens = MarkdownIt('commonmark', {'html': True}).parse(markdown)
    headings = [(token, tokens[index + 1]) for index, token in enumerate(tokens)
        if token.type == 'heading_open' and token.level == 0 and token.map]
    entries = [(heading, inline) for heading, inline in headings if heading.tag != 'h1']
    if not entries:
        return markdown
    marker = preferences['listMarker']
    toc = ['<!-- report-md-toc:v1 -->\n\n', '**目录**\n\n']
    used = set(re.findall(r'\breport-md-heading-\d+\b', markdown))
    levels: list[int] = []
    for index, (heading, inline) in enumerate(entries, 1):
        anchor = 'report-md-heading-' + str(index)
        while anchor in used:
            anchor += '0'
        used.add(anchor)
        label = ''.join(child.content for child in inline.children or [] if child.type in ('text', 'code_inline', 'image'))
        label = label.replace('\n', ' ').strip()
        level = int(heading.tag[1:])
        while levels and levels[-1] >= level:
            levels.pop()
        indent = '  ' * len(levels)
        levels.append(level)
        toc.append(indent + marker + ' [' + _literal(label) + '](#' + anchor + ')\n')
        start = heading.map[0]
        lines[start] = '<!-- report-md-anchor:v1 --><a id="' + anchor + '"></a>\n\n' + lines[start]
    toc.append('\n<!-- /report-md-toc:v1 -->\n\n')
    title = next((heading for heading, _ in headings if heading.tag == 'h1'), None)
    insertion = title.map[1] if title else 0
    if insertion and insertion < len(lines) and not lines[insertion].strip():
        insertion += 1
    lines.insert(insertion, ''.join(toc))
    return ''.join(lines)


def apply_markdown_preferences(markdown: str, preferences: dict, *, citation_presentations: list[dict] | None = None,
    heading_numbers: list[dict] | None = None) -> str:
    """依据解析器确认的块位置改写语法，不触碰代码和行内文字。"""
    if heading_numbers is None:
        heading_numbers = heading_presentations(markdown)
    markdown = restore_heading_levels(markdown)
    # 先还原引用，图注图片身份与表格源仍按原始正文核对。
    if citation_presentations is None:
        citation_presentations = reference_presentations(markdown)
    markdown = _tables(restore_reference_markers(markdown), preferences)
    markdown = apply_image_caption_preference(markdown, preferences['imageCaptions'])
    lines = markdown.splitlines(keepends=True)
    marker = preferences['listMarker']
    fence_char = '~' if preferences['codeFence'] == 'tildes' else chr(96)
    tokens = MarkdownIt('commonmark').parse(markdown)
    lists = [token for token in tokens if token.type == 'bullet_list_open' and token.map]
    protected = set()
    for previous, current in zip(lists, lists[1:]):
        if previous.level == current.level and previous.map[1] == current.map[0]:
            # 相邻异符号列表原本是两个块，统一符号会错误合并。
            protected.update(range(previous.map[0], current.map[1]))
    for token in tokens:
        if not token.map:
            continue
        start, end = token.map
        if token.type == 'list_item_open' and token.markup in ('-', '*', '+') and start not in protected:
            lines[start] = re.sub(r'^(\s*(?:>\s*)*)[-*+](?=\s)',
                lambda match: match.group(1) + marker, lines[start], count=1)
        elif token.type == 'fence':
            # 反引号围栏的信息字符串不能含反引号，保留原语法才能保持内容。
            if fence_char == chr(96) and chr(96) in token.info:
                continue
            longest = max((len(match.group()) for match in re.finditer(
                re.escape(fence_char) + '+', token.content)), default=0)
            fence = fence_char * max(3, longest + 1)
            pattern = re.escape(token.markup)
            lines[start] = re.sub(pattern, lambda _: fence, lines[start], count=1)
            closing = end - 1
            if closing > start:
                lines[closing] = re.sub(
                    r'^(\s*(?:>\s*)*)' + re.escape(token.markup[0]) +
                    '{' + str(len(token.markup)) + r',}(?=\s*$)',
                    lambda match: match.group(1) + fence, lines[closing], count=1)
    result = _navigation(''.join(lines), preferences)
    result = apply_reference_preferences(result, preferences['references'], citation_presentations)
    return apply_heading_preferences(result, preferences.get('sectionHeadingLevel', 2), heading_numbers)


def append_signature(markdown: str, preferences: dict, generated_date: str, *, citation_presentations: list[dict] | None = None,
    heading_numbers: list[dict] | None = None) -> str:
    lines = [preferences['common']['signer'],
        displayed_date(generated_date, preferences['common']['dateFormat']),
        *preferences['signature']['description'].splitlines()]
    body = apply_markdown_preferences(strip_signature(markdown), preferences, citation_presentations=citation_presentations,
        heading_numbers=heading_numbers)
    return body.rstrip() + '\n\n' + START + '\n\n' + (
        '\n\n'.join(_literal(line) for line in lines)) + '\n\n' + END + '\n'
