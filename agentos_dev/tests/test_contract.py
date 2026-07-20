import ast
import hashlib
import json
from pathlib import Path

from agentos_dev import app


def odoo_contract():
    source = Path("agui_chat/models/agui_chat_config.py").read_text(encoding="utf-8")
    values = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
    material = {
        "protocol": values["PROTOCOL"],
        "commands": values["HOST_COMMAND_NAMES"],
        "revision": values["COMMAND_CATALOG_REVISION"],
    }
    digest = hashlib.sha256(json.dumps(
        material, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")).hexdigest()
    return values, digest


def test_agentos_contract_matches_odoo_source():
    values, digest = odoo_contract()
    assert values["COMMAND_CATALOG_REVISION"] == 8
    assert digest == "66999dc4e1f22d94cf04b9fda3463c99538f00f86150204d4d0dea5d73c8cb60"
    assert app.PROTOCOL == values["PROTOCOL"]
    assert app.BUNDLE_VERSION == values["MODULE_VERSION"]
    assert app.COMMAND_CATALOG_HASH == digest


def test_agent_instructions_enforce_staged_odoo_workflow():
    instructions = "\n".join(app.assistant.instructions)

    assert "能力发现 → odoo.stage_current_form 暂存依赖标量" in instructions
    assert "等待 onchange 新快照 → odoo.search_relation" in instructions
    assert "odoo.validate_current_form" in instructions
    assert "独立确认后 odoo.save_current_form" in instructions


def test_agent_instructions_prioritize_selected_menu_navigation():
    instructions = "\n".join(app.assistant.instructions)

    assert "第一个且唯一可调用的页面工具是 odoo.open_menu" in instructions
    assert "菜单名称只用于定位" in instructions
    assert "用户消息明确要求创建" in instructions
    assert "不得从菜单名称中的“新建”或“创建”推断创建意图" in instructions


def test_agent_instructions_enforce_tool_result_truthfulness():
    instructions = "\n".join(app.assistant.instructions)

    assert "所有工具操作都必须先执行、后回答" in instructions
    assert "查询结论只能来自工具结果" in instructions
    assert "确认中、排队中或准备完成不等于执行成功" in instructions
    assert "失败或部分成功时必须准确说明" in instructions
    assert "第一个响应只能调用 odoo.enter_edit_mode" in instructions
    assert "不得先输出文字或询问字段" in instructions


def test_智能体说明明确工作区确认边界():
    instructions = "\n".join(app.assistant.instructions)

    assert "新建文件使用 workspace_write_file" in instructions
    assert "移动或重命名使用 workspace_move_file" in instructions
    assert "覆盖文件使用 workspace_replace_file" in instructions
    assert "删除文件或目录使用 workspace_delete_file" in instructions
    assert "执行可信技能脚本使用 run_skill_script" in instructions
    assert "不存在任意 Shell 或 Python 执行工具" in instructions
