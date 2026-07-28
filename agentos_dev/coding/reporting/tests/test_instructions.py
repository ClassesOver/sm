from types import SimpleNamespace

from agno.run import RunContext

from agentos_dev.coding.reporting.instructions import (
    REPORT_AGENT_INSTRUCTIONS,
    build_report_agent_instructions,
)
from agentos_dev.instructions import (
    PURE_CODING_PARALLEL_READ_INSTRUCTIONS,
    build_coding_agent_instructions,
)


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
    assert "新文件使用一次 create_files" in instructions
    assert "完整覆盖已有文件使用 overwrite_file" in instructions
    assert "精确替换优先使用 replace_text" in instructions
    assert "其他文件变更使用 apply_patch" in instructions
    assert "apply_changes" not in instructions
    assert "process" in instructions
    assert "view_image" in instructions
    assert "Python、Shell 或其他命令" in instructions
    assert "分析不经过 Report 层二次封装" in instructions
    assert "成功验证 execution_id" not in instructions
    assert not any(rule in resolved for rule in PURE_CODING_PARALLEL_READ_INSTRUCTIONS)


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
