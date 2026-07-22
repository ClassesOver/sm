import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from agno.run import RunContext

from agentos_dev import app
from agentos_dev.instructions import (
    BUSINESS_COMMAND_INSTRUCTIONS,
    CORE_INSTRUCTIONS,
    FORM_EDIT_INSTRUCTIONS,
    LIST_VIEW_INSTRUCTIONS,
    NAVIGATION_INSTRUCTIONS,
    SELECTED_SKILL_INSTRUCTIONS,
    VIEW_CONTROL_INSTRUCTIONS,
    X2MANY_INSTRUCTIONS,
    build_agent_instructions,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def odoo_contract():
    source = (REPO_ROOT / "agui_chat/models/agui_chat_config.py").read_text(encoding="utf-8")
    values = {}
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
    material = {
        "protocol": values["PROTOCOL"],
        "commands": values["HOST_COMMAND_NAMES"],
        "revision": values["COMMAND_CATALOG_REVISION"],
    }
    digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return values, digest


def instruction_context(*tools, dependencies=None):
    return RunContext(
        run_id="run-1",
        session_id="thread-1",
        client_tools=[SimpleNamespace(name=name) for name in tools],
        dependencies=dependencies,
    )


def test_agentos_contract_matches_odoo_source():
    values, digest = odoo_contract()
    assert values["COMMAND_CATALOG_REVISION"] == 15
    assert digest == "23ea66d90181a45b4a52705c171372c38955208af6f556f56f26643bcc033512"
    assert app.PROTOCOL == values["PROTOCOL"]
    assert app.BUNDLE_VERSION == values["MODULE_VERSION"]
    assert app.COMMAND_CATALOG_HASH == digest


def test_agent_uses_dynamic_instructions_callable():
    assert app.assistant.instructions is build_agent_instructions


def test_plain_request_only_uses_core_instructions():
    assert build_agent_instructions(instruction_context()) == CORE_INSTRUCTIONS


def test_navigation_tools_only_add_navigation_policy():
    instructions = build_agent_instructions(instruction_context("odoo.navigate_menu"))

    assert instructions == CORE_INSTRUCTIONS + NAVIGATION_INSTRUCTIONS
    assert not set(FORM_EDIT_INSTRUCTIONS) & set(instructions)
    assert "stage_current_form" not in "\n".join(instructions)


def test_list_view_tools_add_list_policy():
    instructions = build_agent_instructions(instruction_context("odoo.apply_group"))
    text = "\n".join(instructions)

    assert instructions == CORE_INSTRUCTIONS + LIST_VIEW_INSTRUCTIONS
    assert "viewType 为 list 或 kanban" in text
    assert "groupBy 是有序的完整目标状态" in text
    assert "切到 form 会进入空白新建表单" in text
    assert "当前 viewType 为 form 时禁止调用" in text


def test_discard_form_tool_adds_form_view_policy():
    instructions = build_agent_instructions(instruction_context("odoo.discard_current_form"))

    assert instructions == CORE_INSTRUCTIONS + FORM_EDIT_INSTRUCTIONS
    assert "viewType 为 form" in "\n".join(instructions)


def test_view_control_tools_add_ambiguous_navigation_policy():
    instructions = build_agent_instructions(instruction_context("odoo.activate_view_control"))

    assert instructions == CORE_INSTRUCTIONS + VIEW_CONTROL_INSTRUCTIONS
    text = "\n".join(instructions)
    assert "控件语义不明确或存在多个合理路径时停止并请用户选择" in text
    assert "不得猜测控件、目标模型、action 或记录" in text


def test_form_tools_add_staged_edit_policy_without_report_workflow():
    instructions = build_agent_instructions(instruction_context("odoo.stage_current_form"))
    text = "\n".join(instructions)

    assert instructions == CORE_INSTRUCTIONS + FORM_EDIT_INSTRUCTIONS
    assert "能力发现 → stage_current_form 暂存依赖标量" in text
    assert "独立确认后 save_current_form" in text
    assert "odoo-current-view-report" not in text
    assert "scripts/generate_reports.py" not in text


def test_x2many_business_and_selected_skill_policies_are_selected_independently():
    x2many = build_agent_instructions(instruction_context("odoo.open_x2many_record"))
    business = build_agent_instructions(instruction_context("odoo.business.test.execute"))
    selected_skill = build_agent_instructions(
        instruction_context(dependencies={"已选智能体技能": [{"name": "report"}]})
    )

    assert x2many == CORE_INSTRUCTIONS + X2MANY_INSTRUCTIONS
    assert business == CORE_INSTRUCTIONS + BUSINESS_COMMAND_INSTRUCTIONS
    assert selected_skill == CORE_INSTRUCTIONS + SELECTED_SKILL_INSTRUCTIONS


def test_instruction_character_budgets():
    core_length = len("\n".join(CORE_INSTRUCTIONS))
    scenario_lengths = [
        len("\n".join(CORE_INSTRUCTIONS + policy))
        for policy in (
            NAVIGATION_INSTRUCTIONS,
            LIST_VIEW_INSTRUCTIONS,
            VIEW_CONTROL_INSTRUCTIONS,
            FORM_EDIT_INSTRUCTIONS,
            X2MANY_INSTRUCTIONS,
            BUSINESS_COMMAND_INSTRUCTIONS,
            SELECTED_SKILL_INSTRUCTIONS,
        )
    ]

    assert core_length <= 1500
    assert max(scenario_lengths) <= 2200


def test_智能体说明明确工作区确认边界():
    instructions = "\n".join(build_agent_instructions(instruction_context()))

    assert "工作区只属于当前 thread" in instructions
    assert "覆盖、删除及执行可信技能脚本仍须独立确认" in instructions
    assert "不存在任意 Shell 或 Python 执行能力" in instructions
