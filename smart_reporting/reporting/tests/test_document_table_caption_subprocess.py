"""固定ZIP入口必须在隔离子进程真正消费共享契约，而非只测应用内导入。"""
import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from agno.run import RunContext
from docx import Document

from smart_reporting.preferences.document_adapter import document_design
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.workspace import WorkspaceReportService

from .test_document_table_caption_numbering import caption_input, sample_markdown
from .test_report_runtime_full_render import _build_workspace


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_fixed_runtime_zip_generates_bound_table_captions_in_isolated_process(tmp_path):
    state = _build_workspace(tmp_path)
    state.pop('_editorExportSettings')
    source = tmp_path / 'report.md'
    source.write_text(source.read_text() + '\n\n' + sample_markdown())
    value = caption_input(source.read_text())
    (tmp_path / 'trace-index.json').write_bytes(value['traceIndexText'].encode())
    state.update(_tableCaptionManifest=value['manifest'], _tableCaptionWorkflowRunId=value['workflowRunId'])
    preferences = FormatPreferences.model_validate({'common': {'signer': '独立进程验证'},
        **{fmt: {'cover': False, 'toc': False, 'tables': {'captionNumbering': fmt == 'word'}}
            for fmt in ('word', 'pdf')}})
    state['_formatDesigns'] = {fmt: document_design(resolve_format_preferences(preferences, fmt)).compact()
        for fmt in ('word', 'pdf')}
    before = source.read_bytes(), (tmp_path / 'trace-index.json').read_bytes(), deepcopy(state)
    commands = []
    class Workspace:
        async def awrite_bytes(self, _thread, path, content):
            (tmp_path / path).write_bytes(content)
        async def adelete_file(self, _thread, path):
            (tmp_path / path).unlink()
        async def arun_command(self, _thread, args, *, timeout, tail):
            commands.append(args)
            result = subprocess.run([args[0], '-I', *args[1:]], cwd=tmp_path,
                capture_output=True, text=True, timeout=timeout)
            assert result.returncode == 0, result.stderr
            return result.stdout
    result = await WorkspaceReportService(Workspace())._run_report_runtime('render_markdown',
        {'job': state, 'markdown_path': 'report.md', 'output_path': 'revision/report.pdf',
            'temporary_path': '.reporting-tmp/workspace-report-subprocess-render/render.pdf'},
        RunContext(run_id=value['workflowRunId'], session_id='bound-workspace'))
    assert result['status'] == 'rendered'
    assert result['render']['tableCaptionSource']['status'] == 'verified'
    word = Document(tmp_path / 'revision/report.docx')
    assert [p.text for p in word.paragraphs if p._p.xpath('.//w:bookmarkStart[starts-with(@w:name,"tblcap_")]')] == [
        '表 1：收支明细 1234.5600', '表 2：收支明细 1234.5600']
    assert len(commands) == 1
    assert (source.read_bytes(), (tmp_path / 'trace-index.json').read_bytes(), state) == before
    assert not list(tmp_path.glob('.workspace-report-runtime-*'))
    output = Path('output/system-config-preferences/document-table-captions/subprocess')
    output.mkdir(parents=True, exist_ok=True)
    identities = []
    for suffix in ('pdf', 'docx'):
        raw = (tmp_path / f'revision/report.{suffix}').read_bytes()
        (output / f'report.{suffix}').write_bytes(raw)
        identities.append({'path': f'report.{suffix}', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    (output / 'readback.json').write_text(json.dumps({'isolatedProcess': True,
        'tableCaptionSource': result['render']['tableCaptionSource'], 'artifacts': identities}, ensure_ascii=False, indent=2))
