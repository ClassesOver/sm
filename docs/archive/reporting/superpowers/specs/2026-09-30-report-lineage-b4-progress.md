# Report Editor 数据追溯 B4 进度记录（第二增量）

日期：2026-09-30。状态：B4 计划实施项主体落地（计算记录链 + correlations 元数据 + Editor 计算链 API）；复算任务与真实跑批随 G9。

上游：计划 B4、`2026-09-29-report-lineage-b0-freeze.md`。

## 已完成

| 项 | 实现 | 测试 |
| --- | --- | --- |
| 执行环境指纹（未决#8 关闭） | `ExecutionReceipt.environment`（Python 版本、平台、polars/pandas/numpy/scipy/statsmodels/scikit-learn 版本，逐项容错）；`run_script` 签发回执时捕获；旧回执无字段 → reproducibility=limited | `test_trace_computation_service.py` 11 例 |
| ComputationRecordV1 构造 | `trace/computation_service.py build_supplemental_computation_record`：服务端从 script/evidence 身份 + ExecutionReceipt + 计划 requirements 构造（computationId 内容寻址、输出指向 findings 行、verification=not_checked、environment 缺失 → limited）；finding_count=0 时锚定 findings 数组本身不伪造数值 | 同上 |
| 补充分析链路接入 | `complete_analysis_item`：服务端在 durable payload 写入 `computationRecord` + `computationScriptFile`（模型不参与构造）；无执行回执或无补充 evidence 时返回 None 不伪造；`AnalysisEvidence` 增可选字段透传（旧 payload 兼容） | 同上（含跳过反例） |
| finalize 提取入索引 | 从 `checkpoint.evidence_manifest.evidence` 提取记录（无效记录软告警跳过）；`detect_computation_cycles` 检测到环 → `report_computation_cycle_invalid` 硬失败；script/evidence 文件进索引 files，evidence（json）同时登记为 `supplemental_evidence` 类事实条目使 outputFactRefs 通过契约一致性校验 | 同上 + 索引登记测试 |
| 依赖展开与循环检测 | `expand_computation_chain`（output→input 沿链展开，深度/节点 B0 预算、环短路、未知入口 source_missing）；`detect_computation_cycles`（自环与多节点环、canonical 去重） | 同上（三层链展开、深度截断、环检测） |

验证：B4 受影响面 24 个测试文件 408 passed（2026-09-30，含 code_agent batches 回归）。

## 第二增量：correlations 元数据 + Editor 计算链 API（2026-09-30 完成）

| 项 | 实现 | 测试 |
| --- | --- | --- |
| correlations 元数据（B0 未决清单关闭） | `CorrelationDetail`（datasetId+sha256、leftField/rightField、method=pearson、sampleCount、value、factId）；`_correlations` 同时产出旧键值投影（模型兼容）与新元数据数组；factId 分配与 `/correlationDetails/{i}` 指针定位 | `test_trace_computation_service.py`（样本量/字段身份/指针定位） |
| Editor 计算链 API | `GET /api/computations`（清单：method/executionId/verification/reproducibility/输入输出计数）、`GET /api/computations/{id}`（详情：parameters、environment、limitations、outputFactRefs 指针、script 身份（不返回路径）、依赖链展开 depth 参数）；未知 ID → 404 | `test_report_editor_trace.py` 21 例（含 HTTP） |
| 索引登记容错 | computation_files 同时接受 FileIdentity 与 dict 形态 | 同上 |

验证：B4 受影响面 24 个测试文件 411 passed（2026-09-30）。

## B4 剩余（随 G9 闭环）

1. **复算受控验证任务**（计划 B4-5）：复算作为独立任务形成新记录，不覆盖历史——需要真实执行环境联调。
2. **确定性多步 facts 的显式 ComputationRecord**：贡献分解等确定性多步计算目前走 bundle input relations（B2 的 fact_input_relations 已覆盖依赖展开），升级为显式记录待真实跑批评估收益。
3. **真实跑批验证**：补充分析全流程的计算记录端到端（当前单测/集成级）。

## 设计决定（如实记录）

- 计算记录只由服务端构造（计划 3.4）；模型不提交来源、hash、路径。
- 补证 evidence 在索引中登记为 `supplemental_evidence` 类事实条目（`FactFileContentKindV1` 预留枚举），与 deterministic bundle 并列，FactRef 解析层按 contentKind 区分。
- 循环依赖是发布阻断项（计划 5.3"拒绝循环依赖"），无效记录本身软告警（旧数据兼容）。
- 环境指纹缺失 → reproducibility=limited（未决#8 倾向落实），不因保存了脚本就声称可重现。
