"""附表只自动展示小型汇总，完整证据及来源索引独立保留。"""

import hashlib
import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.tests.test_trace_index_builder import _build, _handle, _lineage
from smart_reporting.reporting.tests.test_trace_server_tables import _Harness
from smart_reporting.reporting.trace.computation_service import (
    build_standard_supplemental_computation_record,
)
from smart_reporting.reporting.trace.contracts_v1 import (
    FactRefV1,
    RevisionTraceIndexV1,
    SubjectBindingV1,
    TableCellBindingV1,
    TableOperandV1,
    TableTraceV1,
    derive_resource_id,
)
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.trace.subject_builder import bind_table_subjects
from smart_reporting.reporting.trace.table_builder import build_supplemental_tables
from smart_reporting.reporting.trace.table_sources import resolve_source_cell
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin


@pytest.mark.parametrize("rows,columns", [(653, 10), (58, 4), (21, 11)])
def test_summary_only_does_not_publish_large_or_wide_evidence_tables(rows, columns):
    document = {"findings": [{"name": "完整分析明细", "columns": [f"列{i}" for i in range(columns)],
                              "rows": [[f"科室{r}", *range(1, columns)] for r in range(rows)]}]}
    assert build_supplemental_tables(
        document, file_resource_id="trf-" + "1" * 20, summary_only=True,
    ) == ()
    full = build_supplemental_tables(document, file_resource_id="trf-" + "1" * 20)
    cells = {(cell.source_cell.row_index, cell.source_cell.column_index)
             for trace, _ in full for cell in trace.cells}
    assert len(cells) == rows * columns


@pytest.mark.parametrize("rows,columns,published", [(30, 5, True), (31, 5, False), (30, 6, False)])
def test_automatic_summary_size_boundary(rows, columns, published):
    document = {"findings": [{"columns": [f"列{i}" for i in range(columns)],
                              "rows": [[r, *range(1, columns)] for r in range(rows)]}]}
    tables = build_supplemental_tables(document, file_resource_id="trf-" + "1" * 20, summary_only=True)
    assert bool(tables) is published


@pytest.mark.anyio
async def test_report_keeps_small_summary_and_original_large_evidence_unchanged():
    document = {"analysisId": "analysis_001", "datasetIds": ["dataset-url-abc0001"],
                "findings": [
                    {"name": "院区收入汇总", "columns": ["院区", "收入"], "rows": [["总部", 100], ["北部", 50]]},
                    {"name": "科室月度完整明细", "columns": ["科室", "收入"],
                     "rows": [[f"科室{i}", i] for i in range(653)]},
                ]}
    raw = json.dumps(document, ensure_ascii=False).encode()
    identity = FileIdentity(path="evidence/analysis_001.json", size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    evidence = SimpleNamespace(analysis_id="analysis_001", dataset_ids=("dataset-url-abc0001",),
                               evidence_files=(identity,))
    checkpoint = SimpleNamespace(deterministic_fact_files={}, evidence_manifest=SimpleNamespace(evidence=(evidence,)))
    outline = SimpleNamespace(sections=(SimpleNamespace(code="section_001", analysis_ids=("analysis_001",)),))
    tables, traces, _, _ = await RuntimeSectionsMixin._build_server_tables(
        _Harness({identity.path: raw}), None, checkpoint=checkpoint, outline=outline,
    )
    assert len(tables) == len(traces) == 1
    assert traces[0].row_keys == ("source-row:0", "source-row:1")
    assert "院区收入汇总" in tables[0].markdown
    assert all(cell.source_cell.table_pointer == "/findings/0" for cell in traces[0].cells)
    assert len(json.loads(raw)["findings"][1]["rows"]) == 653
    assert checkpoint.evidence_manifest.evidence[0].evidence_files == (identity,)

    record = build_standard_supplemental_computation_record(
        analysis_id=evidence.analysis_id, dataset_ids=evidence.dataset_ids, input_files=(),
        evidence_file=identity.model_dump(), method="group_comparison", method_version="1",
        parameters={}, execution_id="summary-scope-test", finding_count=655, finding_row_counts=(2, 653),
    )
    index = _build(
        (_handle("dataset-url-abc0001"),), (_lineage("dataset-url-abc0001"),),
        computation_files=(identity,), computations=(record,),
    )
    assert index.tables == ()
    resource = derive_resource_id(identity.path)
    assert any(entry.file_resource_id == resource and entry.content_kind == "supplemental_evidence"
               for entry in index.fact_files)
    assert any(ref.json_pointer == "/findings/1" for ref in index.computations[0].output_fact_refs)
    # 未进入附表的末行仍可使用登记文件和原始单元格地址精确查询。
    operand = TableOperandV1(fileResourceId=resource, tablePointer="/findings/1",
                             rowIndex=652, columnIndex=1, coefficient="1")
    assert resolve_source_cell(operand, {resource: raw})["value"] == 652


def test_subject_expansion_is_bounded_roundtrippable_and_preserves_all_table_cells():
    fact = ArtifactFile(path="facts.json", mediaType="application/json", size=30, sha256="b" * 64)
    ref = FactRefV1(analysisId="analysis_001", fileResourceId=derive_resource_id(fact.path),
                    jsonPointer="/metrics/0", factKind="metric")
    claim = SubjectBindingV1(subjectId="sub-" + "f" * 16, subjectKind="text_claim",
                              locator={"sectionId": "section_001"}, subjectSha256="a" * 64,
                              claimId="claim-income", factRefs=(ref,))
    cells = tuple(TableCellBindingV1(rowKey=f"row-{i}", columnKey="金额", factRefs=(ref,)) for i in range(1000))
    tables = tuple(TableTraceV1(tableId=f"table-{i}", rowKeys=tuple(cell.row_key for cell in cells),
                                columnKeys=("金额",), cells=cells) for i in range(21))
    index = _build(
        (_handle("dataset-url-abc0001"),), (_lineage("dataset-url-abc0001"),),
        fact_files={"analysis_001": fact}, subject_bindings=(claim,), server_table_traces=tables,
    )
    assert len(index.subject_bindings) == 20000
    assert index.subject_bindings[0] == claim
    assert sum(len(table.cells) for table in index.tables) == 21000
    assert RevisionTraceIndexV1.model_validate_json(encode_trace_index(index)) == index
    assert any(notice.kind == "source_review" and "1001" in notice.reason for notice in index.review_notices)
    assert bind_table_subjects(index) == index
