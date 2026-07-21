import ast
import hashlib
import json
from pathlib import Path

from agentos_dev import app

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


def test_agentos_contract_matches_odoo_source():
    values, digest = odoo_contract()
    assert values["COMMAND_CATALOG_REVISION"] == 14
    assert digest == "e075e3f9f2229aa8d2347f5d5f0e95f867e7e1bbc411e60e25f5dc3443fdb287"
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

    assert "结合当前请求和对话历史确定用户选择" in instructions
    assert "使用其中的 menuId、actionId 调用 odoo.navigate_menu" in instructions
    assert "存在“HRP 菜单导航请求”时先执行 requiredFirstTool" in instructions
    assert "多个候选必须请用户选择" in instructions
    assert "不得构造菜单 ID" in instructions
    assert "失败时不得自动改选其他菜单" in instructions
    assert "odoo.navigate_menu 返回 stale_menu_catalog" in instructions
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


def test_agent_instructions_treat_grouping_as_complete_host_state():
    instructions = "\n".join(app.assistant.instructions)

    assert "必须先读取最新快照的 capabilities.groupFields" in instructions
    assert "groupBy 是按顺序排列的完整目标状态" in instructions
    assert "明确要求清除分组时才能提交空数组" in instructions
    assert "只能依据工具返回的 groupBy 和新快照" in instructions
    assert "odoo.apply_filter 仍只负责筛选" in instructions


def test_agent_instructions_restrict_native_view_switching():
    instructions = "\n".join(app.assistant.instructions)

    assert "明确要求切换当前视图时才能调用 odoo.switch_view" in instructions
    assert "viewType 必须来自最新快照 capabilities.viewTypes" in instructions
    assert "不能代替 odoo.open_record 打开已有记录" in instructions


def test_agent_instructions_defer_current_view_report_workflow_to_skill():
    instructions = "\n".join(app.assistant.instructions)
    skill = (REPO_ROOT / "deploy/agentos/skills/odoo-current-view-report/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "odoo-current-view-report" not in instructions
    assert "current_view 明细" not in instructions
    assert "pandas_create_report_config" not in instructions
    assert "scripts/generate_reports.py" not in instructions
    assert "workspace_read_file 不得读取新旧受控原始 JSONL 分片" in instructions
    assert 'source={"kind":"current_view"}' in skill
    assert "有勾选记录时导出当前 domain 与勾选 IDs 的交集" in skill
    assert "没有勾选记录时导出完整当前 domain" in skill
    assert "不得提交 domain、context、IDs 或自行改选范围" in skill
    assert "pandas_create_report_config" in skill
    assert "run_skill_script" in skill
    assert 'script_path="generate_reports.py"' in skill
    assert 'args=["render", configPath]' in skill
    assert "agui.odoo.report.skill.v1" in skill
    assert "唯一产物" in skill and "分析报告.pdf" in skill


def test_智能体说明明确工作区确认边界():
    instructions = "\n".join(app.assistant.instructions)

    assert "新建文件使用 workspace_write_file" in instructions
    assert "移动或重命名使用 workspace_move_file" in instructions
    assert "覆盖文件使用 workspace_replace_file" in instructions
    assert "删除文件或目录使用 workspace_delete_file" in instructions
    assert "执行可信技能脚本使用 run_skill_script" in instructions
    assert "不存在任意 Shell 或 Python 执行工具" in instructions
