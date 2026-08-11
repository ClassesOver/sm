from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from agno.run import RunContext

from agentos_dev.agent_control import AGENT_PLAN_STATE_KEY
from agentos_dev.coding.reporting.delivery.draft_v1 import (
    ReportChartRegistration,
    ReportDraftBlock,
)
from agentos_dev.coding.reporting.hospital_operation.detailed_analysis import (
    build_profile_model_view,
)
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.tests.workspace_fakes import service
from agentos_dev.coding.reporting.tools import (
    REPORT_CHART_STATE_KEY,
    REPORT_PROFILE_READ_RECEIPTS_STATE_KEY,
    ReportWorkspaceTaskToolkit,
)
from agentos_dev.task_execution.execution import WorkspaceTaskToolkit


class _EmptyExecutionRepository:
    async def list_executions(self, _external_run_id: str) -> list[object]:
        return []


def _identity(path: str, content: bytes) -> dict[str, object]:
    return {
        "path": path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _profile_pointer_toolkit(monkeypatch, tmp_path, *, extra_field_count: int = 0):
    profile = {
        "table": {"n": 100, "n_var": 1, "types": {"Numeric": 1}},
        "variables": {
            "amount": {
                "type": "Numeric",
                "count": 100,
                "skewness": 4.5,
                "kurtosis": 21.0,
                "histogram": {
                    "counts": list(range(100)),
                    "bin_edges": list(range(101)),
                },
            },
            **{
                f"field_{index}": {
                    "type": "Numeric",
                    "count": 100,
                    "histogram": {"counts": [1]},
                }
                for index in range(extra_field_count)
            },
        },
        "alerts": ["[amount] is highly skewed"],
        "correlations": {"pearson": [{"amount": 1.0}]},
        "time_series_analysis": {
            "enabled": True,
            "sort_field": "period",
            "fields": {
                "amount": {
                    "acf": [{"lag": 0, "value": 1.0}],
                    "pacf": [{"lag": 0, "value": 1.0}],
                    "seasonality": {"presence": False, "periods": []},
                }
            },
        },
    }
    profile_content = json.dumps(profile, separators=(",", ":")).encode()
    profile_identity = _identity("profiles/dataset-1.json", profile_content)
    analysis_context = json.dumps(
        {
            "datasetContexts": [
                {
                    "datasetId": "dataset-1",
                    "fields": list(profile["variables"]),
                    "profileFile": profile_identity,
                    "profileModelView": build_profile_model_view(profile),
                }
            ]
        },
        separators=(",", ":"),
    ).encode()
    analysis_identity = _identity("contexts/analysis.json", analysis_context)
    validation_context = json.dumps(
        {"analysisContextFile": analysis_identity}, separators=(",", ":")
    ).encode()
    validation_identity = _identity("contexts/validation.json", validation_context)
    files = {
        profile_identity["path"]: profile_content,
        analysis_identity["path"]: analysis_context,
        validation_identity["path"]: validation_context,
    }
    workspace_service = service(tmp_path)
    monkeypatch.setattr(
        workspace_service,
        "file_bytes",
        lambda _thread_id, path: (files[path], "application/json"),
    )
    toolkit = ReportWorkspaceTaskToolkit(workspace_service, _EmptyExecutionRepository())
    scope = SimpleNamespace(
        thread_id="thread-1",
        task=SimpleNamespace(
            acceptance_contract={
                "requirements": [
                    {
                        "id": "report-artifact",
                        "parameters": {"validationContextFile": validation_identity},
                    }
                ]
            }
        ),
    )

    async def resolve_scope(_run_context):
        return scope

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)
    return toolkit, files, profile_identity


def test_report工具schema只暴露dataset引用和analysis计划(tmp_path) -> None:
    chart_schema = ReportChartRegistration.model_json_schema(by_alias=True)
    assert set(chart_schema["properties"]) == {
        "chartId",
        "sourcePath",
        "title",
        "altText",
        "citationIds",
    }

    block_schema = ReportDraftBlock.model_json_schema(by_alias=True)
    serialized = str(block_schema)
    assert "markdown" in block_schema["properties"]
    assert "analysisIds" not in serialized
    assert "$defs" not in block_schema
    assert "table" not in block_schema["properties"]
    assert "factIds" not in serialized
    assert "seriesId" not in serialized

    toolkit = ReportWorkspaceTaskToolkit(service(tmp_path), _EmptyExecutionRepository())
    analysis_schema = toolkit.async_functions["complete_report_analysis"].parameters
    assert set(analysis_schema["properties"]["reportBrief"]["properties"]) == {
        "objective",
        "executiveSummary",
        "managementQuestions",
        "warnings",
    }
    assert set(analysis_schema["properties"]["metricDefinitions"]["items"]["properties"]) == {
        "code",
        "name",
        "definition",
        "unit",
        "periodBasis",
    }


def test_report图表路径必须为安全相对路径() -> None:
    registration = ReportChartRegistration(
        chartId="income-trend",
        sourcePath="analysis/income.png",
        title="收入趋势",
        altText="收入趋势图",
        citationIds=("citation_001",),
    )
    assert registration.source_path == "analysis/income.png"


def test_report_finish_task_schema不暴露verification_ids(tmp_path) -> None:
    toolkit = ReportWorkspaceTaskToolkit(service(tmp_path), _EmptyExecutionRepository())

    properties = toolkit.async_functions["finish_task"].parameters["properties"]

    assert "verification_ids" not in properties
    assert "verification_ids" not in toolkit.instructions
    assert "verify" not in toolkit.instructions


@pytest.mark.anyio
async def test_report_finish_task无verify时绕过Coding验证门禁(tmp_path) -> None:
    repository = _EmptyExecutionRepository()
    workspace_service = service(tmp_path)
    report_toolkit = ReportWorkspaceTaskToolkit(workspace_service, repository)
    coding_toolkit = WorkspaceTaskToolkit(workspace_service, repository)
    scope = SimpleNamespace(
        task=SimpleNamespace(mutation_sequence=1),
        external_run_id="report-run",
    )
    arguments = {"summary": "done", "artifact_paths": []}

    report_rejection = await report_toolkit._state_admission_rejection(
        scope,
        "finish_task",
        arguments,
        {},
    )
    coding_rejection = await coding_toolkit._state_admission_rejection(
        scope,
        "finish_task",
        arguments,
        {},
    )

    assert report_rejection is None
    assert coding_rejection is not None
    assert coding_rejection["code"] == "coding_verification_required"


@pytest.mark.anyio
async def test_read_profile_pointer只读取受信节点且输出有界(monkeypatch, tmp_path) -> None:
    toolkit, _files, _profile_identity = _profile_pointer_toolkit(monkeypatch, tmp_path)
    context = RunContext(run_id="run", session_id="thread", session_state={})

    result = await toolkit.read_profile_pointer(
        datasetId="dataset-1",
        profilePointer="/variables/amount/histogram",
        maxItems=5,
        purpose="核验收入分布与异常值",
        run_context=context,
    )

    assert result["ok"] is True
    assert result["datasetId"] == "dataset-1"
    assert result["profilePointer"] == "/variables/amount/histogram"
    assert result["truncated"] is True
    assert result["readReceipt"]["snapshotHash"] == _profile_identity["sha256"]
    assert result["readReceipt"]["purpose"] == "核验收入分布与异常值"
    assert context.session_state[REPORT_PROFILE_READ_RECEIPTS_STATE_KEY] == [result["readReceipt"]]
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 16 * 1024


@pytest.mark.anyio
async def test_read_profile_pointer拒绝整份展开和身份变化(monkeypatch, tmp_path) -> None:
    toolkit, files, profile_identity = _profile_pointer_toolkit(monkeypatch, tmp_path)

    with pytest.raises(ReportingError, match="Pointer"):
        await toolkit.read_profile_pointer(
            datasetId="dataset-1",
            profilePointer="/variables",
            purpose="尝试读取完整变量集合",
        )

    files[profile_identity["path"]] += b" "
    with pytest.raises(ReportingError, match="身份"):
        await toolkit.read_profile_pointer(
            datasetId="dataset-1",
            profilePointer="/variables/amount",
            purpose="核验收入统计",
        )


@pytest.mark.anyio
async def test_inspect_profile_index返回紧凑覆盖告警和pointer目录(monkeypatch, tmp_path) -> None:
    toolkit, _files, _profile_identity = _profile_pointer_toolkit(monkeypatch, tmp_path)

    result = await toolkit.inspect_profile_index(datasetId="dataset-1")

    assert result["ok"] is True
    assert result["datasetId"] == "dataset-1"
    assert result["coverage"]["fullAlertCount"] == 1
    assert result["coverage"]["indexedAlertCount"] == 1
    assert result["truncation"] == {
        "variableIndexTruncated": False,
        "detailIndexTruncated": False,
        "alertIndexTruncated": False,
    }
    assert result["pointerCatalog"]["variableRoots"] == {"amount": "/variables/amount"}
    assert result["pointerCatalog"]["indexedFieldTypes"] == {"amount": "Numeric"}
    assert result["pointerCatalog"]["correlations"] == {"pearson": "/correlations/pearson"}
    assert result["pointerCatalog"]["timeSeriesFields"][0]["acfPointer"] == (
        "/time_series_analysis/fields/amount/acf"
    )
    assert "/variables/{field}/histogram" in result["pointerCatalog"]["numericDetailTemplates"]
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 16 * 1024


@pytest.mark.anyio
async def test_inspect_profile_index可发现未进入模型视图的字段(monkeypatch, tmp_path) -> None:
    toolkit, _files, _profile_identity = _profile_pointer_toolkit(
        monkeypatch, tmp_path, extra_field_count=50
    )

    result = await toolkit.inspect_profile_index(datasetId="dataset-1")

    assert len(result["pointerCatalog"]["variableRoots"]) == 51
    assert result["pointerCatalog"]["variableRoots"]["field_49"] == ("/variables/field_49")


@pytest.mark.anyio
async def test_analysis完成工具冻结brief_evidence_profile回执和图表(monkeypatch, tmp_path) -> None:
    toolkit = ReportWorkspaceTaskToolkit(service(tmp_path), _EmptyExecutionRepository())
    receipt = {
        "receiptId": "profile-read-" + "a" * 24,
        "datasetId": "dataset-1",
        "profilePointer": "/variables/amount/histogram",
        "snapshotHash": "b" * 64,
        "purpose": "核验收入分布",
    }
    context = RunContext(
        run_id="analysis-run",
        session_id="analysis-session",
        session_state={
            AGENT_PLAN_STATE_KEY: {
                "plan": [
                    {"step": "完成全局分析", "status": "completed"},
                    {"step": "冻结分析产物", "status": "in_progress"},
                ],
                "explanation": "",
            },
            REPORT_PROFILE_READ_RECEIPTS_STATE_KEY: [receipt],
            REPORT_CHART_STATE_KEY: {
                "attemptNo": 0,
                "charts": {
                    "income_trend": {
                        "chartId": "income_trend",
                        "sourcePath": "charts/income.png",
                        "size": 256,
                        "sha256": "c" * 64,
                        "title": "医疗收入月度趋势",
                        "altText": "医疗收入按月变化",
                        "citationIds": ["citation_001"],
                    }
                },
            },
        },
    )
    parameters = {
        "phase": "analysis",
        "analysisOutputPath": "analysis/manifest.json",
        "phaseContract": {
            "analysisIds": ["analysis_001"],
            "datasetIds": ["dataset-1"],
            "citationIds": ["citation_001"],
        },
    }
    scope = SimpleNamespace(
        attempt_no=0,
        thread_id="thread",
        task=SimpleNamespace(acceptance_contract={"requirements": [{"parameters": parameters}]}),
    )
    captured = {}
    write_count = 0

    async def resolve_scope(_run_context):
        return scope

    async def hash_file(_thread_id, path):
        if path == "evidence/income.json":
            return {"path": path, "size": 512, "sha256": "d" * 64}
        assert path == "charts/income.png"
        return {"path": path, "size": 256, "sha256": "c" * 64}

    async def write_phase_json(*, scope, path, payload, run_context):
        nonlocal write_count
        write_count += 1
        assert scope is not None and run_context is context
        captured.update(path=path, payload=payload)
        return {"path": path, "size": 1024, "sha256": "e" * 64}

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)
    monkeypatch.setattr(toolkit.kernel.service, "ahash_file", hash_file)
    monkeypatch.setattr(toolkit, "_write_phase_json", write_phase_json)

    arguments = {
        "reportBrief": {
            "objective": "形成年度运营报告。",
            "executiveSummary": "收入规模与趋势分析已完成。",
            "managementQuestions": ["收入增长来自哪里？"],
        },
        "evidence": [
            {
                "analysisId": "analysis_001",
                "summary": "收入规模、趋势和异常已从 CSV 复算。",
                "datasetIds": ["dataset-1"],
                "evidencePaths": ["evidence/income.json"],
                "citationIds": ["citation_001"],
                "chartIds": ["income_trend"],
                "profileReadReceiptIds": [receipt["receiptId"]],
            }
        ],
        "metricDefinitions": [
            {
                "code": "income_amount",
                "name": "医疗收入",
                "definition": "本期医疗收入求和",
                "unit": "元",
                "periodBasis": "自然月",
            }
        ],
        "warnings": [],
        "run_context": context,
    }
    result = await toolkit.complete_report_analysis(**arguments)
    repeated = await toolkit.complete_report_analysis(**arguments)
    changed = await toolkit.complete_report_analysis(
        **{**arguments, "warnings": ["尝试替换已冻结产物"]}
    )
    forbidden_render = await toolkit.render_report_section(
        "income",
        [
            {
                "blockId": "summary",
                "markdown": "### 不应生成的章节",
                "citationIds": ["citation_001"],
                "chartIds": [],
            }
        ],
        context,
    )

    assert captured["path"] == "analysis/manifest.json"
    assert captured["payload"]["reportBrief"]["objective"] == "形成年度运营报告。"
    assert captured["payload"]["evidenceManifest"]["evidence"][0]["profileReadReceiptIds"] == [
        receipt["receiptId"]
    ]
    assert captured["payload"]["evidenceManifest"]["charts"][0]["chartId"] == ("income_trend")
    assert result["nextToolCall"]["arguments"]["artifact_paths"] == ["analysis/manifest.json"]
    assert all(
        item["status"] == "completed"
        for item in context.session_state[AGENT_PLAN_STATE_KEY]["plan"]
    )
    assert repeated["artifactFile"] == result["artifactFile"]
    assert write_count == 1
    assert changed["ok"] is False
    assert changed["code"] == "report_analysis_already_submitted"
    assert changed["retryable"] is False
    assert forbidden_render["code"] == "report_phase_tool_forbidden"


@pytest.mark.anyio
async def test_analysis阶段图表登记直接使用phase引用注册表(monkeypatch, tmp_path) -> None:
    toolkit = ReportWorkspaceTaskToolkit(service(tmp_path), _EmptyExecutionRepository())
    context = RunContext(run_id="analysis-run", session_id="analysis-session", session_state={})
    parameters = {
        "phase": "analysis",
        "analysisOutputPath": "analysis/manifest.json",
        "phaseContract": {
            "analysisIds": ["analysis_001"],
            "datasetIds": ["dataset-1"],
            "citationIds": ["citation_001"],
        },
    }
    scope = SimpleNamespace(
        attempt_no=0,
        thread_id="thread",
        task=SimpleNamespace(
            mutation_sequence=1,
            acceptance_contract={"requirements": [{"parameters": parameters}]},
        ),
    )

    async def resolve_scope(_run_context):
        return scope

    async def inspect_chart(*, thread_id, registration):
        assert thread_id == "thread"
        return (
            {
                **registration.model_dump(mode="json", by_alias=True),
                "size": 256,
                "sha256": "c" * 64,
                "format": "PNG",
                "mediaType": "image/png",
                "extension": ".png",
                "width": 1200,
                "height": 675,
            },
            [],
        )

    async def reject_old_render_contract(_scope):
        raise AssertionError("analysis phase 不应读取旧草稿 renderContract")

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)
    monkeypatch.setattr(toolkit, "_inspect_chart", inspect_chart)
    monkeypatch.setattr(toolkit, "_render_contract", reject_old_render_contract)

    result = await toolkit.register_report_charts(
        [
            {
                "chartId": "income_trend",
                "sourcePath": "charts/income.png",
                "title": "医疗收入月度趋势",
                "altText": "医疗收入按月变化",
                "citationIds": ["citation_001"],
            }
        ],
        context,
    )

    assert result["ok"] is True
    assert result["charts"][0]["chartId"] == "income_trend"
    assert context.session_state[REPORT_CHART_STATE_KEY]["charts"]["income_trend"][
        "citationIds"
    ] == ["citation_001"]


@pytest.mark.anyio
async def test_section_run只调用一次render并可请求analysis定点返工(monkeypatch, tmp_path) -> None:
    toolkit = ReportWorkspaceTaskToolkit(service(tmp_path), _EmptyExecutionRepository())
    work_item = {
        "sectionCode": "income",
        "title": "收入规模与趋势",
        "objective": "解释收入变化及主要贡献对象。",
        "completionConditions": ["给出规模、趋势、同比和异常"],
        "analysisIds": ["analysis_001"],
        "evidence": [
            {
                "analysisId": "analysis_001",
                "summary": "收入分析已完成。",
                "datasetIds": ["dataset-1"],
                "evidenceFiles": [
                    {
                        "path": "evidence/income.json",
                        "size": 512,
                        "sha256": "d" * 64,
                    }
                ],
                "citationIds": ["citation_001"],
                "chartIds": ["income_trend"],
            }
        ],
        "charts": [
            {
                "chartId": "income_trend",
                "sourceFile": {
                    "path": "charts/income.png",
                    "size": 256,
                    "sha256": "c" * 64,
                },
                "title": "医疗收入月度趋势",
                "altText": "医疗收入按月变化",
                "citationIds": ["citation_001"],
            }
        ],
        "citations": [
            {
                "citationId": "citation_001",
                "datasetId": "dataset-1",
                "requirementId": "income-monthly",
                "snapshotHash": "e" * 64,
            }
        ],
        "markdownRequirements": ["章节内部标题从三级标题开始"],
    }
    parameters = {
        "phase": "section",
        "sectionOutputPath": "sections/income.json",
        "reworkRequestPath": "sections/income.rework.json",
        "phaseContract": {
            "sectionWorkItemFile": {
                "path": "contexts/income-work-item.json",
                "size": 1024,
                "sha256": "a" * 64,
            }
        },
    }
    scope = SimpleNamespace(
        attempt_no=0,
        thread_id="thread",
        task=SimpleNamespace(acceptance_contract={"requirements": [{"parameters": parameters}]}),
    )
    context = RunContext(
        run_id="section-run",
        session_id="section-session",
        session_state={
            AGENT_PLAN_STATE_KEY: {
                "plan": [{"step": "生成当前章节", "status": "in_progress"}],
                "explanation": "",
            }
        },
    )
    writes = []

    async def resolve_scope(_run_context):
        return scope

    async def write_phase_json(*, scope, path, payload, run_context):
        writes.append((path, payload))
        return {"path": path, "size": 256, "sha256": "f" * 64}

    async def read_trusted_json(**kwargs):
        assert kwargs["identity"]["path"] == "contexts/income-work-item.json"
        return work_item

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)
    monkeypatch.setattr(toolkit, "_write_phase_json", write_phase_json)
    monkeypatch.setattr(toolkit, "_read_trusted_json", read_trusted_json)

    rendered = await toolkit.render_report_section(
        "income",
        [
            {
                "blockId": "income-summary",
                "markdown": "### 核心结论\n\n医疗收入保持增长。",
                "citationIds": ["citation_001"],
                "chartIds": ["income_trend"],
            }
        ],
        context,
    )

    assert writes[0][0] == "sections/income.json"
    assert rendered["nextToolCall"]["arguments"]["artifact_paths"] == ["sections/income.json"]
    assert "analysisIds" not in writes[0][1]["blocks"][0]
    assert context.session_state[AGENT_PLAN_STATE_KEY]["plan"][0]["status"] == "completed"

    forbidden_begin = await toolkit.begin_report_draft(context)
    forbidden_registration = await toolkit.register_report_charts([], context)

    assert forbidden_begin["code"] == "report_phase_tool_forbidden"
    assert forbidden_registration["code"] == "report_phase_tool_forbidden"

    rework_context = RunContext(
        run_id="section-rework-run",
        session_id="section-rework-session",
        session_state={
            AGENT_PLAN_STATE_KEY: {
                "plan": [{"step": "提交补证请求", "status": "in_progress"}],
                "explanation": "",
            }
        },
    )
    rework_arguments = {
        "analysisIds": ["analysis_001"],
        "reason": "同比证据缺少可复现明细。",
        "missingEvidence": ["补充同比分子、分母和期间口径"],
        "run_context": rework_context,
    }
    rework = await toolkit.request_analysis_rework(
        **rework_arguments,
    )
    repeated_rework = await toolkit.request_analysis_rework(**rework_arguments)

    assert writes[1][0] == "sections/income.rework.json"
    assert writes[1][1]["sectionCode"] == "income"
    assert rework["nextToolCall"]["arguments"]["artifact_paths"] == ["sections/income.rework.json"]
    assert rework_context.session_state[AGENT_PLAN_STATE_KEY]["plan"][0]["status"] == "completed"
    assert repeated_rework["artifactFile"] == rework["artifactFile"]
    assert len(writes) == 2


@pytest.mark.anyio
async def test_section文件读取只允许当前work_item_evidence(monkeypatch, tmp_path) -> None:
    toolkit = ReportWorkspaceTaskToolkit(service(tmp_path), _EmptyExecutionRepository())
    evidence_content = b'{"analysisId":"analysis_001","value":1}\n'
    evidence_path = "analysis/evidence/analysis_001.json"
    evidence_file = _identity(evidence_path, evidence_content)
    work_item = {
        "sectionCode": "income",
        "title": "收入规模与趋势",
        "objective": "解释收入变化及主要贡献对象。",
        "completionConditions": ["给出规模、趋势、同比和异常"],
        "analysisIds": ["analysis_001"],
        "evidence": [
            {
                "analysisId": "analysis_001",
                "summary": "收入分析已完成。",
                "datasetIds": ["dataset-1"],
                "evidenceFiles": [evidence_file],
                "citationIds": ["citation_001"],
            }
        ],
        "citations": [
            {
                "citationId": "citation_001",
                "datasetId": "dataset-1",
                "requirementId": "income-monthly",
                "snapshotHash": "e" * 64,
            }
        ],
        "markdownRequirements": ["章节内部标题从三级标题开始"],
    }
    parameters = {
        "phase": "section",
        "sectionOutputPath": "sections/income.json",
        "reworkRequestPath": "sections/income.rework.json",
        "phaseContract": {"sectionWorkItem": work_item},
    }
    scope = SimpleNamespace(
        attempt_no=0,
        external_run_id="report-coding-section",
        thread_id="thread",
        task=SimpleNamespace(
            mutation_sequence=0,
            acceptance_contract={"requirements": [{"parameters": parameters}]},
        ),
    )
    context = RunContext(
        run_id="section-run",
        session_id="section-session",
        user_id="user-1",
        session_state={},
        dependencies={
            "AgentOS 编码任务": {
                "externalRunId": "report-coding-section",
                "reportingPhase": "section",
            }
        },
    )
    files = {
        evidence_path: evidence_content,
        "analysis/evidence/analysis_002.json": b'{"analysisId":"analysis_002"}\n',
        "sections/section_002.json": b'{"sectionCode":"section_002"}\n',
    }
    read_file_calls: list[str] = []
    read_lines_calls: list[str] = []
    forbidden_terminal_calls = 0

    async def resolve_scope(_run_context):
        return scope

    def file_bytes(_thread_id, path):
        read_file_calls.append(path)
        return files[path], "application/json"

    async def read_lines(_thread_id, path, start_line, line_count):
        read_lines_calls.append(path)
        return {
            "path": path,
            "startLine": start_line,
            "endLine": start_line,
            "lineCount": line_count,
            "content": files[path].decode(),
        }

    async def forbidden_terminal_call(_scope):
        nonlocal forbidden_terminal_calls
        forbidden_terminal_calls += 1
        return {"ok": True}

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)
    monkeypatch.setattr(toolkit.kernel.service, "file_bytes", file_bytes)
    monkeypatch.setattr(toolkit.kernel.service, "aread_lines", read_lines)

    allowed_file = await toolkit.coding_read_file(evidence_path, run_context=context)
    allowed_lines = await toolkit.read_lines(evidence_path, run_context=context)
    other_evidence = await toolkit.coding_read_file(
        "analysis/evidence/analysis_002.json", run_context=context
    )
    other_section = await toolkit.read_lines("sections/section_002.json", run_context=context)
    forbidden_terminal = await toolkit._invoke(
        "terminal",
        {"command": "pwd"},
        forbidden_terminal_call,
        context,
    )

    assert allowed_file["content"] == evidence_content.decode()
    assert allowed_lines["content"] == evidence_content.decode()
    assert other_evidence.get("code") == "report_section_evidence_path_forbidden"
    assert other_section.get("code") == "report_section_evidence_path_forbidden"
    assert forbidden_terminal.get("code") == "report_phase_tool_forbidden"
    assert forbidden_terminal_calls == 0
    assert read_file_calls == [evidence_path]
    assert read_lines_calls == [evidence_path]
