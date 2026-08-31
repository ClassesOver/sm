# Task 11 实施报告

## 状态

已完成 Task 11，并提交 commit `feat: 汇总 worker 语义目录受信投影与全局收口回归`。

## 实际改动

- 在 `runtime/analysis.py` 增加 `_finalize_semantic_catalog`，从冻结 `analysisPlans`、已验身份的 deterministic fact bundles 和授权 Dataset 顺序投影紧凑的 `datasetSemantics` 与 `metricDefinitions`。
- 汇总 worker instruction 增加完整 `analysisPlans`，并将语义目录和 `chartRegistrationRules` 作为同一份服务端投影注入 instruction 与 acceptance contract。
- 对 facts 覆盖范围增加显式校验，缺少冻结 analysis facts 时失败关闭。
- 增加 finalize 语义提交测试，确认模型传入的语义会被 acceptance contract 的投影值覆盖，并精确覆盖 evidence Dataset。
- 增加全局零图 finalize 测试，确认空图表在读取 phase contract 前返回 `report_visualization_charts_not_registered`。
- 同步既有可视化 instruction 测试对新增 `organizationGrain` 字段的字面期望。

## 验证

- focused pytest：2 passed。
- 指定回归 pytest：364 passed，9 deselected。
- `ruff check reporting/`：通过。
- changed-file `ruff format --check`：通过。
- `git diff --check`：通过。
- mypy：本次 `analysis.py` 新增错误已清零；命令仍报告仓库既有 `reporting/delivery/report_runtime/docx.py` 和 `reporting/phase.py` 类型错误。

## 未执行

- 未执行真实 Reporting CLI 验收；该步骤属于简报标注的提交单元之外，且需要外部运行依赖和真实数据源。

## 风险与关注

- 全仓 `ruff format --check reporting/` 仍会报告未改动的 `reporting/tests/test_reporting_state.py` 需要格式化，本任务未修改该无关文件。
- 当前工作区未执行真实 PDF 产物验证。

## Round 2 修复

- 增加真实 `_run_analysis_phase` runtime 路径断言，确认 acceptance contract 的 `datasetSemantics` 和 `metricDefinitions` 来自 durable analysis item 与 deterministic facts 投影，而不是 `_phase_parameters` 注入。
- runtime projection 与 finalize durable binding 均在迭代前校验 `datasetIds` 为非字符串、非空、全部为字符串的序列；`None`、整数和含非字符串成员的列表统一返回 `report_analysis_dataset_inconsistent`。
- `_finalize_semantic_catalog` 在无分析计划、无 Dataset、缺少 facts 或计划 Dataset 越权时失败关闭，并保留模型语义覆盖保护与全局零图提前拒绝行为。

## Round 2 验证

- 定点 pytest：新增及直接相关用例 `10 passed`（runtime projection、semantic catalog、durable finalize binding）。
- changed-file Ruff format 与 Ruff check：通过。
- 未执行完整 Reporting CLI、真实 PDF 和全量回归；这些仍需要外部运行依赖或超出本轮 Task 11 定点范围。
