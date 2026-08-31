# Task 11 评审修复报告

## 修复内容

- 语义目录的 Dataset 集合改为从 durable `analysisItems` 的 evidence `datasetIds` 投影；phase contract 的 `datasetIds` 与 `datasetSemantics` 必须精确覆盖该集合。
- 保留 `authorizedDatasetIds` 作为授权 Dataset snapshot，并在 finalize 时校验 evidence Dataset 不得越权或与 contract 不一致。
- `_finalize_semantic_catalog` 对缺失或空 `organizationGrain`、计划 Dataset 不一致、指标 formula/unit/期间缺失或冲突统一以 `report_analysis_semantic_invalid` fail closed，不再使用 `record`、`None` 或未声明期间默认值。
- finalize 成功测试改为从 durable analysis plan、analysis item 和 deterministic facts 构造受信 contract 字段，继续断言模型提交的目录改写会被服务端投影覆盖。
- 保留并验证全局零图 finalize 拒绝测试。

## 验证

- `/home/junge/pros/chat/.venv-agent/bin/python -m pytest reporting/tests/test_reporting_tool_contracts.py -k 'projected_catalog or zero_charts or ambiguous_facts' -q`
  - 3 passed
- `/home/junge/pros/chat/.venv-agent/bin/python -m pytest reporting/tests/test_reporting_agent_projection.py reporting/tests/test_reporting_tool_contracts.py reporting/tests/test_reporting_state.py reporting/tests/test_reporting_section_concurrency.py -q`
  - 366 passed, 9 deselected
- `/home/junge/pros/chat/.venv-agent/bin/ruff format reporting/workflow/runtime/analysis.py reporting/tools/analysis.py reporting/tests/test_reporting_tool_contracts.py`
  - 2 files reformatted
- `/home/junge/pros/chat/.venv-agent/bin/ruff check reporting/workflow/runtime/analysis.py reporting/tools/analysis.py reporting/tests/test_reporting_tool_contracts.py`
  - All checks passed
- `git diff --check`
  - 通过

未运行 live CLI 或 PostgreSQL，符合本次任务约束。
