# Report Editor 数据追溯 B0 冻结：契约、能力覆盖、权限、预算与独立答案

日期：2026-09-29。状态：B0 交付（G0 自检见末节）。

上游计划：`2026-09-29-report-editor-data-lineage-batched-implementation.md`（下称"计划"）。
本文冻结 B0 全部交付物；后续批次以本文为契约基线，字段变更必须先修订本文并记录原因。

## 1. 契约代码（B0-2）

权威实现：`smart_reporting/reporting/trace/contracts_v1.py`（单测
`smart_reporting/reporting/tests/test_trace_contracts.py`，32 例通过）。

| 契约对象 | 计划名 | 关键冻结点 |
| --- | --- | --- |
| `TraceFileRefV1` | FileRefV1 | resourceId=`trf-{sha256(path)[:20]}`，必须由登记路径派生；path 仅存服务端 sidecar，API 不返回；POSIX 相对路径、拒绝 `..`/绝对/反斜杠 |
| `DatasetSnapshotRefV1` | DatasetSnapshotRefV1 | sourceType 限 `starrocks_materialized`/`url_csv`；materializedAt 未知为 null（禁止 mtime 推断）；filename/businessLabel 仅展示 |
| `FactRefV1` | FactRefV1 | analysisId + fileResourceId + RFC 6901 JSON Pointer（≤256 字符）；factKind 六类；factKey 为防御性核对键（B2 起写入 factId） |
| `ComputationRecordV1` | ComputationRecordV1 | 输入输出引用齐全；同 analysis 自环拒绝；verification 初始 `not_checked`（运行成功≠数值复核通过） |
| `ChartSeriesV1`/`ChartTraceV1` | ChartTraceV1 | seriesKind 区分 observed/predicted/confidence_interval/target；预测/区间系列必须绑定 facts 或计算记录；plotData 文件与源 CSV 分角色登记；B6 可选 presentationSha256 冻结图题/紧邻图注指纹，N+1 不重设，旧记录从哈希校验后的冻结正文迁移 |
| `TableCellBindingV1`/`TableTraceV1` | 表格单元格定位 | 单元格身份=(rowKey, columnKey)，必须在冻结行/列键集合内且不重复；插入行列不能复用旧身份 |
| `SubjectBindingV1`/`SubjectLocatorV1` | SubjectBindingV1 | subjectId=`sub-{16hex}` 内容寻址；按 kind 校验定位组合（table_cell→table+row+col；chart*→chartId；text_claim→仅章节）；必须至少绑定 fact 或计算记录；evidenceKind 区分数值与解释 |
| `RevisionTraceIndexV1` | RevisionTraceIndexV1 | 顶层全局校验：所有 resourceId/datasetId/analysisId/tableId/chartId/computationId 引用必须已登记且一致；上限见预算表 |

状态维度（读取层运行时计算，不写入不可变索引）：`valid/stale/unbound`、
`available/missing/expired/integrity_failed`、`verified/not_checked/failed/not_applicable`、
`observed/computed/estimated/interpretation`、`reproducible/limited/unavailable`。

canonical 规则（`canonical_json_bytes`/`subject_fingerprint`）：
- JSON：`sort_keys + 紧凑分隔 + ensure_ascii + allow_nan=False`（NaN/±Inf 构造期拒绝）。
- 时间：ISO8601 UTC（`...Z`）或 null。
- sha256 一律小写 64 hex；subject 指纹 = 规范化内容（统一 `\n`、去行首尾空白）的 sha256。
- 现有 float facts 按既有精度冻结；核对使用指标明确精度与容差，不换序列化格式伪造相同 hash。

信任根：`RevisionTraceIndexV1` 是 sidecar，不以自身 hash 为唯一信任根；B1 起由权威
manifest/context 登记（见未决清单 #2）。

## 2. 能力覆盖表（B0-1）

### 2.1 F01～F12 × 现有代码基础 × 测试责任

| F | 现有基础（已核对源码） | B0 起需新增 | 主批次 | 测试责任 |
| --- | --- | --- | --- | --- |
| F01 | `DatasetHandle`（path/size/sha256/requirementId/sqlHash/queryWindowId/periodRoles/sourceType/filename，`data_sources.py`）；durable 找回路径仅 `ProfileCoverageManifest.datasets[].datasetPath` | revision 级 `DatasetSnapshotRefV1` 索引 + 物化时间 | B1 | 扩展 `test_report_data_sources.py` + B1 新索引测试 |
| F02 | `read_asset` 的"登记-校验-逐字节哈希"模式（`report_editor/service.py:321`） | CSV 预览分页/列选择/签名游标 + 原始/派生下载任务 | B1、B5 | B1 后端（含 `boundaries.csv`、宽表）+ B5 浏览器 |
| F03 | 四类 facts 已带 dataset_id+sha256+formula 文本（`deterministic_analysis.py`） | per-fact 稳定 ID + `FactRefV1` + 派生输入 fact 关系；correlations 补 n/sha256/字段身份 | B2 | 扩展 `test_deterministic_analysis.py`；fixtures R1/R2 独立答案 |
| F04 | `SupplementalEvidence`（findings 列式）、`ExecutionReceipt`（runId+文件身份）、evidenceFiles ≤50×10MiB | `ComputationRecordV1` 登记（参数/环境摘要/中间表/inputFactRefs） | B4 | fixtures contribution/edge；B4 新测试 |
| F05 | `SectionClaim` 仅 citation_ids（dataset 级，`checkpoint.py:477`） | claim.factRefs + `SubjectBindingV1` + 受控 subject 标记 | B2、B4、B5 | R3 stale 场景（`r3_stale_expected.json`） |
| F06 | `TableArtifact` 仅 tableId+sha256（`artifacts_v1.py:82`） | `TableTraceV1` 行列键冻结 + 单元格绑定 | B2、B5 | B2 单元格错位/总计对账反例 |
| F07 | `AnalysisChart`（图片身份+视觉回执）；`chart_inputs.py` chart-input/v1 按 dataPath 位置寻址、绑定失败回退 | 作图数据固化进契约 + ChartTraceV1 + 图片/数据联合验收 | B3、B5 | `chart_series.csv` + `chart_expected.json` |
| F08 | draft CAS、history、export N+1（`artifact_manifest=None`，`service.py:703`） | subject 指纹校验 + manifest 传递 + revision 来源继承 | B6 | R3 + 生命周期集合 |
| F09 | metrics aggregation 枚举（sum/average/min/max/count/count_distinct）+ scope | 维度声明 + 受限聚合 + 对账摘要 | B7 | 每类指标正例+拒绝例 |
| F10 | `pdf.py` 已移除 citation marker；`citationPresentations` 已生成 `[引用 001]` 别名但未展示 | 来源编号 + 附录 + 状态表达（双格式） | B8 | 双格式实际检查 |
| F11 | GrantService（grant 10y/share 30d/session 8h）+ Origin/CSRF（`api.py:429`） | 明细权限矩阵接入 + trace API | B0～B9 | B1 权限矩阵测试 |
| F12 | `QualityAuditCollector` 台账 | 功能开关 + 诊断 + 回滚 | B9 | 验收矩阵 |

### 2.2 现有适用类型清单（测试范围冻结）

- 确定性事实：聚合 6 种（sum/average/min/max/count/count_distinct）、比较 2 种（yoy/mom）、
  派生比率、对账、Pearson 相关（补全元数据后纳入）。
- 补充分析：`SupplementalEvidence` findings/reconciliations——**无方法枚举**
  （`calculation` 为自由文本）。B0 决定：不发明方法分类引擎；`ComputationRecordV1.method`
  为受控字符串 + limitations 必填；B4 只对确定性五类建专属字段映射。
- 图表：matplotlib/plotly 两渲染器、chart-input/v1 数据绑定。
- 数据来源：`starrocks_materialized` 与 `url_csv` 两类，均纳入索引。
- 排除项与计划 1.2 一致：Plotly 交互图内点选、任意 SQL、跨报告查询不实施。

## 3. 权限矩阵与配置（B0-3）

会话类型沿用现有：editor session（grant 兑换，8h）与 share session（30 天分享链接）。

| 能力 | editor session | share session（默认） | share session（可配置） |
| --- | --- | --- | --- |
| 来源元数据 + 绑定状态 | 允许 | 允许（只读） | — |
| CSV 预览（允许字段内） | 允许 | 允许 | — |
| 下载原始 CSV | 允许 | 拒绝（`dataset_access_denied`） | `share_download_original_enabled` |
| 下载派生/脱敏文件 | 允许 | 拒绝 | `share_download_derived_enabled` |
| 快照内下钻 | 允许 | 拒绝 | `share_drilldown_enabled` |
| 创建导出任务（写） | 允许（Origin+CSRF） | 拒绝 | — |

字段级预览：`preview_blocked_columns`（列名精确匹配黑名单，默认空=全可见）；
派生导出策略：B1 注册 `masked_columns` 策略代码，未登记策略代码的请求 4xx，不伪造"已脱敏"。

配置入口（B1 落地到现有 settings 机制，命名前缀 `report_editor.trace.`）：
`share_download_original_enabled`、`share_download_derived_enabled`、`share_drilldown_enabled`、
`preview_blocked_columns`、`download_original_max_bytes`（默认 200MiB）、
`derived_export_retention_seconds`（默认 86400）。
缺配置行为：按上表默认值（最严格）执行，loguru 记一次告警；分享编辑链接不自动升级明细权限。

## 4. 错误码与 HTTP 映射（B0 冻结）

代码常量 `TRACE_ERROR_HTTP_STATUS`（单测锁定）：

| code | HTTP | 语义 |
| --- | --- | --- |
| source_missing | 404 | 对象缺失或不属于当前授权索引（不泄露其他报告对象存在性） |
| subject_stale | 409 | 元数据 200 携带 warningCodes；依赖该 subject 的写操作/校验按 409 |
| fact_binding_unavailable | 409 | fact 引用无法解析（指针失效等） |
| snapshot_expired | 410 | 快照超过保留期 |
| snapshot_integrity_failed | 409 | 身份/hash 不一致，拒绝内容；前端保留编辑能力 |
| dataset_access_denied | 403 | 会话/能力不允许 |
| cursor_invalid | 400 | 游标非法/过期/重放 |
| request_invalid | 400 | 请求形状非法（不存在的列、非法 limit 等），不进入执行器（B1 实施时按计划 5.2 补入） |
| drilldown_unavailable | 409 | 维度未声明或输入缺失 |
| resource_limit_exceeded | 413 | 请求形状超固定预算；并发饱和沿用现有 busy(429) |

接入方式：沿用 `report_editor/api.py` 的 `HTTPException(detail={"code","message","requestId"})`
与 `_editor_error_status` 映射扩展；预览/下载错误正文不泄露字段或路径。

## 5. 资源预算与性能门槛（B0-6）

常量 `TRACE_BUDGETS_V1`（单测锁定）；下表含基线依据。

### 5.1 输入与契约上限（源码常量推导）

| 项 | 值 | 来源 |
| --- | --- | --- |
| 单 CSV 上限 | 200 MiB | `MAX_DATASET_FILE_BYTES` |
| 报告输入数 | ≤100 | `MAX_REPORT_INPUTS` |
| facts bundle 条目 | metrics≤500、derived≤500、comparisons≤400、reconciliations≤500 | `DeterministicAnalysisBundle` |
| 补证 | 单文件≤10 MiB、≤50 文件 | `MAX_SUPPLEMENTAL_EVIDENCE_BYTES`/`AnalysisEvidence` |
| 索引 | files≤2000、datasets≤100、subjectBindings≤2000、charts≤200、tables≤2000、computations≤500 | `RevisionTraceIndexV1` |

### 5.2 API 预算（计划 4.1 数值冻结）

预览：默认 50 行/页、最大 100 行/页、50 列、单元格 4 KiB、响应 1 MiB；
fact 展开：深度 3、节点 50、响应 1 MiB；下钻：100 组、响应 1 MiB；
派生导出保留 24h。宽表受控列选择；字节超限返回不足一页并声明截断。

### 5.3 实测基线（2026-09-29，合成 CSV，本机）

100 万行 / 62 MiB / 7 列：`read_csv` 全量 0.24s（内存 63 MiB）；
`scan_csv().head(100)` 107ms；`scan_csv().group_by().sum()` 0.21s（20 组）。
外推 200 MiB：全量读约 0.8s / 内存约 200 MiB——**预览与下钻必须走 lazy scan**，
禁止每次翻页全文件入内存（计划 4.1-4）。

### 5.4 性能门槛（B1 生效，B9 复测）

预览首页 p95 ≤ 1s（200 MiB 输入）；fact 一层展开 p95 ≤ 300ms；
下钻 p95 ≤ 3s；索引（≤2000 files）加载 p95 ≤ 200ms。

### 5.5 待实测清单（无真实报告环境，B1 执行）

真实报告的典型 facts 条目数/图表数/claims 数/来源数量分布；
真实名称长 CSV（长中文名、引号）解析；200 MiB 上限文件的流式下载吞吐。
当前仓库 e2e-logs 仅有错误日志，无完整真实报告产物，B0 不虚构该部分基线。

## 6. Fixtures 与独立标准答案（B0-4/5）

位置：`smart_reporting/reporting/tests/lineage_fixtures/`；
自洽测试：`test_lineage_fixtures.py`（9 例通过）。

| 文件 | 场景 | 独立答案 |
| --- | --- | --- |
| `csv/hospital_revenue.csv` | 计划 9.1 四条记录（元） | `r1_expected.json`（3600/30/120/20%）、`r2_expected.json`（1200/10/120/20%，本期基期同受范围限制）、`r3_stale_expected.json`（改 3800→stale）、`contribution_expected.json`（A 200/B 400/总 600 → 33.33%/66.67%） |
| `csv/chart_series.csv` | 排序/Top N+其他/缺值/单位换算/负数/多系列 | `chart_expected.json`（B 2400/A 1200/C 600/其他 350；万元 3 位；C 费用 missing；D 负数入其他） |
| `csv/edge_cases.csv` | 零分母/缺失期间/缺失值 | `edge_expected.json`（D mom_change=100、rate=null `zero_denominator`；E `missing_baseline`、空值不计入聚合计入 missing_count） |
| `csv/boundaries.csv` | 引号内逗号/换行、空字段、128 字长字段、转义引号 | `boundaries_expected.json`（5 条记录） |
| `wide_csv_bytes()` | 宽表生成器（61 列 > 预算 50 列） | B1 受控列选择验证 |

答案独立性：expected/*.json 为手算常量；`answers.py` 用标准库 csv + 纯 Python
（与被测 polars 管线不同路径）独立重算并与手算互证；不从被测实现反向生成答案。
R3 由 B2/B6 在真实链路上复现（B0 只冻结状态规则）。

## 7. 未决设计清单（依赖开发前必须关闭）

| # | 未决项 | 影响批次 | 当前倾向 |
| --- | --- | --- | --- |
| 1 | 物化时间来源：`DatasetHandle` 未记录时间 | B1 | handle 增 `materializedAt`（默认 null 向后兼容），materialize/register 时写入 |
| 2 | 索引的权威登记载体：manifest 新增登记字段 vs context 登记 | B1 | `ReportArtifactManifest` 增可选 `traceIndex: ArtifactFile`（需先扩展 mediaType 枚举 +json/csv）；旧 manifest 无此字段=无来源索引，正常降级 |
| 3 | per-fact 稳定 ID：bundle 条目现按数组位置寻址 | B2 | bundle 条目增 `factId`（`fact_` + 内容寻址）；旧文件无 factId 时 FactRef 仅位置寻址 + factKey 空 |
| 4 | chart-input 绑定失败回退 vs ChartTrace"同一份数据"要求 | B3 | 回退图标记 unbound（保留图），不伪造 ChartTrace；B3 定稿 |
| 5 | SupplementalEvidence findings 的 fact 化定位 | B4 | findings 列式结构加行键，FactRef 指向 `findings/rows/{key}`；自由 dict 部分仅 analysis 级引用 |
| 6 | citation 序号不稳定（`citation_{index:03d}` 随排序变化） | B8 | 导出编号用 trace 索引稳定 ID，不复用 citation 序号 |
| 7 | 分享会话明细权限默认值需业务确认 | B1 上线前 | 保持本文最严格默认，业务书面确认后可改配置 |
| 8 | ExecutionReceipt 无环境指纹 | B4 | receipt 增 `environment` 摘要（Python/关键依赖版本/种子）；旧回执无此字段→reproducibility=limited |

## 8. 修订工期

原计划 38～60 人日不变。B0 实际完成于 2026-09-29（契约+单测+fixtures+冻结文档）。
B1 前置条件已满足：身份契约、权限矩阵、预算、独立答案、错误映射全部冻结。

## 9. G0 自检

| G0 条件 | 结果 |
| --- | --- |
| 全部功能有归属批次 | 通过（第 2.1 节覆盖表 + 计划第 7 节） |
| 权限与资源预算已写成数值/规则 | 通过（第 3、5 节 + `TRACE_BUDGETS_V1`/`TRACE_ERROR_HTTP_STATUS` 常量） |
| 至少三份基础样本 | 通过（R1/R2/R3 手算答案 + 输入 CSV） |
| 一条复杂事实独立答案 | 通过（贡献分解链 200/400/600 → 33.33%/66.67%，`contribution_expected.json`） |
| 一张图表独立答案 | 通过（Top N+其他+换算+缺值+负数系列，`chart_expected.json`） |
| 未决设计记录到待解决清单 | 通过（第 7 节 8 项，均标注影响批次与倾向，依赖批次开发前关闭） |

真实报告规模基线未实测（第 5.5 节如实记录原因与执行批次），不作为跳过项：
预算以源码常量上限推导并以单测锁定，B1 压测补齐。
