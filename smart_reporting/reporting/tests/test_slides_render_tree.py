from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE = Path(__file__).parents[1] / 'slides_engine'
FIXTURE = ENGINE / 'packages/pptx-engine/tests/fixtures/01_standard_business.pptx'


def test_render_bridge_uses_original_element_ids_and_pixel_geometry(tmp_path: Path):
    request = tmp_path / 'render.json'
    request.write_text(json.dumps({'input': str(FIXTURE)}))
    result = subprocess.run(
        ['node_modules/.bin/tsx', 'bridge/render-pptx.ts', str(request)],
        cwd=ENGINE, capture_output=True, text=True, check=False, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert len(rendered['slides']) >= 2
    first = rendered['slides'][0]
    assert 1200 < first['widthPx'] < 1300
    assert first['heightPx'] > 0
    selectable = [node for node in first['nodes'] if not node.get('decoration')]
    assert selectable
    assert all(node['sourceId'] for node in selectable)
    assert any(node.get('text', {}).get('lines') for node in selectable)
    assert all(node['box']['w'] > 0 for node in selectable)


def test_render_service_reuses_verified_bytes(tmp_path: Path):
    from smart_reporting.report_editor.slides_render import render_pptx_tree

    rendered = render_pptx_tree(FIXTURE.read_bytes())
    assert len(rendered['slides']) >= 2
    assert rendered['slides'][0]['nodes']



@pytest.mark.anyio
async def test_render_preview_edits_use_original_engine_without_persisting(monkeypatch):
    from smart_reporting.report_editor.slides import ReportSlidesEditorService

    service = ReportSlidesEditorService(state_repository=None, workspace_registry=None, workspace=None)
    content = FIXTURE.read_bytes()
    inspected = service._run_engine(content, 'inspect')
    first = next(item for item in inspected['slides'][0]['elements'] if item['editable'] and item['text'].strip())
    async def context(_session):
        return SimpleNamespace(revision=1, pptx_sha256='a' * 64)
    async def verified(_context):
        return content
    monkeypatch.setattr(service, 'context_for_session', context)
    monkeypatch.setattr(service, '_read_verified_pptx', verified)
    rendered = await service.render_tree_for_session(None, {'expectedSha256': 'a' * 64, 'edits': [{'slideIndex': 0, 'elementId': first['id'], 'text': '实时画布文字'}]})
    node = next(item for item in rendered['slides'][0]['nodes'] if item['sourceId'] == first['id'])
    assert '实时画布文字' in ''.join(run['text'] for line in node['text']['lines'] for run in line['runs'])
    assert FIXTURE.read_bytes() == content


@pytest.mark.parametrize('payload', [
    {'expectedSha256': 'b' * 64, 'edits': []},
    {'expectedSha256': 'a' * 64, 'edits': [{'slideIndex': 0, 'elementId': 'sp_0', 'text': {'invalid': True}}]},
    {'expectedSha256': 'a' * 64, 'edits': [{'slideIndex': True, 'elementId': 'sp_0', 'text': 'x'}]},
    {'expectedSha256': 'a' * 64, 'edits': [{'slideIndex': 0, 'elementId': 'sp_0', 'geometry': {'x': 0, 'y': 0, 'width': float('nan'), 'height': 10}}]},
])
def test_render_preview_rejects_invalid_edit_payload(payload):
    from smart_reporting.report_editor.slides_render import validate_preview_edits
    from smart_reporting.reporting.models import ReportingError

    with pytest.raises(ReportingError):
        validate_preview_edits(payload, 'a' * 64)

def test_naming_bridge_projects_current_slide_text_without_render_payload(tmp_path: Path):
    request = tmp_path / 'naming.json'
    request.write_text(json.dumps({'input': str(FIXTURE), 'purpose': 'fileName'}))
    from smart_reporting.reporting.delivery.office_engine import run_bridge

    result = run_bridge('slides', 'render-pptx', request)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == {'content'}
    assert payload['content'].startswith('## Slide 1\n')
    assert '## Slide 2' in payload['content']
    assert 50 < len(payload['content']) <= 4002
    assert 'data:image' not in payload['content']

def test_naming_bridge_withholds_marked_runs_in_actual_pptx(tmp_path: Path):
    from zipfile import ZipFile

    from lxml import etree
    from smart_reporting.reporting.delivery.office_engine import run_bridge

    a = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
    source = tmp_path / 'marked.pptx'
    with ZipFile(FIXTURE) as original, ZipFile(source, 'w') as output:
        for part in original.namelist():
            data = original.read(part)
            if part == 'ppt/slides/slide1.xml':
                xml = etree.fromstring(data)
                run = next(run for run in xml.iter(a + 'r') if run.find(a + 't') is not None)
                run.find(a + 't').text = 'PRIVATE00'
                props = run.find(a + 'rPr')
                if props is None:
                    props = etree.Element(a + 'rPr')
                    run.insert(0, props)
                extensions = etree.SubElement(props, a + 'extLst')
                ext = etree.SubElement(extensions, a + 'ext', uri='{9F1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D}')
                etree.SubElement(ext, '{https://genspark.ai/genoffice/redaction/2026}redact',
                                 label='private client', nsmap={'go': 'https://genspark.ai/genoffice/redaction/2026'})
                data = etree.tostring(xml)
            output.writestr(part, data)
    request = tmp_path / 'naming.json'
    request.write_text(json.dumps({'input': str(source), 'purpose': 'fileName'}))
    result = run_bridge('slides', 'render-pptx', request)
    assert result.returncode == 0, result.stderr
    text = json.loads(result.stdout)['content']
    assert '{{private client}}' in text
    assert 'PRIVATE00' not in text
