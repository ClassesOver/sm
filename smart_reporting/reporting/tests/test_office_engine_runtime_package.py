"""镜像裁剪必须保留许可，并在没有源码/依赖的独立目录运行桥接。"""

import base64
import json
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from smart_reporting.reporting.delivery import office_engine

_REPO = Path(__file__).resolve().parents[3]
_PACKAGE_SCRIPT = _REPO / "docker/package-office-engine.mjs"


def test_runtime_package_retains_licenses_without_development_files(tmp_path):
    source = tmp_path / "source"
    files = {
        "dist/cli.mjs": "console.log('ok')",
        "dist/cli.mjs.map": "{}",
        "LICENSE": "engine license",
        "NOTICE": "engine notice",
        "SOURCE.md": "source origin",
        "SOURCE-SHA256.json": "{}",
        "packages/engine/src/vendor/LICENSE": "vendor license",
        "packages/engine/src/index.ts": "export const value = 1",
        "packages/engine/tests/fixture.bin": "fixture",
        "node_modules/example/package.json": '{"name":"example","version":"1.0.0","license":"MIT"}',
        "node_modules/example/index.js": "module.exports = 1",
        "node_modules/example/README.md": "license in readme",
        "node_modules/example/LICENSE": "dependency license",
    }
    for name, content in files.items():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    metafile = {
        "inputs": {"node_modules/example/index.js": {}},
        "outputs": {"dist/cli.mjs": {"imports": [{"path": "node:fs/promises", "external": True}]}},
    }
    (source / "dist/metafile.json").write_text(json.dumps(metafile))
    destination = tmp_path / "runtime"

    subprocess.run(["node", str(_PACKAGE_SCRIPT), str(source), str(destination)], check=True)

    assert {str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()} == {
        "dist/cli.mjs", "LICENSE", "NOTICE", "SOURCE.md", "SOURCE-SHA256.json",
        "licenses/packages/engine/src/vendor/LICENSE",
        "licenses/node_modules/example/LICENSE", "licenses/node_modules/example/README.md",
        "licenses/node_modules/example/package.json",
    }


def test_runtime_package_rejects_unbundled_npm_dependency(tmp_path):
    source = tmp_path / "source"
    (source / "dist").mkdir(parents=True)
    (source / "dist/metafile.json").write_text(json.dumps({
        "inputs": {},
        "outputs": {"dist/cli.mjs": {"imports": [{"path": "unbundled-package", "external": True}]}},
    }))

    result = subprocess.run(
        ["node", str(_PACKAGE_SCRIPT), str(source), str(tmp_path / "runtime")],
        capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert "unbundled-package" in result.stderr


@pytest.fixture
def isolated_engines(tmp_path, monkeypatch):
    roots = {name: _REPO / "smart_reporting/reporting" / f"{name}_engine" for name in ("slides", "workbook")}
    if shutil.which("node") is None or any(not (root / "node_modules/.bin/esbuild").is_file() for root in roots.values()):
        pytest.skip("需要先为两引擎执行 npm ci")
    monkeypatch.delenv("NODE_PATH", raising=False)
    monkeypatch.delenv("NODE_OPTIONS", raising=False)
    for name, root in roots.items():
        subprocess.run(["npm", "run", "bundle:bridges", "--", "--metafile=dist/metafile.json"], cwd=root, check=True)
        destination = tmp_path / name
        subprocess.run(["node", str(_PACKAGE_SCRIPT), str(root), str(destination)], check=True)
        monkeypatch.setenv(f"AGENT_REPORTING_{name.upper()}_ENGINE_DIR", str(destination))
        assert not (destination / "node_modules").exists()
        assert not (destination / "packages").exists()
        assert not (destination / "bridge").exists()
    return tmp_path


def _bridge(root, engine, script, request):
    path = root / f"{engine}-{script}-request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    result = office_engine.run_bridge(engine, script, path)
    assert result.returncode == 0, result.stderr
    return office_engine.last_json_line(result.stdout)


def test_docx_bundle_runs_without_source_or_node_modules(tmp_path, monkeypatch):
    from docx import Document

    from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

    bundle = _REPO / "smart_reporting/reporting/slides_engine/dist/edit-docx.mjs"
    if not bundle.is_file():
        pytest.skip("需要先为 slides_engine 执行 bundle:bridges")
    runtime = tmp_path / "runtime"
    (runtime / "dist").mkdir(parents=True)
    shutil.copy2(bundle, runtime / "dist/edit-docx.mjs")
    monkeypatch.setenv("AGENT_REPORTING_SLIDES_ENGINE_DIR", str(runtime))
    monkeypatch.delenv("NODE_PATH", raising=False)
    monkeypatch.delenv("NODE_OPTIONS", raising=False)

    document = Document()
    document.add_paragraph("独立运行原文")
    stream = BytesIO()
    document.save(stream)
    source = stream.getvalue()
    target = next(block for block in inspect_docx(source)["blocks"] if block["editable"])
    edited = patch_docx(source, [{
        "kind": "replaceParagraph", "blockId": target["blockId"],
        "expectedObjectSha256": target["expectedObjectSha256"], "text": "独立运行已编辑",
    }])

    assert Document(BytesIO(edited)).paragraphs[0].text == "独立运行已编辑"
    assert Document(BytesIO(source)).paragraphs[0].text == "独立运行原文"
    assert not (runtime / "node_modules").exists()
    assert not (runtime / "packages").exists()


def test_isolated_bundles_build_edit_render_slides_and_patch_workbook(isolated_engines):
    root = isolated_engines
    image = root / "chart.png"
    image.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=="
    ))
    presentation = root / "report.pptx"
    receipt = _bridge(root, "slides", "build-pptx", {
        "output": str(presentation), "title": "隔离运行", "period": "2026", "theme": "executive",
        "slides": [{"title": "图表", "bullets": ["样例"], "chartPath": str(image)}],
    })
    assert receipt["slideCount"] == 2
    inspected = _bridge(root, "slides", "edit-pptx", {"action": "inspect", "input": str(presentation)})
    target = next(element for element in inspected["slides"][0]["elements"] if element["text"] == "隔离运行")
    edited = root / "edited.pptx"
    _bridge(root, "slides", "edit-pptx", {
        "action": "edit", "input": str(presentation), "output": str(edited),
        "edits": [{"slideIndex": 0, "elementId": target["id"], "text": "已修改"}],
    })
    rendered = _bridge(root, "slides", "render-pptx", {"input": str(edited)})
    assert len(rendered["slides"]) == 2
    pictures = _bridge(root, "slides", "replace-picture", {"action": "inspect", "input": str(edited)})["pictures"]
    assert len(pictures) == 1
    replaced = root / "replaced.pptx"
    receipt = _bridge(root, "slides", "replace-picture", {
        "action": "replace", "input": str(edited), "output": str(replaced),
        "replacements": [{**pictures[0], "expectedSize": pictures[0]["size"],
                          "expectedSha256": pictures[0]["sha256"],
                          "bytesBase64": base64.b64encode(image.read_bytes()).decode(), "extension": "png"}],
    })
    assert receipt == {"replaced": 1}
    with ZipFile(replaced) as archive:
        assert "已修改" in archive.read("ppt/slides/slide1.xml").decode()

    workbook = root / "report.xlsx"
    receipt = _bridge(root, "workbook", "cli", {
        "kind": "create", "output": str(workbook), "title": "隔离运行", "period": "2026",
        "sheets": [{"name": "Data", "rows": [["名称", "金额"], ["样例", 7]]}],
    })
    assert receipt["sheetCount"] == 1
    patched = root / "patched.xlsx"
    _bridge(root, "workbook", "cli", {
        "kind": "patch", "input": str(workbook), "output": str(patched),
        "operations": [
            {"kind": "applyCellEdits", "edits": [{"sheetName": "Data", "row": 1, "column": 1,
                                                       "writeValue": True, "cell": {"value": 9}}]},
            {"kind": "applyDefinedNames", "plan": {"sets": [{"name": "Amount", "refersTo": "Data!$B$2"}]}},
        ],
    })
    inspected = _bridge(root, "workbook", "cli", {"kind": "inspect", "input": str(patched)})
    assert inspected["sheets"][0]["cells"]["B2"]["value"] == 9
    with ZipFile(patched) as archive:
        assert '<definedName name="Amount">Data!$B$2</definedName>' in archive.read("xl/workbook.xml").decode()


def test_runtime_package_collects_cross_workspace_bundle_licenses_without_escaping(tmp_path):
    source = tmp_path / 'reporting/pdf_engine'
    files = {
        'reporting/pdf_engine/dist/edit-pdf.mjs': "console.log('bundled')",
        'reporting/pdf_engine/LICENSE': 'pdf engine license',
        'reporting/slides_engine/LICENSE': 'shared engine license',
        'reporting/slides_engine/packages/shared/package.json': '{"name":"shared","license":"Apache-2.0"}',
        'reporting/slides_engine/packages/shared/src/index.ts': 'export const shared = 1',
        'report_editor/frontend/node_modules/@scope/dependency/package.json': '{"name":"@scope/dependency","license":"MIT"}',
        'report_editor/frontend/node_modules/@scope/dependency/LICENSE': 'external npm license',
        'report_editor/frontend/node_modules/@scope/dependency/README.md': 'npm attribution',
        'report_editor/frontend/node_modules/@scope/dependency/dist/index.js': 'module.exports = 1',
        'report_editor/frontend/src/vendor/example/LICENSE': 'vendor license',
        'report_editor/frontend/src/vendor/example/NOTICE': 'vendor attribution',
        'report_editor/frontend/src/vendor/example/src/helper.ts': 'export const helper = 1',
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (source / 'dist/metafile.json').write_text(json.dumps({
        'inputs': {name: {} for name in [
            '../slides_engine/packages/shared/src/index.ts',
            '../../report_editor/frontend/node_modules/@scope/dependency/dist/index.js',
            '../../report_editor/frontend/src/vendor/example/src/helper.ts',
        ]},
        'outputs': {'dist/edit-pdf.mjs': {'imports': []}},
    }))
    destination = tmp_path / 'runtime'
    subprocess.run(['node', str(_PACKAGE_SCRIPT), str(source), str(destination)], check=True)
    output = {str(path.relative_to(destination)): path.read_text() for path in destination.rglob('*') if path.is_file()}
    assert 'external npm license' in output.values()
    assert 'vendor license' in output.values()
    assert 'vendor attribution' in output.values()
    assert 'shared engine license' in output.values()
    assert len([value for value in output.values() if value == 'external npm license']) == 1
    assert all(name == 'dist/edit-pdf.mjs' or name == 'LICENSE' or name.startswith('licenses/') for name in output)
    assert not any(name.endswith(('.ts', '.js')) for name in output)
    assert not (tmp_path / 'runtime/report_editor').exists()
    assert not (tmp_path / 'report_editor/frontend/node_modules/@scope/dependency/LICENSE').samefile(destination / 'LICENSE')
