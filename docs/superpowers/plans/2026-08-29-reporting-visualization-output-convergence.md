# Reporting Visualization Output Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 防止 visualization 模型在单轮纯文本规划中耗尽输出额度，同时为复杂图表脚本保留 64K 生成空间。

**Architecture:** 保留现有 Reporting Worker、工具白名单和生命周期门禁。仅在受信 `reportingTaskKind=visualization` 的模型调用边界覆盖 Agno 公共 `tool_choice` 为 `required`，并把该阶段的单请求输出上限提高到 64K；analysis item、section 和 facade 行为不变。

**Tech Stack:** Python 3.12、Agno 3.0.0、pytest、Ruff、Mypy。

---

### Task 1: 锁定模型请求契约

**Files:**
- Modify: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`

- [x] 将 visualization 阶段输出上限期望改为 `65_536`。
- [x] 增加异步流式模型边界测试，断言调用方传入 `auto` 时只有 visualization 被覆盖为 `required`，analysis item 和 section 仍为 `auto`。
- [x] 使用 `.venv-agent/bin/pytest` 运行两个定点节点，确认新断言因旧行为失败。

### Task 2: 最小实现与配置同步

**Files:**
- Modify: `smart_reporting/reporting/agent.py`
- Modify: `.env.example`
- Local only: `.env`

- [x] 把 `_REPORT_VISUALIZATION_OUTPUT_TOKEN_LIMIT` 提高到 `64 * 1024`。
- [x] 在 `ReportingOpenAIChat` 四种响应入口共用的参数规范化函数中，仅为 visualization 设置 `tool_choice="required"`。
- [x] 将示例配置和本机非提交配置的 `AGENT_REPORT_OUTPUT_TOKEN_RESERVE` 提高到 `65536`。
- [x] 重跑定点测试，确认新契约通过且既有阶段隔离不变。

### Task 3: 静态检查与回归

**Files:**
- Verify: `smart_reporting/reporting/agent.py`
- Verify: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`

- [x] 对改动 Python 文件运行 Ruff format check 和 Ruff lint。
- [x] 运行 `test_reporting_agent_projection.py` 与 `test_reporting_worker_execution.py`。
- [x] 对改动实现运行必要的 Mypy，并区分新增错误与既有错误。
- [x] 检查最终 diff，确认没有覆盖工作树原有修改或加入运行产物。

### Task 4: 真实日志复现与输入收敛修复

**Files:**
- Runtime output only: `/tmp/reporting_cli_<timestamp>/`

- [x] 从中止的真实 CLI 日志确认 64K 与 `tool_choice=required` 已生效，并定位 Skill 重读循环由 visualization 错套 analysis 128K 输入硬上限触发。
- [x] 增加任务级输入上限回归：analysis item 保持 128K、section 保持 48K，visualization 使用 Reporting 已配置输入预算。
- [x] 按用户要求不再运行真实 CLI；以定点 pytest、相关回归、Ruff、Mypy 差异和最终代码审查完成验收。
