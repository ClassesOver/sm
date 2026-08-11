from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from agno.run import RunContext

from agentos_dev.coding.reporting.data_sources import DatasetHandle
from agentos_dev.coding.reporting.workflow.checkpoint import ReportingCheckpoint
from agentos_dev.coding.reporting.workflow.runtime import (
    REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY,
    REPORT_ARTIFACTS_STATE_KEY,
    REPORT_CHECKPOINT_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_EFFECTIVE_PROFILE_STATE_KEY,
    REPORT_OUTLINE_HASH_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    REPORT_PROFILE_COVERAGE_STATE_KEY,
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    REPORT_WORKFLOW_RESULT_STATE_KEY,
    ReportWorkflowRuntime,
    _payload_sha256,
)
from agentos_dev.task_execution import TaskState


class _MemoryFs:
    def __init__(self, files: dict[str, bytes]):
        self.files = files

    async def upload_file(self, content: bytes, path: str) -> None:
        self.files[path] = bytes(content)


class _MemoryWorkspace:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.sandbox = SimpleNamespace(id="sandbox-1", fs=_MemoryFs(self.files))

    @asynccontextmanager
    async def _async_client(self):
        yield object()

    async def _asandbox_for(self, _client: object, _thread_id: str):
        return self.sandbox

    @staticmethod
    async def _aensure_directory(_sandbox: object, _path: str) -> None:
        return None

    def normalize_path(self, path: str, *, allow_root: bool) -> tuple[str, str]:
        assert not allow_root and path and not path.startswith("/") and ".." not in path.split("/")
        return path, path

    async def _adownload_file(self, _sandbox: object, path: str, limit: int) -> bytes:
        content = self.files[path]
        assert len(content) <= limit
        return content

    @staticmethod
    def _validate_content(content: bytes) -> None:
        assert content

    async def ahash_file(self, _thread_id: str, path: str) -> dict[str, Any]:
        content = self.files[path]
        return {
            "path": path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    async def abatch_hash_files(self, _thread_id: str, paths: list[str]) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for path in paths:
            if path not in self.files:
                values.append({"path": path, "missing": True})
            else:
                values.append(await self.ahash_file(_thread_id, path))
        return values

    def write_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.files[path] = content
        return {
            "path": path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    def write_bytes(self, path: str, content: bytes) -> dict[str, Any]:
        self.files[path] = content
        return {
            "path": path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }


class _PhaseRepository:
    def __init__(self) -> None:
        self.snapshots: dict[str, Any] = {}

    async def get_task_snapshot(self, task_id: str):
        return self.snapshots.get(task_id)


class _PhaseRunner:
    def __init__(self, workspace: _MemoryWorkspace) -> None:
        self.workspace = workspace
        self.repository = _PhaseRepository()
        self.instructions: dict[str, dict[str, Any]] = {}
        self.contracts: dict[str, dict[str, Any]] = {}
        self.started_scopes: list[Any] = []
        self.analysis_runs = 0
        self.section_runs: dict[str, int] = {}
        self.interrupt_section_once = True

    async def start(
        self,
        scope: Any,
        instruction: str,
        *,
        acceptance_contract: dict[str, Any],
    ) -> None:
        parameters = acceptance_contract["requirements"][0]["parameters"]
        payload = json.loads(instruction)
        assert parameters["phase"] == payload["phase"]
        self.started_scopes.append(scope)
        self.instructions[scope.external_run_id] = payload
        self.contracts[scope.external_run_id] = acceptance_contract
        self.repository.snapshots[scope.external_run_id] = SimpleNamespace(state=TaskState.ACTIVE)

    async def run(self, scope: Any, *, parent_run_id: str) -> dict[str, Any]:
        assert parent_run_id == "workflow-run"
        payload = self.instructions[scope.external_run_id]
        if payload["phase"] == "analysis":
            self.analysis_runs += 1
            identity = self._write_analysis(payload)
        else:
            if (
                payload["sectionWorkItem"]["sectionCode"] == "section_002"
                and self.interrupt_section_once
            ):
                self.interrupt_section_once = False
                raise asyncio.CancelledError
            identity = self._write_section(payload)
        self.repository.snapshots[scope.external_run_id] = SimpleNamespace(
            state=TaskState.COMPLETED
        )
        return {"artifacts": [identity], "modelMetrics": {"inputTokens": 321}}

    def _write_analysis(self, payload: dict[str, Any]) -> dict[str, Any]:
        trend_chart = self.workspace.write_bytes(
            f"charts/trend-run-{self.analysis_runs}.png", b"trend-image"
        )
        preview_chart = self.workspace.write_bytes(
            f"charts/preview-run-{self.analysis_runs}.png", b"preview-image"
        )
        evidence: list[dict[str, Any]] = []
        for index, analysis in enumerate(payload["detailedAnalysisPlan"]["analyses"], start=1):
            path = f"evidence/{analysis['analysisId']}-run-{self.analysis_runs}.json"
            evidence_file = self.workspace.write_json(
                path, {"analysisId": analysis["analysisId"], "run": self.analysis_runs}
            )
            evidence.append(
                {
                    "analysisId": analysis["analysisId"],
                    "summary": f"第 {self.analysis_runs} 次全局分析证据 {index}",
                    "datasetIds": ["dataset-1"],
                    "evidenceFiles": [evidence_file],
                    "citationIds": ["citation_001"],
                    "chartIds": (
                        ["income_trend", "unused_preview"]
                        if analysis["analysisId"] == "analysis_001"
                        else []
                    ),
                    "profileReadReceiptIds": [],
                    "warnings": [],
                }
            )
        return self.workspace.write_json(
            payload["analysisOutputPath"],
            {
                "version": "1",
                "reportBrief": {
                    "objective": "形成经营分析报告",
                    "executiveSummary": "已完成跨章节统一分析",
                    "managementQuestions": ["收入变化来自哪里"],
                    "warnings": [],
                },
                "evidenceManifest": {
                    "version": "1",
                    "evidence": evidence,
                    "metricDefinitions": [],
                    "charts": [
                        {
                            "chartId": "income_trend",
                            "sourceFile": trend_chart,
                            "title": "收入趋势",
                            "altText": "收入按月变化",
                            "citationIds": ["citation_001"],
                        },
                        {
                            "chartId": "unused_preview",
                            "sourceFile": preview_chart,
                            "title": "未采用预览",
                            "altText": "未采用的预览图",
                            "citationIds": ["citation_001"],
                        },
                    ],
                    "warnings": [],
                },
                "profileReadReceipts": [],
            },
        )

    def _write_section(self, payload: dict[str, Any]) -> dict[str, Any]:
        work_item = payload["sectionWorkItem"]
        section_code = work_item["sectionCode"]
        count = self.section_runs.get(section_code, 0) + 1
        self.section_runs[section_code] = count
        if section_code == "section_001" and count == 1:
            return self.workspace.write_json(
                payload["reworkRequestPath"],
                {
                    "version": "1",
                    "sectionCode": section_code,
                    "analysisIds": work_item["analysisIds"],
                    "reason": "缺少更新后的异常贡献证据",
                    "missingEvidence": ["补充异常对象贡献明细"],
                },
            )
        return self.workspace.write_json(
            payload["sectionOutputPath"],
            {
                "version": "1",
                "sectionCode": section_code,
                "blocks": [
                    {
                        "blockId": "conclusion",
                        "markdown": f"### 管理结论\n\n{work_item['evidence'][0]['summary']}",
                        "citationIds": ["citation_001"],
                        "chartIds": (["income_trend"] if section_code == "section_001" else []),
                    }
                ],
            },
        )


def _analysis_item(analysis_id: str, section: str) -> dict[str, Any]:
    return {
        "analysisId": analysis_id,
        "domain": "income",
        "managementQuestion": f"完成{section}分析",
        "datasetIds": ["dataset-1"],
        "fields": ["period", "amount"],
        "metrics": ["amount"],
        "periods": ["2025-01"],
        "comparisonBasis": ["同比"],
        "organizationGrain": [],
        "actions": ["复算规模与趋势"],
        "evidenceSummary": "从不可变 CSV 复算",
        "limitations": [],
        "recommendedTables": [],
        "recommendedCharts": [],
        "suggestedSection": section,
        "completionConditions": ["给出规模、趋势与异常"],
    }


@pytest.mark.anyio
async def test_runtime隔离analysis与章节run并只返工当前章后服务端装配() -> None:
    workspace = _MemoryWorkspace()
    dataset = b"period,amount\n2025-01,10\n"
    workspace.files["datasets/one.csv"] = dataset
    profile = b'{"table":{"n":1},"variables":{"amount":{"mean":10}}}'
    workspace.files["profiles/one.json"] = profile
    profile_coverage = {
        "version": "1",
        "authorizedDatasetCount": 1,
        "coveredDatasetCount": 1,
        "datasets": [
            {
                "datasetId": "dataset-1",
                "datasetPath": "datasets/one.csv",
                "datasetSize": len(dataset),
                "datasetSnapshotHash": hashlib.sha256(dataset).hexdigest(),
                "profileFile": {
                    "path": "profiles/one.json",
                    "size": len(profile),
                    "sha256": hashlib.sha256(profile).hexdigest(),
                },
                "rowCount": 1,
                "fieldCount": 2,
                "fields": ["period", "amount"],
            }
        ],
    }
    analysis_context = workspace.write_json(
        "contexts/analysis.json",
        {
            "version": 1,
            "datasetIds": ["dataset-1"],
            "datasetContexts": [],
            "profileCoverageManifest": profile_coverage,
        },
    )
    handle = DatasetHandle(
        dataset_id="dataset-1",
        source_id="operations",
        path="datasets/one.csv",
        row_count=1,
        size=len(dataset),
        sha256=hashlib.sha256(dataset).hexdigest(),
        requirement_id="income-monthly",
        sql_hash="b" * 64,
    )
    outline = {
        "reportType": "topic",
        "title": "经营分析报告",
        "sections": [
            {
                "code": "section_001",
                "title": "收入规模与趋势",
                "focus": ["解释收入变化"],
                "analysisIds": ["analysis_001"],
            },
            {
                "code": "section_002",
                "title": "异常与行动",
                "focus": ["识别异常贡献"],
                "analysisIds": ["analysis_002"],
            },
        ],
        "assumptions": [],
    }
    state: dict[str, Any] = {
        REPORT_WORKFLOW_INPUT_STATE_KEY: {
            "version": "1",
            "reportGoal": "分析收入趋势与异常",
            "reportType": "topic",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "sourceIds": ["operations"],
        },
        REPORT_OUTLINE_STATE_KEY: outline,
        REPORT_OUTLINE_HASH_STATE_KEY: _payload_sha256(outline),
        REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: {
            "version": "1",
            "analyses": [
                _analysis_item("analysis_001", "收入规模与趋势"),
                _analysis_item("analysis_002", "异常与行动"),
            ],
            "datasetIds": ["dataset-1"],
            "reportGoal": "分析收入趋势与异常",
            "analysisGoal": "分析收入趋势与异常",
            "warnings": [],
        },
        REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY: analysis_context,
        REPORT_PROFILE_COVERAGE_STATE_KEY: profile_coverage,
        REPORT_DATASET_LINEAGE_STATE_KEY: [
            {
                "datasetId": "dataset-1",
                "sourceId": "operations",
                "requirementId": "income-monthly",
                "sqlHash": "b" * 64,
                "rowCount": 1,
                "size": len(dataset),
                "sha256": hashlib.sha256(dataset).hexdigest(),
                "periodRoles": ["current"],
                "queryWindowId": "current",
            }
        ],
        REPORT_DATA_REQUIREMENTS_STATE_KEY: [],
        REPORT_EFFECTIVE_PROFILE_STATE_KEY: {},
        REPORT_WORKFLOW_RESULT_STATE_KEY: {
            "jobId": "job-1",
            "revision": 0,
            "datasets": [handle.public_dict()],
        },
    }
    runner = _PhaseRunner(workspace)
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = workspace
    runtime.task_runner = runner
    runtime.report_worker = SimpleNamespace(id="report-worker")
    runtime._data_shapes = lambda _context: ()
    runtime._profile = lambda _context: SimpleNamespace(effective_profile_hash="f" * 64)
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state=state,
        dependencies={
            "AgentOS 报表工作流": {
                "externalRunId": "workflow-run",
                "threadId": "thread-1",
                "userId": "user-1",
            }
        },
    )

    with pytest.raises(asyncio.CancelledError):
        await runtime._run_coding(context, feedback=None)
    interrupted = ReportingCheckpoint.model_validate(state[REPORT_CHECKPOINT_STATE_KEY])
    assert [item.section_code for item in interrupted.completed_sections] == ["section_001"]
    assert interrupted.pending_sections == ("section_002",)
    assert interrupted.trace[-1].section_code == "section_002"
    assert interrupted.trace[-1].status == "started"

    output = await runtime._run_coding(context, feedback=None)

    assert output["markdownPath"].endswith("report-revision-1.md")
    assert runner.analysis_runs == 2
    assert runner.section_runs == {"section_001": 2, "section_002": 1}
    analysis_instructions = [
        item for item in runner.instructions.values() if item["phase"] == "analysis"
    ]
    assert len(analysis_instructions) == 2
    assert all("profileCoverageManifest" not in item for item in analysis_instructions)
    assert all(
        item["profileCoverage"]["manifestFile"] == analysis_context
        and item["profileCoverage"]["manifestPointer"] == "/profileCoverageManifest"
        and item["profileCoverage"]["datasets"] == [{"datasetId": "dataset-1", "fieldCount": 2}]
        for item in analysis_instructions
    )
    assert all(
        "fields" not in item["profileCoverage"]["datasets"][0] for item in analysis_instructions
    )
    task_ids = [item.external_run_id for item in runner.started_scopes]
    assert len(task_ids) == len(set(task_ids)) == 5
    assert all(item.startswith("report-coding-") for item in task_ids)
    checkpoint = ReportingCheckpoint.model_validate(state[REPORT_CHECKPOINT_STATE_KEY])
    assert checkpoint.phase == "completed"
    assert checkpoint.pending_sections == ()
    assert [item.section_code for item in checkpoint.completed_sections] == [
        "section_001",
        "section_002",
    ]
    assert [item.status for item in checkpoint.trace].count("rework") == 1
    assert all(
        item.model_input_tokens == 321
        for item in checkpoint.trace
        if item.status in {"completed", "rework"} and item.task_id is not None
    )
    markdown = workspace.files[output["markdownPath"]].decode("utf-8")
    assert "[[analysis:analysis_001]]" in markdown
    assert "[[analysis:analysis_002]]" in markdown
    assert "第 2 次全局分析证据 1" in markdown
    assert "chart-001.png" in markdown
    assert "报表/智能分析/workflow-run/chart-001.png" in workspace.files
    assert "报表/智能分析/workflow-run/chart-002.png" not in workspace.files
    assert any(item.get("code") == "unused_chart_excluded" for item in checkpoint.warnings)
    assert state[REPORT_ARTIFACTS_STATE_KEY]["draft"]["analysisIds"] == [
        "analysis_001",
        "analysis_002",
    ]
    assert [item["path"] for item in state[REPORT_ARTIFACTS_STATE_KEY]["draft"]["charts"]] == [
        "报表/智能分析/workflow-run/chart-001.png"
    ]
    latest_analysis_task_id = next(
        item.task_id
        for item in reversed(checkpoint.trace)
        if item.phase == "analysis" and item.status == "completed"
    )
    assert state[REPORT_ARTIFACTS_STATE_KEY]["draft"]["codingTaskKey"] == latest_analysis_task_id
    assert any(item.path.endswith("report-revision-1.manifest.json") for item in checkpoint.files)

    runner.interrupt_section_once = True
    with pytest.raises(asyncio.CancelledError):
        await runtime._run_coding(context, feedback="补充管理建议")
    interrupted_feedback = ReportingCheckpoint.model_validate(state[REPORT_CHECKPOINT_STATE_KEY])
    assert interrupted_feedback.revision == 2
    assert [item.section_code for item in interrupted_feedback.completed_sections] == [
        "section_001"
    ]
    assert runner.analysis_runs == 3
    assert runner.section_runs == {"section_001": 3, "section_002": 1}

    revised = await runtime._run_coding(context, feedback="补充管理建议")

    assert revised["markdownPath"].endswith("report-revision-2.md")
    assert runner.analysis_runs == 3
    assert runner.section_runs == {"section_001": 3, "section_002": 2}
