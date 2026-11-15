"""Dedicated native theme acceptance: execute the real TypeScript engine roundtrip."""
from pathlib import Path
import subprocess


def test_docx_theme_engine_roundtrip():
    engine = Path(__file__).resolve().parents[1] / "doc_engine"
    result = subprocess.run(
        ["node", "--import", "tsx", "--test", "bridge/tests/docx-theme.test.ts"],
        cwd=engine, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pass 2" in result.stdout


def test_docx_theme_accepts_real_python_docx_theme(tmp_path):
    from docx import Document
    from zipfile import ZipFile

    document = tmp_path / "source.docx"
    Document().save(document)
    theme = tmp_path / "theme.xml"
    with ZipFile(document) as archive:
        theme.write_bytes(archive.read("word/theme/theme1.xml"))
    engine = Path(__file__).resolve().parents[1] / "doc_engine"
    script = """
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {inspectDocxTheme} from './bridge/docx-theme.ts';
const model=inspectDocxTheme(readFileSync(process.argv[1],'utf8'),false);
assert.equal(model.editable,true);
assert.equal(model.colors.name,'Office');
"""
    result = subprocess.run(
        ["node", "--import", "tsx", "--input-type=module", "-e", script, str(theme)],
        cwd=engine, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
