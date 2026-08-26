# 移除 Coding 产品入口实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除纯 Coding 产品入口，同时保持 Reporting 依赖的任务执行底座及其回归测试完整。

**Architecture:** `smart_reporting/coding/` 不再作为产品包存在；其下实际归属于共享执行底座的测试迁入 `smart_reporting/task_execution/tests/`。Reporting 继续使用现有 `task_execution` API、数据库 schema 和内部协议名，本轮不做持久化迁移。

**Tech Stack:** Python 3.12、pytest、FastAPI、Agno 3.0.0、SQLAlchemy、Ruff、Mypy

---

### Task 1: 迁移共享执行测试所有权

**Files:**
- Move: `smart_reporting/coding/tests/workspace_fakes.py` -> `smart_reporting/task_execution/tests/workspace_fakes.py`
- Move: `smart_reporting/coding/tests/test_coding_acceptance.py` -> `smart_reporting/task_execution/tests/test_acceptance.py`
- Move: `smart_reporting/coding/tests/test_coding_daytona.py` -> `smart_reporting/task_execution/tests/test_daytona.py`
- Move: `smart_reporting/coding/tests/test_coding_execution.py` -> `smart_reporting/task_execution/tests/test_execution.py`
- Move: `smart_reporting/coding/tests/test_coding_repository.py` -> `smart_reporting/task_execution/tests/test_repository_execution.py`
- Move: `smart_reporting/coding/tests/test_coding_repository_v2.py` -> `smart_reporting/task_execution/tests/test_repository.py`
- Move: `smart_reporting/coding/tests/test_coding_session.py` -> `smart_reporting/task_execution/tests/test_session.py`
- Delete: `smart_reporting/coding/tests/test_coding_tools.py`
- Create: `smart_reporting/task_execution/tests/__init__.py`

- [x] **Step 1: 移动测试文件并修正包引用**

将 `CodingScope`、`Lease`、`CodingEvent` 等共享类型改从 `smart_reporting.task_execution` 或其 `models` 导入；将 fake 引用改为 `smart_reporting.task_execution.tests.workspace_fakes`；将 `CODING_FINISH_FAILURE_STATE_KEY` 改从 `task_execution.execution` 导入。

- [x] **Step 2: 删除纯 Coding Toolkit 测试**

删除 `test_coding_tools.py` 整个文件。该文件覆盖已废弃的 `CodingToolkit`/`HermesCodingToolkit` 和 Coding Facade，Reporting 生产路径不使用这些实现；共享的受控执行、补丁、命令策略和输出句柄测试保留在迁移后的 `test_execution.py`。

- [x] **Step 3: 运行迁移后的定点测试**

Run:

```bash
.venv-agent/bin/python -m pytest \
  smart_reporting/task_execution/tests/test_acceptance.py \
  smart_reporting/task_execution/tests/test_repository.py \
  smart_reporting/task_execution/tests/test_session.py -q
```

Expected: 所有用例通过，且测试收集不导入 `smart_reporting.coding`。

### Task 2: 删除 Coding 产品包和专属契约

**Files:**
- Delete: `smart_reporting/coding/`
- Delete: `smart_reporting/instructions.py`
- Modify: `smart_reporting/agent_control.py`
- Modify: `smart_reporting/tests/test_contract.py`

- [x] **Step 1: 添加边界失败检查**

先运行以下扫描，确认删除前仍能发现 Coding 产品引用：

```bash
rg -n 'smart_reporting\.coding|smart_reporting/coding|smart_reporting\.coding\.cli' \
  smart_reporting pyproject.toml README.md docs scripts
```

Expected: 扫描命中现有 Coding 包、测试配置和 README 入口。

- [x] **Step 2: 删除纯 Coding 包与孤立指令**

删除剩余 `smart_reporting/coding/`；删除仅由该包消费的 `smart_reporting/instructions.py`；从 `agent_control.py` 删除仅构造 `WorkspaceCodingToolkit` 的 `build_coding_agent_tools`，保留 Reporting 使用的计划状态契约。

- [x] **Step 3: 删除顶层契约测试中的纯 Coding 断言**

从 `smart_reporting/tests/test_contract.py` 删除 `smart_reporting.instructions` 导入和 `test_pure_coding_agent_batches_only_independent_reads`，保留 Reporting AgentOS 契约测试。

- [x] **Step 4: 验证包独立导入**

Run:

```bash
.venv-agent/bin/python -c 'import smart_reporting.reporting.agent; import smart_reporting.reporting.bootstrap; import smart_reporting.task_execution'
```

Expected: 退出码为 0。

### Task 3: 删除失效配置和文档入口

**Files:**
- Modify: `pyproject.toml`
- Modify: `smart_reporting/settings.py`
- Modify: `smart_reporting/tests/test_settings.py`
- Modify: `.env.example`
- Modify: `smart_reporting/.env.example`
- Modify: `smart_reporting/README.md`

- [x] **Step 1: 更新 pytest 收集路径**

把 `smart_reporting/coding/tests` 替换为 `smart_reporting/task_execution/tests`。

- [x] **Step 2: 删除纯 Coding 配置字段**

删除 `AgentSettings` 的 `coding_temperature`、`coding_enable_thinking`、`coding_reasoning_effort`、`coding_thinking_budget` 及 `_coding_reasoning_effort`。保留 Reporting 实际消费的 `report_coding_*` 配置。

- [x] **Step 3: 同步测试和示例配置**

删除 `AGENT_CODING_*` 示例、README 表项和相应设置测试；收窄参数化测试，使其只覆盖 `AGENT_REPORT_CODING_*` 与 planner 配置。

- [x] **Step 4: 运行配置定点测试**

Run:

```bash
.venv-agent/bin/python -m pytest smart_reporting/tests/test_settings.py -q
```

Expected: 所有设置测试通过。

### Task 4: 全面验证并检查最终差异

**Files:**
- Verify: `smart_reporting/`
- Verify: `pyproject.toml`
- Verify: `.env.example`
- Verify: `smart_reporting/.env.example`
- Verify: `smart_reporting/README.md`

- [x] **Step 1: 验证旧产品路径清零**

Run:

```bash
test ! -d smart_reporting/coding
! rg -n 'smart_reporting\.coding|smart_reporting/coding|python -m smart_reporting\.coding\.cli' \
  smart_reporting pyproject.toml README.md scripts
```

Expected: 两条命令退出码均为 0。

- [x] **Step 2: 运行定点 Reporting 和执行层回归**

Run:

```bash
.venv-agent/bin/python -m pytest \
  smart_reporting/task_execution/tests \
  smart_reporting/reporting/tests/test_reporting_tool_contracts.py \
  smart_reporting/reporting/tests/test_reporting_worker_execution.py \
  smart_reporting/tests/test_application.py \
  smart_reporting/tests/test_contract.py -q
```

Expected: 所有非 integration 用例通过。

- [ ] **Step 3: 运行静态检查和完整非集成回归**

Run:

```bash
bash scripts/check_agentos.sh
```

Expected: Ruff format、Ruff lint、Mypy 和默认非 integration pytest 全部通过。

Actual: 脚本在 Ruff format 阶段被本次未修改的
`smart_reporting/tests/test_reporting_compose.py` 既有格式差异阻断；未顺带格式化该无关文件。
Ruff lint、Mypy 和默认 pytest 已分别执行并通过。

- [x] **Step 4: 检查差异边界**

Run:

```bash
git diff --check
git status --short
git diff --stat HEAD~1..HEAD
```

Expected: 没有空白错误、临时产物或与 Coding 产品移除无关的改动。
