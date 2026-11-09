"""四格式汇编读取同一已登记快照，不重绘、不修改历史数据。"""
import hashlib
import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from smart_reporting.reporting.tests.test_report_data_revision_service import (
    attach_runner,
    service_case,
)
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    workspace,  # noqa: F401
)

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize('anyio_backend', ['asyncio'])]


@pytest.mark.parametrize('fault', [None, 'pptx', 'pptx_after_write', 'xlsx_after_write', 'validation'])
async def test_four_exporters_share_snapshot_images_and_failures_keep_document_files(tmp_path, monkeypatch, fault):
    from smart_reporting.report_editor import data_revision_exports as module

    service, context, repository, files, editor = service_case()
    baseline = await service.freeze(context)
    attach_runner(service, files)
    snapshot = await service.revise(context, {'expectedSnapshotId': baseline['snapshotId'], 'edits': [
        {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180},
    ]})
    original = deepcopy(repository.state), dict(files)
    for path, raw in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    editor.workspace_registry.get = lambda thread: SimpleNamespace(root=tmp_path)
    calls = []

    def record(kind, paths):
        calls.append((kind, [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths]))

    def render(runtime, state, markdown_path, output_path, temporary_path, **kwargs):
        images = state['render']['images']
        record('document', [tmp_path / image['path'] for image in images])
        assert state['sources'] and all(source['path'].endswith('.json') for source in state['sources'])
        for output in [output_path, kwargs['word_output_path']]:
            (tmp_path / output).write_bytes(b'generated document')
        return {'renderIssues': [], 'render': {}}

    def pptx(**kwargs):
        record('pptx', [slide['chartPath'] for slide in kwargs['slides']])
        if fault == 'pptx':
            raise RuntimeError('pptx_failed')
        kwargs['output_path'].write_bytes(b'generated pptx')
        if fault == 'pptx_after_write':
            raise RuntimeError('pptx_receipt_invalid_after_write')
        return SimpleNamespace(issues=())

    def xlsx(**kwargs):
        record('xlsx', [item['path'] for item in kwargs['images']])
        assert kwargs['source_mapping']['snapshotId'] == snapshot['snapshotId']
        for item in kwargs['images']:
            assert item['snapshotId'] == snapshot['snapshotId']
            assert item['chartRevision'] == snapshot['charts'][item['chartId']]['chartRevision']
            assert item['sourceRanges']
        assert any(180 in row for sheet in kwargs['sheets'] for row in sheet['rows'])
        kwargs['output_path'].write_bytes(b'generated xlsx')
        if fault == 'xlsx_after_write':
            raise RuntimeError('xlsx_receipt_invalid_after_write')
        return SimpleNamespace(issues=())

    def validate(*args, **kwargs):
        if fault == 'validation':
            raise RuntimeError('validation_failed')
        return {'ok': True, 'issues': []}

    monkeypatch.setattr(module.ReportRuntime, 'render_markdown', render)
    monkeypatch.setattr(module, 'build_editable_pptx', pptx)
    monkeypatch.setattr(module, 'build_workbook', xlsx)
    monkeypatch.setattr(module, 'validate_data_revision_documents', validate)
    result = module.render_data_revision_formats(root=tmp_path, snapshot=snapshot,
        tables={key: files[value['file']['path']] for key, value in snapshot['tables'].items()},
        job=context.job, output_root='reports/exports/test-export')
    assert [kind for kind, _digests in calls] == ['document', 'pptx', 'xlsx']
    assert calls[0][1] == calls[1][1] == calls[2][1]
    assert result['snapshotId'] == snapshot['snapshotId']
    assert result['chartRevisions'] == {key: value['chartRevision'] for key, value in snapshot['charts'].items()}
    expected = ({'pdf', 'word', 'xlsx'} if fault == 'pptx' else {'pdf', 'word', 'pptx', 'xlsx'})
    assert set(result['artifacts']) == expected
    if fault:
        assert result['validation']['ok'] is False and result['validation']['issues']
    if fault == 'pptx_after_write':
        assert (tmp_path / result['artifacts']['pptx']['path']).read_bytes() == b'generated pptx'
    if fault == 'xlsx_after_write':
        assert (tmp_path / result['artifacts']['xlsx']['path']).read_bytes() == b'generated xlsx'
    assert repository.state == original[0] and files == original[1]
    assert all((tmp_path / ref['path']).read_bytes() == b'generated document' for label, ref in result['artifacts'].items() if label in {'pdf', 'word'})


def test_export_rejects_symlink_ancestor_before_creating_any_output(tmp_path, anyio_backend):
    from smart_reporting.report_editor.data_revision_exports import render_data_revision_formats

    root, outside = tmp_path / 'workspace', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (root / 'exports').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        render_data_revision_formats(root=root, snapshot={}, tables={}, job={}, output_root='exports/attempt')
    assert list(outside.iterdir()) == []


def test_export_identity_rejects_symlink_file(tmp_path, anyio_backend):
    from smart_reporting.report_editor.data_revision_exports import _identity

    real = tmp_path / 'real.pdf'
    real.write_bytes(b'actual')
    (tmp_path / 'linked.pdf').symlink_to(real)
    with pytest.raises(ValueError, match='symlink'):
        _identity(tmp_path, tmp_path / 'linked.pdf')


@pytest.mark.integration
def test_real_exporters_embed_the_same_chinese_chart_and_workbook_cells(tmp_path, anyio_backend):
    from openpyxl import load_workbook
    from PIL import Image
    from pypdf import PdfReader

    from smart_reporting.report_editor.data_revision_exports import render_data_revision_formats

    fixture = Path(__file__).parent / 'fixtures' / 'data_revision'
    png = (fixture / 'revenue.png').read_bytes()
    table = json.dumps({'columns': ['期间', '营业收入（万元）'], 'rows': [['2026-10', 150]]},
        ensure_ascii=False).encode()

    def save(path, raw):
        (tmp_path / path).write_bytes(raw)
        return {'path': path, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

    snapshot = {'snapshotId': 'snapshot-150',
        'markdown': save('source.md', (fixture / 'report.md').read_bytes()),
        'tables': {'revenue': {'file': save('data.json', table)}},
        'charts': {'revenue-chart': {'image': save('revenue.png', png),
            'originalRelativePath': 'revenue.png', 'chartRevision': 'chart-150',
            'title': '营业收入', 'altText': '2026年10月营业收入150万元', 'tableIds': ['revenue']}},
        'warnings': [{'code': 'report_data_business_review_pending', 'message': '业务结论待复核。'}]}
    document = json.loads((fixture / 'document-context.json').read_bytes())
    job = {'jobId': 'data-export-probe', '_documentContext': document,
        '_editorExportSettings': {'cover': False, 'toc': False, 'sources': False}}
    result = render_data_revision_formats(root=tmp_path, snapshot=snapshot, tables={'revenue': table},
        job=job, output_root='exports/revision-2')
    artifacts = result['artifacts']
    assert set(artifacts) == {'pdf', 'word', 'pptx', 'xlsx'}, result['validation']
    assert not any(issue['code'] == 'report_data_document_validation_failed' for issue in result['validation']['issues'])
    assert not any(issue['code'] == 'report_data_pptx_layout_warning' for issue in result['validation']['issues'])
    expected = Image.open(BytesIO(png)).convert('RGB')
    pdf = PdfReader(tmp_path / artifacts['pdf']['path'])
    assert any(image.image.convert('RGB').tobytes() == expected.tobytes()
        for page in pdf.pages for image in page.images)
    for label, prefix in [('word', 'word/media/'), ('pptx', 'ppt/media/'), ('xlsx', 'xl/media/')]:
        with ZipFile(tmp_path / artifacts[label]['path']) as archive:
            assert any(archive.read(name) == png for name in archive.namelist() if name.startswith(prefix)), label
            if label == 'xlsx':
                mapping = json.loads(archive.read('smart-reporting/source-mapping.json'))
                assert mapping['sources']['snapshotId'] == 'snapshot-150'
                assert mapping['sources']['chartRevisions'] == {'revenue-chart': 'chart-150'}
                assert mapping['images'][0]['sourceRanges'] == [{'sheetName': '数据1', 'range': 'A1:B2'}]
    workbook = load_workbook(tmp_path / artifacts['xlsx']['path'], read_only=True)
    try:
        assert workbook['数据1']['B2'].value == 150
    finally:
        workbook.close()


@pytest.mark.integration
@pytest.mark.parametrize('image_suffix', ['.png', '.jpg', '.jpeg'])
async def test_native_paginated_data_revision_redraws_and_exports_current_images(workspace, image_suffix):  # noqa: F811
    from agno.tools.code import CodeMode
    from openpyxl import load_workbook
    from PIL import Image
    from pypdf import PdfReader

    from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
    from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
    from smart_reporting.reporting.delivery.publishing import (
        ReportArtifactPersistenceService,
        ReportDownloadGrantService,
    )
    from smart_reporting.reporting.host_workspace import ReportingWorkspaceRouter
    from smart_reporting.reporting.tests.delivery_fakes import (
        InMemoryDownloadGrantRepository,
        InMemoryReportArtifactRepository,
    )
    from smart_reporting.reporting.workflow.runtime.code_generation import (
        ReportingCodeGenerationRunner,
    )

    service, context, repository, files, editor = service_case(paginated=True, image_suffix=image_suffix)
    thread = workspace.identity.workspace_key
    context.scope.update(threadId=thread, database='test', companyId='company-1', sessionId='session-1')
    fixture = Path(__file__).parent / 'fixtures' / 'data_revision'
    document = json.loads((fixture / 'document-context.json').read_bytes())
    context.job.update(_documentContext=document,
        _editorExportSettings={'cover': False, 'toc': False, 'sources': False})
    repository.state = repository.state.model_copy(update={'thread_id': thread})
    repository.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    markdown = (fixture / 'report.md').read_text().replace('(revenue.png)', f'(chart_a{image_suffix})')
    markdown += f'\n![未修改图](chart_c{image_suffix})\n'
    files[context.markdown_path] = markdown.encode()
    load = editor.trace.load_manifest_and_index

    async def load_fixture(expected):
        manifest, index = await load(expected)
        manifest.markdown.size = len(files[context.markdown_path])
        manifest.markdown.sha256 = hashlib.sha256(files[context.markdown_path]).hexdigest()
        manifest.charts = [chart for chart in manifest.charts if chart.chart_id != 'chart_b']
        index.chart_traces = [trace for trace in index.chart_traces if trace.chart_id != 'chart_b']
        return manifest, index

    editor.trace.load_manifest_and_index = load_fixture
    for path, raw in files.items():
        await workspace.awrite_bytes(thread, path, raw)
    editor.workspace_registry = SimpleNamespace(get=lambda key: workspace.identity if key == thread else None)
    editor.workspace = ReportingWorkspaceRouter(editor.workspace_registry)
    storage = InMemoryReportArtifactRepository()
    editor.artifact_persistence = ReportArtifactPersistenceService(storage, editor.workspace)
    editor.download_grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    editor.public_base_url = 'http://test'

    reviews = []

    async def review(key, path, **kwargs):
        assert key == thread
        image = await workspace.ahash_file(thread, path)
        reviews.append((path, image['sha256']))
        return {'sourcePath': path, 'sha256': image['sha256'], 'reviewed': True,
            'requiresRevision': False, 'modelId': 'fixture-reviewer'}

    def forbid_model(*args, **kwargs):
        pytest.fail('已支持的标准分页不得调用绘图模型')

    runtime = ReportingCodeModeRuntime(CodeMode(snapshot=False, allow_shell=True,
        cwd=str(workspace.identity.root), timeout=45, max_kernels=1))
    lsp = ReportingLspProcessManager()
    service.chart_service = SimpleNamespace(runner=ReportingCodeGenerationRunner(
        forbid_model, runtime, lsp, vision_reviewer=SimpleNamespace(review=review)))
    try:
        baseline = await service.freeze(context)
        revised = await service.revise(context, {'expectedSnapshotId': baseline['snapshotId'], 'edits': [
            {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180},
        ]})
        chart = revised['charts']['chart_a']
        images = [chart['image'], chart['pages'][0]['image']]
        assert all(Path(ref['path']).suffix == image_suffix for ref in images)
        assert set(reviews) == {(ref['path'], ref['sha256']) for ref in images}
        assert len(chart['standardRenderProof']) == 2
        assert chart['image']['sha256'] != baseline['charts']['chart_a']['image']['sha256']
        assert revised['charts']['chart_c'] == baseline['charts']['chart_c']
        assert await service.read(context, baseline['snapshotId']) == baseline
        exported = await service.export(context, revised['snapshotId'])
        assert exported['chartRevisions']['chart_a'] == revised['snapshotId']
        assert exported['exportRegistered']
        copies = {item.artifact: b''.join(storage.chunks[item.artifact_key]) for item in storage.records.values()}
        assert set(copies) == {'pdf', 'word', 'pptx', 'xlsx'}, exported['validation']
        assert not any(issue['code'] == 'report_data_document_validation_failed'
            for issue in exported['validation']['issues'])
        raw_pages = [(workspace.identity.root / image['path']).read_bytes() for image in images]
        pdf_images = [image for page in PdfReader(BytesIO(copies['pdf'])).pages for image in page.images]
        if image_suffix == '.png':
            pdf_pixels = [image.image.convert('RGB').tobytes() for image in pdf_images]
            assert all(Image.open(BytesIO(raw)).convert('RGB').tobytes() in pdf_pixels for raw in raw_pages)
        else:
            # pypdf's extracted JPEG is decoded again; verify the original DCT stream.
            embedded = [image.indirect_reference.get_object().get_data() for image in pdf_images]
            assert set(raw_pages) <= set(embedded)
        for label, prefix in [('word', 'word/media/'), ('pptx', 'ppt/media/'), ('xlsx', 'xl/media/')]:
            with ZipFile(BytesIO(copies[label])) as archive:
                media = {archive.read(name) for name in archive.namelist() if name.startswith(prefix)}
                assert set(raw_pages) <= media
                if label == 'xlsx':
                    mapping = json.loads(archive.read('smart-reporting/source-mapping.json'))
                    assert mapping['sources']['snapshotId'] == revised['snapshotId']
                    assert {item['sha256'] for item in mapping['images'] if item['chartId'] == 'chart_a'} == {
                        image['sha256'] for image in images}
        workbook = load_workbook(BytesIO(copies['xlsx']), read_only=True)
        try:
            assert workbook['数据1']['B3'].value == 180
        finally:
            workbook.close()
    finally:
        await lsp.aclose()
        await runtime.aclose()
