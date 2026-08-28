# Reporting Visualization Complete Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不压缩预算、不改变 Python 图表脚本架构的前提下，让 visualization facts 与合法签发脚本一次完整进入模型上下文。

**Architecture:** 底层 bounded tool result 接受调用方显式预览上限，默认行为不变；Reporting 只在 visualization facts 和已通过路径门禁的签发脚本读取上选择更大窗口。写入预检对 visualization 签发脚本的最终候选内容执行 64 KiB 失败关闭校验。

**Tech Stack:** Python 3.12、Agno 3.0.0、JMESPath、pytest、Ruff、Mypy。

---

### Task 1: Visualization Facts 完整窗口

**Files:**
- Modify: `smart_reporting/reporting/tools/profile.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Modify: `smart_reporting/task_execution/execution.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

- [ ] 添加回归测试：约 40 KiB 的 visualization 聚合结果不降低 `maxItems`、不截断；相同单项 analysis 查询仍保持 16 KiB。
- [ ] 运行定点测试并确认因当前 16 KiB 上限失败。
- [ ] 为 bounded result 增加显式预览上限，并仅在 visualization facts 使用 128 KiB。
- [ ] 重跑定点测试确认通过。

### Task 2: 签发脚本一次读取与写入上限

**Files:**
- Modify: `smart_reporting/reporting/tools/analysis.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Modify: `smart_reporting/task_execution/execution.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
- Test: `smart_reporting/task_execution/tests/test_execution.py`

- [ ] 添加回归测试：40 KiB visualization 签发脚本完整展示；普通 Reporting 结果仍按 16 KiB 截断。
- [ ] 添加回归测试：超过 64 KiB 的签发脚本在 mutation 前返回 `report_visualization_script_too_large`。
- [ ] 运行测试确认当前分别被截断和错误接受。
- [ ] 只为已通过 visualization 路径门禁的 `read_file` 选择 64 KiB 预览，并在 Python 写入预检校验最终候选脚本。
- [ ] 重跑定点测试确认通过。

### Task 3: 指令、回归与静态检查

**Files:**
- Modify: `smart_reporting/reporting/instructions.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Test: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`

- [ ] 更新 visualization 指令：默认一次聚合读取，完整脚本不得分段重读；`outputTruncated=false` 不调用 `read_tool_output`。
- [ ] 使用 `.venv-agent` 运行相关 Reporting 与 task execution 定点 pytest。
- [ ] 对改动 Python 文件运行 Ruff format check、Ruff lint 和必要 Mypy。
- [ ] 运行 `git diff --check`，复核预算常量、HTTP API、数据库和纯 Coding Agent 行为均未改变。
