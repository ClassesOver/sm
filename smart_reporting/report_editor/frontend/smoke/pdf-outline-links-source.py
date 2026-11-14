"""生成带内部、嵌套外链和不安全动作的真实 PDF 目录夹具。"""
import base64
import io
import json

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject


def outline_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.add_blank_page(width=300, height=400)
    first = writer.add_outline_item("First page", 0)
    for title, url, parent in [
        ("Website", "https://example.com/report", first),
        ("Contact", "mailto:review@example.com", first),
        ("HTTP", "http://example.com/help", None),
        ("Unsafe script", "javascript:alert(1)", None),
        ("Unsafe file", "file:///tmp/private.pdf", None),
    ]:
        ref = writer.add_outline_item(title, 0, parent=parent)
        ref.get_object()[NameObject("/A")] = DictionaryObject({
            NameObject("/S"): NameObject("/URI"),
            NameObject("/URI"): TextStringObject(url),
        })
    writer.add_outline_item("Second page", 1)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


if __name__ == "__main__":
    print(json.dumps({"bytes": base64.b64encode(outline_pdf_bytes()).decode()}))
