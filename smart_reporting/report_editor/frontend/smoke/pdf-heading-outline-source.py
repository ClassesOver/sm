"""真实字号层次 PDF：仅供标题目录读取与导航验证，不写业务报告。"""
import base64
import io
import json

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from smart_reporting.reporting.delivery.pdf_native import inspect_pdf


def create_source(kind):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    }))
    titles = [
        [('User Guide', 24, 720)],
        [('Chapter Alpha', 16, 720), ('Section Details', 13, 470)],
        [('Chapter Beta', 16, 720)],
    ]
    for index in range(3):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font}),
        })
        lines = [] if kind == 'plain' else [('ACME Corporation', 12, 770), *titles[index]]
        lines += [(f'Body paragraph number {number} for page {index + 1}', 10, 685 - number * 13) for number in range(12)]
        if index == 1:
            lines += [(f'Detailed body paragraph number {number}', 10, 445 - number * 13) for number in range(10)]
        commands = '\n'.join(f'BT /F1 {size} Tf 72 {y} Td ({text}) Tj ET' for text, size, y in lines)
        stream = DecodedStreamObject()
        stream.set_data(commands.encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    if kind == 'embedded':
        writer.add_outline_item('Embedded First', 0)
        writer.add_outline_item('Embedded Last', 2)
    output = io.BytesIO()
    writer.write(output)
    data = output.getvalue()
    return {'bytes': base64.b64encode(data).decode(), 'model': inspect_pdf(data)}


if __name__ == '__main__':
    print(json.dumps({kind: create_source(kind) for kind in ['headings', 'plain', 'embedded']}))
