from pathlib import Path
from runpy import run_path


def test_pdf_smoke_static_directory_uses_explicit_snapshot(monkeypatch, tmp_path):
    helper = Path(__file__).parents[2] / 'report_editor/frontend/smoke/pdf_smoke_static.py'
    monkeypatch.setenv('PDF_SMOKE_STATIC_DIRECTORY', str(tmp_path))
    resolve = run_path(str(helper))['pdf_smoke_static_directory']
    assert resolve() == tmp_path.resolve()
    monkeypatch.delenv('PDF_SMOKE_STATIC_DIRECTORY')
    assert resolve() == helper.parents[2] / 'static'
