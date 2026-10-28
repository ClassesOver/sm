from __future__ import annotations

import hashlib
import json

import pytest

from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin
from smart_reporting.reporting.workflow.runtime.base import ReportingError


def _payload(*, reconciliation_passed: bool = True) -> bytes:
    return json.dumps(
        {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset_001"],
            "findings": [
                {
                    "name": "department_income",
                    "columns": ["department", "value"],
                    "rows": [["A", 10.0]],
                }
            ],
            "reconciliations": [
                {"name": "department_income_total", "passed": reconciliation_passed}
            ],
            "warnings": ["reconciliation mismatch"] if not reconciliation_passed else [],
        },
        separators=(",", ":"),
    ).encode()


class _MemoryWorkspace:
    def __init__(
        self,
        *,
        mutate_after_write: bool = False,
        fail_delete: bool = False,
        concurrent_identical_write: bool = False,
    ):
        self.files: dict[str, bytes] = {}
        self.read_counts: dict[str, int] = {}
        self.mutate_after_write = mutate_after_write
        self.fail_delete = fail_delete
        self.concurrent_identical_write = concurrent_identical_write
        self.deleted: list[str] = []

    def validate_content(self, _content: bytes) -> None:
        return None

    async def abatch_hash_files(self, _thread_id: str, paths: list[str]):
        result = []
        for path in paths:
            content = self.files.get(path)
            if content is None:
                result.append({"path": path, "missing": True})
            else:
                result.append(
                    {
                        "path": path,
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
        return result

    def normalize_path(self, path: str, *, allow_root: bool):
        assert allow_root is False
        return path

    async def awrite_bytes(self, _thread_id: str, path: str, content: bytes):
        if self.concurrent_identical_write:
            self.concurrent_identical_write = False
            self.files[path] = content
            raise FileExistsError(path)
        self.files[path] = content

    async def read_limited_regular_file(self, _thread_id: str, path: str, *, max_bytes: int):
        self.read_counts[path] = self.read_counts.get(path, 0) + 1
        if self.mutate_after_write and self.read_counts[path] == 1:
            self.files[path] = b"foreign replacement"
        content = self.files[path]
        assert len(content) <= max_bytes
        return content

    async def adelete_registered_file(self, _thread_id: str, path: str, *, size: int, sha256: str):
        if self.fail_delete:
            raise OSError("delete failed")
        content = self.files.get(path)
        if content is not None and len(content) == size and hashlib.sha256(content).hexdigest() == sha256:
            del self.files[path]
            self.deleted.append(path)


def _runtime(workspace: _MemoryWorkspace) -> RuntimeAnalysisMixin:
    runtime = object.__new__(RuntimeAnalysisMixin)
    runtime.workspace_service = workspace
    return runtime


@pytest.mark.anyio
async def test_post_write_identity_drift_is_rejected_and_replacement_is_preserved():
    workspace = _MemoryWorkspace(mutate_after_write=True)
    runtime = _runtime(workspace)
    content = _payload()

    with pytest.raises(ReportingError, match="身份校验失败"):
        await runtime._write_verified_standard_supplemental_evidence(
            "thread-1", "analysis/evidence.json", content, {"analysisId": "analysis_001", "datasetIds": ["dataset_001"]}
        )

    assert workspace.files["analysis/evidence.json"] == b"foreign replacement"
    assert workspace.deleted == []


@pytest.mark.anyio
async def test_cleanup_failure_does_not_replace_post_write_identity_error():
    workspace = _MemoryWorkspace(mutate_after_write=True, fail_delete=True)
    runtime = _runtime(workspace)

    with pytest.raises(ReportingError, match="身份校验失败"):
        await runtime._write_verified_standard_supplemental_evidence(
            "thread-1", "analysis/evidence.json", _payload(), {"analysisId": "analysis_001", "datasetIds": ["dataset_001"]}
        )

    assert workspace.files["analysis/evidence.json"] == b"foreign replacement"


@pytest.mark.anyio
async def test_reconciliation_mismatch_remains_a_soft_warning_and_keeps_evidence():
    workspace = _MemoryWorkspace()
    runtime = _runtime(workspace)

    identity, evidence, created = await runtime._write_verified_standard_supplemental_evidence(
        "thread-1",
        "analysis/evidence.json",
        _payload(reconciliation_passed=False),
        {"analysisId": "analysis_001", "datasetIds": ["dataset_001"]},
    )

    assert identity.path == "analysis/evidence.json"
    assert created is True
    assert workspace.files[identity.path] == _payload(reconciliation_passed=False)
    assert evidence.reconciliations[0]["passed"] is False
    assert evidence.warnings == ("reconciliation mismatch",)


@pytest.mark.anyio
async def test_concurrent_identical_artifact_is_reused_and_not_claimed_as_created():
    workspace = _MemoryWorkspace(concurrent_identical_write=True)
    runtime = _runtime(workspace)
    content = _payload()

    identity, evidence, created = await runtime._write_verified_standard_supplemental_evidence(
        "thread-1",
        "analysis/evidence.json",
        content,
        {"analysisId": "analysis_001", "datasetIds": ["dataset_001"]},
    )

    assert identity.path == "analysis/evidence.json"
    assert evidence.findings
    assert created is False
    assert workspace.files[identity.path] == content
    assert workspace.deleted == []


@pytest.mark.anyio
async def test_runtime_standard_callback_signs_evidence_without_script(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agno.agent import Agent
    from agno.run import RunContext

    from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.runtime import analysis as analysis_module
    from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
        StandardSupplementalSpec,
    )

    workspace = _MemoryWorkspace()
    content = b'period,department,actual_equipment\n2025-01,A,10\n2025-02,B,20\n'
    identity = {'path': 'datasets/income.csv', 'size': len(content),
                'sha256': hashlib.sha256(content).hexdigest()}
    runtime = ReportWorkflowRuntime(
        db=SimpleNamespace(),
        reporting_agent_template=Agent(model=ReportingPhaseOpenAIChat(id='test', api_key='test')),
        task_runner=SimpleNamespace(repository=SimpleNamespace()), workspace_service=workspace,
        registry=SimpleNamespace(), profiles=SimpleNamespace(), state_repository=SimpleNamespace(),
        planner_enable_thinking=False,
    )
    runtime.standard_supplemental_enabled = True
    runtime.code_mode_runtime = SimpleNamespace()
    runtime._scope = lambda _: {'threadId': 'thread-1'}
    workspace.files[identity['path']] = content
    toolkit = SimpleNamespace(read_file=AsyncMock(), complete_analysis_item=AsyncMock())
    monkeypatch.setattr(analysis_module, 'build_reporting_tools', lambda *args, **kwargs: [toolkit])
    spec = StandardSupplementalSpec(operation='group_summary', measureField='actual_equipment',
                                    dimensionField='department', periodField='period',
                                    currentPeriods=['2025-01', '2025-02'], parentFactId='fact-aaaaaaaaaaaaaaaa')

    async def run(workflow, payload, context):
        parent = SimpleNamespace(**{'fact_id': 'fact-aaaaaaaaaaaaaaaa', 'scope': {}},
                                 **{'period_values': [SimpleNamespace(period='2025-01', value=10),
                                                     SimpleNamespace(period='2025-02', value=20)]})
        state = SimpleNamespace(
            decision=SimpleNamespace(coding_requirements=[SimpleNamespace(dataset_id='dataset_001', output_name='departments')]),
            instruction={'currentAnalysisId': 'analysis_001', 'analysisOutputRoot': 'evidence/analysis_001',
                         'currentAnalysis': {'analysisId': 'analysis_001', 'datasetIds': ['dataset_001']},
                         'datasets': [{'datasetId': 'dataset_001', **identity,
                                       'columns': ['period', 'department', 'actual_equipment']}]},
            facts=SimpleNamespace(metrics=[parent]),
        )
        result = await workflow.run_standard_supplemental(spec=spec, state=state, run_context=context)
        return SimpleNamespace(output=result)

    monkeypatch.setattr(analysis_module.AnalysisItemWorkflow, 'run', run)
    result = await runtime._execute_analysis_item_workflow(
        json.dumps({'currentAnalysisId': 'analysis_001', 'currentAnalysis': {}}),
        RunContext(run_id='task-1', session_id='session-1'),
        parent_run_context=RunContext(run_id='report-1', session_id='session-1'),
        model_metrics_recorder=lambda *args: None,
    )
    assert result['evidenceFile'].path == 'evidence/analysis_001/supplement.json'
    assert result['computationRecord']['scriptFileResourceId'] is None
    assert len(result['evidence'].findings[0]['rows']) == 2
