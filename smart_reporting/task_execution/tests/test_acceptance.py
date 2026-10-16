import pytest

from smart_reporting.task_execution.acceptance import (
    AcceptanceContractError,
    normalize_acceptance_contract,
)


def contract(*requirements):
    return {"version": 1, "requirements": list(requirements)}


def requirement(
    requirement_id="report",
    validator_id="analysis:report",
    *,
    parameters=None,
    artifact_patterns=None,
):
    return {
        "id": requirement_id,
        "validatorId": validator_id,
        "parameters": parameters or {},
        "artifactPatterns": artifact_patterns or ["reports/*.json"],
    }


def test_acceptance_contract_is_strict_bounded_and_canonical():
    raw = contract(requirement(parameters={"currency": "CNY"}))

    normalized = normalize_acceptance_contract(raw)

    assert normalized == raw
    assert normalize_acceptance_contract(normalized) is not normalized

    with pytest.raises(AcceptanceContractError, match="version"):
        normalize_acceptance_contract({"version": 2, "requirements": []})
    with pytest.raises(AcceptanceContractError, match="重复"):
        normalize_acceptance_contract(contract(requirement(), requirement()))
    with pytest.raises(AcceptanceContractError, match="相对 glob"):
        normalize_acceptance_contract(contract(requirement(artifact_patterns=["../report.json"])))
    with pytest.raises(AcceptanceContractError, match="64 KiB"):
        normalize_acceptance_contract(
            contract(
                *[
                    requirement(
                        f"report-{index}",
                        parameters={f"part-{part}": "x" * 4000 for part in range(4)},
                    )
                    for index in range(5)
                ]
            )
        )
