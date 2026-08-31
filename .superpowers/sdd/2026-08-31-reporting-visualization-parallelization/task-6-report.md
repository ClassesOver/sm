# Task 6 实施报告

## 状态

已完成 `submit_visualization_charts` 章节图表提交终态工具与定点测试。

## 实施内容

- 在 `smart_reporting/reporting/tools/sections.py` 新增异步 `submit_visualization_charts` 方法。
- 通过 `_require_phase_tool` 仅允许 `analysis` 阶段的 `visualization_section` Task 调用。
- 校验 `sectionCode` 与当前章节 phase contract 一致，允许 `charts=[]`。
- 复用 `ReportChartRegistration`、`_require_chart_output_path` 和 `_inspect_chart_file`，不重复实现图表或文件校验。
- 将 inspection 产生的实际 `path`、`size`、`sha256` 写入 reducer 所需的 `files` FileIdentity 列表。
- 使用 durable state 的 `revision`、章节代码和 charts/files digest 生成确定性 `viz-section:{revision}:{sectionCode}:{digest}` commandId。
- 成功返回 `committed`、章节代码和图表数量；校验失败统一返回 `_failure` 回执。

## 验证

- `/home/junge/pros/chat/.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py -k "submit_visualization or register_report_charts" -q`
  - `17 passed, 134 deselected`
  - 存在依赖库既有的 15 条弃用警告（`imghdr`、PyParsing），与本次改动无关。
- `/home/junge/pros/chat/.venv-agent/bin/ruff format smart_reporting/reporting/tools/sections.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
  - 通过，格式化 1 个文件。
- `/home/junge/pros/chat/.venv-agent/bin/ruff check smart_reporting/reporting/tools/sections.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
  - 通过。
- `git diff --check`
  - 通过。

## Concerns

- 未运行完整测试套件；本任务变更已按简报运行 `submit_visualization` 与既有 `register_report_charts` 相关定点回归。
- 未运行 PostgreSQL 集成测试；本任务仅修改工具方法和契约单元测试。
