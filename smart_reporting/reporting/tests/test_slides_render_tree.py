from __future__ import annotations

import json
import subprocess
from pathlib import Path


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


