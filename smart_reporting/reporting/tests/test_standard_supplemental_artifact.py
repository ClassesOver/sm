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
@pytest.mark.parametrize('mode', ['single', 'query_scope', 'ratio', 'batch', 'batch_failure', 'disabled'])
async def test_runtime_standard_callback_signs_evidence_without_script(monkeypatch, mode):
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
    content = b'period,department,actual_equipment,visits\n2025-01,A,10,3\n2025-02,B,20,4\n'
    identity = {'path': 'datasets/income.csv', 'size': len(content),
                'sha256': hashlib.sha256(content).hexdigest()}
    runtime = ReportWorkflowRuntime(
        db=SimpleNamespace(),
        reporting_agent_template=Agent(model=ReportingPhaseOpenAIChat(id='test', api_key='test')),
        task_runner=SimpleNamespace(repository=SimpleNamespace()), workspace_service=workspace,
        registry=SimpleNamespace(), profiles=SimpleNamespace(), state_repository=SimpleNamespace(),
        planner_enable_thinking=False,
        **({'standard_supplemental_enabled': False} if mode == 'disabled' else {}),
    )
    assert runtime.standard_supplemental_enabled is (mode != 'disabled')
    runtime.code_mode_runtime = SimpleNamespace()
    runtime._scope = lambda _: {'threadId': 'thread-1'}
    workspace.files[identity['path']] = content
    toolkit = SimpleNamespace(read_file=AsyncMock(), complete_analysis_item=AsyncMock())
    monkeypatch.setattr(analysis_module, 'build_reporting_tools', lambda *args, **kwargs: [toolkit])
    spec = StandardSupplementalSpec(operation='group_summary', measureField='actual_equipment',
                                    dimensionField='department', periodField='period',
                                    currentPeriods=['2025-01', '2025-02'], parentFactId='fact-aaaaaaaaaaaaaaaa')

    async def run(workflow, payload, context):
        if mode == 'disabled':
            assert workflow.run_standard_supplemental is None
            return SimpleNamespace(output={'disabled': True})
        parent = SimpleNamespace(**{'fact_id': 'fact-aaaaaaaaaaaaaaaa', 'scope': {}},
                                 **{'period_values': [SimpleNamespace(period='2025-01', value=10),
                                                     SimpleNamespace(period='2025-02', value=20)]})
        dataset = {'datasetId': 'dataset_001', **identity,
                   'columns': ['period', 'department', 'actual_equipment', 'visits']}
        if mode == 'query_scope':
            parent.scope = {'income_nature': '开单收入'}
            query = ("SELECT period, department, actual_equipment, visits FROM db.income "
                     "WHERE income_nature = '开单收入'")
            dataset.update({
                'sourceType': 'starrocks_materialized',
                'provenance': {'querySql': query, 'sqlHash': hashlib.sha256(query.encode()).hexdigest()},
            })
        state = SimpleNamespace(
            decision=SimpleNamespace(coding_requirements=[SimpleNamespace(dataset_id='dataset_001', output_name='departments')]),
            instruction={'currentAnalysisId': 'analysis_001', 'analysisOutputRoot': 'evidence/analysis_001',
                         'currentAnalysis': {'analysisId': 'analysis_001', 'datasetIds': ['dataset_001']},
                         'datasets': [dataset]},
            facts=SimpleNamespace(metrics=[parent], derived_metrics=[]),
        )
        selected = spec
        if mode == 'ratio':
            denominator = SimpleNamespace(**vars(parent))
            denominator.fact_id = 'fact-bbbbbbbbbbbbbbbb'
            denominator.period_values = [SimpleNamespace(period='2025-01', value=3),
                                         SimpleNamespace(period='2025-02', value=4)]
            state.facts.metrics.append(denominator)
            ratio_fact = SimpleNamespace(fact_id='fact-cccccccccccccccc', denominator_scale=1)
            state.facts.derived_metrics.append(ratio_fact)
            selected = spec.model_copy(update={
                'operation': 'group_ratio',
                'denominator_field': 'visits',
                'denominator_parent_fact_id': denominator.fact_id,
                'ratio_fact_id': ratio_fact.fact_id,
            })
        elif mode in {'batch', 'batch_failure'}:
            second = spec.model_copy(update={'measure_field': 'visits', 'parent_fact_id': 'fact-bbbbbbbbbbbbbbbb'})
            other_parent = SimpleNamespace(**vars(parent))
            other_parent.fact_id = second.parent_fact_id
            other_parent.period_values = [SimpleNamespace(period='2025-01', value=3),
                                          SimpleNamespace(period='2025-02', value=4)]
            state.facts.metrics.append(other_parent)
            state.decision.coding_requirements.append(SimpleNamespace(dataset_id='dataset_001', output_name='visits'))
            selected = (spec, second)
            if mode == 'batch_failure':
                original = analysis_module.run_standard_supplemental
                def fail_second(**kwargs):
                    if kwargs['request'].measure_field == 'visits':
                        raise ValueError('injected second computation failure')
                    return original(**kwargs)
                monkeypatch.setattr(analysis_module, 'run_standard_supplemental', fail_second)
        result = await workflow.run_standard_supplemental(spec=selected, state=state, run_context=context)
        return SimpleNamespace(output=result)

    monkeypatch.setattr(analysis_module.AnalysisItemWorkflow, 'run', run)
    if mode == 'batch_failure':
        with pytest.raises(ValueError, match='injected second'):
            await runtime._execute_analysis_item_workflow(
                json.dumps({'currentAnalysisId': 'analysis_001', 'currentAnalysis': {}}),
                RunContext(run_id='task-1', session_id='session-1'),
                parent_run_context=RunContext(run_id='report-1', session_id='session-1'),
                model_metrics_recorder=lambda *args: None,
            )
        assert set(workspace.files) == {identity['path']}
        return
    result = await runtime._execute_analysis_item_workflow(
        json.dumps({'currentAnalysisId': 'analysis_001', 'currentAnalysis': {}}),
        RunContext(run_id='task-1', session_id='session-1'),
        parent_run_context=RunContext(run_id='report-1', session_id='session-1'),
        model_metrics_recorder=lambda *args: None,
    )
    if mode == 'disabled':
        assert result == {'disabled': True}
        return
    assert result['evidenceFile'].path == 'evidence/analysis_001/supplement.json'
    assert result['computationRecord']['scriptFileResourceId'] is None
    assert len(result['evidence'].findings[0]['rows']) == 2

    if mode == 'ratio':
        assert result['computationRecord']['method'] == 'supplemental_standard_group_ratio'
        assert result['evidence'].findings[0]['columns'] == [
            'department', 'numerator', 'denominator', 'difference', 'ratio',
        ]
        assert result['evidence'].findings[0]['rows'][0] == ['B', 20.0, 4.0, 16.0, 5.0]
    if mode == 'query_scope':
        assert result['evidence'].findings[0]['scope'] == {'income_nature': '开单收入'}
        assert result['computationRecord']['parameters']['queryBoundScopeFields'] == ['income_nature']

    assert workspace.read_counts[identity['path']] == 1
    if mode == 'batch':
        assert len(result['evidence'].findings) == 2
        record = result['computationRecord']
        assert record['method'] == 'supplemental_standard_batch'
        assert record['parameters']['findingRowCounts'] == [2, 2]
        assert [ref['jsonPointer'] for ref in record['outputFactRefs']] == [
            '/findings/0/rows/0', '/findings/0/rows/1', '/findings/1/rows/0', '/findings/1/rows/1',
        ]
        assert result['evidence'].findings[1]['rows'][0][1] == 4
