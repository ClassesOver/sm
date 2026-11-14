"""独立读取实际 PDF 下载：目标像素、范围、正文和相邻图像。"""
import hashlib
import json
import sys
from pathlib import Path
import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader

source_path, output_path, mode = sys.argv[1:]
a, b = fitz.open(source_path), fitz.open(output_path)
assert len(a) == len(b) == 1
assert a[0].get_text() == b[0].get_text()
assert PdfReader(source_path).pages[0].extract_text() == PdfReader(output_path).pages[0].extract_text()
def images(doc):
    result = []
    for info in doc[0].get_image_info(xrefs=True):
        pix = fitz.Pixmap(doc, info['xref'])
        result.append((info, pix))
    return sorted(result, key=lambda item: item[0]['bbox'][0])
before, after = images(a), images(b)
assert len(before) == len(after) == 2
assert before[1][0]['bbox'] == after[1][0]['bbox']
assert before[1][1].samples == after[1][1].samples
old, new = before[0], after[0]
assert old[1].samples != new[1].samples
bbox = new[0]['bbox']
if mode == 'crop':
    assert abs(bbox[0]-72)<.1 and abs(bbox[2]-172)<.1
    assert abs(bbox[1]-old[0]['bbox'][1])<.1 and abs(bbox[3]-old[0]['bbox'][3])<.1
    assert new[1].width == 300 and new[1].height == 450
else:
    assert bbox == old[0]['bbox']
    mask_xref = next(item[1] for item in b[0].get_images(full=True) if item[0] == new[0]['xref'])
    assert mask_xref
    mask = fitz.Pixmap(b, mask_xref)
    alpha = Image.frombytes('L', (mask.width,mask.height), mask.samples)
    assert alpha.getpixel((3,3)) == 0
    assert alpha.getpixel((mask.width//2,mask.height//2)) == 255
print(json.dumps({'ok':True,'mode':mode,'bodyPreserved':True,'neighborPixelsPreserved':True,'targetChanged':True,'bbox':bbox,'bytes':Path(output_path).stat().st_size,'sha256':hashlib.sha256(Path(output_path).read_bytes()).hexdigest()}))
