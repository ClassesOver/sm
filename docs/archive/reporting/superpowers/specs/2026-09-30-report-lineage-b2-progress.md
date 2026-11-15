# Report Editor 数据追溯 B2 进度记录（第三增量：表格正文装配集成完成）

日期：2026-09-30。状态：B2 计划的全部实施项（B2-1~B2-5）已落地；correlations 元数据按 B0 未决清单归 B4。

上游：计划 B2、`2026-09-29-report-lineage-b0-freeze.md`。

## 已完成

| 项 | 实现 | 测试 |
| --- | --- | --- |
| fact 稳定 ID（未决#3 关闭） | 四类确定性条目增 `factId`（`fact-` + 16hex，内容寻址：dataset sha256 + field_ref + aggregation + scope + 期间）；`build_deterministic_analysis_bundle` 出口统一 `assign_fact_ids`，幂等、bundle 内唯一；旧 bundle 兼容 | `test_trace_fact_service.py` 9 例 |
| bundle 事实索引 | `trace/fact_index.py`：`fact_pointer`、`fact_input_relations`（派生/比较/对账 → metric facts，按权威 code 匹配） | 同上 |
| FactRef 查询/展开服务 | `trace/fact_service.py`：`resolve_fact`（analysisId 不一致/指针越界/factKey 漂移 → `fact_binding_unavailable`）、`expand_fact_tree`（深度≤3、节点≤50，环短路） | 同上 |
| claim 绑定 | `SectionClaimSubmission.fact_ids` + `SectionClaim.fact_ids`（可选、去重校验）；claim 冻结透传 | 既有 claim 流程回归 |
| 发布门禁核对 | claim.factIds 未知 → `report_claim_fact_unknown` 硬失败；数值容差外 → `report_claim_fact_value_mismatch` 软告警；无 factIds 旧 claim 跳过 | `test_trace_claim_gate.py` 3 例 |
| **索引登记事实文件（B2-g）** | `build_csv_trace_index` 增 `fact_files`（analysisId → ArtifactFile，application/json）；finalize 把 `checkpoint.deterministic_fact_files` 登记进索引并经权威 manifest 发布 | `test_trace_index_builder.py` + 集成 |
| **Editor fact API（B2-h）** | `GET /api/facts`（分析清单）、`GET /api/facts/{analysis_id}/{fact_id}`（fact 详情 + 一层输入）：bundle 从索引冻结文件读取并复核 sha256，factId 在四类数组唯一定位 | `test_report_editor_trace.py` 16 例（含 HTTP） |
| **表格绑定生成器核心（B2-3 部分）** | `trace/table_builder.py`：从 bundle 按规格生成冻结行列键的 `TableTraceV1` + 带 `[[table:id]]` 协议块的 Markdown；单元格逐格绑定 FactRef（factId + JSON Pointer）；歧义指标（同 code 多 fact）、rowKey 重复、期间不匹配、未知列全部拒绝；生成的 trace 通过 `RevisionTraceIndexV1` 全局引用校验 | `test_trace_table_builder.py` 4 例 |

验证：B2 受影响面 18 个测试文件 218 passed（2026-09-30）。

## 第三增量：表格正文装配集成（2026-09-30 完成）

| 项 | 实现 | 测试 |
| --- | --- | --- |
| 装配器协议扩展 | `draft_v1.ReportServerTable`：服务端表格契约（单个成对 `[[table:id]]` 协议块、禁止其他协议标记与图片语法、校验器强制）；`assemble_report_markdown` 新增 `server_tables` 参数，表格在章节全部模型 blocks 渲染完成后追加；tableId 唯一、章节必须已注册；**模型提交路径不变**——`validate_report_body_markdown` 继续拒绝正文中的 table 协议标记 | `test_trace_server_tables.py` 9 例 |
| 自动出表规则 | `build_analysis_table`：列 = 权威 code 唯一对应的 metric fact（歧义跳过）；行 = periodValues 期间并集（冻结顺序）；无可用指标或无分期间值 → 不生成表；`tableId=table-{analysisId}`；渲染器修复数据行与表头列数错位 bug 并增加单元格数校验 | 同上 |
| finalize 接入 | `RuntimeSectionsMixin._build_server_tables`：从 `checkpoint.deterministic_fact_files` 读 bundle（身份复核）→ 生成表格 → 分配到第一个引用该 analysis 的批准章节；bundle 不可读/生成失败按软告警跳过（不阻断发布）；`TableTraceV1` 随索引登记（`build_csv_trace_index` 新增 `server_table_traces`），单元格 FactRef 指向真实 fact 文件资源 | 同上（含未分配章节跳过用例） |

验证：B2 受影响面 21 个测试文件 288 passed（2026-09-30，含 `test_report_runtime.py` 渲染回归）。

## G2 门禁对照（计划 B2）

| G2 条件 | 状态 |
| --- | --- |
| 每类确定性事实均能由正文/单元格精确定位并回到全部输入 CSV | 服务端侧完成：factId → JSON Pointer → dataset 身份链全程校验（`test_trace_fact_service.py`、`test_trace_table_builder.py`）；模型 claim→fact 绑定通过门禁硬核对。**模型实际提交 factIds 的端到端运行**依赖真实工作流跑批，随 G9 全链路验收 |
| 无错误有效绑定 | 未知 factId 硬失败、位置漂移拒绝、歧义指标拒绝装配、游标/快照身份绑定（各自反例测试覆盖） |
| 目标新生成对象达到 B0 冻结的覆盖清单 | 服务端生成的结构化表格（分期间指标表）完整绑定；模型直写表格按计划显示"未绑定"。覆盖清单执行率随真实报告跑批统计（B2 剩余项，见下） |

## B2 剩余（不阻塞 B3 启动，随真实跑批/G9 闭环）

1. **真实报告跑批验证**：服务端表格出现在真实报告正文的端到端跑批（当前为单测级 verify，finalize 全流程冒烟随 G9）。
2. **claim 数值匹配强化**：期间/单位/范围核对（当前核 factId 存在性 + 数值容差）。
3. **correlations 元数据补齐**：n、字段身份、稳定 ID（B0 未决清单归 B4 计算记录）。

## 设计决定（如实记录）

- factId 不含数值本身：身份锚是"哪个快照（dataset sha256）+ 哪个字段/范围"；数值变化必然伴随快照身份变化产生新 ID。
- 门禁数值核对容差：`max(0.01, |expected| × 1e-9)`；claim.value 非 float 跳过数值核对，只核 factId 存在性。
- claim.factIds 为空 = 旧路径完全兼容。
- 表格歧义拒绝：同一 metric code 对应多条 fact（多数据集/多范围）时表格装配拒绝而非猜测——符合"没有歧义才建立有效绑定"（计划 B2-1）。
- fact API 以 (analysisId, factId) 为不透明资源引用，不向客户端暴露 JSON Pointer 或文件路径。
- 服务端表格走装配器参数通道而非模型 block：模型协议零改动，`ReportServerTable` 契约限制表格只能是单个成对协议块；现有报告（无分期间值或无 metric code 的 bundle）不生成表格，正文不变。
