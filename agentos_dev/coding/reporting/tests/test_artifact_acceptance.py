from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agno.run import RunContext

from agentos_dev.coding.acceptance import normalize_acceptance_contract
from agentos_dev.coding.reporting.acceptance import (
    REPORT_ARTIFACT_VALIDATOR_ID,
    REPORT_ARTIFACT_VALIDATOR_SCRIPT,
    build_report_artifact_acceptance_contract,
)
from agentos_dev.coding.reporting.artifacts_v1 import (
    REQUIRED_REPORT_SECTIONS,
    ArtifactFile,
    Citation,
    ReportArtifactManifest,
)
from agentos_dev.coding.reporting.runtime import (
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    REPORT_EFFECTIVE_PROFILE_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    REPORT_RECONCILIATIONS_STATE_KEY,
    ReportWorkflowRuntime,
)


def _identity(path: Path, root: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _request(tmp_path: Path, *, include_citation: bool = True, extra_artifact: bool = False):
    markdown = tmp_path / "report.md"
    manifest = tmp_path / "report.manifest.json"
    citation = "[[citation:income]]" if include_citation else ""
    section_markers = "\n".join(
        f"[[section:{section}]]" for section in sorted(REQUIRED_REPORT_SECTIONS)
    )
    markdown.write_text(f"# 报告\n{citation}\n{section_markers}\n", encoding="utf-8")
    markdown_identity = _identity(markdown, tmp_path)
    expected_identity = {
        "reportId": "report-1",
        "revision": 1,
        "codingTaskKey": "report-coding-1",
        "datasetSnapshotHash": "a" * 64,
        "effectiveProfileHash": "b" * 64,
        "markdownPath": markdown.relative_to(tmp_path).as_posix(),
        "artifactManifestPath": manifest.relative_to(tmp_path).as_posix(),
    }
    contract = build_report_artifact_acceptance_contract(expected_identity)
    parameters = contract["requirements"][0]["parameters"]
    manifest.write_text(
        json.dumps(
            {
                "reportId": expected_identity["reportId"],
                "revision": expected_identity["revision"],
                "codingTaskKey": expected_identity["codingTaskKey"],
                "datasetSnapshotHash": expected_identity["datasetSnapshotHash"],
                "effectiveProfileHash": expected_identity["effectiveProfileHash"],
                "markdown": {
                    **markdown_identity,
                    "mediaType": "text/markdown",
                },
                "charts": [],
                "citations": [
                    {
                        "citationId": "income",
                        "datasetId": "dataset-1",
                        "requirementId": "income",
                    }
                ],
                "sections": sorted(REQUIRED_REPORT_SECTIONS),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    artifacts = [_identity(markdown, tmp_path), _identity(manifest, tmp_path)]
    if extra_artifact:
        extra = tmp_path / "invented.png"
        extra.write_bytes(b"not-a-report-artifact")
        artifacts.append(_identity(extra, tmp_path))
    return {
        "version": 1,
        "validatorId": REPORT_ARTIFACT_VALIDATOR_ID,
        "workspaceRoot": tmp_path.as_posix(),
        "mutationSequence": 1,
        "requirements": [
            {
                "id": "report-artifact",
                "parameters": parameters,
                "artifactPatterns": contract["requirements"][0]["artifactPatterns"],
                "artifacts": [
                    {**item, "absolutePath": str(tmp_path / str(item["path"]))}
                    for item in artifacts
                ],
            }
        ],
    }


def _validate(tmp_path: Path, request: dict[str, object]) -> dict[str, object]:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(REPORT_ARTIFACT_VALIDATOR_SCRIPT), str(request_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_reporting产物契约强校验但不进入模型动态输入(tmp_path: Path):
    request = _request(tmp_path)
    parameters = request["requirements"][0]["parameters"]

    contract = normalize_acceptance_contract(
        build_report_artifact_acceptance_contract(parameters["expectedIdentity"])
    )

    assert contract["requirements"][0]["validatorId"] == REPORT_ARTIFACT_VALIDATOR_ID
    assert "manifestSchema" in contract["requirements"][0]["parameters"]


@pytest.mark.parametrize(
    ("include_citation", "extra_artifact", "issue"),
    [
        (False, False, "missingCitationIds"),
        (True, True, "unexpectedArtifactPaths"),
    ],
)
def test_reporting服务端validator拒绝marker或实际路径漂移(
    tmp_path: Path,
    include_citation: bool,
    extra_artifact: bool,
    issue: str,
):
    result = _validate(
        tmp_path,
        _request(
            tmp_path,
            include_citation=include_citation,
            extra_artifact=extra_artifact,
        ),
    )

    requirement = result["requirements"][0]
    assert requirement["passed"] is False
    assert issue in requirement["details"]


def test_reporting服务端validator接受正式manifest契约(tmp_path: Path):
    result = _validate(tmp_path, _request(tmp_path))

    assert result == {
        "version": 1,
        "requirements": [{"id": "report-artifact", "passed": True}],
    }


@pytest.mark.anyio
async def test_coding任务启动即绑定正式产物契约且workflow不再二次纠错():
    captured: dict[str, Any] = {}

    class Repository:
        task = None

        async def get_task_snapshot(self, _task_id):
            return self.task

    class Supervisor:
        repository = Repository()

        async def start_task(self, scope, instruction, *, acceptance_contract=None):
            parsed_instruction = json.loads(instruction)
            captured.update(
                scope=scope,
                instruction=parsed_instruction,
                acceptance_contract=acceptance_contract,
            )
            self.repository.task = SimpleNamespace(
                finish_receipt={
                    "artifacts": [
                        {
                            "path": parsed_instruction["artifactManifestPath"],
                            "size": 1,
                            "sha256": "d" * 64,
                        }
                    ],
                    "acceptance": {"version": 1, "requirements": []},
                }
            )

        async def run_task(self, _scope):
            yield SimpleNamespace(type="terminal", data={"state": "completed"})

        async def revise_task(self, *_args, **_kwargs):
            pytest.fail("正式 acceptance contract 失败应在 Coding 内纠错")

    class Workspace:
        @asynccontextmanager
        async def _async_client(self):
            yield object()

        async def _asandbox_for(self, _client, _thread_id):
            return SimpleNamespace(id="sandbox")

    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = Workspace()
    runtime.supervisor = Supervisor()
    runtime.report_worker = SimpleNamespace(id="report-worker")
    runtime._state = lambda _context: {
        REPORT_OUTLINE_STATE_KEY: {},
        REPORT_EFFECTIVE_PROFILE_STATE_KEY: {},
        REPORT_ANALYSIS_PLAN_STATE_KEY: {},
        REPORT_DATA_REQUIREMENTS_STATE_KEY: [],
        REPORT_DATASET_LINEAGE_STATE_KEY: [],
        REPORT_RECONCILIATIONS_STATE_KEY: [],
    }
    result = {"datasets": [], "jobId": "job-1", "revision": 0}
    runtime._workflow_result = lambda _state: result
    runtime._scope = lambda _context: {
        "userId": "user",
        "threadId": "thread",
    }
    runtime._envelope = lambda _context: SimpleNamespace(report_goal="生成报表")
    runtime._data_shapes = lambda _context: ()
    runtime._profile = lambda _context: SimpleNamespace(effective_profile_hash="b" * 64)

    async def load_manifest(_manifest_path, **_kwargs):
        return ReportArtifactManifest(
            reportId="workflow-run",
            revision=1,
            codingTaskKey=captured["scope"].external_run_id,
            datasetSnapshotHash=hashlib.sha256(b"[]").hexdigest(),
            effectiveProfileHash="b" * 64,
            markdown=ArtifactFile(
                path=captured["instruction"]["markdownPath"],
                mediaType="text/markdown",
                size=1,
                sha256="c" * 64,
            ),
            citations=(Citation(citationId="c", datasetId="d", requirementId="r"),),
            sections=tuple(sorted(REQUIRED_REPORT_SECTIONS)),
        )

    runtime._load_artifact_manifest = load_manifest
    context = RunContext(run_id="workflow-run", session_id="session", user_id="user")

    await runtime._run_coding(context, feedback=None)

    instruction = captured["instruction"]
    contract = captured["acceptance_contract"]
    assert instruction["artifactAcceptance"] == {
        "validatorId": REPORT_ARTIFACT_VALIDATOR_ID,
        "requiredArtifactPaths": [
            "报表/智能分析/workflow-run/report-revision-1.md",
            "报表/智能分析/workflow-run/report-revision-1.manifest.json",
        ],
        "includeManifestChartPaths": True,
    }
    assert "manifestSchema" not in instruction
    assert contract["requirements"][0]["validatorId"] == REPORT_ARTIFACT_VALIDATOR_ID
    assert result["markdownPath"] == instruction["markdownPath"]
