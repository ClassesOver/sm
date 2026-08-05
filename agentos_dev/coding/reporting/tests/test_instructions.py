from types import SimpleNamespace

from agno.run import RunContext

from agentos_dev.coding.reporting.instructions import (
    HOSPITAL_ANALYSIS_INSTRUCTIONS,
    HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS,
    HOSPITAL_REPORT_WRITING_INSTRUCTIONS,
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
    assert "少量阶段" in instructions
    assert "只调用零参数 verify_report_draft" in instructions
    assert "最多再调用一次 verify_report_draft" in instructions
    assert "服务端自动完成计划" in instructions
    assert "warning 不得触发 repair" in instructions
    assert "确定性调用 finish_task" in instructions
    assert "finish_task 的 summary 和 artifact_paths 必须使用" in instructions
    assert "HospitalOperationFactSet" in instructions
    assert "analysisFactSetRef.path" in instructions
    assert "禁止修改、覆盖、移动或删除" in instructions
    assert "不得读取原始数据集" in instructions
    assert "不得使用“大概率”" in instructions
    assert "FactSet 是摘要、正文和图表唯一事实来源" in instructions
    assert "不得读取基础明细自行换算、累计、构造指标" in instructions
    assert "工作区根目录" in instructions
    assert "不得使用 /workspace" in instructions
    assert "/home/daytona/workspace" in instructions
    assert "不得再拼接工作区根相对路径" in instructions
    assert "Noto Sans CJK SC" in instructions
    assert "任何缺失、混合覆盖或未完整覆盖的观测" in instructions
    assert "不得添加拟合线、平滑曲线、趋势外推或插补点" in instructions
    assert "优先拆成共享横轴的小多图" in instructions
    assert "按数据角色建立一致配色" in instructions
    assert "坐标轴端部预留空间" in instructions
    assert "不得逐字重复" in instructions
    assert "避免章节标题、图表题注或单个列表项孤立在页尾" in instructions
    assert "ReportArtifactManifest 由服务端" in instructions
    assert "禁止创建、覆盖或修改 manifest" in instructions
    assert "2 到 10 个" in instructions
    assert "只调用一次 render_report_draft" in instructions
    assert "调用一次 repair_report_draft" in instructions
    assert "不得重新读取完整 Markdown" in instructions
    assert "从工作区根目录执行" in instructions
    assert "篇幅是发布质量建议" in instructions
    assert "优先保证全部章节" in instructions
    assert "服务端负责归档图表并生成章节/citation/fact marker" in instructions
    assert "每份报告至少包含一个事实表格" in instructions
    assert "不得提交单元格数值" in instructions
    assert "逐字使用所绑定 MetricFact.displayText" in instructions
    assert "只提交 Markdown" in instructions
    assert "不得提交 manifest" in instructions
    assert "成功验证 execution_id" not in instructions
    assert not any(rule in resolved for rule in PURE_CODING_PARALLEL_READ_INSTRUCTIONS)


def test_报表智能体说明只包含workflow已准备的分析边界():
    instructions = "\n".join(build_report_agent_instructions(instruction_context()))

    assert "Coding Agent 的智能报表扩展" in instructions
    assert "HospitalOperationFactSet" in instructions
    assert "不得读取原始数据集" in instructions
    assert "分析不经过 Report 层二次封装" in instructions
    assert "确定性生成并校验 hash" in instructions
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
    assert "不得新增 FactSet 之外的计算" in writing_prompt
    assert "不得重复执行选表、取数、趋势识别或归因分析" in writing_prompt
    assert "待管理确认" in writing_prompt
    assert "不设置数据来源、技术说明、系统实现或审计血缘章节" in writing_prompt
    assert "报告必须提供简洁的分析依据与分析方法" in writing_prompt
    assert "经营指标、分析期间、组织范围和比较基准" in writing_prompt
    assert "规模与结构、趋势与拐点、同比环比、异常贡献和归因验证" in writing_prompt
    assert "不得把方法说明写成取数或系统技术过程" in writing_prompt
    assert "只有在影响结论时才简短披露" in writing_prompt
    assert "不罗列来源系统或技术细节" in writing_prompt


def test_报表用户可见内容使用中文且机器标记保持稳定():
    instructions = "\n".join(build_report_agent_instructions(instruction_context()))

    assert "用户可见内容必须使用简体中文" in instructions
    assert "图表标题、坐标轴、图例、表头" in instructions
    assert "不得用英文机器 ID 代替中文标题" in instructions
    assert "不得生成数据来源清单或技术说明" in instructions
    assert "不得展示来源系统、数据表名、字段名" in instructions
    assert "服务端据此归档实际引用图表并生成不可修改的路径和血缘绑定" in instructions
    assert "draftSections[].title" in instructions
    assert "sectionCode 必须逐项复制" in instructions
    assert "必选章节和扩展章节的中文标题均由服务端" in instructions
    assert "正文 text 不得包含" in instructions
    assert "禁止直接执行 validator 脚本" in instructions
    assert "只处理 failedRequirements" in instructions
    assert "真实 Markdown SHA-256" in instructions
    assert "requiredIssueIds" in instructions
    assert "不得附加其他修改" in instructions
    assert "最多再调用一次 verify" in instructions
