from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from smart_reporting.database import create_agent_database
from smart_reporting.reporting.workflow import state as reporting_state_module
from smart_reporting.reporting.workflow.repository import ReportingStateRepository
from smart_reporting.reporting.workflow.state import (
    ReportingPhase,
    ReportingRunState,
    ReportingStateConflict,
    ReportingStateError,
    ReportingStateReducer,
    ReportingStateVersionUnsupported,
)


def initial_state() -> ReportingRunState:
    return ReportingRunState.initial(
        report_run_id="workflow-run-1",
        external_run_id="external-run-1",
        thread_id="thread-1",
        owner_user_id="user-1",
        now=datetime(2026, 8, 13, tzinfo=UTC),
    )


def apply_phase(state: ReportingRunState, name: str) -> ReportingRunState:
    return ReportingStateReducer.apply(
        state,
        {"name": name, "commandId": f"{name}-{state.state_version}"},
        state.state_version,
    ).state


@pytest.mark.parametrize(
    ("commands", "expected"),
    [
        (("start_analysis",), ReportingPhase.ANALYSIS_RUNNING),
        (("start_analysis", "start_visualization"), ReportingPhase.VISUALIZATION),
        (
            ("start_analysis", "start_visualization", "freeze_analysis"),
            ReportingPhase.ANALYSIS_FREEZING,
        ),
        (
            ("start_analysis", "start_visualization", "freeze_analysis", "enter_sections"),
            ReportingPhase.SECTIONS,
        ),
        (
            (
                "start_analysis",
                "start_visualization",
                "freeze_analysis",
                "enter_sections",
                "start_finalize",
                "complete",
            ),
            ReportingPhase.COMPLETED,
        ),
    ],
)
def test_reducer_allows_declared_phase_paths(commands, expected):
    state = initial_state()
    for command in commands:
        state = apply_phase(state, command)
    assert state.phase is expected
    assert state.state_version == len(commands)


def test_reducer_rejects_illegal_transition_and_stale_version():
    state = initial_state()
    with pytest.raises(ReportingStateError) as illegal:
        apply_phase(state, "start_finalize")
    assert illegal.value.code == "report_state_transition_invalid"

    with pytest.raises(ReportingStateConflict):
        ReportingStateReducer.apply(
            state,
            {"name": "start_analysis", "commandId": "start"},
            expected_version=3,
        )


def test_record_artifact_is_idempotent_and_rejects_identity_change() -> None:
    identity = {"path": "analysis/evidence.json", "size": 12, "sha256": "a" * 64}
    state = initial_state()
    recorded = ReportingStateReducer.apply(
        state,
        {
            "name": "record_artifact",
            "commandId": "artifact-1",
            "payload": {"artifact": identity},
        },
        state.state_version,
    ).state
    replayed = ReportingStateReducer.apply(
        recorded,
        {
            "name": "record_artifact",
            "commandId": "artifact-2",
            "payload": {"artifact": identity},
        },
        recorded.state_version,
    ).state

    assert replayed.payload["artifacts"] == [identity]
    with pytest.raises(ReportingStateError) as raised:
        ReportingStateReducer.apply(
            replayed,
            {
                "name": "record_artifact",
                "commandId": "artifact-changed",
                "payload": {
                    "artifact": {
                        **identity,
                        "size": 13,
                        "sha256": "b" * 64,
                    }
                },
            },
            replayed.state_version,
        )

    assert raised.value.code == "report_artifact_identity_mismatch"


def test_complete_analysis_items_can_finish_out_of_order_and_enter_visualization():
    state = apply_phase(initial_state(), "start_analysis")
    state = ReportingStateReducer.apply(
        state,
        {
            "name": "set_analysis_plan",
            "commandId": "plan",
            "payload": {"analysisIds": ["analysis_001", "analysis_002"]},
        },
        state.state_version,
    ).state

    second_completed_first = ReportingStateReducer.apply(
        state,
        {
            "name": "complete_analysis_item",
            "commandId": "complete-002",
            "payload": {"analysisId": "analysis_002", "summary": "成本已复算"},
        },
        state.state_version,
    ).state
    assert second_completed_first.phase is ReportingPhase.ANALYSIS_RUNNING
    assert second_completed_first.payload["completedAnalysisIds"] == ["analysis_002"]
    assert second_completed_first.payload["currentAnalysisId"] == "analysis_001"

    completed = ReportingStateReducer.apply(
        second_completed_first,
        {
            "name": "complete_analysis_item",
            "commandId": "complete-001",
            "payload": {"analysisId": "analysis_001", "summary": "收入已复算"},
        },
        second_completed_first.state_version,
    ).state
    assert completed.phase is ReportingPhase.VISUALIZATION
    assert completed.payload["currentAnalysisId"] is None


def test_set_analysis_plan_freezes_matching_durable_plan_details():
    state = apply_phase(initial_state(), "start_analysis")
    plans = {
        "analysis_001": {
            "analysisId": "analysis_001",
            "domain": "income",
            "datasetIds": ["dataset-1"],
        }
    }

    frozen = ReportingStateReducer.apply(
        state,
        {
            "name": "set_analysis_plan",
            "commandId": "plan-details",
            "payload": {"analysisIds": ["analysis_001"], "analysisPlans": plans},
        },
        state.state_version,
    ).state
    plans["analysis_001"]["domain"] = "changed"

    assert frozen.payload["analysisPlans"]["analysis_001"]["domain"] == "income"
    with pytest.raises(ReportingStateError) as raised:
        ReportingStateReducer.apply(
            state,
            {
                "name": "set_analysis_plan",
                "commandId": "plan-details-invalid",
                "payload": {
                    "analysisIds": ["analysis_001"],
                    "analysisPlans": {"analysis_002": {}},
                },
            },
            state.state_version,
        )
    assert raised.value.code == "report_analysis_plan_invalid"


def test_targeted_rework_requires_analysis_ids_and_missing_evidence():
    state = initial_state()
    state = apply_phase(state, "start_analysis")
    state = ReportingStateReducer.apply(
        state,
        {
            "name": "set_analysis_plan",
            "commandId": "rework-plan",
            "payload": {"analysisIds": ["analysis_001"]},
        },
        state.state_version,
    ).state
    state = ReportingStateReducer.apply(
        state,
        {
            "name": "complete_analysis_item",
            "commandId": "rework-analysis-complete",
            "payload": {"analysisId": "analysis_001", "summary": "收入已复算"},
        },
        state.state_version,
    ).state
    for command in ("freeze_analysis", "enter_sections"):
        state = apply_phase(state, command)

    with pytest.raises(ReportingStateError) as invalid:
        ReportingStateReducer.apply(
            state,
            {
                "name": "request_analysis_rework",
                "commandId": "bad-rework",
                "payload": {"analysisIds": ["analysis_001"]},
            },
            state.state_version,
        )
    assert invalid.value.code == "report_analysis_rework_invalid"

    rework = ReportingStateReducer.apply(
        state,
        {
            "name": "request_analysis_rework",
            "commandId": "rework-1",
            "payload": {
                "analysisIds": ["analysis_001"],
                "missingEvidence": ["缺少同比明细"],
                "reason": "章节证据不足",
            },
        },
        state.state_version,
    ).state
    assert rework.phase is ReportingPhase.ANALYSIS_REWORK
    assert rework.payload["rework"]["analysisIds"] == ["analysis_001"]


def test_section_start_is_idempotent_and_rejects_other_work_item() -> None:
    state = initial_state().model_copy(update={"phase": ReportingPhase.SECTIONS})
    started = ReportingStateReducer.apply(
        state,
        {
            "name": "start_section",
            "commandId": "start-section-1",
            "payload": {"sectionCode": "section_001", "workItemHash": "a" * 64},
        },
        state.state_version,
    ).state

    assert started.payload["runningSections"] == {"section_001": "a" * 64}
    with pytest.raises(ReportingStateError) as raised:
        ReportingStateReducer.apply(
            started,
            {
                "name": "start_section",
                "commandId": "start-section-conflict",
                "payload": {"sectionCode": "section_001", "workItemHash": "b" * 64},
            },
            started.state_version,
        )

    assert raised.value.code == "report_section_start_conflict"


def test_targeted_rework_only_invalidates_selected_analysis_and_dependent_sections():
    state = initial_state().model_copy(
        update={
            "phase": ReportingPhase.SECTIONS,
            "payload": {
                **initial_state().payload,
                "analysisIds": ["analysis_001", "analysis_002"],
                "completedAnalysisIds": ["analysis_001", "analysis_002"],
                "analysisItems": {
                    "analysis_001": {"analysisId": "analysis_001"},
                    "analysis_002": {"analysisId": "analysis_002"},
                },
                "completedSections": ["overview", "income"],
                "sectionArtifacts": {
                    "overview": {"sectionCode": "overview", "analysisIds": ["analysis_002"]},
                    "income": {"sectionCode": "income", "analysisIds": ["analysis_001"]},
                },
                "charts": [{"chartId": "income", "sha256": "a" * 64}],
                "reportBrief": {"objective": "旧目标"},
                "analysisEvidenceManifest": {"version": "1"},
                "profileReadReceipts": [{"receiptId": "receipt-1", "datasetId": "dataset-1"}],
                "workflowCheckpoint": {
                    "phase": "sections",
                    "reportBrief": {"objective": "旧目标"},
                    "evidenceManifest": {"version": "1"},
                    "analysisManifestFile": {
                        "path": "analysis/old.json",
                        "size": 1,
                        "sha256": "b" * 64,
                    },
                },
                "checkpointMirrorFile": {
                    "path": "analysis/checkpoint.json",
                    "size": 1,
                    "sha256": "c" * 64,
                },
            },
        }
    )
    rework = ReportingStateReducer.apply(
        state,
        {
            "name": "request_analysis_rework",
            "commandId": "rework-income",
            "payload": {
                "analysisIds": ["analysis_001"],
                "missingEvidence": ["缺少收入同比明细"],
            },
        },
        state.state_version,
    ).state

    assert rework.payload["completedAnalysisIds"] == ["analysis_002"]
    assert set(rework.payload["analysisItems"]) == {"analysis_002"}
    assert rework.payload["completedSections"] == ["overview"]
    assert set(rework.payload["sectionArtifacts"]) == {"overview"}
    assert rework.payload["pendingSections"] == ["income"]
    assert rework.payload["charts"] == []
    assert rework.payload["reportBrief"] is None
    assert rework.payload["analysisEvidenceManifest"] is None
    assert rework.payload["profileReadReceipts"] == [
        {"receiptId": "receipt-1", "datasetId": "dataset-1"}
    ]
    assert rework.payload["workflowCheckpoint"]["phase"] == "analysis"
    assert rework.payload["workflowCheckpoint"]["reportBrief"] is None
    assert rework.payload["workflowCheckpoint"]["evidenceManifest"] is None
    assert rework.payload["workflowCheckpoint"]["analysisManifestFile"] is None
    assert rework.payload["checkpointMirrorFile"] is None

    running = apply_phase(rework, "start_analysis")
    assert running.phase is ReportingPhase.ANALYSIS_RUNNING
    assert running.payload["currentAnalysisId"] == "analysis_001"


def test_write_intent_is_durable_and_identity_conflicts_fail_closed():
    state = apply_phase(initial_state(), "start_analysis")
    intent = {
        "intentId": "a" * 64,
        "toolName": "create_files",
        "arguments": {"files": [{"path": "analysis/large.txt", "content": "x"}]},
        "affectedPaths": ["analysis/large.txt"],
        "expectedStates": {"analysis/large.txt": "present"},
    }
    pending = ReportingStateReducer.apply(
        state,
        {"name": "record_write_intent", "commandId": "intent", "payload": {"intent": intent}},
        state.state_version,
    ).state
    assert pending.payload["writeIntents"]["a" * 64]["status"] == "pending"

    identity = {"path": "analysis/large.txt", "size": 40_000, "sha256": "b" * 64}
    committed = ReportingStateReducer.apply(
        pending,
        {
            "name": "commit_write_intent",
            "commandId": "commit",
            "payload": {"intentId": "a" * 64, "artifacts": [identity]},
        },
        pending.state_version,
    ).state
    assert committed.payload["writeIntents"]["a" * 64]["artifacts"] == [identity]

    with pytest.raises(ReportingStateError) as conflict:
        ReportingStateReducer.apply(
            committed,
            {
                "name": "commit_write_intent",
                "commandId": "commit-changed",
                "payload": {
                    "intentId": "a" * 64,
                    "artifacts": [{**identity, "sha256": "c" * 64}],
                },
            },
            committed.state_version,
        )
    assert conflict.value.code == "report_analysis_write_identity_mismatch"


def test_write_intent_commit_sequence_follows_actual_commit_order():
    state = apply_phase(initial_state(), "start_analysis")
    intents = (
        {
            "intentId": "a" * 64,
            "toolName": "create_files",
            "arguments": {"files": [{"path": "analysis/chart.py", "content": "a"}]},
            "affectedPaths": ["analysis/chart.py"],
            "expectedStates": {"analysis/chart.py": "present"},
        },
        {
            "intentId": "b" * 64,
            "toolName": "create_files",
            "arguments": {"files": [{"path": "analysis/chart.py", "content": "b"}]},
            "affectedPaths": ["analysis/chart.py"],
            "expectedStates": {"analysis/chart.py": "present"},
        },
    )
    for intent in intents:
        state = ReportingStateReducer.apply(
            state,
            {
                "name": "record_write_intent",
                "commandId": f"record-{intent['intentId']}",
                "payload": {"intent": intent},
            },
            state.state_version,
        ).state

    for intent, sha256 in ((intents[1], "b" * 64), (intents[0], "a" * 64)):
        state = ReportingStateReducer.apply(
            state,
            {
                "name": "commit_write_intent",
                "commandId": f"commit-{intent['intentId']}",
                "payload": {
                    "intentId": intent["intentId"],
                    "artifacts": [{"path": "analysis/chart.py", "size": 1, "sha256": sha256}],
                },
            },
            state.state_version,
        ).state

    committed = state.payload["writeIntents"]
    assert committed["b" * 64]["commitSequence"] < committed["a" * 64]["commitSequence"]


def test_duplicate_section_completion_is_idempotent_only_for_same_artifact():
    state = apply_phase(initial_state(), "start_analysis")
    state = ReportingStateReducer.apply(
        state,
        {
            "name": "set_analysis_plan",
            "commandId": "plan",
            "payload": {"analysisIds": ["analysis_001"]},
        },
        state.state_version,
    ).state
    state = ReportingStateReducer.apply(
        state,
        {
            "name": "complete_section",
            "commandId": "section-1",
            "payload": {
                "sectionCode": "income",
                "analysisIds": ["analysis_001"],
                "artifactFile": {"path": "a.json", "size": 1, "sha256": "a" * 64},
            },
        },
        state.state_version,
    ).state
    with pytest.raises(ReportingStateError) as conflict:
        ReportingStateReducer.apply(
            state,
            {
                "name": "complete_section",
                "commandId": "section-2",
                "payload": {
                    "sectionCode": "income",
                    "analysisIds": ["analysis_001"],
                    "artifactFile": {"path": "b.json", "size": 1, "sha256": "b" * 64},
                },
            },
            state.state_version,
        )
    assert conflict.value.code == "report_section_completion_conflict"


@pytest.fixture
async def state_repository(tmp_path):
    database = create_agent_database(f"sqlite:///{tmp_path / 'reporting-state.db'}")
    repository = ReportingStateRepository(database.async_db)
    yield repository
    await database.async_engine.dispose()
    database.sync_engine.dispose()


@pytest.mark.anyio
async def test_repository_create_cas_idempotency_and_conflict(state_repository):
    created = await state_repository.create(initial_state())
    assert created.state_version == 0

    command = {"name": "start_analysis", "commandId": "start-1"}
    first = await state_repository.apply(
        created.report_run_id, command, expected_version=created.state_version
    )
    assert first.state.phase is ReportingPhase.ANALYSIS_RUNNING
    assert first.state.state_version == 1

    replay = await state_repository.apply(
        created.report_run_id, command, expected_version=created.state_version
    )
    assert replay.idempotent is True
    assert replay.state.state_version == 1

    with pytest.raises(ReportingStateConflict):
        await state_repository.apply(
            created.report_run_id,
            {"name": "freeze_analysis", "commandId": "freeze-1"},
            expected_version=0,
        )


@pytest.mark.anyio
async def test_repository_rejects_command_id_rebound_to_other_payload(state_repository):
    created = await state_repository.create(initial_state())
    await state_repository.apply(
        created.report_run_id,
        {
            "name": "set_analysis_plan",
            "commandId": "same-id",
            "payload": {"analysisIds": ["analysis_001"]},
        },
        expected_version=0,
    )
    with pytest.raises(ReportingStateError) as conflict:
        await state_repository.apply(
            created.report_run_id,
            {
                "name": "set_analysis_plan",
                "commandId": "same-id",
                "payload": {"analysisIds": ["analysis_002"]},
            },
            expected_version=0,
        )
    assert conflict.value.code == "report_command_replay_conflict"


@pytest.mark.anyio
async def test_repository_keeps_idempotency_after_inline_command_cache_eviction(
    state_repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reporting_state_module, "MAX_INLINE_APPLIED_COMMANDS", 2)
    state = await state_repository.create(initial_state())
    first = {"name": "trace", "commandId": "trace-0", "payload": {"index": 0}}
    for index in range(3):
        command = {"name": "trace", "commandId": f"trace-{index}", "payload": {"index": index}}
        state = (
            await state_repository.apply(
                state.report_run_id,
                command,
                expected_version=state.state_version,
            )
        ).state

    assert "trace-0" not in state.payload["appliedCommands"]
    replay = await state_repository.apply(
        state.report_run_id,
        first,
        expected_version=0,
    )

    assert replay.idempotent is True
    assert replay.state.state_version == state.state_version
    assert replay.state.payload["trace"] == state.payload["trace"]


@pytest.mark.anyio
async def test_repository_rejects_evicted_command_id_rebound_to_other_payload(
    state_repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reporting_state_module, "MAX_INLINE_APPLIED_COMMANDS", 1)
    state = await state_repository.create(initial_state())
    for index in range(2):
        state = (
            await state_repository.apply(
                state.report_run_id,
                {"name": "trace", "commandId": f"trace-{index}", "payload": {"index": index}},
                expected_version=state.state_version,
            )
        ).state

    with pytest.raises(ReportingStateError) as conflict:
        await state_repository.apply(
            state.report_run_id,
            {"name": "trace", "commandId": "trace-0", "payload": {"index": 99}},
            expected_version=0,
        )

    assert conflict.value.code == "report_command_replay_conflict"


@pytest.mark.anyio
async def test_repository_rejects_concurrent_workflow_execution_lock(state_repository) -> None:
    async with state_repository.workflow_execution_lock("external-run-1"):
        with pytest.raises(ReportingStateError) as conflict:
            async with state_repository.workflow_execution_lock("external-run-1"):
                pass

    assert conflict.value.code == "report_workflow_run_conflict"


@pytest.mark.anyio
async def test_repository_persists_workflow_thread_owner_across_instances(
    state_repository,
) -> None:
    assert await state_repository.claim_workflow_thread(
        thread_id="thread-1", external_run_id="run-1", owner_user_id="user-1"
    )

    restarted = ReportingStateRepository(state_repository.db)
    assert await restarted.ensure_workflow_thread_owner(
        thread_id="thread-1", external_run_id="run-1", owner_user_id="user-1"
    )
    assert not await restarted.claim_workflow_thread(
        thread_id="thread-1", external_run_id="run-2", owner_user_id="user-1"
    )
    assert not await restarted.ensure_workflow_thread_owner(
        thread_id="thread-1", external_run_id="run-2", owner_user_id="user-1"
    )


@pytest.mark.anyio
async def test_repository_only_releases_matching_workflow_thread_owner(
    state_repository,
) -> None:
    await state_repository.claim_workflow_thread(
        thread_id="thread-1", external_run_id="run-1", owner_user_id="user-1"
    )

    assert not await state_repository.release_workflow_thread(
        thread_id="thread-1", external_run_id="run-2", owner_user_id="user-1"
    )
    assert await state_repository.release_workflow_thread(
        thread_id="thread-1", external_run_id="run-1", owner_user_id="user-1"
    )
    assert await state_repository.claim_workflow_thread(
        thread_id="thread-1", external_run_id="run-2", owner_user_id="user-1"
    )


@pytest.mark.anyio
async def test_analysis_facts_survive_repository_restart(state_repository):
    state = await state_repository.create(initial_state())
    for command in (
        {"name": "start_analysis", "commandId": "start"},
        {
            "name": "set_analysis_plan",
            "commandId": "plan",
            "payload": {"analysisIds": ["analysis_001", "analysis_002"]},
        },
        {
            "name": "record_profile_receipt",
            "commandId": "receipt-1",
            "payload": {"receipt": {"receiptId": "receipt-1", "datasetId": "dataset-1"}},
        },
        {
            "name": "complete_analysis_item",
            "commandId": "item-1",
            "payload": {"analysisId": "analysis_001", "summary": "收入规模已复算"},
        },
    ):
        result = await state_repository.apply(
            state.report_run_id, command, expected_version=state.state_version
        )
        state = result.state

    restarted = ReportingStateRepository(state_repository.db)
    restored = await restarted.get(state.report_run_id)

    assert restored is not None
    assert restored.phase is ReportingPhase.ANALYSIS_RUNNING
    assert restored.payload["currentAnalysisId"] == "analysis_002"
    assert restored.payload["profileReadReceipts"][0]["receiptId"] == "receipt-1"
    assert restored.payload["analysisItems"]["analysis_001"]["summary"] == "收入规模已复算"


def test_chart_batch_registration_is_atomic_and_closes_lifecycle():
    state = apply_phase(apply_phase(initial_state(), "start_analysis"), "start_visualization")
    first = ReportingStateReducer.apply(
        state,
        {
            "name": "register_charts",
            "commandId": "charts-1",
            "payload": {
                "charts": [
                    {"chartId": "chart-1", "sha256": "a" * 64},
                    {"chartId": "chart-2", "sha256": "b" * 64},
                ]
            },
        },
        state.state_version,
    ).state
    assert first.payload["chartsRegistered"] is True
    assert [item["chartId"] for item in first.payload["charts"]] == ["chart-1", "chart-2"]
    replayed = ReportingStateReducer.apply(
        first,
        {
            "name": "register_charts",
            "commandId": "charts-1",
            "payload": {
                "charts": [
                    {"chartId": "chart-1", "sha256": "a" * 64},
                    {"chartId": "chart-2", "sha256": "b" * 64},
                ]
            },
        },
        first.state_version,
    )
    assert replayed.idempotent is True

    with pytest.raises(ReportingStateError) as conflict:
        ReportingStateReducer.apply(
            first,
            {
                "name": "register_charts",
                "commandId": "charts-2",
                "payload": {"charts": [{"chartId": "chart-3", "sha256": "c" * 64}]},
            },
            first.state_version,
        )
    assert conflict.value.code == "report_chart_registration_closed"


def test_profile_receipt_reuses_stable_identity_when_purpose_changes() -> None:
    state = apply_phase(initial_state(), "start_analysis")
    first_receipt = {
        "receiptId": "profile-read-abc",
        "datasetId": "dataset-1",
        "query": "variables.area.value_counts_without_nan",
        "snapshotHash": "a" * 64,
        "purpose": "读取院区分布",
    }
    first = ReportingStateReducer.apply(
        state,
        {
            "name": "record_profile_receipt",
            "commandId": "profile-purpose-1",
            "payload": {"receipt": first_receipt},
        },
        state.state_version,
    ).state
    reused = ReportingStateReducer.apply(
        first,
        {
            "name": "record_profile_receipt",
            "commandId": "profile-purpose-2",
            "payload": {
                "receipt": {**first_receipt, "purpose": "复核院区结构"},
            },
        },
        first.state_version,
    ).state

    assert reused.payload["profileReadReceipts"] == [first_receipt]


@pytest.mark.anyio
async def test_repository_rejects_legacy_schema_row(state_repository):
    state = await state_repository.create(initial_state())
    async with state_repository.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
        await connection.execute(
            update(state_repository.states)
            .where(state_repository.states.c.report_run_id == state.report_run_id)
            .values(schema_version=1)
        )
    with pytest.raises(ReportingStateVersionUnsupported):
        await state_repository.get(state.report_run_id)
