import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    supplemental_evidence_output_contract,
    validate_supplemental_evidence,
)


@pytest.mark.parametrize("reconciliation,valid", [
    ({"kind": "total", "passed": True}, False),
    ({"name": "   ", "passed": True}, False),
    ({"name": "total", "passed": "true"}, False),
    ({"name": "total", "passed": False, "difference": 3}, True),
])
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
