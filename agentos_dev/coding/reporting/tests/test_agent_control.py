from types import SimpleNamespace

import pytest
from agno.exceptions import RetryAgentRun
from agno.run import RunContext

from agentos_dev import app
from agentos_dev.agent_control import AgentControlToolkit, build_agent_tools
from agentos_dev.coding.reporting.delivery.draft_v1 import ReportSectionDefinition
from agentos_dev.coding.reporting.delivery.report_runtime import REPORT_VISUAL_THEME
from agentos_dev.coding.reporting.tests.workspace_fakes import service
from agentos_dev.coding.reporting.tools import build_report_worker_tools


def test_report_toolkit_is_discoverable_but_requires_skill_route(tmp_path):
    workspace_service = service(tmp_path)
    toolkit = AgentControlToolkit(workspace_service)
    context = RunContext(run_id="run", session_id="thread", session_state={})

    found = toolkit.agent_tool_search("报表", run_context=context)

    assert found["matches"][0]["name"] == "report"
    assert found["matches"][0]["routeSkill"] == "workspace-smart-report"
    with pytest.raises(ValueError, match="workspace-smart-report Skill"):
        toolkit.agent_load_toolkit("report", run_context=context)
    assert "agentos_loaded_toolkits" not in context.session_state

    tools = build_agent_tools(
        workspace_service,
        run_context=SimpleNamespace(session_state=context.session_state, dependencies={}),
    )
    assert [tool.name for tool in tools] == ["agent_control", "base"]

    report_tools = build_report_worker_tools(
        workspace_service,
        app.coding_repository,
        run_context=SimpleNamespace(session_state=context.session_state, dependencies={}),
    )
    assert [tool.name for tool in report_tools] == ["workspace_coding"]
    assert "view_image" not in report_tools[0].async_functions
    assert "verify" not in report_tools[0].async_functions
    assert {
        "complete_report_analysis",
        "inspect_profile_index",
        "read_profile_pointer",
        "register_report_charts",
        "render_report_section",
        "request_analysis_rework",
    }.issubset(report_tools[0].async_functions)
    assert {
        "discard_report_charts",
        "begin_report_draft",
        "finalize_report_draft",
        "render_report_draft",
        "resume_report_draft",
        "verify_report_draft",
        "repair_report_draft",
    }.isdisjoint(report_tools[0].async_functions)
    section_schema = report_tools[0].async_functions["render_report_section"].parameters
    assert "markdown" in str(section_schema)
    assert "evidencePaths" in section_schema["properties"]
    assert "$defs" not in str(section_schema)

    vision_tools = build_report_worker_tools(
        workspace_service,
        app.coding_repository,
        vision_reviewer=SimpleNamespace(),
        run_context=SimpleNamespace(session_state=context.session_state, dependencies={}),
    )
    assert "view_image" in vision_tools[0].async_functions


def test_report_worker_tools保留全集避免agno跨phase缓存污染(tmp_path):
    workspace_service = service(tmp_path)

    def context(phase: str):
        return SimpleNamespace(
            session_state={},
            dependencies={"AgentOS 编码任务": {"reportingPhase": phase}},
        )

    analysis = build_report_worker_tools(
        workspace_service,
        app.coding_repository,
        run_context=context("analysis"),
    )[0]
    section = build_report_worker_tools(
        workspace_service,
        app.coding_repository,
        run_context=context("section"),
    )[0]

    section_tools = {
        "finish_task",
        "read_file",
        "read_lines",
        "read_tool_output",
        "render_report_section",
        "request_analysis_rework",
    }

    # Agno 2.8.2 会缓存动态 Toolkit。analysis 首次构建时若删除章节工具，后续
    # section run 只能复用残缺缓存，模型将无法提交章节或请求分析返工。Toolkit
    # 必须保持 phase 无关的完整能力，实际可见工具由每次模型请求投影并由执行门禁复核。
    assert section_tools.issubset(analysis.async_functions)
    assert section_tools.issubset(section.async_functions)
    assert "terminal" in analysis.async_functions
    assert "terminal" in section.async_functions
    assert "complete_report_analysis" in analysis.async_functions
    assert "complete_report_analysis" in section.async_functions
    assert analysis.instructions == section.instructions


@pytest.mark.anyio
async def test_report逐章Markdown状态机使用RetryAgentRun(monkeypatch, tmp_path):
    context = RunContext(
        run_id="run",
        session_id="thread",
        user_id="user",
        session_state={},
    )
    toolkit = build_report_worker_tools(
        service(tmp_path),
        app.coding_repository,
        run_context=context,
    )[0]

    async def scope(_run_context):
        return SimpleNamespace(attempt_no=1, thread_id="thread")

    async def render_contract(_scope):
        return (
            "运营报告",
            "reports/report.md",
            (
                ReportSectionDefinition(code="summary", title="摘要"),
                ReportSectionDefinition(code="income", title="收入"),
            ),
            ("citation_001",),
            False,
        )

    monkeypatch.setattr(toolkit.kernel, "scope", scope)
    monkeypatch.setattr(toolkit, "_render_contract", render_contract)

    async def hash_file(_thread_id, path):
        assert path == "analysis/evidence/summary.json"
        return {"path": path, "size": 128, "sha256": "a" * 64}

    monkeypatch.setattr(toolkit.kernel.service, "ahash_file", hash_file)

    started = await toolkit.begin_report_draft(context)
    assert started["nextSectionCode"] == "summary"
    assert started["visualTheme"] == REPORT_VISUAL_THEME

    accepted = await toolkit.render_report_section(
        "summary",
        [
            {
                "blockId": "overview",
                "markdown": "### 核心结论\n\n- 医疗收入保持增长\n- 风险项需持续跟踪",
                "citationIds": ["citation_001"],
            }
        ],
        context,
        evidencePaths=["analysis/evidence/summary.json"],
    )
    assert accepted["nextSectionCode"] == "income"
    assert accepted["evidenceFiles"] == [
        {
            "path": "analysis/evidence/summary.json",
            "size": 128,
            "sha256": "a" * 64,
        }
    ]
    stored = context.session_state["agentos_reporting_structured_draft"]
    assert stored["sections"][0]["blocks"][0]["markdown"].startswith("### 核心结论")
    assert stored["sectionEvidence"]["summary"] == accepted["evidenceFiles"]

    replaced = await toolkit.render_report_section(
        "summary",
        [
            {
                "blockId": "overview",
                "markdown": "### 核心结论\n\n- 医疗收入数据已从 CSV 复算\n- 风险项需持续跟踪",
                "citationIds": ["citation_001"],
            }
        ],
        context,
    )
    assert replaced["status"] == "replaced"
    assert replaced["replaced"] is True
    assert replaced["acceptedSectionCount"] == 1
    assert replaced["nextSectionCode"] == "income"
    assert "从 CSV 复算" in stored["sections"][0]["blocks"][0]["markdown"]

    with pytest.raises(RetryAgentRun, match="report_section_citation_unknown"):
        await toolkit.render_report_section(
            "summary",
            [
                {
                    "blockId": "overview",
                    "markdown": "### 未授权替换",
                    "citationIds": ["citation_unknown"],
                }
            ],
            context,
        )

    completed = await toolkit.render_report_section(
        "income",
        [
            {
                "blockId": "income",
                "markdown": "收入分析正文。",
                "citationIds": ["citation_001"],
            }
        ],
        context,
    )
    assert completed["nextSectionCode"] is None

    async def validate_and_store(*, scope, state, draft):
        del scope, state, draft
        stored["submitted"] = True
        return None, "reports/report.md", (), (), stored

    async def resume_saved_draft(**_kwargs):
        return {
            "ok": True,
            "status": "completed",
            "draftId": "draft-1",
            "markdownPath": "reports/report.md",
            "markdownSha256": "b" * 64,
            "artifactPaths": ["reports/report.md"],
        }

    async def content_validator_must_not_run(_run_context):
        raise AssertionError("finalize_report_draft 不应运行报告内容 validator")

    monkeypatch.setattr(toolkit, "_validate_and_store_draft", validate_and_store)
    monkeypatch.setattr(toolkit, "_resume_saved_draft", resume_saved_draft)
    monkeypatch.setattr(
        toolkit,
        "_verify_finalized_draft",
        content_validator_must_not_run,
        raising=False,
    )

    finalized = await toolkit.finalize_report_draft(context)
    assert finalized["ok"] is True
    assert finalized["markdownPath"] == "reports/report.md"
    assert "从 CSV 复算" in stored["sections"][0]["blocks"][0]["markdown"]

    with pytest.raises(RetryAgentRun, match="report_draft_already_finalized"):
        await toolkit.render_report_section(
            "income",
            [
                {
                    "blockId": "income",
                    "markdown": "收入分析正文。",
                    "citationIds": ["citation_unknown"],
                }
            ],
            context,
        )
