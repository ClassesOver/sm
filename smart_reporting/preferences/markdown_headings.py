"""仅调整登记标题的显示层级；元数据不存储或恢复任何隐藏正文。"""
import hashlib
import re

from markdown_it import MarkdownIt

_MARKER = re.compile(r' <!-- report-md-heading-level:v1 original=([234]) displayed=([3-6]) '
    r'sha256=([a-f0-9]{64}) -->(?P<closing>[ \t]+#+[ \t]*)?$')
_PREFIX = re.compile(r'^( {0,3})(#{2,6})(?=[ \t])')


def _headings(markdown):
    lines = markdown.splitlines(keepends=True)
    for token in MarkdownIt('commonmark', {'html': True}).parse(markdown):
        if token.type == 'heading_open' and token.level == 0 and token.map:
            start, end = token.map
            if end == start + 1 and _PREFIX.match(lines[start]):
                yield start, token.tag, lines[start].rstrip('\r\n')


def _with_level(line, level):
    return _PREFIX.sub(lambda match: match[1] + '#' * level, line, count=1)


def _matches(markdown):
    if 'report-md-heading-level:' not in markdown:
        return
    for index, tag, line in _headings(markdown):
        match = _MARKER.search(line)
        if not match:
            continue
        original, displayed = int(match[1]), int(match[2])
        base = line[:match.start()] + (match['closing'] or '')
        if (displayed - original in (1, 2) and tag == 'h' + str(displayed)
                and hashlib.sha256(base.encode()).hexdigest() == match[3]):
            yield index, original, displayed, base, line


def restore_heading_levels(markdown: str, *, preserve_offsets: bool = False) -> str:
    if 'report-md-heading-level:' not in markdown:
        return markdown
    lines = markdown.splitlines(keepends=True)
    for index, original, displayed, base, line in _matches(markdown):
        ending = lines[index][len(line):]
        if preserve_offsets:
            match = _MARKER.search(line)
            closing = match['closing'] or ''
            masked = line[:match.start()] + ' ' * (match.end() - match.start() - len(closing)) + closing
            prefix = _PREFIX.match(masked)
            restored = prefix[1] + '#' * original + ' ' * (displayed - original) + masked[prefix.end():]
            lines[index] = restored + ending
        else:
            lines[index] = _with_level(base, original) + ending
    return ''.join(lines)


def heading_presentations(markdown: str) -> list[dict]:
    parser = MarkdownIt('commonmark', {'html': True})
    return [{'level': original, 'label': next(token.content for token in parser.parse(base) if token.type == 'inline')}
        for _index, original, _displayed, base, _line in _matches(markdown)]


def _label(source):
    from .markdown_references import restore_reference_markers

    source = restore_reference_markers(source)
    source = re.sub(r'\[\[(?:analysis|claim|citation):[^\]\r\n]+\]\]', '', source)
    tokens = MarkdownIt('commonmark', {'html': True}).parseInline(source)
    return ''.join(token.content for token in tokens[0].children or []
        if token.type in {'text', 'code_inline', 'image'}).strip()


def apply_heading_preferences(markdown: str, level: int, headings: list[dict] | None = None) -> str:
    from ..reporting.delivery.report_runtime.markdown import format_heading_label

    if headings is None:
        headings = heading_presentations(markdown)
    markdown = restore_heading_levels(markdown)
    if level == 2 or not headings:
        return markdown
    allowed = {(item['level'], _label(item['label'] if 'label' in item else format_heading_label(
        level=item['level'], number=item['number'], title=item['title']))) for item in headings}
    lines = markdown.splitlines(keepends=True)
    parser = MarkdownIt('commonmark', {'html': True})
    tokens = parser.parse(markdown)
    for index, token in enumerate(tokens):
        if token.type != 'heading_open' or token.level != 0 or not token.map or token.tag not in {'h2', 'h3', 'h4'}:
            continue
        start, end = token.map
        line = lines[start].rstrip('\r\n')
        original = int(token.tag[1:])
        if (end != start + 1 or not _PREFIX.match(line) or 'report-md-heading-level:' in line
                or (original, _label(tokens[index + 1].content)) not in allowed):
            continue
        displayed = original + level - 2
        rendered = _with_level(line, displayed)
        marker = (f' <!-- report-md-heading-level:v1 original={original} displayed={displayed} '
            f'sha256={hashlib.sha256(rendered.encode()).hexdigest()} -->')
        # 结束井号必须留在行尾，否则会从标题语法变成读者可见文字。
        closing = re.search(r'[ \t]+#+[ \t]*$', rendered)
        position = closing.start() if closing else len(rendered)
        lines[start] = rendered[:position] + marker + rendered[position:] + lines[start][len(line):]
    return ''.join(lines)
