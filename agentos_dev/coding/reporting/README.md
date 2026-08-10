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
Pointer 索引，单个 Dataset 视图硬限制在 12 KiB 内。模型先通过
`inspect_profile_index` 获取单个 Dataset 的紧凑 coverage、完整/已索引告警数、分层截断状态和
分页字段 Pointer 目录；`read_profile_pointer` 再定点读取变量、相关性、缺失、极端值、字符串、变量交互和时序统计。工具
核验 `validationContextFile`、`analysisContextFile` 与 `profileFile` 的大小和 SHA-256，并对返回
内容设置有界 item 预算。禁止把完整 Profile、完整 variables 或相关矩阵打印到工具输出。

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

## 提纲与逐章成稿

步骤 12 使用 `DetailedAnalysisPlan + DataShape + Warning` 生成动态提纲。章节引用唯一且真实的
`analysisId`，并继续使用现有人工审核或 CLI 提纲自动确认机制。

步骤 13 向 Report Coding Worker 提供用户目标、批准提纲、DetailedAnalysisPlan 的紧凑执行投影、
DatasetHandle、DatasetLineage、CSV 身份、Profile 文件与 Warning。执行投影中的每项只包含
`analysisId + domain + step + datasetIds`；字段、期间、Profile 信号和完整 Warning 继续保存在受信
`analysisContextFile`，不在动态指令中重复。Worker 先形成少量执行步骤，再按照提纲章节逐章读取
CSV、实现对应 analysis、生成正文、表格和图表。完整 Profile 只用于发现分析方向，最终
数字和证据全部从不可变 CSV 复算。图表候选由实际字段、期间、组织粒度、偏度/峰度、零值、缺失、
相关性、预算阶段和跨域关系共同产生，Worker 按管理问题选择趋势、结构、贡献、分布、热力、预算、
漏斗、散点或象限表达，不受固定图表数量约束。

Worker 在生成分析脚本和图表前调用 `begin_report_draft`，获取冻结章节顺序和服务端统一
`visualTheme`（当前默认主题为 `enterprise-tech-blue`）。PDF、Word 和 Coding 生成的图表共用该配色；配色只作为视觉一致性基准，
不限制图表类型、系列数量或数据强调方式。图表登记安全工作区相对路径和 `citationIds`，
再通过 `render_report_section` 逐章提交原生 Markdown；正文块绑定
`citationIds + analysisIds + chartIds`，已登记图表由服务端插入。全部章节完成后先按
`unreferencedChartIds` 区分处理：计划发布图补齐正文引用，误登记且未被正文引用的预览图通过
`discard_report_charts` 从当前 Attempt 的登记状态移除，再调用 `finalize_report_draft`；若拼装仍返回
`unused_chart_excluded`，可替换相关完整章节并重新定稿。服务端统一拼装、归档并完成收尾。单章可恢复错误使用 Agno
`RetryAgentRun` 返回当前工具循环，不重传整份报告。

## 引用与发布

Citation 由服务端按 `datasetId + requirementId + snapshotHash` 签发。图表绑定 citation，章节绑定
analysis。服务端生成 `ArtifactManifest`，并继续验收 Markdown、PDF、DOCX 的路径、大小、哈希、
章节、图表、引用和数据血缘。发布门禁、下载授权、审计、Daytona thread 隔离和 Warning 传播保持
不变。

当前实现不提供独立计算 DSL。可追溯边界由不可变 Dataset、脚本执行记录、Dataset citation、
ArtifactManifest 和产物哈希共同组成。
