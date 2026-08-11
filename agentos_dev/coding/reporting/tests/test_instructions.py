from types import SimpleNamespace

from agno.run import RunContext

from agentos_dev.coding.reporting.hospital_operation.domains import build_domain_stage_guidance
from agentos_dev.coding.reporting.instructions import (
    HOSPITAL_ANALYSIS_INSTRUCTIONS,
    HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS,
    HOSPITAL_REPORT_WRITING_INSTRUCTIONS,
    REPORT_AGENT_INSTRUCTIONS,
    REPORT_SECTION_AGENT_INSTRUCTIONS,
    build_report_agent_instructions,
)
from agentos_dev.instructions import (
    CODING_DELIVERABLE_VERIFICATION_INSTRUCTION,
    CODING_FINISH_VERIFICATION_INSTRUCTION,
    CODING_VALIDATOR_FEEDBACK_INSTRUCTION,
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

    excluded = {
        CODING_VALIDATOR_FEEDBACK_INSTRUCTION,
        CODING_DELIVERABLE_VERIFICATION_INSTRUCTION,
        CODING_FINISH_VERIFICATION_INSTRUCTION,
    }
    assert resolved == [
        *(rule for rule in build_coding_agent_instructions(context) if rule not in excluded),
        *REPORT_AGENT_INSTRUCTIONS,
    ]
    assert "terminal" in instructions
    assert "verify" not in instructions
    assert "verification_ids" not in instructions
    assert "finish_task" in instructions
    assert "读取全部 CSV" in instructions
    assert "SHA-256" in instructions
    assert "DetailedAnalysisPlan" in instructions
    assert "analysisIds" in instructions
    assert "profileFile" in instructions
    assert "独立完整 Profile JSON" in instructions
    assert "read_profile_pointer" in instructions
    assert "inspect_profile_index" in instructions
    assert "nextFieldOffset" in instructions
    assert "ProfileCoverageManifest" in instructions
    assert "ProfileReadReceipt" in instructions
    assert "purpose" in instructions
    assert "outputHandle" in instructions
    assert "面板数据先聚合后计算的 ACF" in instructions
    assert "仅在工具列表实际包含 view_image" in instructions
    assert "先按月及适当组织粒度聚合" in instructions
    assert "Profile 只用于发现分析方向" in instructions
    assert "最终报告数字" in instructions and "不可变 CSV" in instructions
    assert "图表类型" in instructions and "数据实际" in instructions
    assert "report-visualization" in instructions
    assert "空白、截断、严重重叠或文字不可读" in instructions
    assert "requiresRevision" in instructions
    assert "普通警告和建议" in instructions and "可选" in instructions
    assert "把 DetailedAnalysisPlan 视为已批准执行计划" in instructions
    assert "禁止 round(None)" in instructions
    assert "None-safe 格式化" in instructions
    assert "phase=analysis" in instructions and "phase=section" in instructions
    assert "complete_report_analysis" in instructions
    assert "ReportBrief" in instructions and "AnalysisEvidenceManifest" in instructions
    assert "SectionWorkItem" in instructions
    assert "正常只调用一次 render_report_section" in instructions
    assert "request_analysis_rework" in instructions
    assert "不得调用 begin_report_draft 或 finalize_report_draft" in instructions
    assert "visualTheme" in instructions and "chartPalette" in instructions
    assert "不限定图表类型" in instructions
    assert "block 不得重复一级或二级章节标题" in instructions
    assert "章节内部标题从三级标题开始" in instructions
    assert "正文块只提交 blockId、Markdown、citationIds 和 chartIds" in instructions
    assert "不提交 analysisIds" in instructions
    assert "unused_chart_excluded" in instructions
    assert "不阻断 Finalize" in instructions
    assert "analysis/report_analysis.py" in instructions
    assert "优先通过一次 apply_patch" in instructions
    assert "分析命令从工作区根目录执行" in instructions
    assert "脚本自身位置" in instructions
    assert "evidence" in instructions
    assert "执行成功且 evidence 落盘后" in instructions
    assert "最终定稿后一次登记" in instructions
    assert "登记后不得改写" in instructions
    assert not any(
        term in instructions
        for term in ("FactSet", "analysisFactSetRef", "factSetIdentity", "MetricFact", "FactSeries")
    )
    assert len("\n".join(REPORT_AGENT_INSTRUCTIONS).encode("utf-8")) < 32 * 1024
    assert not any(rule in resolved for rule in PURE_CODING_PARALLEL_READ_INSTRUCTIONS)


def test_section_phase只接收章节指令且不再注入coding与analysis规则():
    context = RunContext(
        run_id="run-1",
        session_id="thread-1",
        dependencies={"AgentOS 编码任务": {"reportingPhase": "section"}},
    )

    resolved = build_report_agent_instructions(context)
    instructions = "\n".join(resolved)

    assert resolved == REPORT_SECTION_AGENT_INSTRUCTIONS
    assert "render_report_section" in instructions
    assert "request_analysis_rework" in instructions
    assert "read_tool_output" in instructions
    assert "terminal" not in instructions
    assert "apply_patch" not in instructions
    assert "phase=analysis" not in instructions
    assert "report-visualization" not in instructions
    assert "完整 Profile" not in instructions


def test_报表成稿提示词要求图表结合且表格直接使用markdown():
    instructions = "\n".join(REPORT_AGENT_INSTRUCTIONS)

    assert "根据 SectionWorkItem 中的实际证据决定图表和表格" in instructions
    assert "标准 Markdown 管道表" in instructions
    assert "直接写入相关 render_report_section 正文" in instructions
    assert "不得将表格渲染为图片或登记为 chartId" in instructions
    assert "具体图表类型、表格数量和列项根据数据实际决定" in instructions
    assert "不设置固定模板、固定数量或服务端门禁" in instructions


def test_报表智能体说明只包含workflow已准备的分析边界():
    instructions = "\n".join(build_report_agent_instructions(instruction_context()))

    assert "Coding Agent 的智能报表扩展" in instructions
    assert "本轮不可变 CSV" in instructions
    assert "datasetId、requirementId、snapshotHash" in instructions
    assert "report_list_data_sources" not in instructions
    assert "report_describe_data_source" not in instructions
    assert "report_materialize_dataset" not in instructions
    assert "report_prepare_dataset" not in instructions
    assert "report_render_markdown" not in instructions
    assert "report_validate_pdf" not in instructions
    assert "report_job_status" not in instructions


def test_医院运营成稿规则仅进入report_worker():
    context = instruction_context()
    report_instructions = build_report_agent_instructions(context)
    coding_instructions = build_coding_agent_instructions(context)

    assert all(rule in report_instructions for rule in HOSPITAL_REPORT_WRITING_INSTRUCTIONS)
    assert not any(rule in coding_instructions for rule in HOSPITAL_REPORT_WRITING_INSTRUCTIONS)
    assert not any(rule in REPORT_AGENT_INSTRUCTIONS for rule in HOSPITAL_ANALYSIS_INSTRUCTIONS)


def test_医院运营分析规则明确六类主题按目标和数据条件触发():
    prompt = "\n".join(HOSPITAL_ANALYSIS_INSTRUCTIONS)

    assert "条件规则，不是必须覆盖的主题清单" in prompt
    assert "报告目标未涉及" in prompt
    assert "不得创建对应 analysis 或 requirement" in prompt
    assert not any(
        rule in REPORT_AGENT_INSTRUCTIONS for rule in HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS
    )

    writing_prompt = "\n".join(HOSPITAL_REPORT_WRITING_INSTRUCTIONS)
    assert "计算只能基于本轮不可变 CSV" in writing_prompt
    assert "待管理确认" in writing_prompt
    assert "不设置数据来源、技术说明、系统实现或审计血缘章节" in writing_prompt
    assert "报告必须提供简洁的分析依据与分析方法" in writing_prompt
    assert "经营指标、分析期间、组织范围和比较基准" in writing_prompt
    assert "规模与结构、趋势与拐点、同比环比、异常贡献和归因验证" in writing_prompt
    assert "不得把方法说明写成取数或系统技术过程" in writing_prompt
    assert "只有在影响结论时才简短披露" in writing_prompt
    assert "不罗列来源系统或技术细节" in writing_prompt


def test_报表规划提示词使用陈述式分析目标():
    stages = ("request", "data_understanding", "analysis", "findings", "outline", "draft")
    prompts = [item for stage in stages for item in build_domain_stage_guidance(stage)]
    prompts.extend(HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS)
    prompts.extend(HOSPITAL_ANALYSIS_INSTRUCTIONS)
    prompts.extend(HOSPITAL_REPORT_WRITING_INSTRUCTIONS)
    prompts.extend(REPORT_AGENT_INSTRUCTIONS)

    assert all("陈述式的 DetailedAnalysisPlan" not in prompt for prompt in prompts)
    assert all("？" not in prompt and "?" not in prompt for prompt in prompts)
    assert any("收入规模与结构分析" in prompt for prompt in prompts)
    assert any("核心分析目标" in prompt for prompt in prompts)


def test_报表用户可见内容使用中文且机器标记保持稳定():
    instructions = "\n".join(build_report_agent_instructions(instruction_context()))

    assert "不得展示来源系统、数据表名、字段名" in instructions
    assert "正常只调用一次 render_report_section" in instructions
    assert "sectionCode 必须原样复制" in instructions
    assert "不得调用 begin_report_draft 或 finalize_report_draft" in instructions
    assert "citationIds" in instructions
    assert "当前 WorkItem 的 citationIds" in instructions
    assert "snapshotHash" in instructions
    assert "FactSet" not in instructions
    assert "?" not in instructions and "？" not in instructions
