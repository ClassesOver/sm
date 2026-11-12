"""Independently verify physical-point calibration and immutable saved labels."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import ContentStream


def verify(directory: Path) -> dict:
    def read(name: str) -> dict:
        return json.loads((directory / name).read_text())
    info, preview, saved, reopened = [read(name) for name in (
        'server-info.json', 'preview.json', 'payload.json', 'reopened.json')]
    operations = json.loads((directory / 'staged.json').read_text())
    labels = ['2.00 m', '1.00 m', '2.00 m', '2.00 m', '4.00 m']
    pages = [0, 1, 1, 1, 0]
    assert [op['label'] for op in operations] == labels
    assert preview['appliedOperationIndices'] == list(range(5)) and preview['skippedOperations'] == []
    assert not preview.get('reviewIssues')
    source, output = PdfReader(directory / 'source.pdf'), PdfReader(directory / 'downloaded.pdf')
    source_sha = hashlib.sha256((directory / 'source.pdf').read_bytes()).hexdigest()
    output_bytes = (directory / 'downloaded.pdf').read_bytes()
    output_sha = hashlib.sha256(output_bytes).hexdigest()
    assert source_sha == info['sourceSha256'] == preview['sourceSha256']
    assert output_sha == saved['artifacts']['pdf']['sha256'] == reopened['context']['sourceFile']['sha256']
    assert len(output_bytes) == saved['artifacts']['pdf']['size']
    assert saved['revisionRegistered'] and saved['parentRevision'] == 4 and saved['revision'] == 5
    assert reopened['context']['revision'] == 5
    assert len(source.pages) == len(output.pages) == 2
    units = [float(page['/UserUnit']) for page in source.pages]
    assert units == [2, 1]
    reference_points = math.dist(operations[0]['from'], operations[0]['to']) * units[0]
    scale = reference_points / 2
    assert abs(reference_points - 160) < .1
    expected_by_page = [[], []]
    for index, (operation, page_index) in enumerate(zip(operations, pages, strict=True)):
        assert operation['kind'] == 'addDrawing' and operation['shape'] == 'measure'
        assert operation['pageId'] == f'sha256:{source_sha}:page:{page_index}'
        assert 'userUnit' not in operation
        raw = math.dist(operation['from'], operation['to'])
        assert abs(raw - (160 if index == 2 else 80)) < .1
        if index == 3:
            scale = raw * units[page_index] / 2
        expected = f'{raw * units[page_index] / scale:.2f} m'
        assert operation['label'] == expected
        expected_by_page[page_index].append(operation)
    evidence = []
    for index, (original, page) in enumerate(zip(source.pages, output.pages, strict=True)):
        assert original['/UserUnit'] == page['/UserUnit'] == units[index]
        assert list(original.cropbox) == list(page.cropbox) == [30, 40, 430, 440]
        assert list(original.mediabox) == list(page.mediabox) == [0, 0, 500, 600]
        text = f'UNIT{int(units[index])} CONTROL'
        assert text in original.extract_text() and text in page.extract_text()
        assert not original.get('/Annots')
        annotations = page['/Annots']
        assert len(annotations) == len(expected_by_page[index])
        for raw, operation in zip(annotations, expected_by_page[index], strict=True):
            annotation = raw.get_object()
            assert annotation['/Subtype'] == '/Line'
            assert list(map(float, annotation['/L'])) == operation['from'] + operation['to']
            appearance = annotation['/AP']['/N'].get_object()
            instructions = ContentStream(appearance, output).operations
            label = next(str(args[0]) for args, op in instructions if op == b'Tj')
            assert label == operation['label']
            assert appearance['/Resources']['/Font']['/F1']['/BaseFont'] == '/Helvetica'
            evidence.append({'page': index + 1, 'userUnit': units[index], 'label': label})
    return {'ok': True, 'sourceSha256': source_sha, 'outputSha256': output_sha,
            'labels': labels, 'actualSavedAnnotations': evidence, 'sourcePhysicalReferencePoints': reference_points,
            'scope': 'Mixed-UserUnit synthetic source, physical points from actual PDF geometry and saved AP labels; no automatic drawing-scale inference.'}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]))))
