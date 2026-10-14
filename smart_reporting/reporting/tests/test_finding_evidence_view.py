"""动态章节只能向模型暴露分配发现的真实来源。"""

import json

from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.phase_models import SectionEvidenceFile


def _item(refs):
    from smart_reporting.reporting.tests.test_dynamic_section_rendering import _item as item

    return item(findingSummaries=[{
        "findingId": "finding_0000000000000001", "summary": "成本异常",
        "sourceRefs": refs,
    }])


def _file():
    return SectionEvidenceFile(
        identity=FileIdentity(path="facts.json", sha256="a" * 64, size=300),
        content=json.dumps({
            "analysisId": "analysis_001",
            "metrics": [
                {"factId": "fact-aaaaaaaaaaaaaaaa", "total": 10, "field": "income"},
                {"factId": "fact-bbbbbbbbbbbbbbbb", "total": 20, "field": "cost",
                 "periodValues": [{"period": "2025-01", "value": 20}]},
            ],
            "findings": [{"name": "未分配的补证", "rows": [[999]]}],
        }),
    )


def _ref(**changes):
    return {
        "analysisId": "analysis_001", "path": "facts.json", "fileSha256": "a" * 64,
        "pointer": "/metrics/1/periodValues", **changes,
    }


def test_view_keeps_original_pointer_and_atomic_fact_identity_without_other_facts():
    from smart_reporting.reporting.workflow.runtime.finding_evidence import finding_evidence_view

    source = _file()
    files, fact_ids, warnings = finding_evidence_view((source,), _item([_ref()]))
    assert not warnings
    assert fact_ids == {"fact-bbbbbbbbbbbbbbbb"}
    assert files[0].identity == source.identity
    view = json.loads(files[0].content)
    assert view["selected"][0]["pointer"] == "/metrics/1"
    assert view["selected"][0]["value"]["total"] == 20
    assert "income" not in files[0].content
    assert "999" not in files[0].content
    assert json.loads(source.content)["metrics"][0]["total"] == 10


def test_supplemental_view_preserves_real_finding_index_and_table_values():
    from smart_reporting.reporting.workflow.runtime.finding_evidence import finding_evidence_view

    files, fact_ids, warnings = finding_evidence_view(
        (_file(),), _item([_ref(pointer="/findings/0")])
    )
    assert not warnings
    assert not fact_ids
    assert json.loads(files[0].content)["selected"] == [{
        "pointer": "/findings/0", "value": {"name": "未分配的补证", "rows": [[999]]},
    }]
    assert "metrics" not in files[0].content


def test_wrong_identity_or_missing_pointer_is_soft_and_never_exposes_full_file():
    from smart_reporting.reporting.workflow.runtime.finding_evidence import finding_evidence_view

    for ref in (_ref(fileSha256="b" * 64), _ref(pointer="/metrics/5"), _ref(analysisId="analysis_002")):
        files, fact_ids, warnings = finding_evidence_view((_file(),), _item([ref]))
        assert not files
        assert not fact_ids
        assert warnings[0]["code"] == "report_section_finding_source_unavailable"
        assert warnings[0]["details"]["findingId"] == "finding_0000000000000001"


def test_legacy_evidence_remains_complete():
    from smart_reporting.reporting.tests.test_dynamic_section_rendering import _item
    from smart_reporting.reporting.workflow.runtime.finding_evidence import finding_evidence_view

    source = _file()
    files, fact_ids, warnings = finding_evidence_view(
        (source,), _item(findingIds=[], findingSummaries=[])
    )
    assert files == (source,)
    assert fact_ids is None
    assert not warnings
