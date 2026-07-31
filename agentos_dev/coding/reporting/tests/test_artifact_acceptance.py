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

from agentos_dev.coding.reporting.acceptance import (
    REPORT_ARTIFACT_VALIDATOR_ID,
    REPORT_ARTIFACT_VALIDATOR_SCRIPT,
    build_report_artifact_acceptance_contract,
    build_report_artifact_validation_context,
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
    _accepted_artifacts_match_manifest,
    _observed_data_fact_cards,
    _report_machine_terms,
)
from agentos_dev.task_execution.acceptance import normalize_acceptance_contract


def _identity(path: Path, root: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _request(
    tmp_path: Path,
    *,
    include_citation: bool = True,
    missing_section_marker: str | None = None,
    extra_artifact: bool = False,
    sections: list[str] | None = None,
    visible_machine_term: str | None = None,
    include_chart: bool = False,
    reference_chart: bool = True,
    visible_text: str = "",
    observed_data_facts: list[dict[str, object]] | None = None,
    citation_bindings: list[tuple[str, str, str]] | None = None,
):
    markdown = tmp_path / "report.md"
    manifest = tmp_path / "report.manifest.json"
    bindings = citation_bindings or [("income", "dataset-1", "income")]
    citation = (
        "\n".join(
            f"[[citation:{citation_id}]]" for citation_id, _dataset_id, _requirement_id in bindings
        )
        if include_citation
        else ""
    )
    section_markers = "\n".join(
        f"[[section:{section}]]"
        for section in sorted(REQUIRED_REPORT_SECTIONS)
        if section != missing_section_marker
    )
    machine_text = f"数据源：{visible_machine_term}\n" if visible_machine_term else ""
    chart_reference = "![收入趋势](chart.png)\n" if include_chart and reference_chart else ""
    markdown.write_text(
        f"# 报告\n{citation}\n{section_markers}\n{machine_text}{visible_text}\n{chart_reference}",
        encoding="utf-8",
    )
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
    bound_facts = [
        {"datasetId": bindings[0][1], "requirementId": bindings[0][2], **fact}
        for fact in (observed_data_facts or [])
    ]
    validation_context = build_report_artifact_validation_context(
        forbidden_visible_terms=("dwd_income_view", "dataset-1", "income"),
        observed_data_facts=bound_facts,
        expected_sections=tuple(sorted(REQUIRED_REPORT_SECTIONS)),
        expected_citation_bindings=tuple(
            (dataset_id, requirement_id) for _citation_id, dataset_id, requirement_id in bindings
        ),
    )
    validation_context_path = tmp_path / "validation-context.json"
    validation_context_path.write_text(
        json.dumps(validation_context, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    contract = build_report_artifact_acceptance_contract(
        expected_identity,
        validation_context_file=_identity(validation_context_path, tmp_path),
    )
    parameters = contract["requirements"][0]["parameters"]
    chart = tmp_path / "chart.png"
    if include_chart:
        chart.write_bytes(b"chart")
    chart_identity = _identity(chart, tmp_path) if include_chart else None
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
                "charts": (
                    [
                        {
                            **chart_identity,
                            "chartId": "income-trend",
                            "datasetIds": ["dataset-1"],
                            "mediaType": "image/png",
                        }
                    ]
                    if chart_identity is not None
                    else []
                ),
                "citations": [
                    {
                        "citationId": citation_id,
                        "datasetId": dataset_id,
                        "requirementId": requirement_id,
                    }
                    for citation_id, dataset_id, requirement_id in bindings
                ],
                "sections": (sorted(REQUIRED_REPORT_SECTIONS) if sections is None else sections),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    artifacts = [_identity(markdown, tmp_path), _identity(manifest, tmp_path)]
    if chart_identity is not None:
        artifacts.append(chart_identity)
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
        build_report_artifact_acceptance_contract(
            parameters["expectedIdentity"],
            validation_context_file=parameters["validationContextFile"],
        )
    )

    assert contract["requirements"][0]["validatorId"] == REPORT_ARTIFACT_VALIDATOR_ID
    assert set(contract["requirements"][0]["parameters"]) == {
        "expectedIdentity",
        "validationContextFile",
    }


def test_reporting大体量事实不进入通用acceptance_parameters():
    facts = [
        {
            "datasetId": f"dataset-{index}",
            "requirementId": f"requirement-{index}",
            "sourceId": "operations",
            "table": f"reporting.table_{index}",
            "periodCoverage": [f"2025-{(day % 12) + 1:02d}" for day in range(365)],
            "missingPeriods": [],
        }
        for index in range(2)
    ]
    context = build_report_artifact_validation_context(observed_data_facts=facts)
    encoded = json.dumps(
        context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()

    contract = normalize_acceptance_contract(
        build_report_artifact_acceptance_contract(
            {
                "reportId": "report-1",
                "revision": 1,
                "codingTaskKey": "task-1",
                "datasetSnapshotHash": "a" * 64,
                "effectiveProfileHash": "b" * 64,
                "markdownPath": "report.md",
                "artifactManifestPath": "report.manifest.json",
            },
            validation_context_file={
                "path": "validation-context.json",
                "size": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            },
        )
    )

    assert "observedDataFacts" not in contract["requirements"][0]["parameters"]


def test_reporting正式回执必须精确包含manifest声明的全部产物():
    manifest = ReportArtifactManifest(
        reportId="report-1",
        revision=1,
        codingTaskKey="task-1",
        datasetSnapshotHash="a" * 64,
        effectiveProfileHash="b" * 64,
        markdown=ArtifactFile(path="report.md", mediaType="text/markdown", size=2, sha256="c" * 64),
        citations=(Citation(citationId="c", datasetId="d", requirementId="r"),),
        sections=tuple(sorted(REQUIRED_REPORT_SECTIONS)),
    )
    manifest_artifact = {"path": "report.manifest.json", "size": 3, "sha256": "d" * 64}
    markdown_artifact = {"path": "report.md", "size": 2, "sha256": "c" * 64}

    assert not _accepted_artifacts_match_manifest(
        manifest, "report.manifest.json", [manifest_artifact]
    )
    assert _accepted_artifacts_match_manifest(
        manifest, "report.manifest.json", [manifest_artifact, markdown_artifact]
    )


def test_reporting给小模型的事实卡保持有界且指向完整事实():
    cards = _observed_data_fact_cards(
        [
            {
                "datasetId": "dataset-1",
                "requirementId": "income",
                "periodRowCount": 100,
                "periodCoverage": ["2025-01", "2025-12"],
                "missingPeriods": [f"{year:04d}-01" for year in range(2000, 2030)],
            },
            {
                "datasetId": "dataset-1",
                "requirementId": "income",
                "periodRowCount": 0,
                "periodCoverage": [],
                "missingPeriods": ["2025-01"],
            },
        ]
    )

    assert cards[0]["coverageStart"] == "2025-01"
    assert cards[0]["coverageEnd"] == "2025-12"
    assert cards[0]["missingPeriodCount"] == 29
    assert len(cards[0]["missingPeriods"]) == 24
    assert cards[0]["missingPeriodsTruncated"] is True
    assert cards[0]["mixedCoveragePeriods"] == ["2025-01"]


def test_reporting验收机器词来自workflow结构化字段():
    terms = _report_machine_terms(
        {
            "requirementId": "R01",
            "sourceId": "rj",
            "tables": [
                {
                    "table": "rj.dwd_income_view",
                    "periodColumn": "period_code",
                    "measureColumns": ["indicator_value"],
                }
            ],
        },
        {"datasetId": "dataset-1"},
    )

    assert terms == (
        "R01",
        "dataset-1",
        "indicator_value",
        "period_code",
        "rj",
        "rj.dwd_income_view",
    )


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


def test_reporting服务端validator明确返回markdown_marker修复目标(tmp_path: Path):
    result = _validate(
        tmp_path,
        _request(
            tmp_path,
            include_citation=False,
            missing_section_marker="executive_summary",
        ),
    )

    requirement = result["requirements"][0]
    assert requirement["passed"] is False
    assert requirement["message"] == "报告 Markdown 缺少协议标记，请只修复 Markdown。"
    assert requirement["details"]["repairTarget"] == "report.md"
    assert requirement["details"]["missingCitationIds"] == ["income"]
    assert requirement["details"]["missingCitationMarkers"] == ["[[citation:income]]"]
    assert requirement["details"]["missingSectionIds"] == ["executive_summary"]
    assert requirement["details"]["missingSectionMarkers"] == ["[[section:executive_summary]]"]
    assert requirement["details"]["repairInstructions"] == [
        "只在 report.md 中补齐上述协议标记，不要改写 manifest 的 citations 或 sections 清单。",
        "标记应紧邻对应中文结论或章节标题；章节标题继续使用 effectiveProfile 中的中文 title。",
        "修改后重新计算 Markdown 的 size 和 SHA-256，并更新 manifest 的 markdown 元数据。",
    ]


def test_reporting服务端validator接受正式manifest契约(tmp_path: Path):
    result = _validate(tmp_path, _request(tmp_path))

    assert result == {
        "version": 1,
        "requirements": [{"id": "report-artifact", "passed": True}],
    }


def test_reporting服务端validator拒绝验证上下文文件变化(tmp_path: Path):
    request = _request(tmp_path)
    context_file = request["requirements"][0]["parameters"]["validationContextFile"]
    (tmp_path / context_file["path"]).write_text("{}", encoding="utf-8")

    result = _validate(tmp_path, request)

    requirement = result["requirements"][0]
    assert requirement["passed"] is False
    assert requirement["details"]["validationContextError"] == "file_changed"


def test_reporting服务端validator拒绝schema未表达的重复citation_id(tmp_path: Path):
    result = _validate(
        tmp_path,
        _request(
            tmp_path,
            citation_bindings=[
                ("same", "dataset-1", "income"),
                ("same", "dataset-2", "workload"),
            ],
        ),
    )

    requirement = result["requirements"][0]
    assert requirement["passed"] is False
    assert requirement["details"]["manifestInvariantErrors"] == ["citationId 不能重复"]


def test_reporting服务端validator拒绝markdown展示已知机器标识(tmp_path: Path):
    result = _validate(
        tmp_path,
        _request(tmp_path, visible_machine_term="dwd_income_view"),
    )

    requirement = result["requirements"][0]
    assert requirement["passed"] is False
    assert requirement["message"] == "报告 Markdown 暴露机器标识，请只修复 Markdown。"
    assert requirement["details"]["repairTarget"] == "report.md"
    assert requirement["details"]["visibleMachineTerms"] == ["dwd_income_view"]
    assert requirement["details"]["repairInstructions"] == [
        "将 visibleMachineTerms 对应的可见文字改为中文业务名称；不要修改协议标记、"
        "citations 或 sections 清单。修改后重新计算 Markdown 的 size 和 SHA-256，"
        "并仅更新 manifest 的 markdown 元数据。"
    ]


def test_reporting服务端validator在pdf前拒绝manifest声明但markdown未引用的图表(
    tmp_path: Path,
):
    result = _validate(
        tmp_path,
        _request(tmp_path, include_chart=True, reference_chart=False),
    )

    requirement = result["requirements"][0]
    assert requirement["passed"] is False
    assert requirement["message"] == "报告 Markdown 与图表清单不一致，请只修复 Markdown。"
    assert requirement["details"]["repairTarget"] == "report.md"
    assert requirement["details"]["missingMarkdownChartPaths"] == ["chart.png"]
    assert requirement["details"]["repairInstructions"] == [
        "在 Markdown 中使用相对路径和中文替代文字引用 missingMarkdownChartPaths "
        "列出的全部图表；不要修改 manifest 的 charts 清单。修改后重新计算 Markdown "
        "的 size 和 SHA-256，并仅更新 manifest 的 markdown 元数据。"
    ]


def test_reporting服务端validator拒绝markdown中的拟合和推算结论(tmp_path: Path):
    result = _validate(
        tmp_path,
        _request(tmp_path, visible_text="全年收入按去年同期比例推算。"),
    )

    requirement = result["requirements"][0]
    assert requirement["passed"] is False
    assert requirement["message"] == "报告 Markdown 包含禁止的数据派生，请只修复 Markdown。"
    assert requirement["details"]["repairTarget"] == "report.md"
    assert requirement["details"]["forbiddenDerivedClaims"] == ["全年收入按去年同期比例推算。"]
    assert "只保留不可变数据集中的观测值" in requirement["details"]["repairInstructions"][0]


def test_reporting服务端validator拒绝把已覆盖期间描述为无记录(tmp_path: Path):
    result = _validate(
        tmp_path,
        _request(
            tmp_path,
            visible_text="工作量11-12月无记录。",
            observed_data_facts=[
                {
                    "sourceId": "operations",
                    "table": "reporting.workload",
                    "periodGranularity": "month",
                    "periodCoverage": ["2025-10", "2025-11", "2025-12"],
                    "missingPeriods": [],
                }
            ],
        ),
    )

    requirement = result["requirements"][0]
    assert requirement["passed"] is False
    assert (
        requirement["message"]
        == "报告 Markdown 的期间结论与固定事实或 citation 绑定不一致，请只修复 Markdown。"
    )
    assert requirement["details"]["repairTarget"] == "report.md"
    assert requirement["details"]["contradictoryPeriodClaims"] == [
        {
            "claim": "工作量11-12月无记录。",
            "observedPeriods": ["2025-11", "2025-12"],
            "observedFacts": [
                {
                    "sourceId": "operations",
                    "table": "reporting.workload",
                    "observedPeriods": ["2025-11", "2025-12"],
                }
            ],
        }
    ]


@pytest.mark.parametrize(
    ("claim", "expected_periods"),
    [
        (
            "工作量2025年1月至12月数据缺失。",
            [f"2025-{month:02d}" for month in range(1, 13)],
        ),
        (
            "工作量2024年11月至2025年2月数据缺失。",
            ["2024-11", "2024-12", "2025-01", "2025-02"],
        ),
    ],
)
def test_reporting服务端validator完整解析中文月份范围(
    tmp_path: Path, claim: str, expected_periods: list[str]
):
    result = _validate(
        tmp_path,
        _request(
            tmp_path,
            visible_text=claim,
            observed_data_facts=[
                {
                    "sourceId": "operations",
                    "table": "reporting.workload",
                    "periodGranularity": "month",
                    "periodCoverage": expected_periods,
                    "missingPeriods": [],
                }
            ],
        ),
    )

    issue = result["requirements"][0]["details"]["contradictoryPeriodClaims"][0]
    assert issue["observedPeriods"] == expected_periods
    assert issue["observedFacts"][0]["observedPeriods"] == expected_periods


def test_reporting服务端validator按citation绑定隔离不同数据集的期间事实(tmp_path: Path):
    result = _validate(
        tmp_path,
        _request(
            tmp_path,
            visible_text="收入2025年11月数据缺失。[[citation:income-citation]]",
            citation_bindings=[
                ("income-citation", "dataset-income", "income"),
                ("workload-citation", "dataset-workload", "workload"),
            ],
            observed_data_facts=[
                {
                    "datasetId": "dataset-income",
                    "requirementId": "income",
                    "sourceId": "operations",
                    "table": "reporting.income",
                    "periodCoverage": ["2025-11"],
                    "missingPeriods": [],
                },
                {
                    "datasetId": "dataset-workload",
                    "requirementId": "workload",
                    "sourceId": "operations",
                    "table": "reporting.workload",
                    "periodCoverage": [],
                    "missingPeriods": ["2025-11"],
                },
            ],
        ),
    )

    requirement = result["requirements"][0]
    assert requirement["passed"] is False
    assert requirement["details"]["contradictoryPeriodClaims"] == [
        {
            "claim": "收入2025年11月数据缺失。",
            "citationIds": ["income-citation"],
            "observedPeriods": ["2025-11"],
            "observedFacts": [
                {
                    "sourceId": "operations",
                    "table": "reporting.income",
                    "observedPeriods": ["2025-11"],
                }
            ],
        }
    ]


def test_reporting服务端validator在同一绑定内仍按表隔离期间事实(tmp_path: Path):
    result = _validate(
        tmp_path,
        _request(
            tmp_path,
            visible_text="2025年11月数据缺失。[[citation:combined]]",
            citation_bindings=[("combined", "dataset-combined", "combined")],
            observed_data_facts=[
                {
                    "datasetId": "dataset-combined",
                    "requirementId": "combined",
                    "sourceId": "operations",
                    "table": "reporting.income",
                    "periodCoverage": ["2025-11"],
                    "missingPeriods": [],
                },
                {
                    "datasetId": "dataset-combined",
                    "requirementId": "combined",
                    "sourceId": "operations",
                    "table": "reporting.workload",
                    "periodCoverage": [],
                    "missingPeriods": ["2025-11"],
                },
            ],
        ),
    )

    issue = result["requirements"][0]["details"]["contradictoryPeriodClaims"][0]
    assert issue["observedPeriods"] == ["2025-11"]
    assert issue["observedFacts"] == [
        {
            "sourceId": "operations",
            "table": "reporting.income",
            "observedPeriods": ["2025-11"],
        }
    ]


def test_reporting服务端validator允许否定派生及真实缺失期间披露(tmp_path: Path):
    result = _validate(
        tmp_path,
        _request(
            tmp_path,
            visible_text="报告不进行估算或年化；2025年2月数据缺失。",
            observed_data_facts=[
                {
                    "sourceId": "operations",
                    "table": "reporting.workload",
                    "periodGranularity": "month",
                    "periodCoverage": ["2025-01", "2025-03"],
                    "missingPeriods": ["2025-02"],
                }
            ],
        ),
    )

    assert result["requirements"][0]["passed"] is True


def test_reporting服务端validator拒绝篡改章节或数据引用绑定(tmp_path: Path):
    request = _request(tmp_path)
    manifest_artifact = next(
        item
        for item in request["requirements"][0]["artifacts"]
        if item["path"] == "report.manifest.json"
    )
    manifest_path = Path(manifest_artifact["absolutePath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sections"] = [*manifest["sections"], "invented_section"]
    manifest["citations"][0]["datasetId"] = "forged-dataset"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    manifest_artifact.update(_identity(manifest_path, tmp_path))
    manifest_artifact["absolutePath"] = str(manifest_path)

    result = _validate(tmp_path, request)

    details = result["requirements"][0]["details"]
    assert details["repairTarget"] == "report.manifest.json"
    assert details["manifestSectionMismatch"]["expected"] == sorted(REQUIRED_REPORT_SECTIONS)
    assert details["manifestCitationBindingMismatch"]["missing"] == [
        {"datasetId": "dataset-1", "requirementId": "income"}
    ]
    assert details["manifestCitationBindingMismatch"]["unexpected"] == [
        {"datasetId": "forged-dataset", "requirementId": "income"}
    ]
    assert "不得删除、替换或伪造绑定" in details["repairInstructions"][0]


def test_reporting服务端validator在coding阶段拒绝缺少固定code的sections(tmp_path: Path):
    result = _validate(
        tmp_path,
        _request(
            tmp_path,
            sections=["执行摘要", "分析范围与方法", "关键发现", "局限性", "建议"],
        ),
    )

    requirement = result["requirements"][0]
    assert requirement["passed"] is False
    assert {
        issue["expectedContains"] for issue in requirement["details"]["schemaErrors"]
    } == REQUIRED_REPORT_SECTIONS
    assert requirement["details"]["repairTarget"] == "report.manifest.json"
    assert requirement["details"]["authorizedManifestMutationPaths"] == ["sections"]
    assert "不得整份覆盖 manifest" in requirement["details"]["repairInstructions"][0]


@pytest.mark.anyio
async def test_coding任务启动即绑定正式产物契约且workflow不再二次纠错():
    captured: dict[str, Any] = {}

    class Repository:
        task = None

        async def get_task_snapshot(self, _task_id):
            return self.task

    class TaskRunner:
        repository = Repository()

        async def start(self, scope, instruction, *, acceptance_contract=None):
            parsed_instruction = json.loads(instruction)
            captured.update(
                scope=scope,
                instruction=parsed_instruction,
                acceptance_contract=acceptance_contract,
            )
            self.repository.task = SimpleNamespace()
            self.finish_receipt = {
                "artifacts": [
                    {
                        "path": parsed_instruction["markdownPath"],
                        "size": 1,
                        "sha256": "c" * 64,
                    },
                    {
                        "path": parsed_instruction["artifactManifestPath"],
                        "size": 1,
                        "sha256": "d" * 64,
                    },
                ],
                "acceptance": {"version": 1, "requirements": []},
            }

        async def run(self, _scope):
            return self.finish_receipt

        async def revise(self, *_args, **_kwargs):
            pytest.fail("正式 acceptance contract 失败应在 Coding 内纠错")

    class Workspace:
        @asynccontextmanager
        async def _async_client(self):
            yield object()

        async def _asandbox_for(self, _client, _thread_id):
            return SimpleNamespace(id="sandbox")

    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = Workspace()
    runtime.task_runner = TaskRunner()
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
    runtime._profile = lambda _context: SimpleNamespace(
        effective_profile_hash="b" * 64,
        sections=tuple(SimpleNamespace(code=code) for code in sorted(REQUIRED_REPORT_SECTIONS)),
    )

    async def write_validation_context(_thread_id, path, context):
        captured["validation_context"] = context
        return {"path": path, "size": 1, "sha256": "e" * 64}

    runtime._write_artifact_validation_context = write_validation_context

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
    assert set(contract["requirements"][0]["parameters"]) == {
        "expectedIdentity",
        "validationContextFile",
    }
    assert instruction["observedDataFactCards"] == []
    assert result["markdownPath"] == instruction["markdownPath"]
