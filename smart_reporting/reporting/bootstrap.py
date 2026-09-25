"""Reporting Agent、Workflow Runtime 和执行依赖的协议无关装配。"""

from agno.agent import Agent

from ..model_routing import build_model_profiles
from ..quality_warnings.service import QualityWarningService
from ..report_editor import ReportEditorGrantService
from ..runtime.execution import ExecutionContext
from ..runtime.settings import AgentSettings
from ..task_execution import TaskExecutionKernel, TaskExecutionRepository
from .agent import (
    create_reporting_code_agent_factory,
    create_reporting_generator_agent,
    create_reporting_phase_agent,
)
from .code_agent.context import ReportingCodingTaskRegistry
from .data_source import load_configured_report_source_registry
from .delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
)
from .host_workspace import ReportingWorkspaceRegistry, ReportingWorkspaceRouter
from .knowledge import ReportingKnowledgeIndex
from .metadata import ReportingMetadataClient
from .profile import load_configured_reporting_profiles
from .vision import ReportVisionReviewer
from .workflow.execution import ReportingTaskCoordinator
from .workflow.repository import ReportingStateRepository
from .workflow.runtime import ReportWorkflowRuntime
from .workflow.runtime.phase_models import SectionDecisionOutput, VisualizationPlanDraft

_VISUALIZATION_CODE_COMMON_INSTRUCTIONS = (
    "只能修改 visualizationWorkspace.scriptPath 签发的唯一 Python 文件。",
    "收到视觉审查的 critical 问题后，只修改与该问题直接相关的局部代码；禁止插入临时诊断、raise、打印、探针数据或改写无关数据读取。",
    "warning、info 和已通过图片不触发修复；不要为了验证假设重新生成整段脚本或改变未被指出的图表。",
    "逐字使用 facts 中的 factFile.path、visualizationPlan.charts 和输出路径。",
    "脚本从冻结 facts 生成计划中的全部图表，不得增删图表或改写引用元数据；"
    "首轮 write_script 直接完整实现全部图表并写出所有签发产物，"
    "禁止先写探索占位脚本或以打印 facts 结构、字段概览代替绘图。",
    "百分比标签必须区分小数比率和百分数：例如增减额/基数为 0.0619 时显示 6.19%，"
    "不能直接拼接 %；已乘过 100 的百分数不得再次乘 100。以源字段说明及分子分母核对单位。",
    "source descriptor 的 metricIndex、findingIndex 是源文件数组的零基下标，不是数组元素内的字段。"
    "按 dataPath 从源文件根读取，例如 findingIndex=2、dataPath=findings[2] 对应 "
    'source["findings"][2]；只读取 descriptor.fields 声明的元素字段。',
    "source descriptor 声明 rowEncoding=columns_rows 时，每个 row 都是与 columns 按位置对应的列表；"
    "必须先校验行列长度一致，再用 dict(zip(columns, row)) 解码，禁止把 row 当作字典使用"
    '或写 row["字段名"]。',
    "source descriptor 若声明 nullableFields，字段中的 null 是源数据的合法不可用值；"
    "必须保留并显式标注不可计算或无数据，禁止用 0、空字符串或常数替换。",
    "字段缺失、行列不一致、类型不符或数值转换失败时必须显式抛出异常；"
    "禁止使用 .get(..., 0)、or 0、except 后赋 0 等默认值掩盖解析失败。",
    "只有冻结 facts 中的真实数据全零时才允许绘制全零系列；真实全零或恒定序列必须保留"
    "真实刻度并明确标注数据为零或无变化，不得隐藏系列。不得把缺失、解析失败或空输入"
    "替换成零值、常数值或占位数据来规避脚本执行与可视化审查。",
    "每个 metricIndex 的 topGroups 和 bottomGroups 都是指标局部集合；不同 metricIndex 的"
    "分组标签、顺序和数量可以完全不同，禁止跨指标复用分组标签、数组位置或查找结果。",
    "多个指标需要展示分组贡献时必须在同一签发图片内使用独立子图，各子图只读取自身"
    "metricIndex 的真实分组；同一指标内缺失的分类值保留为 NaN 或空白并明确标注无数据，"
    "不得补零。",
    "数据形状契约：metrics/derivedMetrics/comparisons 中的 periodValues、topGroups、"
    "bottomGroups 是行对象数组；supplementalEvidenceSources[].findings[] 是 columns+rows "
    "表格对象。两类形状不得混用，必须按 binding.dataPath 与 dataDescriptors.fields 解码。",
    "禁止编写通用 resolve()、table_rows()、read_table() 等动态路径解析器或通用数据读取 helper；"
    "逐字使用 binding.dataPath 读取数据，不要用正则、字符串拼接、+、f-string 或 os.path.join 构造/推导路径。",
    "输入文件路径必须使用 task.authorized_read_paths 或 binding.factFile.path 中的逐字字符串，"
    "不得把 facts 文件（如 analysis_*.json）当作 supplement 来访问 findings。",
    "修复 execution_output_error 时必须修正原始数据读取或解码错误，不得仅删除失败代码、"
    "吞掉异常或补默认数据。",
    "按 visualizationMode 选择 Matplotlib 或 Plotly；每张图都必须生成签发路径的 PNG/JPEG 静态图，"
    "Plotly 图还必须生成签发路径的 .plotly.json。"
    "使用 Matplotlib 时在导入 pyplot 前设置 Agg；Plotly 的静态图使用 fig.write_image()"
    "（Kaleido 已随环境提供），交互产物使用 fig.write_json()。",
    "不得调用或导入 run_python_script、submit_visualization_charts 等编排工具。",
)

_VISUALIZATION_CODE_LEGACY_INSTRUCTIONS = _VISUALIZATION_CODE_COMMON_INSTRUCTIONS

_VISUALIZATION_CODE_CHART_INPUT_INSTRUCTIONS = (
    "facts 提供 chartInputs 时，每张图只逐字读取 chartId 与本图相同的 chartInputs[].path"
    "（json.load），不要再读取原始事实文件；每个文件是宿主按 dataBindings 预解析的 "
    "{columns, rows} 表格，按 dict(zip(columns, row)) 解码。nullableColumns 中的 null 是"
    "源数据的合法不可用值，必须保留并显式标注无数据，禁止替换成 0、空字符串或常数；"
    "columnMeta 声明的单位与是否百分数优先于自行推断。",
    "不在 chartInputs 中的图（或 facts 未提供 chartInputs 时的全部图）按 visualizationFacts "
    "与 binding.dataPath 从源文件根读取原始事实：metricIndex、findingIndex 是源文件数组零基"
    "下标；periodValues/topGroups/bottomGroups 是行对象数组，findings 是 columns+rows 表格，"
    "rows 须按位置解码；只读取 descriptor.fields 声明的字段。输入路径只能逐字使用 "
    "task.authorized_read_paths 或 binding.factPath，不得把 facts 文件当作 supplement 访问 findings。",
    "每个 metricIndex 的 topGroups 和 bottomGroups 都是指标局部集合，禁止跨指标复用分组标签、"
    "数组位置或查找结果；多个指标展示分组贡献时在同一签发图片内使用独立子图，缺失分类值"
    "保留为 NaN 或空白并标注无数据，不得补零。",
)

_VISUALIZATION_CODE_INSTRUCTIONS = (
    *_VISUALIZATION_CODE_COMMON_INSTRUCTIONS[:2],
    "逐图直接实现 visualizationPlan.charts[].visualForm 和 dataBindings；不得重新选择数据源、"
    "字段或图型；函数组织、布局细节和同章脚本组织由当前实现决定。",
    _VISUALIZATION_CODE_COMMON_INSTRUCTIONS[2],
    "逐字使用 chartInputs[].path（或回退图的 factFile.path）、visualizationPlan.charts 和输出路径。",
    *_VISUALIZATION_CODE_COMMON_INSTRUCTIONS[4:6],
    *_VISUALIZATION_CODE_CHART_INPUT_INSTRUCTIONS,
    *_VISUALIZATION_CODE_COMMON_INSTRUCTIONS[9:11],
    # 通用指令 [13:16] 要求按 binding.dataPath / factFile.path 读取原始事实，与
    # chartInputs 冲突（全部物化时事实文件不在授权路径内）。数据形状与路径规则已
    # 并入上方回退图规则，这里只保留与数据来源无关的"禁止通用 helper"约束。
    "禁止编写通用 resolve()、table_rows()、read_table() 等动态路径解析器或通用数据读取 helper；"
    "输入路径只用逐字字符串，不要用正则、字符串拼接、+、f-string 或 os.path.join 构造/推导路径。",
    *_VISUALIZATION_CODE_COMMON_INSTRUCTIONS[16:],
)


def create_report_runtime(
    context: ExecutionContext,
    settings: AgentSettings,
    *,
    download_grants: ReportDownloadGrantService | None = None,
    editor_grants: ReportEditorGrantService | None = None,
    artifact_persistence: ReportArtifactPersistenceService | None = None,
    quality_warning_service: QualityWarningService | None = None,
) -> tuple[Agent, ReportWorkflowRuntime]:
    code_mode_runtime = getattr(context, "reporting_code_mode_runtime", None)
    if code_mode_runtime is None:
        raise RuntimeError("reporting_code_mode_runtime_missing")
    lsp_manager = getattr(context, "reporting_lsp_process_manager", None)
    if lsp_manager is None:
        raise RuntimeError("reporting_lsp_process_manager_missing")
    workspace_registry = context.reporting_workspace_registry or ReportingWorkspaceRegistry(
        settings.reporting_host_workspace_root,
        secret=settings.workspace_hmac_secret,
    )
    reporting_workspace = ReportingWorkspaceRouter(workspace_registry)
    knowledge_index = getattr(context, "reporting_knowledge_index", None)
    if knowledge_index is None:
        knowledge_index = ReportingKnowledgeIndex(workspace_registry.root)
    if artifact_persistence is not None:
        artifact_persistence = ReportArtifactPersistenceService(
            artifact_persistence.repository,
            reporting_workspace,
        )
    task_repository = TaskExecutionRepository(context.database)
    state_repository = ReportingStateRepository(context.database)
    reporting_agent_template = create_reporting_phase_agent(
        settings,
        context.database,
        reporting_workspace,
        task_repository,
        state_repository=state_repository,
        workspace_registry=workspace_registry,
    )
    visualization_generator = create_reporting_generator_agent(
        model=reporting_agent_template.model,
        output_schema=VisualizationPlanDraft,
        name="reporting-visualization-generator",
    )
    visualization_code_agent_factory = create_reporting_code_agent_factory(
        model=reporting_agent_template.model,
        name="reporting-visualization-code-agent",
        task_kind="visualization",
        role="只为冻结图表计划签发可视化脚本。",
        instructions=_VISUALIZATION_CODE_INSTRUCTIONS,
    )
    section_generator = create_reporting_generator_agent(
        model=reporting_agent_template.model,
        output_schema=SectionDecisionOutput,
        name="reporting-section-generator",
    )
    section_recovery = create_reporting_generator_agent(
        model=reporting_agent_template.model,
        output_schema=SectionDecisionOutput,
        name="reporting-section-recovery",
    )
    vision_reviewer = (
        ReportVisionReviewer(settings, reporting_workspace)
        if settings.report_enable_vision
        else None
    )
    coding_task_registry = ReportingCodingTaskRegistry()
    task_runner = ReportingTaskCoordinator(
        task_repository,
        TaskExecutionKernel(context.workspace_service, task_repository),
        model_profiles=build_model_profiles(
            fast_model_id=settings.model_fast_id,
            standard_model_id=settings.model_standard_id,
            strong_model_id=settings.model_strong_id,
        ),
    )
    runtime = ReportWorkflowRuntime(
        db=context.database,
        reporting_agent_template=reporting_agent_template,
        task_runner=task_runner,
        visualization_generator=visualization_generator,
        visualization_code_agent_factory=visualization_code_agent_factory,
        section_generator=section_generator,
        section_recovery=section_recovery,
        vision_reviewer=vision_reviewer,
        vision_enabled=settings.report_enable_vision,
        workspace_service=reporting_workspace,
        workspace_registry=workspace_registry,
        code_mode_runtime=code_mode_runtime,
        knowledge_index=knowledge_index,
        lsp_manager=lsp_manager,
        coding_task_registry=coding_task_registry,
        registry=load_configured_report_source_registry(settings.report_data_sources_dir),
        profiles=load_configured_reporting_profiles(settings.report_data_sources_dir),
        planner_enable_thinking=settings.report_enable_thinking,
        planner_reasoning_effort=settings.report_planner_reasoning_effort,
        planner_thinking_budget=settings.report_planner_thinking_budget,
        metadata_client=(
            ReportingMetadataClient(
                settings.report_metadata_url,
                token=settings.report_metadata_token,
            )
            if settings.report_metadata_url
            else None
        ),
        download_grants=download_grants,
        editor_grants=editor_grants,
        artifact_persistence=artifact_persistence,
        quality_warning_service=quality_warning_service,
        report_public_base_url=(
            settings.report_public_base_url if download_grants is not None else None
        ),
        state_repository=state_repository,
        analysis_concurrency=settings.report_analysis_concurrency,
        section_concurrency=settings.report_section_concurrency,
        reporting_execution_mode=settings.reporting_execution_mode,
        visualization_section_deadline_seconds=(
            settings.report_visualization_section_deadline_seconds
        ),
        visualization_total_deadline_seconds=(
            settings.report_visualization_total_deadline_seconds
        ),
    )
    return reporting_agent_template, runtime
