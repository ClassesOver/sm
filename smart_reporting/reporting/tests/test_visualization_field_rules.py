"""standard* 字段规则只随实际使用这些字段的计划下发，不常驻编码 Agent 指令。"""

import json

import pytest
from agno.models.openai import OpenAIChat

from smart_reporting.reporting.bootstrap import _VISUALIZATION_CODE_INSTRUCTIONS
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    ToolkitRuntime,
    _batch_response,
    _custom_response,
    _function_response,
    _run_context,
    _task_context,
    workspace,  # noqa: F401
)
from smart_reporting.reporting.workflow.runtime.code_generation import ReportingCodeGenerationRunner
from smart_reporting.reporting.workflow.runtime.visualization_field_rules import (
    STANDARD_FIELD_RULES,
    STANDARD_FIELD_RULES_INSTRUCTION,
    STANDARD_PREFLIGHT_RULE,
    standard_field_rules,
)

_BREAK_RULE = next(rule for _, rule in STANDARD_FIELD_RULES if rule.startswith("standardBreak"))
_DUAL_RULE = next(rule for _, rule in STANDARD_FIELD_RULES if rule.startswith("stacked-bar"))


def _plan(**chart_fields):
    return {"charts": [{"chartId": "chart_001", "standardAxes": {"rightFields": []}}, {"chartId": "chart_002", **chart_fields}]}


def test_rules_follow_only_fields_with_values_in_plan_order():
    assert standard_field_rules({"visualizationPlan": _plan()}) == []
    assert standard_field_rules({"visualizationPlan": _plan(standardBreak=None, standardSteps=[])}) == []
    selected = standard_field_rules({
        "standardChartPreflight": {"status": "failed"},
        "visualizationPlan": _plan(
            standardBreak={"lower": {"min": 0, "max": 5}}, standardAxes={"rightFields": ["rate"]},
        ),
    })
    # 预检规则在前，字段规则按规则表顺序，每条只出现一次。
    assert selected == [STANDARD_PREFLIGHT_RULE, _DUAL_RULE, _BREAK_RULE]
    assert standard_field_rules({"visualizationPlan": "not-a-plan"}) == []


def test_agent_instructions_keep_only_the_pointer_not_field_rules():
    instructions = "\n".join(_VISUALIZATION_CODE_INSTRUCTIONS)
    assert STANDARD_FIELD_RULES_INSTRUCTION in instructions
    assert STANDARD_PREFLIGHT_RULE not in instructions
    assert all(rule not in instructions for _, rule in STANDARD_FIELD_RULES)


@pytest.mark.anyio
@pytest.mark.parametrize("with_fields", [False, True])
async def test_coding_payload_carries_rules_only_for_used_fields(workspace, with_fields):  # noqa: F811
    from smart_reporting.reporting.agent import create_reporting_code_agent_factory
    from smart_reporting.reporting.tests.test_reporting_code_agent_trajectories import (
        _ResponsesClient,
    )

    client = _ResponsesClient([
        _batch_response(
            _custom_response("write_script", "# Python\n" + SOURCE, 1),
            _function_response(2, "run_script", {}),
            _function_response(3, "submit_script", {}),
        ),
    ])
    factory = create_reporting_code_agent_factory(model=OpenAIChat(id="test", api_key="test"), name="field-rules")

    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        return agent

    plan = _plan(standardBreak={"lower": {"min": 0, "max": 5}}) if with_fields else _plan()
    await ReportingCodeGenerationRunner(make_agent, ToolkitRuntime(), ReportingLspProcessManager()).run(
        _task_context(workspace), workspace, {"visualizationPlan": plan}, run_context=_run_context("task-1"),
    )
    request = json.dumps(client.requests[0]["input"], ensure_ascii=False, default=str)
    assert ("standardFieldRules" in request) is with_fields
    assert (_BREAK_RULE in request) is with_fields
