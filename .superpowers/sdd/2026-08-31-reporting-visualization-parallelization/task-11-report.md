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

## Fix Round 2 Re-review

### 修复内容

- 新增 runtime projection 回归断言，直接调用 `_run_analysis_phase` 并从 task runner 的 acceptance contract 检查 `datasetIds`、`authorizedDatasetIds` 与 `datasetSemantics`，不再预注入 `_phase_parameters` 的语义目录。
- durable finalize binding 与 runtime projection 对 Dataset ID 做严格序列校验；`None`、空序列、空字符串和非字符串成员统一拒绝并返回 `report_analysis_dataset_inconsistent`。
- `_finalize_semantic_catalog` 对空 analysis plans、空 Dataset 集合 fail closed，缺失 grain、计划 Dataset 越界和空/冲突指标语义继续拒绝，不再静默生成默认语义。
- 保留模型语义改写保护与全局零图 finalize 拒绝行为。

### 验证

- `/home/junge/pros/chat/.venv-agent/bin/python -m pytest reporting/tests/test_reporting_tool_contracts.py -k 'projected_catalog or zero_charts or ambiguous_facts or inconsistent_dataset_ids or empty_inputs or malformed_durable' -q`
  - 10 passed
- `/home/junge/pros/chat/.venv-agent/bin/python -m pytest reporting/tests/test_reporting_section_concurrency.py -k 'visualization_retry_projects_citation_ids' -q`
  - 1 passed
- `/home/junge/pros/chat/.venv-agent/bin/python -m pytest reporting/tests/test_reporting_agent_projection.py reporting/tests/test_reporting_tool_contracts.py reporting/tests/test_reporting_state.py reporting/tests/test_reporting_section_concurrency.py -q`
  - 373 passed, 9 deselected
- `/home/junge/pros/chat/.venv-agent/bin/ruff format --check ...`
  - 4 files already formatted
- `/home/junge/pros/chat/.venv-agent/bin/ruff check ...`
  - All checks passed
- `git diff --check`
  - 通过

未运行 live CLI、PostgreSQL 或 Mypy；本轮未派发子代理，未使用或 cherry-pick 共享 f2 commit。

## Fix Round 3

### 修复内容

- 在 `_run_analysis_phase` 的可视化 finalize 编排边界校验授权 `dataset_handles`；为空时以 `report_analysis_dataset_inconsistent` fail closed，不构造 finalize contract、不写入 finalize trace，也不启动 finalize Task。
- 新增空授权 Dataset 的 finalize 编排回归测试，断言稳定错误码和 finalize worker 未被调用。
- 更新全局零图测试夹具，提供合法授权 Dataset 与 organization grain，继续验证单章零图允许但全局零图 finalize 拒绝。

### 验证

- `/home/junge/pros/chat/.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_section_concurrency.py -k 'rejects_empty_authorized_datasets_before_finalize' -q`
  - 1 passed
- `/home/junge/pros/chat/.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_section_concurrency.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py -q`
  - 231 passed
- `/home/junge/pros/chat/.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_agent_projection.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_state.py smart_reporting/reporting/tests/test_reporting_section_concurrency.py -q`
  - 374 passed, 9 deselected
- `/home/junge/pros/chat/.venv-agent/bin/ruff format --check smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/tests/test_reporting_section_concurrency.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
  - 3 files already formatted
- `/home/junge/pros/chat/.venv-agent/bin/ruff check smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/tests/test_reporting_section_concurrency.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
  - All checks passed
- `git diff --check`
  - 通过

未运行 live CLI、PostgreSQL 或 Mypy；未派发子代理。
