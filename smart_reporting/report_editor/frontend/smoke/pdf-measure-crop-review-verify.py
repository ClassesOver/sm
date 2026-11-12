"""Independent pypdf/ReportLab verification of the downloaded browser artifact."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import ContentStream
from reportlab.pdfbase.pdfmetrics import stringWidth


def verify(directory: Path) -> dict:
    def read(name: str) -> dict:
        return json.loads((directory / name).read_text())
    info, saved, preview, reopened = [read(name) for name in (
        'server-info.json', 'payload.json', 'preview.json', 'reopened.json')]
    operations = read('staged.json')
    assert len(operations) == 1
    operation = operations[0]
    assert operation['kind'] == 'addDrawing' and operation['shape'] == 'measure'
    assert operation['label'] == '3.00 ' + 'W' * 12
    source_bytes = (directory / 'source.pdf').read_bytes()
    output_bytes = (directory / 'downloaded.pdf').read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    output_sha = hashlib.sha256(output_bytes).hexdigest()
    assert source_sha == info['sourceSha256'] == preview['sourceSha256']
    assert output_sha == saved['artifacts']['pdf']['sha256']
    assert len(output_bytes) == saved['artifacts']['pdf']['size']
    assert saved['revisionRegistered'] and saved['parentRevision'] == info['context']['revision']
    assert saved['revision'] == info['context']['revision'] + 1
    assert reopened['context']['sourceFile']['sha256'] == output_sha
    assert reopened['context']['revision'] == saved['revision']
    assert preview['appliedOperationIndices'] == [0] and preview['skippedOperations'] == []
    code = 'pdf_measure_label_crop_clipping'
    issue = next(issue for issue in preview['reviewIssues'] if issue['code'] == code)
    assert issue['operationIndex'] == 0 and issue['details']['visibleBox'] == [30, 40, 430, 440]
    assert 'right' in issue['details']['clippedEdges']
    assert saved['validation']['ok'] is False
    assert code in {issue['code'] for issue in saved['validation']['issues']}
    source, output = PdfReader(directory / 'source.pdf'), PdfReader(directory / 'downloaded.pdf')
    assert len(source.pages) == len(output.pages) == 1
    original, page = source.pages[0], output.pages[0]
    assert list(original.cropbox) == list(page.cropbox) == [30, 40, 430, 440]
    assert list(original.mediabox) == list(page.mediabox) == [0, 0, 500, 600]
    assert original['/UserUnit'] == page['/UserUnit'] == 2
    assert original.get('/Rotate', 0) == page.get('/Rotate', 0)
    assert 'CONTROL CONTENT' in original.extract_text() and 'CONTROL CONTENT' in page.extract_text()
    assert not original.get('/Annots') and len(page['/Annots']) == 1
    annotation = page['/Annots'][0].get_object()
    assert annotation['/Subtype'] == '/Line'
    line = list(map(float, annotation['/L']))
    assert line == operation['from'] + operation['to']
    assert float(annotation['/BS']['/W']) == operation['width']
    appearance = annotation['/AP']['/N'].get_object()
    instructions = ContentStream(appearance, output).operations
    label = next(str(args[0]) for args, op in instructions if op == b'Tj')
    matrix = next(list(map(float, args)) for args, op in instructions if op == b'Tm')
    assert label == operation['label']
    assert next(float(args[1]) for args, op in instructions if op == b'Tf') == 9
    assert appearance['/Resources']['/Font']['/F1']['/BaseFont'] == '/Helvetica'
    # Separate font library: nominal unkerned Helvetica advance extends beyond CropBox.
    advance = stringWidth(label, 'Helvetica', 9)
    assert matrix[4] + matrix[0] * advance > 430
    assert float(appearance['/BBox'][2]) > 430
    assert math.isfinite(advance)
    return {'ok': True, 'sourceSha256': source_sha, 'outputSha256': output_sha,
            'revision': saved['revision'], 'label': label, 'tm': matrix,
            'nominalHelveticaAdvance': advance, 'cropBox': list(map(float, page.cropbox)),
            'userUnit': 2, 'controlTextPreserved': True,
            'scope': 'Real downloaded bytes and revision identities; nominal width and AP bounds prove clipping risk, not full pixel equality.'}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1])), ensure_ascii=False))
