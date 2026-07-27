from pathlib import Path
from types import SimpleNamespace

from agno.run import RunContext

from agentos_dev.coding.reporting.instructions import (
    REPORT_AGENT_INSTRUCTIONS,
    build_report_agent_instructions,
)
from agentos_dev.instructions import build_coding_agent_instructions

REPO_ROOT = Path(__file__).resolve().parents[4]


def instruction_context(*tools):
    return RunContext(
        run_id="run-1",
        session_id="thread-1",
        client_tools=[SimpleNamespace(name=name) for name in tools],
    )


def test_report_agent_instructions_support_iterative_python_scripts():
    context = instruction_context("odoo.navigate_menu", "odoo.apply_filter")
    resolved = build_report_agent_instructions(context)
    instructions = "\n".join(resolved)

    assert resolved == [*build_coding_agent_instructions(context), *REPORT_AGENT_INSTRUCTIONS]
    assert "terminal" in instructions
    assert "受控只读工具" in instructions
    assert "verify" in instructions
    assert "terminal 不计为验证" in instructions
    assert "finish_task" in instructions
    assert "新文件使用 create_file" in instructions
    assert "完整覆盖已有文件使用 overwrite_file" in instructions
    assert "精确替换优先使用 replace_text" in instructions
    assert "其他文件变更使用 apply_patch" in instructions
    assert "apply_changes" not in instructions
    assert "process" in instructions
    assert "view_image" in instructions
    assert "Python、Shell 或其他命令" in instructions
    assert "分析不经过 Report 层二次封装" in instructions
    assert "成功验证 execution_id" not in instructions


def test_报表智能体说明明确泛化数据源和验收链路():
    instructions = "\n".join(build_report_agent_instructions(instruction_context()))

    assert "Coding Agent 的智能报表扩展" in instructions
    assert "report_list_data_sources" in instructions
    assert "不可变 DatasetHandle" in instructions
    assert (
        "Report 层不增加分析命令、依赖、输出大小、执行时间、迭代轮次或分析方式限制" in instructions
    )
    assert "分析不经过 Report 层二次封装" in instructions
    assert "最终 job 状态为 validated" in instructions
    assert "只读 PostgreSQL" in instructions


def test_智能报表技能统一使用工作区相对路径和报表工具():
    skill = (REPO_ROOT / "deploy/agentos/skills/workspace-smart-report/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "相对 `/home/daytona/workspace` 的工作区路径" in skill
    assert "受控只读工具检查文件" in skill
    assert "多文件修改使用 `apply_patch`" in skill
    assert "新脚本使用 `create_file`" in skill
    assert "完整覆盖已有脚本使用 `overwrite_file`" in skill
    assert "小范围修改优先使用 `replace_text`" in skill
    assert "`apply_changes`" not in skill
    assert "`process` 的 `poll/wait/write/submit/kill`" in skill
    assert "生产 Coding Toolkit 声明的工具均不要求确认" in skill
    assert "`read_tool_output`" in skill
    assert "`verify`" in skill
    assert "普通 `terminal` 不计为验证" in skill
    assert "`view_image` 检查生成的图表" in skill
    assert "workspace_write_file" not in skill
    assert "workspace_apply_changes" not in skill
    assert "Report 层不限制分析命令、输出大小、执行轮次或分析方式" in skill
    assert "report_list_analysis_capabilities" not in skill
    assert "report_profile_dataset" not in skill
    assert "report_analyze_dataset" not in skill
    assert "直接调用无需确认的 `report_render_markdown`" in skill
    assert "co" + "dex" not in skill.lower()
    assert "`report_validate_pdf`" in skill
    assert "状态为 `validated`" in skill
    assert "`finish_task` 返回 `accepted`" in skill
    assert "不使用 `report_compile`、`blocks`" in skill
