# Enterprise Reporting Workflow

Reporting 是独立于纯 Coding Agent 的企业报表产品。当前唯一工作流为
`enterprise-reporting-workflow-v1`，共 15 步：

1. 规范化请求。
2. 解析数据来源与 Schema。
3. 确定数据范围并执行受限数据画像。
4. 生成指标语义候选。
5. 提交指标语义。
6. 执行跨表对账。
7. 生成初始分析计划与取数需求，并确定报表能力。
8. 生成并审核只读取数方案。
9. 物化不可变 CSV。
10. 准备分析数据上下文。
11. 根据 Profile 索引生成详细分析计划。
12. 生成并审核动态提纲。
13. Coding 按章节分析与成稿。
14. 验收报表产物。
15. 执行发布门禁并返回最终下载回执。

## 数据与 Profile

步骤 9 为每个授权查询物化不可变 CSV，并冻结相对路径、大小、SHA-256 和
`DatasetLineage`。步骤 10 对完整 CSV 执行 `fg-data-profiling`，完整 Profile 作为独立 JSON
文件保存，不截断统计结果。`profileModelView` 只提供 coverage、alerts、highlights 和 JSON
Pointer 索引，单个 Dataset 视图硬限制在 12 KiB 内。服务端同时生成
`ProfileCoverageManifest`，逐个绑定全部授权 Dataset、字段、CSV 身份和完整 Profile 文件身份；
Dataset 或字段缺失会在进入 Coding 前失败。模型先通过
`inspect_profile_index` 获取单个 Dataset 的紧凑 coverage、完整/已索引告警数、分层截断状态和
分页字段 Pointer 目录；`read_profile_pointer` 再定点读取变量、相关性、缺失、极端值、字符串、变量交互和时序统计。工具
核验 `validationContextFile`、`analysisContextFile` 与 `profileFile` 的大小和 SHA-256，并为每次读取
生成带 dataset、pointer、Profile snapshotHash 和 purpose 的 `ProfileReadReceipt`。禁止把完整
Profile、完整 variables 或相关矩阵打印到工具输出。Reporting Coding Task 的通用工具结果超过
8 KiB 时只进入模型摘要、哈希和 `outputHandle`，原文继续保存在工作区工具输出存储中。

Profile 用于定位分析重点，不替代最终计算。报告中的正文数字、表格和图表必须由 Coding Worker
从本轮不可变 CSV 复算。CSV 路径越权、大小或哈希变化、解析失败均阻断执行。

同一期间存在多行的面板数据不启用行级 ACF/PACF。画像会返回
`reason=duplicate_time_index` 和 `aggregationRequired=true`，Coding Worker 先按月及适当组织粒度
聚合，再决定趋势、同比、ACF、PACF 和季节性分析；唯一时间索引才保留 Profile 时序统计。

## 详细分析计划

步骤 11 不启动第二个 Coding Task，也不重复读取 CSV。服务端根据步骤 7 已批准分析项、步骤 10
Profile 索引、DatasetHandle 和 Warning 编排紧凑 `DetailedAnalysisPlan`。每项包含：

- `analysisId`、领域和管理目标；
- Dataset、字段、指标、期间与组织粒度；
- 分析动作和 Profile 证据摘要；
- 数据限制、推荐表格与图表、建议章节和完成条件。

计划只验证 Dataset、字段、期间和来源真实存在。数据缺口、质量问题与假设进入 Warning，不构造
覆盖闭包。

## 提纲与分阶段 Coding

步骤 12 使用 `DetailedAnalysisPlan + DataShape + Warning` 生成动态提纲。章节引用唯一且真实的
`analysisId`，并继续使用现有人工审核或 CLI 提纲自动确认机制。

步骤 13 保持一个外部 Workflow、thread 和 Daytona workspace，但内部拆成以下互不继承消息历史的
Agno run：

1. 全局 analysis run 接收目标、冻结提纲、`ProfileCoverageManifest` 的受信文件身份与有界 Dataset
   摘要、紧凑 `DetailedAnalysisPlan`、Dataset/lineage/citation 注册表和 `analysisContextFile`。完整字段
   coverage 不在动态指令中重复，由 Profile 索引分页恢复。analysis run 读取全部 Dataset
   coverage，按管理问题定点读取 Profile 和 CSV，统一完成规模、结构、趋势、同比环比、预算差异、
   异常和跨域分析，最后通过 `complete_report_analysis` 冻结 `ReportBrief`、
   `AnalysisEvidenceManifest`、共享指标口径、Profile 读取回执、Warning 和图表。
2. 每个冻结章节使用独立 section run。输入 `SectionWorkItem` 只包含当前章节目标与完成条件、对应
   analysisIds 的完整 evidence、共享指标口径、相关 ProfileReadReceipt、chart 和 citation。正常只调用
   一次 `render_report_section`；不携带其他章节 Markdown、terminal 输出、补丁历史或旧错误。
3. section evidence 不足时调用 `request_analysis_rework`。Workflow 新建隔离 analysis run 补证，更新
   冻结分析产物，然后只重跑请求返工的章节；已完成章节保持原产物身份。

每个 phase 使用不同的 `report-coding-*` task key，因此 Agno session、消息和工具状态互相隔离。
`ReportTaskRunner` 将 acceptance contract 中的受信 phase 绑定到内部 run；callable tools factory、模型
tool schema 和执行门禁使用同一 phase 投影。analysis 不能提交章节；section 只保留 `read_file`、
`read_lines`、`read_tool_output`、`render_report_section`、`request_analysis_rework` 和确定性
`finish_task`，不能执行命令、修改文件、读取 Profile、加载 Skill、登记图表或进入旧草稿 Finalize。
section 的模型消息投影同时移除 Agno 自动追加的 `skills_system`，analysis run 仍保留现有 Skill 能力。
其中 `read_file` 和 `read_lines` 只接受当前 `SectionWorkItem.evidence[*].evidenceFiles[*].path`，
猜测到的其他章节产物、分析上下文和未授权 evidence 路径均在文件读取前失败关闭。
旧草稿工具在任一内部 phase 都失败关闭。
`SectionWorkItem` 先写入受信 JSON，acceptance contract 的首个 requirement 只保存 phase、输出路径及
该文件的路径、大小和 SHA-256，避免 16 KiB acceptance 参数上限截断 evidence。analysis 指令不得超过
Reporting 的 512 KiB Task 边界；section work item 以约 64K token 为软上限，超限时明确失败，不静默
删除关键 evidence 或口径。

`ReportingCheckpoint` 在 analysis 前、每次 task 启动和完成、补证请求及 Finalize 前后同步写入
Workflow state 与 workspace JSON。它保存 phase、Profile coverage/读取回执、ReportBrief、evidence、
完成和待生成章节、Warning、最近真实错误、投影字节数、模型实际 input token、Pointer 读取与重试原因
等上下文 trace，以及全部文件路径、大小和 SHA-256。进程在
analysis 或任意 section 中断后，Workflow 依据 checkpoint 与 TaskRepository 恢复未完成 phase；活动 task
可继续原 run，已经终止的 task 只重试当前 phase，不重跑已完成章节。
canonical history 继续由 Agno 完整保存用于审计，但不直接投影到下一个 phase。

图表在 analysis run 中按工作区相对路径和 citationIds 冻结。当前默认 `visualTheme` 为
`enterprise-tech-blue`；启用视觉能力时，`view_image` 仍只返回结构化文字反馈。全部 section 完成后，
服务端按冻结提纲顺序装配 Markdown，并从提纲注入 analysisIds；正文 block 只提交 Markdown、
citationIds 和 chartIds。服务端只归档正文实际引用的图表，其他图表记录
`unused_chart_excluded` 并从发布包排除，不阻断 Finalize。随后继续生成权威 ArtifactManifest、PDF、
DOCX 和下载回执。

## 引用与发布

Citation 由服务端按 `datasetId + requirementId + snapshotHash` 签发。图表绑定 citation，章节绑定
analysis。服务端生成 `ArtifactManifest`，并继续验收 Markdown、PDF、DOCX 的路径、大小、哈希、
章节、图表、引用和数据血缘。发布门禁、下载授权、审计、Daytona thread 隔离和 Warning 传播保持
不变。

当前实现不提供独立计算 DSL。可追溯边界由不可变 Dataset、脚本执行记录、Dataset citation、
ArtifactManifest 和产物哈希共同组成。
