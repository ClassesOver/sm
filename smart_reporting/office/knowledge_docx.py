from io import BytesIO

from docx import Document
from lxml import html
from markdown_it import MarkdownIt


def render_knowledge_docx(markdown: str) -> bytes:
    """Render a knowledge answer as a standalone Word document."""
    document = Document()
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    root = html.fragment_fromstring(parser.render(markdown), create_parent=True)

    def add_inline(paragraph, node, *, bold=False, italic=False, code=False):
        bold = bold or node.tag == "strong"
        italic = italic or node.tag == "em"
        code = code or node.tag == "code"
        if node.tag == "br":
            paragraph.add_run().add_break()
        text = node.get("alt") if node.tag == "img" else node.text
        if text:
            run = paragraph.add_run(text)
            if bold:
                run.bold = True
            if italic:
                run.italic = True
            if code:
                run.font.name = "Consolas"
        for child in node:
            add_inline(paragraph, child, bold=bold, italic=italic, code=code)
            if child.tail:
                run = paragraph.add_run(child.tail)
                if bold:
                    run.bold = True
                if italic:
                    run.italic = True

    def add_block(node):
        if node.tag in {"ul", "ol"}:
            style = "List Bullet" if node.tag == "ul" else "List Number"
            for item in node:
                add_inline(document.add_paragraph(style=style), item)
        elif node.tag == "table":
            rows = node.xpath("./thead/tr | ./tbody/tr")
            table = document.add_table(rows=0, cols=len(rows[0]))
            table.style = "Table Grid"
            for row in rows:
                cells = table.add_row().cells
                for cell, value in zip(cells, row, strict=True):
                    add_inline(cell.paragraphs[0], value, bold=value.tag == "th")
        elif node.tag == "blockquote":
            for child in node:
                add_block(child)
        elif node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            add_inline(document.add_heading(level=int(node.tag[1])), node)
        else:
            add_inline(document.add_paragraph(), node)

    for block in root:
        add_block(block)
    output = BytesIO()
    document.save(output)
    return output.getvalue()
