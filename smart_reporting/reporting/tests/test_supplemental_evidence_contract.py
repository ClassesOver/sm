import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    supplemental_evidence_output_contract,
    validate_supplemental_evidence,
)


@pytest.mark.parametrize(
    "reconciliation,valid",
    [
        ({"kind": "total", "passed": True}, False),
        ({"name": "   ", "passed": True}, False),
        ({"name": "total", "passed": "true"}, False),
        ({"name": "total", "passed": False, "difference": 3}, True),
    ],
)
def test_reconciliation_wire_contract_matches_acceptance(reconciliation, valid):
    payload = {
        "findings": [{"value": 3}],
        "reconciliations": [reconciliation],
        "warnings": ["total mismatch"],
    }
    schema = supplemental_evidence_output_contract()["schema"]
    assert Draft202012Validator(schema).is_valid(payload) is valid
    identity = {"analysisId": "analysis_001", "datasetIds": ["dataset-1"]}
    if valid:
        validate_supplemental_evidence(json.dumps(payload), identity)
    else:
        with pytest.raises(ValidationError):
            validate_supplemental_evidence(json.dumps(payload), identity)


def test_empty_supplement_tables_or_zero_sided_reconciliation_trigger_repair():
    from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
        empty_supplemental_evidence_error,
        validate_supplemental_evidence,
    )

    def evidence(rows, left):
        return validate_supplemental_evidence(json.dumps({
            "findings": [{"name": "成本类型构成", "columns": ["成本类型", "金额"], "rows": rows}],
            "reconciliations": [{"name": "成本类型合计对账", "passed": left == 100, "left": left, "right": 100}],
            "warnings": [],
        }), {"analysisId": "analysis_005", "datasetIds": ["ds"]})

    # period_code 实为“2025-01-01”却按“2025-01”筛选：整表为空、对账左侧为 0。
    error = empty_supplemental_evidence_error(evidence([], 0))
    assert error is not None and error.code == "report_analysis_evidence_empty"
    assert error.details["emptyTables"] and error.details["zeroSidedReconciliations"] == ["成本类型合计对账"]
    # 有数据而对账差异只是业务上的不一致：照常作为软告警，不触发重跑。
    assert empty_supplemental_evidence_error(evidence([["人员支出", 60]], 60)) is None
