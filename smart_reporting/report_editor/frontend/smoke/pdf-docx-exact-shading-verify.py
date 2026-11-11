"""Independent source/DOCX shading inspection, with optional real host PDF."""
import argparse
import hashlib
import json
from pathlib import Path
from runpy import run_path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pymupdf

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = '{' + NS['w'] + '}'
LABELS = ['Exact source shading', 'Peach text', 'Green text', 'Yellow text', 'Plain text', 'White text']
FILLS = {'Peach text': 'FFF2CC', 'Green text': 'E2F0D9', 'Yellow text': 'FFFF00'}


def background_colors(page, label):
    boxes = page.search_for(label)
    assert len(boxes) == 1, (label, boxes)
    box = boxes[0]
    center = pymupdf.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
    colors = []
    for drawing in page.get_drawings():
        fill = drawing.get('fill')
        if fill is None or not drawing['rect'].contains(center):
            continue
        overlap = max(0, min(drawing['rect'].x1, box.x1) - max(drawing['rect'].x0, box.x0))
        if overlap < box.width * .8:
            continue
        colors.append(''.join(f'{round(channel * 255):02X}' for channel in fill))
    return colors


def verify(source, docx, rendered=None):
    source_bytes = source.read_bytes()
    factory = run_path(str(Path(__file__).with_name('pdf-docx-exact-shading-source.py')))['source_pdf']
    assert source_bytes == factory(), 'Source identity differs from deterministic shading fixture'
    original = pymupdf.open(source)
    assert len(original) == 1
    assert all(label in original[0].get_text() for label in LABELS)
    source_colors = {}
    for label, fill in FILLS.items():
        source_colors[label] = background_colors(original[0], label)
        assert source_colors[label] and source_colors[label][-1] == fill, (label, source_colors[label])
    with ZipFile(docx) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        runs = [(run, ''.join(t.text or '' for t in run.findall('w:t', NS))) for run in root.findall('.//w:r', NS)]
        text = ''.join(value for _, value in runs)
        assert all(label in text for label in LABELS), text
        exact = {}
        for label in ['Peach text', 'Green text', 'Yellow text']:
            matching = [run for run, value in runs if value.strip() == label]
            assert len(matching) == 1, (label, len(matching))
            run = matching[0]
            rpr = run.find('w:rPr', NS)
            assert rpr.find('w:color', NS).attrib[W + 'val'] == '123456'
            assert rpr.find('w:sz', NS).attrib[W + 'val'] == '24'
            assert rpr.find('w:rFonts', NS).attrib[W + 'ascii'] == 'Liberation Sans'
            shading = rpr.find('w:shd', NS)
            highlight = rpr.find('w:highlight', NS)
            if label == 'Yellow text':
                assert shading is None and highlight is not None and highlight.attrib[W + 'val'] == 'yellow'
                exact[label] = {'namedHighlight': 'yellow', 'sourceColor': FILLS[label]}
            else:
                assert highlight is None
                assert shading is not None, label
                assert shading.attrib == {W + 'val': 'clear', W + 'color': 'auto', W + 'fill': FILLS[label]}
                exact[label] = {'shadingFill': shading.attrib[W + 'fill'], 'sourceColor': FILLS[label]}
        for run, text in runs:
            if 'Plain text' in text or 'White text' in text:
                assert run.find('w:rPr/w:shd', NS) is None
                assert run.find('w:rPr/w:highlight', NS) is None
        assert len(root.findall('.//w:rPr/w:shd', NS)) == 2
        assert len(root.findall('.//w:rPr/w:highlight', NS)) == 1
        assert not root.findall('.//w:drawing', NS), 'Editable shading text must not be rasterized'
    result = {'ok': True, 'sourceSha256': hashlib.sha256(source_bytes).hexdigest(),
              'docxSha256': hashlib.sha256(docx.read_bytes()).hexdigest(),
              'sourceBackgroundColors': source_colors, 'runBackgrounds': exact,
              'whiteAndPlainUnshaded': True, 'hostExactShadingVerified': False,
              'overallFidelityPassed': False,
              'remaining': ['完整内容/版式保真未通过；脚注 NoteRun 底色不在本批支持范围。']}
    if rendered is not None:
        host = pymupdf.open(rendered)
        assert len(host) == 1
        assert all(label in host[0].get_text() for label in LABELS)
        observations = []
        for label, fill in FILLS.items():
            colors = background_colors(host[0], label)
            assert colors and colors[-1] == fill, (label, fill, colors)
            observations.append({'text': label, 'sourceColor': fill, 'hostBackgroundColors': colors})
        for label in ['Plain text', 'White text']:
            colors = background_colors(host[0], label)
            assert not colors or colors[-1] == 'FFFFFF', (label, colors)
        result.update(hostExactShadingVerified=True, hostBackgroundObservations=observations,
                      renderedPageCount=len(host), renderedSha256=hashlib.sha256(rendered.read_bytes()).hexdigest())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('docx', type=Path)
    parser.add_argument('--rendered', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.source, args.docx, args.rendered)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text)
    print(text)
