"""DOCX 与其他 Office engine 同级，独立选择构建和运行目录。"""
from pathlib import Path

from smart_reporting.reporting.delivery.office_engine import engine_dir


def test_doc_engine_has_its_own_runtime_root(monkeypatch, tmp_path):
    monkeypatch.delenv('AGENT_REPORTING_DOC_ENGINE_DIR', raising=False)
    root = engine_dir('doc')
    assert root.name == 'doc_engine'
    assert (root / 'package.json').is_file()
    assert (root / 'bridge/edit-docx.ts').is_file()
    assert (root / 'packages/docx-engine/src/index.ts').is_file()
    monkeypatch.setenv('AGENT_REPORTING_DOC_ENGINE_DIR', str(tmp_path))
    assert engine_dir('doc') == tmp_path


def test_doc_engine_is_built_packaged_and_selected_independently():
    repo = Path(__file__).resolve().parents[3]
    dockerfile = (repo / 'Dockerfile').read_text()
    assert 'WORKDIR /build/smart_reporting/reporting/doc_engine' in dockerfile
    assert '/runtime/reporting-doc-engine /opt/reporting-doc-engine' in dockerfile
    assert 'AGENT_REPORTING_DOC_ENGINE_DIR=/opt/reporting-doc-engine' in dockerfile
    bridge = (repo / 'smart_reporting/reporting/delivery/docx_native.py').read_text()
    assert "run_bridge('doc', 'edit-docx', request)" in bridge
