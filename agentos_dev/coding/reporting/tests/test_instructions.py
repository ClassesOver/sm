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
    assert "不得尝试调用或声称完成视觉检查" in instructions
    assert "Python、Shell 或其他命令" in instructions
    assert "分析不经过 Report 层二次封装" in instructions
    assert "权威纠错反馈" in instructions
    assert "逐项完成 requiredActions" in instructions
    assert "不得原样重复失败调用" in instructions
    assert "大型 CSV" in instructions
    assert "不得用 read_file 分段抽样" in instructions
    assert "少量阶段" in instructions
    assert "只调用一次服务端最终 verify" in instructions
    assert "manifest 声明的全部图表实际路径" in instructions
    assert "validator_id=report-artifact:manifest" in instructions
    assert "ReportArtifactManifest JSON Schema" not in instructions
    assert "additionalProperties" not in instructions
    assert "observedDataFacts" in instructions
    assert "事实来源" in instructions
    assert "analysisPlan.description" in instructions
    assert "不是数据事实来源" in instructions
    assert "工作区根目录" in instructions
    assert "不得再拼接工作区根相对路径" in instructions
    assert "citationId 和 section 标记" in instructions
    assert "schema 之外的字段" in instructions
    assert "只提交实际存在的交付路径" in instructions
    assert "datasetSnapshotHash" in instructions
    assert "成功验证 execution_id" not in instructions
    assert not any(rule in resolved for rule in PURE_CODING_PARALLEL_READ_INSTRUCTIONS)


def test_报表智能体说明只包含workflow已准备的分析边界():
    instructions = "\n".join(build_report_agent_instructions(instruction_context()))

    assert "Coding Agent 的智能报表扩展" in instructions
    assert "不可变 DatasetHandle" in instructions
    assert "分析不经过 Report 层二次封装" in instructions
    assert "Workflow 已提交并校验 hash" in instructions
    assert "report_list_data_sources" not in instructions
    assert "report_describe_data_source" not in instructions
    assert "report_materialize_dataset" not in instructions
    assert "report_prepare_dataset" not in instructions
    assert "report_render_markdown" not in instructions
    assert "report_validate_pdf" not in instructions
    assert "report_job_status" not in instructions
