"""PDF 原生基础桥接必须脱离源码和 node_modules 运行。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

_REPO = Path(__file__).resolve().parents[3]
_ENGINE = _REPO / 'smart_reporting/reporting/pdf_engine'
_NODE22 = 'docker.m.daocloud.io/library/node:22-slim'


def _run(*args: str, cwd: Path | None = None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture(scope='module')
def runtime(tmp_path_factory):
    if shutil.which('node') is None or not (_ENGINE / 'node_modules/.bin/esbuild').is_file():
        pytest.skip('需要先安装 PDF 引擎构建依赖')
    target = tmp_path_factory.mktemp('pdf-native-runtime')
    _run('npm', 'run', 'bundle:bridges', '--', '--metafile=dist/metafile.json', cwd=_ENGINE)
    _run('node', str(_ENGINE / 'bridge/package-runtime.mjs'), str(_ENGINE), str(target / 'engine'))
    return target


def _request(root: Path, payload: dict, *, node22: bool = False) -> dict:
    request = root / 'request.json'
    request.write_text(json.dumps(payload, ensure_ascii=False))
    if node22:
        command = ['docker', 'run', '--rm', '--pull=never', '--network=none', '--user', f'{os.getuid()}:{os.getgid()}',
                   '-v', f'{root}:{root}', '-w', str(root), _NODE22,
                   'node', str(root / 'engine/dist/cli.mjs'), str(request)]
    else:
        command = ['node', str(root / 'engine/dist/cli.mjs'), str(request)]
    return json.loads(_run(*command).stdout.strip().splitlines()[-1])


@pytest.mark.parametrize('node22', [False, True], ids=['local-node', 'node22'])
def test_pdf_runtime_edits_without_source_or_dependencies(runtime, node22):
    root = runtime
    if node22:
        if shutil.which('docker') is None:
            pytest.skip('Node 22 隔离验证需要 Docker')
        image = subprocess.run(['docker', 'image', 'inspect', _NODE22], capture_output=True)
        if image.returncode:
            pytest.skip('需要预先取得 Node 22 验证镜像')
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(300, 400))
    canvas.drawString(30, 350, 'FIRST PAGE')
    canvas.showPage()
    canvas.drawString(30, 350, 'SECOND PAGE')
    canvas.save()
    content = stream.getvalue()
    source = root / 'source.pdf'
    source.write_bytes(content)
    model = _request(root, {'kind': 'inspect', 'input': str(source)}, node22=node22)
    output = root / f'edited-{node22}.pdf'
    first, second = [p['pageId'] for p in model['pages']]
    receipt = _request(root, {'kind': 'patch', 'input': str(source), 'output': str(output),
        'sourceSha256': model['sourceSha256'], 'operations': [
            {'kind': 'highlight', 'pageId': first, 'rect': [20, 340, 150, 365]},
            {'kind': 'addTextAnnotation', 'pageId': first, 'rect': [150, 200, 174, 224], 'text': '原生批注'},
            {'kind': 'rotatePage', 'pageId': first, 'delta': 90},
            {'kind': 'reorderPages', 'pageIds': [second, first]},
        ]}, node22=node22)
    result = output.read_bytes()
    assert receipt['sha256'] == hashlib.sha256(result).hexdigest()
    pdf = PdfReader(BytesIO(result))
    assert 'SECOND PAGE' in pdf.pages[0].extract_text()
    assert pdf.pages[1]['/Rotate'] == 90
    annotations = [entry.get_object() for entry in pdf.pages[1]['/Annots']]
    assert {a['/Subtype'] for a in annotations} >= {'/Highlight', '/Text'}
    assert any(a.get('/Contents') == '原生批注' for a in annotations)
    assert source.read_bytes() == content
    assert not (root / 'engine/node_modules').exists()
    assert not (root / 'engine/src').exists()
    assert not (root / 'engine/vendor').exists()
    manifest = json.loads((root / 'engine/WASM-SHA256.json').read_text())
    for name, digest in manifest.items():
        assert hashlib.sha256((root / 'engine/wasm' / name).read_bytes()).hexdigest() == digest
    assert (root / 'engine/licenses/node_modules/@embedpdf/pdfium/LICENSE').is_file()
    assert (root / 'engine/licenses/node_modules/@embedpdf/pdfium/LICENSE.pdfium').is_file()
    assert (root / 'engine/licenses/node_modules/harfbuzzjs/LICENSE').is_file()


def test_pdf_runtime_packaging_rejects_missing_assets(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    result = subprocess.run(['node', str(_ENGINE / 'bridge/package-runtime.mjs'), str(source), str(tmp_path / 'out')], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'PDF runtime asset missing' in result.stderr
    assert not (tmp_path / 'out').exists()


def test_pdf_runtime_packaging_rejects_changed_assets(tmp_path):
    source = tmp_path / 'source'
    asset = source / 'node_modules/@embedpdf/pdfium/dist/pdfium.wasm'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b'wrong wasm identity')
    result = subprocess.run(['node', str(_ENGINE / 'bridge/package-runtime.mjs'), str(source), str(tmp_path / 'out')], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'PDF runtime asset identity mismatch: pdfium.wasm' in result.stderr
    assert not (tmp_path / 'out').exists()
