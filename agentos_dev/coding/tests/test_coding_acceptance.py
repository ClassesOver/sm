import hashlib

import pytest

from agentos_dev.task_execution.acceptance import (
    AcceptanceContractError,
    AcceptancePolicy,
    normalize_acceptance_contract,
    requirement_digest,
)
from agentos_dev.task_execution.repository_impl import CodingExecution


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


def execution(
    execution_id,
    *,
    mutation_sequence=3,
    passed=True,
    validator_sha256="a" * 64,
    requirement_value=None,
    artifacts=None,
):
    current_requirement = requirement_value or requirement()
    return CodingExecution(
        execution_id=execution_id,
        external_run_id="run",
        internal_run_id="attempt",
        owner_user_id="user",
        thread_id="thread",
        sandbox_id="sandbox",
        daytona_session_id=f"session-{execution_id}",
        command_id="command",
        status="completed",
        output_cursor=0,
        terminal_output="{}",
        exit_code=0,
        mutation_sequence=mutation_sequence,
        is_verification=True,
        retained_service=False,
        kind="verify",
        operation_receipt={
            "valid": True,
            "acceptance": {
                "version": 1,
                "validatorId": current_requirement["validatorId"],
                "validatorSha256": validator_sha256,
                "mutationSequence": mutation_sequence,
                "artifacts": (
                    artifacts
                    if artifacts is not None
                    else [{"path": "reports/result.json", "size": 2, "sha256": "b" * 64}]
                ),
                "requirements": [
                    {
                        "id": current_requirement["id"],
                        "requirementDigest": requirement_digest(current_requirement),
                        "passed": passed,
                        "message": "ok" if passed else "数据不完整",
                    }
                ],
            },
        },
    )


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


def test_acceptance_policy_reports_missing_failed_stale_and_passed_evidence():
    current_contract = normalize_acceptance_contract(contract(requirement()))
    validators = {"analysis:report": "a" * 64}
    artifacts = [{"path": "reports/result.json", "size": 2, "sha256": "b" * 64}]
    policy = AcceptancePolicy()

    missing = policy.evaluate(current_contract, [], 3, artifacts, validators)
    failed = policy.evaluate(
        current_contract,
        [execution("failed", passed=False)],
        3,
        artifacts,
        validators,
    )
    stale = policy.evaluate(
        current_contract,
        [execution("stale", mutation_sequence=2)],
        3,
        artifacts,
        validators,
    )
    changed_validator = policy.evaluate(
        current_contract,
        [execution("changed", validator_sha256="c" * 64)],
        3,
        artifacts,
        validators,
    )
    passed = policy.evaluate(
        current_contract,
        [execution("passed")],
        3,
        artifacts,
        validators,
    )

    assert missing.code == "finish_acceptance_missing"
    assert failed.code == "finish_acceptance_failed"
    assert stale.code == "finish_acceptance_stale"
    assert changed_validator.code == "finish_acceptance_stale"
    assert passed.accepted is True
    assert passed.summary == {
        "version": 1,
        "requirements": [
            {
                "id": "report",
                "validatorId": "analysis:report",
                "status": "passed",
                "executionId": "passed",
            }
        ],
    }


def test_acceptance_policy_rejects_evidence_not_bound_to_final_artifact_hash():
    current_contract = normalize_acceptance_contract(contract(requirement()))

    decision = AcceptancePolicy().evaluate(
        current_contract,
        [execution("passed")],
        3,
        [{"path": "reports/result.json", "size": 3, "sha256": hashlib.sha256(b"bad").hexdigest()}],
        {"analysis:report": "a" * 64},
    )

    assert decision.code == "finish_acceptance_failed"
    assert decision.details["requirements"][0]["status"] == "failed"


def test_acceptance_policy_rejects_final_artifacts_that_drop_part_of_validator_evidence():
    current_requirement = requirement(artifact_patterns=["reports/*"])
    current_contract = normalize_acceptance_contract(contract(current_requirement))
    evidence = [
        {"path": "reports/result.json", "size": 2, "sha256": "b" * 64},
        {"path": "reports/chart.png", "size": 3, "sha256": "c" * 64},
    ]

    decision = AcceptancePolicy().evaluate(
        current_contract,
        [execution("passed", requirement_value=current_requirement, artifacts=evidence)],
        3,
        [evidence[0]],
        {"analysis:report": "a" * 64},
    )

    assert decision.code == "finish_acceptance_failed"
    assert decision.details["requirements"][0]["status"] == "failed"
