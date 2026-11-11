"""按 Markdown 结构登记无数值绑定的正文，不按固定业务措辞猜测声明类型。"""

from markdown_it import MarkdownIt

from .contracts_v1 import NarrativeReferenceV1, canonical_sha256


def narrative_paragraphs(block):
    lines = block.markdown.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    existing = (*block.number_references, *(block.review_notices or ()))
    paragraphs = []
    tokens = MarkdownIt('commonmark').parse(block.markdown)
    for ordinal, token in enumerate(tokens):
        if token.type != 'paragraph_open' or token.map is None:
            continue
        start, end = (offsets[line] for line in token.map)
        if any(start <= ref.offset <= end for ref in existing):
            continue
        text = block.markdown[start:end].rstrip()
        # 图片不是文字声明；图注和表格有自己的证据入口。
        inline = tokens[ordinal + 1]
        if not any(child.type in {'text', 'code_inline'} and child.content.strip() for child in inline.children or ()):
            continue
        paragraphs.append((ordinal, start + len(text), text))
    return tuple(paragraphs)


def discover_narrative_references(block, *, section_code, basis_id, period):
    references = []
    for ordinal, offset, text in narrative_paragraphs(block):
        identity = canonical_sha256({'sectionCode': section_code, 'blockId': block.block_id,
            'ordinal': ordinal, 'text': text})
        references.append(NarrativeReferenceV1(offset=offset, claimId='narr-' + identity[:24],
            basisId=basis_id, period=period, statementSha256=canonical_sha256(text)))
    return tuple(references)
