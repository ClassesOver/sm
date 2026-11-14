"""只生成一次Word/PPTX并破坏实际尾块；不附加PDF视觉转换验收。"""

import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from pptx import Presentation

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.tests.test_preference_native_signature_evidence import (
    MARKER,
    PATHS,
    mapped,
    material,
)
from smart_reporting.tests.test_preference_signature_readback import (
    signature_case as signature_case,
)


@pytest.mark.parametrize('format', ['word', 'pptx'])
def test_real_native_signature_marker_maps_fields_and_missing_tail_remains_failed(signature_case, format):
    case = signature_case(format)
    if format == 'word':
        document = Document(BytesIO(case.content))
        signature = [paragraph for paragraph in document.paragraphs if paragraph.style.name == 'Report Signature']
        assert signature
        for paragraph in signature:
            paragraph._p.getparent().remove(paragraph._p)
        output = BytesIO()
        document.save(output)
    else:
        deck = Presentation(BytesIO(case.content))
        slide_id = deck.slides._sldIdLst[-1]
        deck.part.drop_rel(slide_id.rId)
        deck.slides._sldIdLst.remove(slide_id)
        output = BytesIO()
        deck.save(output)
    root = Path('output/system-config-preferences/native-signature-evidence')
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for label, content in [('valid', case.content), ('missing-tail', output.getvalue())]:
        actual = readback(content, format, case.prefs, case.frozen)
        checks = [item for item in actual['checks'] if item['path'] in {format + '.' + path for path in PATHS}]
        assert len(checks) == 3 and all(item.get('evidenceKind') == MARKER for item in checks)
        assert all('evidenceKind' not in item for item in actual['checks'] if item not in checks)
        inputs = material(format)
        inputs[0]['formats'][format]['readback'] = actual
        identity = {'size': len(content), 'sha256': sha256(content).hexdigest()}
        inputs[0]['formats'][format]['artifact'].update(identity)
        inputs[3]['formats'][format]['artifact'].update(identity)
        rows = mapped(inputs)
        assert len(rows) == 3
        assert all(row['status'] == ('passed' if label == 'valid' else 'failed') for row in rows)
        assert all(row['dimension'] == 'native' and row['scenario'] == 'configured_field'
            and row['sourceArtifact'] == {'format': format, 'role': 'artifact'} for row in rows)
        suffix = 'docx' if format == 'word' else format
        filename = format + '-' + label + '.' + suffix
        (root / filename).write_bytes(content)
        records.append({'file': filename, **identity, 'signatureChecks': checks, 'evidence': rows})
    (root / (format + '-native-proof.json')).write_text(json.dumps({'format': format,
        'realGenerator': True, 'realReader': True, 'binding': 'fixture',
        'retention': 'fixture_same_identity_not_sql', 'records': records}, ensure_ascii=False, indent=2))
