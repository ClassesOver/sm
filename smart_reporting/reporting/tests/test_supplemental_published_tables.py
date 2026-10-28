"""冻结补证完整表发布与精确单元格来源回归。"""
import hashlib
import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin

from .test_trace_server_tables import _Harness


def evidence_bytes():
    return json.dumps({
        'analysisId': 'analysis_001', 'datasetIds': ['dataset-url-abc0001'],
        'findings': [{'name': '全部科室收入', 'columns': ['科室', '收入', '占比', '排名'],
                      'columnMeta': {'收入': {'unit': '元'}, '占比': {'unit': '%'}},
                      'rows': [[f'科室{i}', 100 + i, (100 + i) / 100, i] for i in range(1, 58)]}],
        'reconciliations': [{'name': '合计', 'passed': True}], 'warnings': [],
    }, ensure_ascii=False).encode()


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('drift', [False, True])
@pytest.mark.parametrize('envelope', ["explicit", "legacy", "foreign"])
async def test_publishes_all_frozen_supplemental_rows_and_rejects_identity_drift(drift, envelope):
    document = json.loads(evidence_bytes())
    if envelope == "legacy":
        document.pop("analysisId")
        document.pop("datasetIds")
    elif envelope == "foreign":
        document["analysisId"] = "analysis_999"
    raw = json.dumps(document, ensure_ascii=False).encode()
    identity = FileIdentity(path='evidence/analysis_001.json', size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    item = SimpleNamespace(analysis_id='analysis_001', dataset_ids=('dataset-url-abc0001',), evidence_files=(identity,))
    checkpoint = SimpleNamespace(deterministic_fact_files={}, evidence_manifest=SimpleNamespace(evidence=(item,)))
    harness = _Harness({identity.path: raw + b' ' if drift else raw})
    outline = SimpleNamespace(sections=(SimpleNamespace(code='section_001', analysis_ids=('analysis_001',)),))
    tables, traces, _, _ = await RuntimeSectionsMixin._build_server_tables(harness, None, checkpoint=checkpoint, outline=outline)
    if drift or envelope == "foreign":
        assert tables == traces == ()
        return
    assert len(tables) == len(traces) == 1
    assert len(traces[0].row_keys) == 57
    assert len(traces[0].cells) == 57 * 4
    assert '科室57' in tables[0].markdown
    assert all(cell.source_cell is not None for cell in traces[0].cells)
    assert traces[0].origin_markdown == tables[0].markdown


def built_source():
    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
    from smart_reporting.reporting.trace.table_builder import build_supplemental_tables
    raw = evidence_bytes()
    source = {'path': 'evidence/table.json', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    resource = derive_resource_id(source['path'])
    trace, markdown = build_supplemental_tables(json.loads(raw), file_resource_id=resource)[0]
    return raw, source, resource, trace, markdown


@pytest.mark.parametrize('fault', ['none', 'missing', 'conflict'])
def test_table_source_index_registration_degrades_only_affected_bindings(fault):
    from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1

    from .test_trace_index_builder import _build_table

    raw, source, resource, trace, markdown = built_source()
    sources = () if fault == 'missing' else (source,)
    if fault == 'conflict':
        sources += ({**source, 'sha256': 'a' * 64},)
    index = _build_table(server_table_traces=(trace,), table_source_files=sources)
    RevisionTraceIndexV1.model_validate(index.model_dump(by_alias=True))
    assert len(index.tables) == 1
    if fault == 'none':
        assert len(index.tables[0].cells) == len(index.subject_bindings) == 228
        assert all(subject.source_cell is not None for subject in index.subject_bindings)
        assert resource in {file.resource_id for file in index.files}
    else:
        assert index.tables[0].cells == index.subject_bindings == ()


@pytest.mark.parametrize('fault', ['none', 'source_drift', 'edited_cell'])
def test_source_cell_quality_verifies_raw_values_without_claiming_business_semantics(fault):
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
    from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle

    from .test_trace_index_builder import _build_table

    raw, source, resource, trace, markdown = built_source()
    md = markdown.encode()
    mdfile = ArtifactFile(path='report/report.md', mediaType='text/markdown', size=len(md), sha256=hashlib.sha256(md).hexdigest())
    index = _build_table(markdown_file=mdfile, server_table_traces=(trace,), table_source_files=(source,))
    sources = {resource: raw + b' ' if fault == 'source_drift' else raw,
               derive_resource_id(mdfile.path): md}
    current = markdown.replace('| 科室1 | 101 |', '| 科室1 | 999 |') if fault == 'edited_cell' else markdown
    result = evaluate_quality_bundle(index, current, sources, authorization_scope_hash='b' * 64)
    check = result.table_checks[trace.table_id]
    assert check.status == ('verified' if fault == 'none' else 'unknown')
    assert check.scope == 'frozen_cells'
    assert check.checked_cells == (228 if fault == 'none' else 0)


def test_publication_quality_loads_supplemental_cell_sources_without_fact_registration():
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
    from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle
    from smart_reporting.reporting.workflow.runtime.publication import _quality_source_ids

    from .test_trace_index_builder import _build_table

    raw, source, resource, trace, markdown = built_source()
    md = markdown.encode()
    mdfile = ArtifactFile(path='report/report.md', mediaType='text/markdown',
                          size=len(md), sha256=hashlib.sha256(md).hexdigest())
    index = _build_table(markdown_file=mdfile, server_table_traces=(trace,), table_source_files=(source,))
    available = {resource: raw, derive_resource_id(mdfile.path): md}
    # 发布端必须加载实际单元格依赖，不能仅从 factFiles 收集来源。
    sources = {key: available[key] for key in _quality_source_ids(index, {}) if key in available}
    result = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='b' * 64)
    assert result.table_checks[trace.table_id].status == 'verified'
    assert result.table_checks[trace.table_id].checked_cells == 228


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('fault', ['none', 'source_missing', 'edited_cell'])
async def test_editor_table_cells_validate_source_text_rank_and_values(fault):
    import re

    from smart_reporting.report_editor.trace_sources import ReportEditorTraceService
    from smart_reporting.reporting.trace.table_sources import resolve_source_cell

    from .test_trace_index_builder import _build_table

    raw, source, resource, trace, markdown = built_source()
    index = _build_table(server_table_traces=(trace,), table_source_files=(source,))

    async def read(*args, **kwargs):
        return markdown.encode()

    async def unused(*args):
        return None

    async def selected(operand):
        return resolve_source_cell(operand, {} if fault == 'source_missing' else {resource: raw})

    service = SimpleNamespace(_workspace=SimpleNamespace(read_limited_regular_file=read))
    context = SimpleNamespace(scope={'threadId': 'thread-1'}, markdown_path='report.md')
    current = markdown.replace('| 科室1 | 101 |', '| 科室1 | 999 |') if fault == 'edited_cell' else markdown
    tables, summary = await ReportEditorTraceService._evaluate_tables(
        service, index, context, current, unused,
        re.compile(r'\[\[table:([^\]]+)\]\]\n(.*?)\n\[\[/table:\1\]\]', re.S),
        lambda *args: False, source_cell_of=selected,
    )
    assert summary['unbound'] == 0
    assert summary['valid'] == (228 if fault == 'none' else 227 if fault == 'edited_cell' else 0)
    assert summary['stale'] == (0 if fault == 'none' else 1 if fault == 'edited_cell' else 228)


def test_wide_supplemental_tables_preserve_every_original_cell_in_bounded_parts():
    from smart_reporting.reporting.trace.table_builder import build_supplemental_tables

    document = {'findings': [{'name': '2025年科室明细', 'columns': [f'列{i}' for i in range(12)],
                              'rows': [[f'科室{row}', *range(1, 12)] for row in range(405)]}]}
    tables = build_supplemental_tables(document, file_resource_id='trf-' + '1' * 20)
    assert len(tables) == 5
    seen = {(cell.source_cell.row_index, cell.source_cell.column_index)
            for trace, _ in tables for cell in trace.cells}
    assert seen == {(row, column) for row in range(405) for column in range(12)}
    assert all(len(trace.column_keys) <= 5 and len(trace.cells) <= 2000 for trace, _ in tables)


def test_source_cell_does_not_infer_business_window_from_title():
    from smart_reporting.reporting.trace.contracts_v1 import TableOperandV1
    from smart_reporting.reporting.trace.table_sources import resolve_source_cell

    doc = json.loads(evidence_bytes())
    doc['findings'][0]['name'] = '2025年收入'
    operand = TableOperandV1(fileResourceId='trf-' + '1' * 20, tablePointer='/findings/0',
                            rowIndex=0, columnIndex=1, coefficient='1')
    selected = resolve_source_cell(operand, {operand.file_resource_id: json.dumps(doc).encode()})
    assert selected['value'] == 101 and selected['periods'] == ()
    doc['findings'][0]['periods'] = ['2025-01', '2025-02']
    selected = resolve_source_cell(operand, {operand.file_resource_id: json.dumps(doc).encode()})
    assert selected['periods'] == ('2025-01', '2025-02')


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_conflicting_registered_evidence_identity_never_selects_first_copy():
    raw = evidence_bytes()
    identity = FileIdentity(path='evidence/table.json', size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    conflicting = identity.model_copy(update={'sha256': 'a' * 64})
    entries = tuple(SimpleNamespace(analysis_id='analysis_001', dataset_ids=('dataset-url-abc0001',),
                                    evidence_files=(item,)) for item in (identity, conflicting))
    checkpoint = SimpleNamespace(deterministic_fact_files={}, evidence_manifest=SimpleNamespace(evidence=entries))
    outline = SimpleNamespace(sections=(SimpleNamespace(code='section_001', analysis_ids=('analysis_001',)),))
    tables, traces, _, _ = await RuntimeSectionsMixin._build_server_tables(
        _Harness({identity.path: raw}), None, checkpoint=checkpoint, outline=outline,
    )
    assert tables == traces == ()
