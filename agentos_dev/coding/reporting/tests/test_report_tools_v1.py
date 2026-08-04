import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agno.run import RunContext
from agno.tools.function import FunctionCall
from PIL import Image, ImageDraw

from agentos_dev.agent_control import AGENT_PLAN_STATE_KEY
from agentos_dev.coding.reporting.delivery.draft_v1 import ReportChartRegistration
from agentos_dev.coding.reporting.delivery.repair_guard import ReportRepairGuard
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncMemoryRegistry,
    Info,
)
from agentos_dev.coding.reporting.tests.workspace_fakes import (
    service as workspace_service,
)
from agentos_dev.coding.reporting.tools import (
    REPORT_DRAFT_STATE_KEY,
    REPORT_TOOL_ARGUMENT_AUTOFIX_STATE_KEY,
    ReportWorkspaceTaskToolkit,
    normalize_reporting_function_call_arguments,
)
from agentos_dev.task_execution.execution import CodingExecutionKernel, WorkspaceTaskToolkit
from agentos_dev.workspace import WORKSPACE_ROOT, WorkspaceError, WorkspaceService

MARKDOWN_PATH = "报表/智能分析/run/report.md"


def _acceptance_contract():
    return {
        "version": 1,
        "requirements": [
            {
                "id": "report-artifact",
                "validatorId": "report-artifact:manifest",
                "artifactPatterns": ["报表/智能分析/*/*"],
                "parameters": {
                    "expectedIdentity": {"markdownPath": MARKDOWN_PATH},
                    "renderContract": {
                        "title": "2025年医院经营分析报告",
                        "sections": [
                            {
                                "code": "executive_summary",
                                "title": "执行摘要",
                                "protocolMarker": True,
                            }
                        ],
                        "citationIds": ["citation_001"],
                    },
                },
            }
        ],
    }


def _draft(text="工作量11月无记录。"):
    return {
        "title": "2025年医院经营分析报告",
        "sections": [
            {
                "sectionCode": "executive_summary",
                "blocks": [
                    {
                        "blockId": "summary",
                        "text": text,
                        "citationIds": ["citation_001"],
                        "chartIds": [],
                    }
                ],
            }
        ],
    }


def _toolkit(*, existing_markdown=False):
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._report_repair_guard = ReportRepairGuard()
    identity = (
        {"path": MARKDOWN_PATH, "size": 10, "sha256": "a" * 64}
        if existing_markdown
        else {"path": MARKDOWN_PATH, "missing": True}
    )
    service = SimpleNamespace(abatch_hash_files=AsyncMock(return_value=[identity]))
    scope = SimpleNamespace(
        thread_id="thread",
        task=SimpleNamespace(acceptance_contract=_acceptance_contract()),
    )
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=scope),
        service=service,
        patch=AsyncMock(
            return_value={"ok": True, "execution_id": "patch-1", "mutation_sequence": 1}
        ),
        batch_copy_files=AsyncMock(
            return_value={
                "ok": True,
                "files": [],
                "execution_id": "copy-1",
                "mutation_sequence": 1,
            }
        ),
    )
    return toolkit


@pytest.mark.anyio
async def test_report结构化工具只使用task合同路径并由服务端生成marker():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    result = await toolkit.render_report_draft(_draft(), run_context=context)

    assert result["ok"] is True
    assert result["markdownPath"] == MARKDOWN_PATH
    patch = toolkit.kernel.patch.await_args
    assert patch.args[:2] == ("create", MARKDOWN_PATH)
    assert "[[section:executive_summary]]" in patch.kwargs["content"]
    assert "[[citation:citation_001]]" in patch.kwargs["content"]
    assert context.session_state[REPORT_DRAFT_STATE_KEY]["markdownPath"] == MARKDOWN_PATH


@pytest.mark.anyio
async def test_report结构化修复只替换validator授权文本并重新渲染():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    first = await toolkit.render_report_draft(_draft(), run_context=context)
    toolkit.kernel.service.abatch_hash_files.return_value = [
        {"path": MARKDOWN_PATH, "size": 10, "sha256": first["markdownSha256"]}
    ]
    failure = {
        "code": "verification_acceptance_failed",
        "failedRequirements": [
            {
                "id": "report-artifact",
                "details": {
                    "repairTarget": MARKDOWN_PATH,
                    "contradictoryPeriodClaims": [
                        {
                            "issueId": "period_claim_workload",
                            "claim": "工作量11月无记录。",
                            "observedPeriods": ["2025-11"],
                        }
                    ],
                },
            }
        ],
    }
    toolkit._bind_repair_targets(failure, context.session_state)
    toolkit._report_repair_guard.record_result(
        "verify",
        {
            "validator_id": "report-artifact:manifest",
            "artifact_paths": [MARKDOWN_PATH],
        },
        failure,
        context.session_state,
    )
    issue = failure["failedRequirements"][0]["details"]["contradictoryPeriodClaims"][0]

    result = await toolkit.repair_report_draft(
        [
            {
                "issueId": issue["issueId"],
                "newText": "工作量11月观测值为零。",
            }
        ],
        run_context=context,
    )

    assert result["ok"] is True
    patch = toolkit.kernel.patch.await_args
    assert patch.args[:2] == ("overwrite", MARKDOWN_PATH)
    assert "工作量11月观测值为零。" in patch.kwargs["content"]
    assert "工作量11月无记录。" not in patch.kwargs["content"]
    assert result["markdownSha256"] != first["markdownSha256"]
    assert result["repairPatches"][0]["path"] == "/sections/0/blocks/0/text"
    assert result["repairPatches"][0]["op"] == "replace"


@pytest.mark.anyio
async def test_report_verify输出与repair示例使用相同稳定issue_id():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    await toolkit.render_report_draft(_draft(), run_context=context)
    validator_result = [
        {
            "id": "report-artifact",
            "passed": False,
            "details": {
                "contradictoryPeriodClaims": [
                    {
                        "issueId": "period_claim_validator_raw",
                        "claim": "工作量11月无记录。",
                        "observedPeriods": ["2025-11"],
                    }
                ]
            },
        }
    ]
    failure = {
        "code": "verification_acceptance_failed",
        "output": json.dumps(validator_result, ensure_ascii=False),
        "failedRequirements": [
            {
                "id": "report-artifact",
                "details": validator_result[0]["details"].copy(),
            }
        ],
    }

    toolkit._bind_repair_targets(failure, context.session_state)

    issue = failure["failedRequirements"][0]["details"]["contradictoryPeriodClaims"][0]
    visible_issue = json.loads(failure["output"])[0]["details"]["contradictoryPeriodClaims"][0]
    repair_change = failure["repairCallExample"]["arguments"]["changes"][0]
    assert issue["issueId"] != "period_claim_validator_raw"
    assert visible_issue["issueId"] == issue["issueId"] == repair_change["issueId"]
    assert visible_issue["validatorIssueId"] == "period_claim_validator_raw"
    assert visible_issue["suggestedText"] == repair_change["newText"]


@pytest.mark.anyio
async def test_report结构化修复用服务端json_pointer区分相同claim():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    draft = _draft()
    draft["sections"][0]["blocks"] = [
        {
            "blockId": "summary_a",
            "text": "工作量11月无记录。",
            "citationIds": ["citation_001"],
            "chartIds": [],
        },
        {
            "blockId": "summary_b",
            "text": "工作量11月无记录。",
            "citationIds": ["citation_001"],
            "chartIds": [],
        },
    ]
    first = await toolkit.render_report_draft(draft, run_context=context)
    toolkit.kernel.service.abatch_hash_files.return_value = [
        {"path": MARKDOWN_PATH, "size": 10, "sha256": first["markdownSha256"]}
    ]
    failure = {
        "code": "verification_acceptance_failed",
        "failedRequirements": [
            {
                "id": "report-artifact",
                "details": {
                    "repairTarget": MARKDOWN_PATH,
                    "contradictoryPeriodClaims": [
                        {
                            "issueId": "period_claim_duplicate",
                            "claim": "工作量11月无记录。",
                            "observedPeriods": ["2025-11"],
                            "citationIds": ["citation_001"],
                        },
                        {
                            "issueId": "period_claim_duplicate",
                            "claim": "工作量11月无记录。",
                            "observedPeriods": ["2025-11"],
                            "citationIds": ["citation_001"],
                        },
                    ],
                },
            }
        ],
    }

    toolkit._bind_repair_targets(failure, context.session_state)
    issues = failure["failedRequirements"][0]["details"]["contradictoryPeriodClaims"]
    assert [item["targetPointer"] for item in issues] == [
        "/sections/0/blocks/0/text",
        "/sections/0/blocks/1/text",
    ]
    assert len({item["issueId"] for item in issues}) == 2
    toolkit._report_repair_guard.record_result(
        "verify",
        {"validator_id": "report-artifact:manifest", "artifact_paths": [MARKDOWN_PATH]},
        failure,
        context.session_state,
    )

    result = await toolkit.repair_report_draft(
        [
            {"issueId": issues[0]["issueId"], "newText": "工作量11月按有效观测处理。"},
            {"issueId": issues[1]["issueId"], "newText": "工作量11月存在有效观测记录。"},
        ],
        run_context=context,
    )

    assert result["ok"] is True
    assert [item["path"] for item in result["repairPatches"]] == [
        "/sections/0/blocks/0/text",
        "/sections/0/blocks/1/text",
    ]
    content = toolkit.kernel.patch.await_args.kwargs["content"]
    assert "工作量11月按有效观测处理。" in content
    assert "工作量11月存在有效观测记录。" in content


@pytest.mark.anyio
async def test_report结构化修复在绑定后draft结构漂移时失败关闭():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    await toolkit.render_report_draft(_draft(), run_context=context)
    failure = {
        "code": "verification_acceptance_failed",
        "failedRequirements": [
            {
                "id": "report-artifact",
                "details": {
                    "repairTarget": MARKDOWN_PATH,
                    "contradictoryPeriodClaims": [
                        {
                            "issueId": "period_claim_workload",
                            "claim": "工作量11月无记录。",
                            "observedPeriods": ["2025-11"],
                        }
                    ],
                },
            }
        ],
    }
    toolkit._bind_repair_targets(failure, context.session_state)
    issue = failure["failedRequirements"][0]["details"]["contradictoryPeriodClaims"][0]
    toolkit._report_repair_guard.record_result(
        "verify",
        {"validator_id": "report-artifact:manifest", "artifact_paths": [MARKDOWN_PATH]},
        failure,
        context.session_state,
    )
    context.session_state[REPORT_DRAFT_STATE_KEY]["draft"]["sections"][0]["blocks"][0][
        "citationIds"
    ] = []

    result = await toolkit.repair_report_draft(
        [{"issueId": issue["issueId"], "newText": "工作量11月按有效观测处理。"}],
        run_context=context,
    )

    assert result["code"] == "report_draft_repair_target_invalid"
    assert toolkit.kernel.patch.await_count == 1


@pytest.mark.anyio
async def test_report结构化修复无法绑定时写入发布审核warning():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    first = await toolkit.render_report_draft(_draft(), run_context=context)
    toolkit.kernel.service.abatch_hash_files.return_value = [
        {"path": MARKDOWN_PATH, "size": 10, "sha256": first["markdownSha256"]}
    ]
    failure = {
        "code": "verification_acceptance_failed",
        "failedRequirements": [
            {
                "id": "report-artifact",
                "details": {
                    "repairTarget": MARKDOWN_PATH,
                    "contradictoryPeriodClaims": [
                        {
                            "issueId": "period_claim_1234567890abcdef",
                            "claim": "收入11月无记录。",
                            "observedPeriods": ["2025-11"],
                            "citationIds": ["citation_001"],
                        }
                    ],
                },
            }
        ],
    }
    toolkit._bind_repair_targets(failure, context.session_state)
    issue = failure["failedRequirements"][0]["details"]["contradictoryPeriodClaims"][0]
    assert issue["targetBindingError"] == "claim_not_bound_to_structured_draft"
    toolkit._report_repair_guard.record_result(
        "verify",
        {"validator_id": "report-artifact:manifest", "artifact_paths": [MARKDOWN_PATH]},
        failure,
        context.session_state,
    )

    result = await toolkit.repair_report_draft(
        [{"issueId": issue["issueId"], "newText": issue["suggestedText"]}],
        run_context=context,
    )

    assert result["ok"] is True
    assert result["repairPatches"] == []
    assert result["warnings"][-1]["code"] == "unresolved_repair_issue"
    content = toolkit.kernel.patch.await_args.kwargs["content"]
    assert "## 发布审核提示" in content
    assert "<!-- repair-warning:period_claim_1234567890abcdef -->" in content


@pytest.mark.anyio
async def test_report结构化修复仍包含缺失表述时自动使用服务端建议():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    first = await toolkit.render_report_draft(_draft(), run_context=context)
    toolkit.kernel.service.abatch_hash_files.return_value = [
        {"path": MARKDOWN_PATH, "size": 10, "sha256": first["markdownSha256"]}
    ]
    failure = {
        "code": "verification_acceptance_failed",
        "failedRequirements": [
            {
                "id": "report-artifact",
                "details": {
                    "repairTarget": MARKDOWN_PATH,
                    "contradictoryPeriodClaims": [
                        {
                            "issueId": "period_claim_1234567890abcdef",
                            "claim": "工作量11月无记录。",
                            "observedPeriods": ["2025-11"],
                        }
                    ],
                },
            }
        ],
    }
    toolkit._bind_repair_targets(failure, context.session_state)
    issue = failure["failedRequirements"][0]["details"]["contradictoryPeriodClaims"][0]
    toolkit._report_repair_guard.record_result(
        "verify",
        {"validator_id": "report-artifact:manifest", "artifact_paths": [MARKDOWN_PATH]},
        failure,
        context.session_state,
    )

    result = await toolkit.repair_report_draft(
        [{"issueId": issue["issueId"], "newText": "工作量11月仍无记录。"}],
        run_context=context,
    )

    assert result["ok"] is True
    assert result["autoFixes"] == [
        {
            "code": "repair_text_replaced_by_server_suggestion",
            "issueId": issue["issueId"],
            "message": "模型修复文本仍包含缺失表述，已使用服务端建议文本。",
        }
    ]
    content = toolkit.kernel.patch.await_args.kwargs["content"]
    assert "工作量11月按有效观测处理。" in content
    assert "仍无记录" not in content


@pytest.mark.anyio
async def test_report正式verify只使用服务端保存的产物路径(monkeypatch):
    captured = {}

    async def verify(
        _self,
        command=None,
        validator_id=None,
        artifact_paths=None,
        run_context=None,
        *,
        timeout=900,
    ):
        captured["artifactPaths"] = artifact_paths
        return {"ok": True, "failedRequirements": []}

    monkeypatch.setattr(WorkspaceTaskToolkit, "verify", verify)
    toolkit = _toolkit()
    context = RunContext(
        run_id="run",
        session_id="thread",
        user_id="user",
        session_state={
            AGENT_PLAN_STATE_KEY: {
                "plan": [
                    {"step": "生成报告", "status": "completed"},
                    {"step": "验收与交付", "status": "in_progress"},
                ],
                "explanation": "",
            }
        },
    )
    rendered = await toolkit.render_report_draft(_draft(), run_context=context)

    result = await toolkit.verify_report_draft(run_context=context)

    assert result["ok"] is True
    assert captured["artifactPaths"] == rendered["artifactPaths"]
    assert result["nextToolCall"] == {
        "name": "finish_task",
        "arguments": {
            "summary": "报告《2025年医院经营分析报告》已通过服务端正式验收。",
            "artifact_paths": rendered["artifactPaths"],
        },
    }
    assert all(
        item["status"] == "completed"
        for item in context.session_state[AGENT_PLAN_STATE_KEY]["plan"]
    )


def test_report专用工具使用strict_schema且正式verify为零参数():
    toolkit = ReportWorkspaceTaskToolkit(SimpleNamespace(), SimpleNamespace())
    tools = {**toolkit.functions, **toolkit.async_functions}

    assert tools["register_report_charts"].strict is True
    assert tools["render_report_draft"].strict is True
    assert tools["resume_report_draft"].strict is True
    assert tools["verify_report_draft"].strict is True
    assert tools["repair_report_draft"].strict is True
    assert set(tools["render_report_draft"].parameters["properties"]) == {"draft"}
    assert tools["verify_report_draft"].parameters == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert "sourcePath" in str(tools["register_report_charts"].parameters)
    assert "oldText" not in str(tools["repair_report_draft"].parameters)
    render_description = tools["render_report_draft"].description
    assert '"text":"图表题注"' in render_description
    assert '"chartIds":["income_trend"]' in render_description


@pytest.mark.anyio
async def test_report工具在真实agno执行链展开唯一一层arguments():
    toolkit = ReportWorkspaceTaskToolkit(SimpleNamespace(), SimpleNamespace())
    function = toolkit.async_functions["render_report_draft"]
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def render_report_draft(draft, run_context=None):
        assert run_context is context
        return {"ok": True, "draft": draft}

    async def passthrough_tool_hook(run_context, function_name, function_call, arguments):
        assert run_context is context
        assert function_name == "render_report_draft"
        return await function_call(**arguments)

    function.entrypoint = render_report_draft
    function.tool_hooks = [passthrough_tool_hook]
    function._run_context = context
    call = FunctionCall(
        function=function,
        arguments={"arguments": {"draft": {"title": "报告", "sections": []}}},
        call_id="render",
    )

    execution = await call.aexecute()

    assert execution.status == "success"
    assert execution.result == {
        "ok": True,
        "draft": {"title": "报告", "sections": []},
    }
    assert context.session_state[REPORT_TOOL_ARGUMENT_AUTOFIX_STATE_KEY] == [
        {
            "code": "report_tool_arguments_unwrapped",
            "toolName": "render_report_draft",
            "mutationSequence": 0,
        }
    ]


@pytest.mark.anyio
async def test_report工具在真实agno执行链按schema解码合法json草稿字符串():
    toolkit = ReportWorkspaceTaskToolkit(SimpleNamespace(), SimpleNamespace())
    function = toolkit.async_functions["render_report_draft"]
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    async def render_report_draft(draft, run_context=None):
        assert run_context is context
        return {"ok": True, "draft": draft}

    function.entrypoint = render_report_draft
    function._run_context = context
    call = FunctionCall(
        function=function,
        arguments={"draft": json.dumps({"title": "报告", "sections": []})},
        call_id="render-json-string",
    )

    execution = await call.aexecute()

    assert execution.status == "success"
    assert execution.result == {
        "ok": True,
        "draft": {"title": "报告", "sections": []},
    }


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            {"arguments": {"draft": {}}, "timeout": 30},
            {"draft": {}, "timeout": 30},
        ),
        ({"arguments": '{"draft":{}}'}, {"draft": {}}),
        (
            {"arguments": {"arguments": {"draft": {}}}},
            {"arguments": {"draft": {}}},
        ),
    ],
)
def test_report工具arguments只做一层等价json规范化(arguments, expected):
    call = SimpleNamespace(
        arguments=arguments,
        function=SimpleNamespace(
            name="render_report_draft",
            parameters={
                "type": "object",
                "properties": {"draft": {"type": "object"}},
            },
        ),
    )

    normalize_reporting_function_call_arguments(call)

    assert call.arguments == expected


@pytest.mark.anyio
async def test_report草稿schema错误返回精确字段且不回显原始内容():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    draft = _draft("不应出现在错误响应中的敏感正文")
    draft["sections"][0]["blocks"][0]["text"] = ""

    result = await toolkit.render_report_draft(draft, run_context=context)

    assert result["code"] == "report_draft_invalid"
    assert result["validationErrors"] == [
        {
            "path": "draft.sections[0].blocks[0].text",
            "code": "string_too_short",
            "message": "String should have at least 1 character",
        }
    ]
    assert "不应出现在错误响应中的敏感正文" not in str(result)


@pytest.mark.anyio
async def test_report草稿图表异常只需登记后resume且完整draft只提交一次():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    draft = _draft()
    draft["sections"][0]["blocks"][0]["chartIds"] = ["income-trend"]

    first = await toolkit.render_report_draft(draft, run_context=context)
    repeated = await toolkit.render_report_draft(draft, run_context=context)

    assert first["code"] == "report_draft_chart_unregistered"
    assert repeated["code"] == "report_draft_already_submitted"
    toolkit._inspect_chart = AsyncMock(
        return_value=(
            {
                "chartId": "income-trend",
                "sourcePath": "analysis/charts/income.png",
                "title": "医疗收入趋势",
                "altText": "医疗收入月度趋势图",
                "citationIds": ["citation_001"],
                "size": 100,
                "sha256": "b" * 64,
                "format": "PNG",
                "mediaType": "image/png",
                "extension": ".png",
                "width": 1200,
                "height": 675,
            },
            [],
        )
    )
    registered = await toolkit.register_report_charts(
        [
            {
                "chartId": "income-trend",
                "sourcePath": "analysis/charts/income.png",
                "title": "医疗收入趋势",
                "altText": "医疗收入月度趋势图",
                "citationIds": ["citation_001"],
            }
        ],
        run_context=context,
    )
    resumed = await toolkit.resume_report_draft(run_context=context)

    assert registered["ok"] is True
    assert resumed["ok"] is True
    assert len(resumed["artifactPaths"]) == 2
    copy = toolkit.kernel.batch_copy_files.await_args.args[0][0]
    assert copy["source"] == "analysis/charts/income.png"
    assert copy["destination"].startswith("报表/智能分析/run/chart-")
    assert copy["expected_sha256"] == "b" * 64


@pytest.mark.anyio
async def test_report通用verify不能伪造正式validator参数():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})

    result = await toolkit.verify(
        validator_id="report-artifact:manifest",
        artifact_paths=["forged.md"],
        run_context=context,
    )

    assert result["code"] == "report_verify_tool_forbidden"
    assert result["expectedCallShape"] == {}
    assert result["correctCallExample"] == {
        "name": "verify_report_draft",
        "arguments": {},
    }


def _chart_png(*, blank: bool = False) -> bytes:
    image = Image.new("RGB", (1200, 675), "white")
    if not blank:
        ImageDraw.Draw(image).rectangle((100, 100, 1100, 575), fill="#175cd3")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _async_workspace(tmp_path):
    current = workspace_service(tmp_path)
    current.sandbox_for("thread")
    return current, WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )


@pytest.mark.anyio
async def test_report图表登记解码真实图片并拒绝符号链接和空白图(tmp_path):
    current, async_service = _async_workspace(tmp_path)
    sandbox = current.sandbox_for("thread")
    sandbox.fs.create_folder(f"{WORKSPACE_ROOT}/analysis", "700")
    sandbox.fs.create_folder(f"{WORKSPACE_ROOT}/analysis/charts", "700")
    sandbox.fs.upload_file(_chart_png(), f"{WORKSPACE_ROOT}/analysis/charts/chart.png")
    sandbox.fs.upload_file(_chart_png(blank=True), f"{WORKSPACE_ROOT}/analysis/charts/blank.png")
    link_info = Info("link.png", mode="lrwxrwxrwx")
    sandbox.fs.entries[f"{WORKSPACE_ROOT}/analysis/charts/link.png"] = (
        link_info,
        _chart_png(),
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(service=async_service)
    registration = ReportChartRegistration(
        chartId="income",
        sourcePath="analysis/charts/chart.png",
        title="收入趋势",
        altText="收入趋势图",
        citationIds=("citation_001",),
    )

    identity, warnings = await toolkit._inspect_chart(thread_id="thread", registration=registration)

    assert identity["sha256"] == hashlib.sha256(_chart_png()).hexdigest()
    assert identity["format"] == "PNG"
    assert identity["width"] == 1200
    assert identity["height"] == 675
    assert warnings == []
    with pytest.raises(WorkspaceError, match="符号链接"):
        await toolkit._inspect_chart(
            thread_id="thread",
            registration=registration.model_copy(
                update={"source_path": "analysis/charts/link.png"}
            ),
        )
    with pytest.raises(ReportingError) as blank_error:
        await toolkit._inspect_chart(
            thread_id="thread",
            registration=registration.model_copy(
                update={"source_path": "analysis/charts/blank.png"}
            ),
        )
    assert blank_error.value.code == "report_chart_blank"


@pytest.mark.anyio
async def test_report图表批量归档记录mutation_lease和哈希回执():
    digest = "b" * 64
    service = SimpleNamespace(
        abatch_hash_files=AsyncMock(
            return_value=[
                {"path": "analysis/chart.png", "size": 100, "sha256": digest},
                {"path": "reports/chart.png", "missing": True},
            ]
        ),
        _validate_patch_hash=lambda value: value,
        copy_file=Mock(
            return_value={
                "path": "reports/chart.png",
                "source": "analysis/chart.png",
                "size": 100,
                "sha256": digest,
                "status": "copied",
            }
        ),
    )
    repository = SimpleNamespace(
        increment_mutation=AsyncMock(return_value=3),
        reserve_execution=AsyncMock(),
        update_execution=AsyncMock(),
    )
    kernel = object.__new__(CodingExecutionKernel)
    kernel.service = service
    kernel.repository = repository
    kernel._check_fence = AsyncMock()
    lease = SimpleNamespace(epoch=2)
    scope = SimpleNamespace(
        external_run_id="task",
        internal_run_id="run",
        owner_user_id="user",
        thread_id="thread",
        sandbox_id="sandbox",
        attempt_no=1,
        lease_epoch=2,
        lease=lease,
        task=SimpleNamespace(mutation_sequence=2),
    )

    result = await kernel.batch_copy_files(
        [
            {
                "source": "analysis/chart.png",
                "destination": "reports/chart.png",
                "expected_sha256": digest,
                "expected_size": 100,
            }
        ],
        None,
        _scope=scope,
    )

    repository.increment_mutation.assert_awaited_once_with(
        "task", lease=lease, internal_run_id="run"
    )
    reserve = repository.reserve_execution.await_args.kwargs
    assert reserve["mutation_sequence"] == 3
    assert reserve["lease"] is lease
    assert reserve["operation_receipt"]["files"] == [
        {
            "path": "reports/chart.png",
            "before_sha256": None,
            "after_sha256": digest,
        }
    ]
    assert result["files"][0]["beforeSha256"] is None
    assert result["files"][0]["afterSha256"] == digest


@pytest.mark.anyio
async def test_report图表批量归档拒绝登记后源文件变化():
    service = SimpleNamespace(
        abatch_hash_files=AsyncMock(
            return_value=[
                {"path": "analysis/chart.png", "size": 100, "sha256": "c" * 64},
                {"path": "reports/chart.png", "missing": True},
            ]
        ),
        _validate_patch_hash=lambda value: value,
    )
    repository = SimpleNamespace(increment_mutation=AsyncMock())
    kernel = object.__new__(CodingExecutionKernel)
    kernel.service = service
    kernel.repository = repository
    scope = SimpleNamespace(thread_id="thread")

    with pytest.raises(WorkspaceError, match="登记后发生变化"):
        await kernel.batch_copy_files(
            [
                {
                    "source": "analysis/chart.png",
                    "destination": "reports/chart.png",
                    "expected_sha256": "b" * 64,
                    "expected_size": 100,
                }
            ],
            None,
            _scope=scope,
        )
    repository.increment_mutation.assert_not_awaited()


@pytest.mark.anyio
async def test_report_issue_id修复允许在授权block内更新指标数值():
    toolkit = _toolkit()
    context = RunContext(run_id="run", session_id="thread", user_id="user", session_state={})
    claim = "2025年11月收入100万元无记录。"
    first = await toolkit.render_report_draft(_draft(claim), run_context=context)
    toolkit.kernel.service.abatch_hash_files.return_value = [
        {"path": MARKDOWN_PATH, "size": 10, "sha256": first["markdownSha256"]}
    ]
    failure = {
        "code": "verification_acceptance_failed",
        "failedRequirements": [
            {
                "id": "report-artifact",
                "details": {
                    "repairTarget": MARKDOWN_PATH,
                    "contradictoryPeriodClaims": [
                        {
                            "issueId": "period_claim_income",
                            "claim": claim,
                            "observedPeriods": ["2025-11"],
                        }
                    ],
                },
            }
        ],
    }
    toolkit._bind_repair_targets(failure, context.session_state)
    toolkit._report_repair_guard.record_result(
        "verify",
        {"validator_id": "report-artifact:manifest", "artifact_paths": [MARKDOWN_PATH]},
        failure,
        context.session_state,
    )
    issue = failure["failedRequirements"][0]["details"]["contradictoryPeriodClaims"][0]

    result = await toolkit.repair_report_draft(
        [
            {
                "issueId": issue["issueId"],
                "newText": "2025年11月收入101万元按有效观测处理。",
            }
        ],
        run_context=context,
    )

    assert result["ok"] is True
    assert result["autoFixes"] == []
    content = toolkit.kernel.patch.await_args.kwargs["content"]
    assert "2025年11月收入101万元按有效观测处理。" in content
    assert "100万元无记录" not in content
    assert toolkit.kernel.patch.await_count == 2


def test_report_issue_id修复示例只陈述validator已证明的期间覆盖():
    claim = (
        "考虑到11-12月实际数据缺失，若按1-10月实际收入年化推算，"
        "全年实际收入预计约125.3亿元，执行率约95.1%。"
    )

    assert ReportWorkspaceTaskToolkit._period_repair_example(claim) == (
        "考虑到11-12月实际数据存在有效观测记录，若按1-10月实际收入年化推算，"
        "全年实际收入预计约125.3亿元，执行率约95.1%。"
    )
