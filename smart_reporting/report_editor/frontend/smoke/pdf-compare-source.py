"""真实 PDF 比较夹具；仅固定文本与图片，不写业务报告。"""
import base64
import io
import json

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf


def pdf(pages, *, password=None, image=False):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data('\n'.join(f'BT /F1 12 Tf 72 {720-i*22} Td ({line}) Tj ET' for i, line in enumerate(lines)).encode())
        if image:
            raster = DecodedStreamObject()
            raster.set_data(Image.new('RGB', (60, 60), '#ccddff').tobytes())
            raster.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),NameObject('/Width'):NumberObject(60),NameObject('/Height'):NumberObject(60),NameObject('/ColorSpace'):NameObject('/DeviceRGB'),NameObject('/BitsPerComponent'):NumberObject(8)})
            page['/Resources'][NameObject('/XObject')] = DictionaryObject({NameObject('/Scan'):writer._add_object(raster)})
            stream.set_data(b'q 400 0 0 400 72 200 cm /Scan Do Q')
        page[NameObject('/Contents')] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    output=io.BytesIO()
    writer.write(output)
    return output.getvalue()


original=[['Comparison source page 1','Stable alpha'],['Comparison source page 2','Old contract line'],['Comparison source page 3','Retained detail','Removed detail']]
changed=[original[0],['Comparison source page 2','New contract line','Added detail'],['Comparison source page 3','Retained detail'],['Only in second document']]
sources={'original':pdf(original),'changed':pdf(changed),'scan':pdf([[]],image=True),'password':pdf(changed,password='secret'),'slow':pdf([['Repeated comparison line']]*800),'invalid':b'%PDF-invalid fixture'}
print(json.dumps({name:{'bytes':base64.b64encode(data).decode(),**({'model':inspect_pdf(data)}if name=='original'else{})}for name,data in sources.items()}))
