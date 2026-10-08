import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin
from smart_reporting.reporting.workflow.runtime.base import FileIdentity
from smart_reporting.reporting.workflow.runtime.chart_inputs import materialize_chart_inputs
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding


@pytest.mark.anyio
async def test_nested_supplement_tables_remain_bindable_without_inheriting_units():
    columns = ["period", "metric", "actual"]
    evidence = {
        "findings": [{
            "name": "预算执行",
            "columnMeta": {"actual": {"unit": "元"}},
            "tables": [
                {"name": "月度", "columns": columns, "rows": [["2025-01", "医疗收入合计", 100]]},
                {"monthly": {"columns": columns, "rows": [["2025-02", "医疗收入合计", None]]}},
            ],
        }],
        "reconciliations": [{"name": "合计对账", "passed": True}],
    }
    runtime = SimpleNamespace(
        _visualization_context={"thread_id": "thread"},
        _read_identity_model=AsyncMock(return_value=SimpleNamespace(model_dump=lambda **_: {"metrics": []})),
        _read_identity_bytes=AsyncMock(return_value=json.dumps(evidence).encode()),
    )
    supplement = FileIdentity(path="analysis/evidence/supplement.json", size=1, sha256="b" * 64)
    projection = await RuntimeAnalysisMixin._visualization_section_fact_projection(
        runtime, "analysis_001", FileIdentity(path="facts/a.json", size=1, sha256="a" * 64),
        {"datasetIds": ["dataset_001"], "evidenceFiles": [supplement.model_dump(mode="json", by_alias=True)]},
    )
    source = projection["supplementalEvidenceSources"][0]
    assert source["sourceFile"] == supplement.model_dump(mode="json", by_alias=True)
    assert {"dataPath": "findings[0].tables[0].rows", "fields": columns} in source["dataDescriptors"]
    nested = next(item for item in source["findings"] if item["dataPath"] == "findings[0].tables[1].monthly")
    assert nested["nullableFields"] == ["actual"]
    assert "columnMeta" not in nested
    binding = ChartDataBinding(analysisId="analysis_001", factPath=supplement.path,
                               dataPath="findings[0].tables[0].rows", fields=columns, role="预算执行")
    plan = SimpleNamespace(charts=[SimpleNamespace(chart_id="budget", data_bindings=[binding], interactive_path=None)])
    materialized = materialize_chart_inputs(plan, [projection], {supplement.path: evidence}, output_root="chart-inputs")
    assert not materialized.fallback_chart_ids
    document = json.loads(materialized.files[0].content)
    assert document["rows"] == [["2025-01", "医疗收入合计", 100]]
    assert not document.get("columnMeta")
