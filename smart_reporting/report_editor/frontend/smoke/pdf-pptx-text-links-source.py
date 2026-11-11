"""Deterministic three-page source with text-range URI and GoTo annotations."""
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.pdfgen.canvas import Canvas


def source_pdf():
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(400, 300), invariant=1)

    def line(text, x, y, label=None, target=None, internal=False):
        canvas.setFont('Helvetica', 12)
        canvas.setFillColor(HexColor('#123456'))
        canvas.drawString(x, y, text)
        if label:
            rect = (x, y - 3, x + canvas.stringWidth(label, 'Helvetica', 12), y + 13)
            if internal:
                canvas.linkRect('', target, rect, relative=0, thickness=0)
            else:
                canvas.linkURL(target, rect, relative=0, thickness=0)

    canvas.bookmarkPage('first')
    line('Source text links', 40, 270)
    line('Web plain', 40, 230, 'Web', 'https://example.com/report?a=1&b=2#part')
    line('Mail plain', 40, 195, 'Mail', 'mailto:reader@example.com?subject=Report')
    line('Jump third', 40, 160, 'Jump', 'third', True)
    line('Unsafe plain', 40, 125, 'Unsafe', 'javascript:alert(1)')
    canvas.setStrokeColor(HexColor('#333333'))
    for x in (40, 200, 360):
        canvas.line(x, 30, x, 100)
    for y in (30, 65, 100):
        canvas.line(40, y, 360, y)
    line('Table link', 48, 79, 'Table link', 'https://example.com/table')
    line('Table plain', 208, 79)
    line('10', 48, 44)
    line('20', 208, 44)
    canvas.showPage()
    line('Second source page', 40, 270)
    line('HTTP plain', 40, 220, 'HTTP', 'http://example.com/second')
    canvas.showPage()
    canvas.bookmarkPage('third')
    line('Destination page', 40, 270)
    line('Back first', 40, 220, 'Back', 'first', True)
    canvas.showPage()
    canvas.save()
    return stream.getvalue()


if __name__ == '__main__':
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_bytes(source_pdf())
