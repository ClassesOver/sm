"""系统生成图注的可逆显示；不根据手写说明的措辞猜测其身份。"""
import base64
import binascii
import hashlib
import re

from markdown_it import MarkdownIt

END = '<!-- /report-md-caption:v1 -->'
MARKER = re.compile(r'<!-- report-md-caption:v1:([0-9a-f]{64}):([A-Za-z0-9+/=]+) -->')


def _wrapper(image: str, caption: str, visible: bool) -> str:
    digest = hashlib.sha256(image.encode()).hexdigest()
    encoded = base64.b64encode(caption.encode()).decode('ascii')
    return '<!-- report-md-caption:v1:' + digest + ':' + encoded + ' -->\n\n' + (
        caption + '\n\n' if visible else '') + END


def image_caption_markdown(image: str, caption: str, *, visible: bool) -> str:
    return image + '\n\n' + _wrapper(image, caption, visible)


def _transform(markdown: str, visible: bool | None) -> str:
    lines = markdown.splitlines(keepends=True)
    tokens = MarkdownIt('commonmark', {'html': True}).parse(markdown)
    previous = None
    replacements = []
    for position, token in enumerate(tokens):
        if token.type == 'inline':
            previous = token
        if token.type != 'html_block' or token.level != 0 or not token.map:
            continue
        match = MARKER.fullmatch(token.content.strip())
        if not match or previous is None or not previous.map or previous.level != 1:
            continue
        children = previous.children or []
        if sum(child.type == 'image' for child in children) != 1 or any(
            child.type not in {'image', 'text'} for child in children
        ):
            continue
        trailing = ''.join(child.content for child in children if child.type == 'text')
        if not re.fullmatch(r'(?:\[\[citation:[^\]\r\n]+\]\])*\s*', trailing):
            continue
        start = token.map[0]
        if any(line.strip() for line in lines[previous.map[1]:start]):
            continue
        image = ''.join(lines[previous.map[0]:previous.map[1]]).rstrip('\r\n')
        if hashlib.sha256(image.encode()).hexdigest() != match.group(1):
            continue
        try:
            caption = base64.b64decode(match.group(2), validate=True).decode('utf-8')
        except (binascii.Error, UnicodeDecodeError):
            continue
        image_token = next(child for child in children if child.type == 'image')
        caption_tokens = MarkdownIt('commonmark', {'html': True}).parse(caption)
        if [item.type for item in caption_tokens] != ['paragraph_open', 'inline', 'paragraph_close']:
            continue
        caption_children = caption_tokens[1].children or []
        if len(caption_children) < 3 or caption_children[0].type != 'em_open' or caption_children[-1].type != 'em_close':
            continue
        text = caption_children[1:-1]
        if any(item.type != 'text' for item in text) or ''.join(item.content for item in text) != (
            '图表：' + str(image_token.attrGet('title') or '')
        ):
            continue
        ending = next((item for item in tokens[position + 1:] if item.type == 'html_block'
            and item.level == 0 and item.content.strip() == END and item.map), None)
        if ending is None or ''.join(lines[token.map[1]:ending.map[0]]).strip() not in {'', caption}:
            continue
        end = ending.map[1]
        replacement = caption if visible is None else _wrapper(image, caption, visible)
        replacements.append((start, end, replacement + ('\n' if lines[end - 1].endswith('\n') else '')))
    for start, end, replacement in reversed(replacements):
        lines[start:end] = [replacement]
    return ''.join(lines)


def apply_image_caption_preference(markdown: str, visible: bool) -> str:
    return _transform(markdown, visible)


def restore_image_captions(markdown: str) -> str:
    return _transform(markdown, None)
