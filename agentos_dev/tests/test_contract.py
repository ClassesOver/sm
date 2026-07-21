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
    assert values["COMMAND_CATALOG_REVISION"] == 11
    assert digest == "5e9686ce3ed1fb4131215d3c9fca997fda7610bb70cb1468f2e5564ef3f99306"
    assert app.PROTOCOL == values["PROTOCOL"]
    assert app.BUNDLE_VERSION == values["MODULE_VERSION"]
    assert app.COMMAND_CATALOG_HASH == digest


def test_agent_instructions_enforce_staged_odoo_workflow():
    instructions = "\n".join(app.assistant.instructions)

    assert "能力发现 → odoo.stage_current_form 暂存依赖标量" in instructions
    assert "等待 onchange 新快照 → odoo.search_relation" in instructions
    assert "odoo.validate_current_form" in instructions
    assert "独立确认后 odoo.save_current_form" in instructions


def test_agent_instructions_wait_for_chat_import_preview():
    instructions = "\n".join(app.assistant.instructions)

    assert "等待用户在 Chat 内完成服务端预览、字段映射和测试导入" in instructions
    assert "kind=x2many_import_ready" in instructions
    assert "odoo.get_x2many_import_status 只用于恢复或查询" in instructions
    assert "不得构造行数据、mappingHash、schema 摘要" in instructions


def test_agent_instructions_prioritize_selected_menu_navigation():
    instructions = "\n".join(app.assistant.instructions)

    assert "第一个且唯一可调用的页面工具是 odoo.open_menu" in instructions
    assert "上下文存在“HRP 菜单导航请求”时" in instructions
    assert "phase=search 时只先调用 odoo.search_menu" in instructions
    assert "phase=open 时只先调用 odoo.open_menu" in instructions
    assert "本轮第一个页面工具必须是 odoo.search_menu" in instructions
    assert "返回多个候选时立即停止" in instructions
    assert "首次 query 必须使用用户请求中的原始菜单名称或路径" in instructions
    assert "最多尝试两个不同 fullPath" in instructions
    assert "complete=false、目录缺失或版本不一致时必须停止" in instructions
    assert "不得从目录生成 menuId 或 actionId" in instructions
    assert "stale_menu_catalog 时，只能用最新 menuTarget 对原始 query 重试一次" in instructions
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
