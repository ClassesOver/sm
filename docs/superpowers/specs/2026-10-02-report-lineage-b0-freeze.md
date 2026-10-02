# Report Editor 数据追溯 B0：现状核对、契约冻结与待决项

日期：2026-10-02

状态：B0 进行中；G0 **未通过**（见第 6 节待决项）。

依据：`2026-09-29-report-editor-data-lineage-batched-implementation.md`（下称“计划”）。

## 1. 计划与代码核对结论

已逐条核对计划第 2 节列出的代码位置，以下为与计划描述不一致或计划未覆盖、会影响后续批次的事实。

| # | 代码事实 | 位置 | 影响与处理 |
| --- | --- | --- | --- |
| C1 | Editor 分享链接与原编辑链接签发同一种 grant/session，`ReportEditorSession` 没有角色或能力字段；两者唯一差别是 TTL（30 天 vs 长期） | `report_editor/service.py` `ReportEditorSession`、`api.py` `/share` | 计划 4.1-8 要求“分享编辑链接不自动升级为明细读取权限”，但当前无法区分会话来源。B1 前必须给 grant/session 增加能力集合，旧 grant 缺省按最小能力处理。权限默认值待决（Q1）。 |
| C2 | 生产环境存在 Plotly 图表：非 `static` 可视化模式允许 `renderer="plotly"`，此时图表同时登记静态 PNG 与 `.plotly.json` | `tools/visualization.py`、`checkpoint.AnalysisChart`、`artifacts_v1.ChartArtifact` | 计划“Plotly 不实施”只能理解为“不做图内点选”。建议：Plotly 图按其静态 PNG 走同一 ChartTrace 契约；作图数据要求相同，交互规格不参与追溯。待确认（Q4）。 |
| C3 | 图表全部由模型在可视化 Task 中自写 matplotlib/plotly 脚本生成，登记入口只有 `submit_visualization_charts`；不存在封闭的“图表类型”清单 | `tools/visualization.py`、`delivery/draft_v1.ReportChartRegistration` | G3“所有 B0 列明的现有静态图类型”无法按类型枚举。改为按登记契约覆盖：B3 在登记工具中要求同时提交作图 CSV 与系列映射，未提交的新图显示“来源不足”，不按类型豁免。 |
| C4 | 补充分析由模型在 CodeMode 中自写脚本完成；`AnalysisCodingRequirement.calculation` 是自由文本，`SupplementalEvidence.findings` 是任意 dict | `workflow/runtime/analysis_item_workflow.py` | 不存在可枚举的“统计/预测/异常方法”。B4 只能用通用 `ComputationRecordV1` 登记输入、脚本、执行身份、中间文件与输出；“方法专属字段”只适用于确定性方法（比较、比率、对账、相关性）。计划 9.2“统计分析集合”的样本范围待决（Q5）。 |
| C5 | `DeterministicComparison` 只有 `fieldRef` 与双方 datasetId/sha256，没有 metricCodes，也没有指向两条 metric fact 的引用 | `hospital_operation/deterministic_analysis.py` | B2 需为比较事实补 `inputFactRefIds`（契约已支持），否则正文按 metricCode 绑定比较值时存在歧义。 |
| C6 | `DeterministicDerivedMetricFact` 以 metric code 引用分子/分母；同一 code 在同一期间有多条 fact 时生成器已拒绝并告警 | 同上 `_derived_metrics` | 唯一性已有保证；B2 只需把被选中的两条 fact 的指针写入 `inputFactRefIds`。 |
| C7 | `correlations` 为 `{"datasetId:left~right": float}`，无方法、样本数、对齐说明 | 同上 `_correlations` | 键中的 `~` 在 JSON Pointer 中须转义为 `~0`。B4 需补样本数与方法（Pearson、成对删除缺失）。 |
| C8 | 确定性 facts 按 `报表/智能分析/{run}/facts/revision-{n}/{analysisId}.json` 落盘，身份在 checkpoint 中冻结并在恢复时重新哈希 | `workflow/runtime/analysis.py` `_restore_or_create_deterministic_analysis_facts` | 与计划“事实文件身份 + JSON Pointer”一致，B2 可直接复用，不需要新建事实库。 |
| C9 | `DatasetHandle` 无物化时间；`DatasetLineage` 无文件路径 | `data_sources.py`、`workflow/query_pipeline.py` | 与计划一致。旧快照 `materializedAt` 一律为未知。 |
| C10 | Editor 导出 N+1 仍传 `artifact_manifest=None` | `report_editor/service.py` `_export_revision` | 与计划一致，B6 处理。 |
| C11 | 计划写的适用仓库路径是 `/home/junge/pros/smart_reporting`（个人本地路径） | 计划头部 | 仅为文档描述，不影响实现。 |

额外基线：用 B0 合成样本运行现有 `build_deterministic_analysis_bundle`，R1、R2 的收入、人次、次均及环比均与手算答案一致，且无告警（见 `test_report_trace_contract.py`）。说明确定性计算本身可作为 B2 的可信起点，B2 的工作集中在“精确引用”，不需要重写计算。

## 2. 已冻结契约（V1）

代码：`smart_reporting/reporting/delivery/trace_v1.py`；测试：`smart_reporting/reporting/tests/test_report_trace_contract.py`。

| 对象 | 冻结要点 |
| --- | --- |
| `FileRefV1` | 继承既有 `FileIdentity`（安全相对路径、size、sha256），增加不透明 `resourceId`（`res_` + 32 hex）与媒体类型（csv/json/png/jpeg/python）。同一索引内同一 resourceId 只能对应同一文件身份。 |
| `DatasetSnapshotRefV1` | 字段与 `DatasetHandle` 对齐；`url_csv` 必须且只能有 filename；`materializedAt` 可空（未知），有值必须带时区。 |
| `FactRefV1` | 事实文件 + RFC 6901 指针；指针长度 ≤512，必须指向该 kind 登记的集合内部记录（如 `metric → /metrics/<i>`），拒绝 `-`、集合根和其他节点；只能登记数值事实，`interpretation` 不允许；必须追溯到 CSV 或输入事实；`resolve_fact` 对未知指针统一返回 `fact_binding_unavailable`。 |
| `ComputationRecordV1` | 方法/版本、JSON 安全参数、输入 CSV/facts、预处理、中间文件、脚本、执行身份、输出 facts、限制、验证状态、复算能力。输入输出不重叠；缺脚本或执行身份不能声明 `reproducible`。 |
| `ChartTraceV1` | 静态 PNG/JPEG + ≥1 份 CSV 作图数据 + 类别列 + 系列（单位、主/次轴、observed/forecast/区间）；必须追溯到 CSV 或 facts；`visualReviewStatus` 只取既有 `passed`/`not_run`。 |
| `SubjectBindingV1` | claim / table_cell / chart 三种对象，必须且只能有对应定位；表格用冻结 `tableId/rowKey/columnKey`；`subjectSha256` 记录生成时规范化内容；解释性结论必须引用支持事实。 |
| `RevisionTraceIndexV1` | 绑定 reportId/revision/workflowRunId/正文 sha/Profile hash；校验所有 ID 唯一、所有引用已登记、同一事实位置不重复登记、每个事实最多一个产出计算、事实依赖与计算依赖均无环。 |
| canonical JSON | 键排序、紧凑分隔、UTF-8、拒绝 NaN/Infinity 与非 JSON 类型；`trace_index_sha256` 基于此。 |
| 状态维度 | `ContentBinding`、`FileAvailability`、`ComputationVerification`、`EvidenceNature`、`Reproducibility` 按计划 3.3 取值冻结。 |
| 错误码 → HTTP | `source_missing` 404、`fact_binding_unavailable` 404、`subject_stale` 409、`snapshot_integrity_failed` 409、`snapshot_expired` 410、`dataset_access_denied` 403、`cursor_invalid` 400、`drilldown_unavailable` 422、`resource_limit_exceeded` 429。元数据读取遇到 stale/过期返回 200 加 warningCodes。 |

尚未冻结：claim 正文规范化与 `subjectSha256` 计算规则（B6 前冻结，依赖 Q3）、签名游标格式（B1 冻结）、来源索引在 manifest/context 中的登记字段（B1 冻结）。

## 3. 能力覆盖表

| 编号 | 依赖的现有基础 | 主要缺口 | 批次 |
| --- | --- | --- | --- |
| F01 | DatasetHandle/Lineage、发布前 CSV 校验 | 索引登记、resourceId、物化时间 | B1 |
| F02 | 现有 polars CSV 解析、200 MiB 上限 | 分页预览、签名游标、会话能力（C1）、派生导出任务 | B1、B5 |
| F03 | 确定性 facts 文件与身份冻结（C8） | 比较/比率输入指针（C5、C6） | B2 |
| F04 | 补充分析脚本与 evidenceFiles | 通用计算记录接入（C4）、相关性元数据（C7） | B4 |
| F05 | SectionClaim、正文 block 的 claimIds | claim → factRefs，解释与数值分离 | B2、B4 |
| F06 | `[[table:…]]` 协议块及 TableArtifact sha | 行列键与单元格绑定 | B2 |
| F07 | AnalysisChart、视觉检查回执 | 作图数据登记（C3）、Plotly 处理（C2） | B3 |
| F08 | 草稿 CAS、历史、N+1 导出 | manifest 传递（C10）、内容指纹 | B6 |
| F09 | Profile 维度与指标聚合语义 | 下钻声明与服务 | B7 |
| F10 | PDF/Word 渲染移除 citation 标记 | 编号与附录 | B8 |
| F11 | Editor 授权、workspace 路径检查 | 会话能力（C1）、保留与恢复 | B0～B9 |
| F12 | loguru、现有开关 | 来源功能开关、诊断、回滚 | B9 |

## 4. 权限矩阵（草案，待 Q1 确认）

| 能力 | 原编辑链接 | 分享链接（30 天） | 旧 grant（无能力字段） |
| --- | --- | --- | --- |
| 查看来源概览、事实、计算说明、图表来源 | 允许 | 允许 | 允许 |
| CSV / 作图表 / 中间表预览 | 允许 | **待决** | 同分享链接 |
| 原始 CSV 下载 | 允许 | **待决**（建议禁止） | 禁止 |
| 派生（脱敏）导出 | 当前无已登记脱敏策略，显示不可用 | 同左 | 同左 |
| 单维度下钻 | 允许 | **待决** | 同分享链接 |

字段级可见性：当前代码没有字段敏感度配置。建议 B1 先以“全字段或全不可见”两档实现，字段级策略作为 Profile 配置项另行登记（Q2）。

## 5. 资源预算（初始值，待真实报告测量后调整）

| 项目 | 初始值 | 来源 |
| --- | --- | --- |
| 预览每页 | 默认 50 条，最大 100 条；≤50 列；单元格 ≤4 KiB；响应 ≤1 MiB | 计划 4.1 |
| 单文件 | ≤200 MiB（沿用 `MAX_DATASET_FILE_BYTES`） | 现有代码 |
| facts 展开 | 单次一层；节点 ≤200；响应 ≤1 MiB | 本文提议 |
| 来源索引 | facts ≤20 000、subjects ≤20 000、charts ≤100、datasets ≤100 | 契约上限 |

本环境没有可用的真实报告与工作区数据，“测量现有报告大小与响应基线”未执行，不能记为完成。

## 6. G0 状态与待决项

已完成：

- 计划 vs 代码核对（第 1 节）。
- V1 契约与反例测试（第 2 节）。
- 基础样本 R1/R2/R3 的输入 CSV 与手算答案：`smart_reporting/reporting/tests/fixtures/report_trace/`；R1、R2 已与现有生成器对账通过。R3 的 stale 判定依赖 B6，当前仅冻结了期望答案。

未完成，G0 不能通过：

| 编号 | 待决/待做 | 需要谁 |
| --- | --- | --- |
| Q1 | 分享链接是否允许 CSV 预览、原始下载与下钻；旧 grant 的缺省能力 | 产品/数据负责人 |
| Q2 | 是否需要字段级可见性；若需要，敏感字段由谁、在何处配置 | 产品/数据负责人 |
| Q3 | 人工改值判定口径：数值格式变化（如 3600 → 3,600 → 0.36 万）是否视为未变化 | 产品 |
| Q4 | Plotly 图是否按其静态 PNG 纳入 ChartTrace（第 1 节 C2） | 产品 |
| Q5 | 补充分析的复杂事实验收样本：由于没有封闭方法清单，需要业务从近期真实报告中选定代表性分析 | 业务 + 工程 |
| Q6 | 来源文件保留期（与报告 revision 保留期对齐还是单独配置） | 运维 |
| T1 | 图表数据集、多步 facts、CSV 边界、生命周期、旧报告样本及独立答案 | 工程，B0 内继续 |
| T2 | 真实报告规模与响应基线测量 | 需可访问真实环境 |
