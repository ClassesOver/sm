# Reporting 模块边界整理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 Reporting Controller 的无锁降级，并将 Workflow Runtime、Reporting Toolkit 和 Delivery Runtime 按职责拆分为同名包，同时保持稳定契约不变。

**Architecture:** 三个旧单文件改为同名包，包级入口导出当前装配需要的稳定符号；能力模块使用 Mixin 机械承载现有实例方法，共享原有 Facade 状态。仓内私有深层导入和 monkeypatch 目标一次迁移，旧文件最终删除，不保留兼容转发空壳。

**Tech Stack:** Python 3.12、pytest、Agno 3.0.0、Pydantic、Ruff、Mypy、PostgreSQL 持久化契约。

## 实施状态（2026-08-26）

- 已提交并推送：Controller 失败关闭、Workflow Runtime、Reporting Toolkit、Delivery Runtime 的职责拆分，以及 Delivery 主题导入归属修正；旧单文件已删除，MR 为 [!10](http://gitlab2.dingyi-china.cn:65080/dingyi-develop-group/agno/smart_reporting/-/merge_requests/10)，目标分支为 `f2`，以避免把 Coding 移除历史带入 Reporting MR。
- 已通过定点验证：报告运行时、标题编号、引用展示、Controller、规划契约、章节并发、工具契约和 Worker 执行测试；相关 Ruff format/lint、Mypy 与旧路径扫描通过。
- 已完成持久化契约收紧：Reporting state、下载授权和产物仓储均在构造时拒绝非 PostgreSQL；SQLite/`aiosqlite` 用例已迁为带 `integration` 标记的 PostgreSQL 测试，默认测试不再启动 SQLite worker。使用隔离库 `reporting_boundary_20260826_102204` 验证 12 个持久化节点通过。
- 仍未完成的仓外门禁：完整 `scripts/check_agentos.sh` 在 `task_execution/tests/test_execution.py` 停滞；该路径不属于本次仅 Reporting 的改动范围，未在本 MR 中扩大处理。

---

## 全局不变量与验证基线

以下内容在四个任务中都不能改变：

- `create_report_agent`、`create_report_runtime`、Controller 的调用签名。
- Workflow ID `enterprise-reporting-workflow-v1`、14 个 step ID、顺序、重试和恢复语义。
- HTTP 路径、错误码、状态键、PostgreSQL schema/table、artifact schema 和 durable state 字段。
- Agno 工具名称、参数 JSON schema、phase/task kind 最小工具集和 callable-tools cache key。
- Reporting Markdown、PDF、DOCX、manifest、下载 URL 和 CLI 退出码。

开始前运行基线：

```bash
.venv-agent/bin/python -m pytest -q
.venv-agent/bin/python -m ruff check smart_reporting
.venv-agent/bin/python -m mypy smart_reporting
```

预期：`760 passed, 1 skipped, 9 deselected`，Ruff 和 Mypy 无错误。

---

### Task 1: 收紧 Workflow Controller 执行锁

**Files:**
- Modify: `smart_reporting/reporting/workflow/controller.py:718-731`
- Test: `smart_reporting/reporting/tests/test_reporting_workflow_controller.py`
- Test: `smart_reporting/reporting/tests/test_reporting_cli.py`

- [ ] **Step 1: 编写缺失执行锁的失败测试**

在 Controller 测试中添加只实现 thread claim/owner/release、但不提供 `workflow_execution_lock` 的最小替身。调用 `start()` 时断言抛出 `AttributeError` 或 `TypeError`，且底层 Workflow 的 `arun` 调用次数仍为 0。其他替身方法复用现有成功 fixture，确保失败原因只来自缺失锁。

- [ ] **Step 2: 运行失败测试确认旧降级**

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_workflow_controller.py::test_controller_fails_closed_when_execution_lock_is_missing -q
```

预期：当前实现因无锁降级而测试失败；若先因替身不完整报错，只补齐替身，不修改生产代码。

- [ ] **Step 3: 删除无锁降级**

将 `_execution_lock` 改为直接调用 `self._thread_ownership.workflow_execution_lock(external_run_id)` 的异步上下文，只保留 `ReportingStateError` 到 `ReportingError` 的转换；删除 `getattr`、`callable` 分支和无锁 `yield`。同步修正测试中只因缺少锁而不符合协议的替身。

- [ ] **Step 4: 运行定点回归**

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_workflow_controller.py smart_reporting/reporting/tests/test_reporting_cli.py -q
```

预期：全部通过，并包含缺失锁失败关闭测试。

- [ ] **Step 5: 静态检查并提交**

```bash
.venv-agent/bin/python -m ruff format --check smart_reporting/reporting/workflow/controller.py smart_reporting/reporting/tests/test_reporting_workflow_controller.py
.venv-agent/bin/python -m ruff check smart_reporting/reporting/workflow/controller.py smart_reporting/reporting/tests/test_reporting_workflow_controller.py smart_reporting/reporting/tests/test_reporting_cli.py
.venv-agent/bin/python -m mypy smart_reporting
git diff --check
git add smart_reporting/reporting/workflow/controller.py smart_reporting/reporting/tests/test_reporting_workflow_controller.py smart_reporting/reporting/tests/test_reporting_cli.py
git commit -m "fix: fail closed when reporting execution lock is unavailable"
```

---

### Task 2: 拆分 Workflow Runtime

**Files:**
- Rename: `smart_reporting/reporting/workflow/runtime.py` -> `smart_reporting/reporting/workflow/runtime/facade.py`
- Create: `smart_reporting/reporting/workflow/runtime/__init__.py`
- Create: `smart_reporting/reporting/workflow/runtime/models.py`
- Create: `smart_reporting/reporting/workflow/runtime/validation.py`
- Create: `smart_reporting/reporting/workflow/runtime/planning.py`
- Create: `smart_reporting/reporting/workflow/runtime/datasets.py`
- Create: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Create: `smart_reporting/reporting/workflow/runtime/sections.py`
- Create: `smart_reporting/reporting/workflow/runtime/publication.py`
- Modify: `smart_reporting/reporting/bootstrap.py`
- Modify: planner、section concurrency、artifact persistence 和 tool contract 测试中的旧导入路径

- [ ] **Step 1: 冻结旧模块导入契约**

记录并测试当前消费者使用的 `ReportWorkflowRuntime`、planner 私有符号、section concurrency 私有符号和 `AnalysisBundle`/`DataUnderstandingPlan`。测试只要求符号从迁移后的实际子模块导入，不要求旧深层路径继续存在。

- [ ] **Step 2: 创建包并迁移叶子模型/校验**

先将仅依赖标准库、Pydantic 和 Reporting domain 的模型、常量、规范化和结构校验函数移入 `models.py`/`validation.py`。能力模块不得运行时导入 `facade.py`；类型标注需要时使用 `TYPE_CHECKING`。Facade 暂时保留原类和方法，只改为显式导入叶子符号。

```bash
.venv-agent/bin/python -c 'from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime; from smart_reporting.reporting.workflow.runtime.models import AnalysisBundle'
```

- [ ] **Step 3: 按阶段提取 Mixin 方法**

按 `planning.py`（请求、来源、范围、指标、提纲、查询）、`datasets.py`（画像、物化、上下文）、`analysis.py`（checkpoint、分析任务、事实）、`sections.py`（WorkItem、章节、返工）和 `publication.py`（渲染、验收、发布、manifest）顺序移动现有方法体，不改变属性名和调用签名。Facade 使用 `RuntimePlanningMixin`、`RuntimeDatasetsMixin`、`RuntimeAnalysisMixin`、`RuntimeSectionsMixin`、`RuntimePublicationMixin` 组合；无法无循环归属的方法暂留 Facade。

- [ ] **Step 4: 更新导入和 monkeypatch 目标**

更新 `bootstrap.py` 及四个测试文件的深层导入到实际子模块，执行：

```bash
rg -n 'workflow\.runtime\.py|from smart_reporting\.reporting\.workflow\.runtime import|import smart_reporting\.reporting\.workflow\.runtime' smart_reporting --glob '*.py'
```

预期：`workflow.runtime` 只作为包入口使用，旧单文件路径没有引用。

- [ ] **Step 5: 删除旧文件并运行定点测试**

确认 `runtime/__init__.py` 存在后删除旧 `workflow/runtime.py`，运行 planner、section concurrency、state、Controller 和 artifact persistence 测试。预期：全部通过，Workflow ID、step ID 和恢复语义不变。

- [ ] **Step 6: 静态检查并提交**

```bash
.venv-agent/bin/python -m ruff format smart_reporting/reporting/workflow/runtime smart_reporting/reporting/bootstrap.py smart_reporting/reporting/tests
.venv-agent/bin/python -m ruff check smart_reporting/reporting/workflow/runtime smart_reporting/reporting/bootstrap.py smart_reporting/reporting/tests
.venv-agent/bin/python -m mypy smart_reporting
git diff --check
git add smart_reporting/reporting/workflow smart_reporting/reporting/bootstrap.py smart_reporting/reporting/tests
git commit -m "refactor: split reporting workflow runtime"
```

---

### Task 3: 拆分 Reporting Toolkit

**Files:**
- Rename: `smart_reporting/reporting/tools.py` -> `smart_reporting/reporting/tools/toolkit.py`
- Create: `smart_reporting/reporting/tools/__init__.py`
- Create: `smart_reporting/reporting/tools/profile.py`
- Create: `smart_reporting/reporting/tools/analysis.py`
- Create: `smart_reporting/reporting/tools/sections.py`
- Create: `smart_reporting/reporting/tools/validation.py`
- Create: `smart_reporting/reporting/tools/factory.py`
- Modify: `smart_reporting/reporting/agent.py`
- Modify: `smart_reporting/task_execution/tests/test_execution.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

- [ ] **Step 1: 冻结工具名称和参数 schema**

在 `test_reporting_tool_contracts.py` 增加快照辅助函数，读取 Toolkit 的同步/异步工具名称和 `parameters`，断言迁移前后完全相等。覆盖 `finish_task`、Profile/context/facts 查询、分析文件写入、分析完成、图表注册和章节渲染。

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py -q
```

- [ ] **Step 2: 迁移纯校验和 Profile 查询**

将 JSON Pointer、schema、路径、证据和预算纯函数移入 `validation.py`；将 Profile/context/facts 查询方法移入 `profile.py`。保持方法名、注册参数和返回值不变，Mixin 不导入 `toolkit.py`。

- [ ] **Step 3: 迁移分析和章节能力**

将分析文件写入、完成提交和 durable evidence 方法移入 `analysis.py`；将图表注册、章节渲染和返工移入 `sections.py`。`toolkit.py` 保留原构造、阶段门禁、Kernel 委托、公共 `_invoke` 和组合类。

- [ ] **Step 4: 迁移工厂并更新消费者**

将 `build_report_worker_tools` 移入 `factory.py`。包入口只稳定导出 `ReportWorkspaceTaskToolkit` 和 `build_report_worker_tools`。更新 `agent.py`、执行层测试和工具契约测试；测试使用的私有符号改从实际能力模块导入。

- [ ] **Step 5: 删除旧文件并验证 schema/cache**

```bash
test -d smart_reporting/reporting/tools
test ! -f smart_reporting/reporting/tools.py
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_worker_execution.py smart_reporting/task_execution/tests/test_execution.py -q
```

预期：工具 schema、阶段最小工具集、callable-tools cache key 和 Toolkit 委托测试全部通过。

- [ ] **Step 6: 静态检查并提交**

```bash
.venv-agent/bin/python -m ruff format smart_reporting/reporting/tools smart_reporting/reporting/agent.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/task_execution/tests/test_execution.py
.venv-agent/bin/python -m ruff check smart_reporting/reporting/tools smart_reporting/reporting/agent.py smart_reporting/reporting/tests smart_reporting/task_execution/tests
.venv-agent/bin/python -m mypy smart_reporting
git diff --check
git add smart_reporting/reporting/tools smart_reporting/reporting/agent.py smart_reporting/reporting/tests smart_reporting/task_execution/tests
git commit -m "refactor: split reporting worker toolkit"
```

---

### Task 4: 拆分 Delivery Runtime

**Files:**
- Rename: `smart_reporting/reporting/delivery/report_runtime.py` -> `smart_reporting/reporting/delivery/report_runtime/runtime.py`
- Create: `smart_reporting/reporting/delivery/report_runtime/__init__.py`
- Create: `smart_reporting/reporting/delivery/report_runtime/markdown.py`
- Create: `smart_reporting/reporting/delivery/report_runtime/pdf.py`
- Create: `smart_reporting/reporting/delivery/report_runtime/docx.py`
- Create: `smart_reporting/reporting/delivery/report_runtime/validation.py`
- Create: `smart_reporting/reporting/delivery/report_runtime/cli.py`
- Modify: `smart_reporting/reporting/workflow/runtime/publication.py`
- Modify: report runtime、heading numbers、citation presentations 和 artifact persistence 测试

- [ ] **Step 1: 冻结渲染和 CLI 契约**

保留现有测试并增加显式断言：Markdown 规范化和 `_pdf_markdown` 输出不变；`DEFAULT_PAGE_LAYOUT`、`REPORT_VISUAL_THEME`、`_WORD_PAGE_FIELDS` 不变；`ReportRuntime.render_markdown`/`validate_pdf` 返回结构不变；CLI 的成功、参数错误和运行失败退出码不变。

- [ ] **Step 2: 迁移叶子渲染和校验函数**

按 `validation.py`（路径、symlink、图片、manifest）、`markdown.py`（规范化、标题、语义文档）、`pdf.py`（渲染、页码、链接、bounds）、`docx.py`（渲染、后处理、结构校验）顺序移动。各模块只依赖更底层模块和标准库，不从 `runtime.py` 反向导入。

- [ ] **Step 3: 迁移 Runtime 和 CLI**

`runtime.py` 只保留 `ReportRuntime` 编排；`ReportFailure` 放在 `validation.py` 并由包入口导出；`cli.py` 保留 `main`，只依赖运行时和输入解析。包入口导出当前 Workflow/CLI 消费的稳定符号。

- [ ] **Step 4: 更新 Workflow 和测试导入**

更新 `workflow/runtime/publication.py` 对 `REPORT_VISUAL_THEME` 的导入，以及测试中的私有符号导入：

```bash
rg -n 'delivery\.report_runtime\.py|from smart_reporting\.reporting\.delivery\.report_runtime import|import smart_reporting\.reporting\.delivery\.report_runtime' smart_reporting --glob '*.py'
```

预期：消费者只指向包入口或实际子模块。

- [ ] **Step 5: 删除旧文件并运行定点测试**

```bash
test -f smart_reporting/reporting/delivery/report_runtime/__init__.py
test ! -f smart_reporting/reporting/delivery/report_runtime.py
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_report_runtime.py smart_reporting/reporting/tests/test_reporting_heading_numbers.py smart_reporting/reporting/tests/test_reporting_citation_presentations.py smart_reporting/reporting/tests/test_report_artifact_persistence.py -q
```

预期：Markdown、PDF、DOCX、manifest 和下载产物测试全部通过。

- [ ] **Step 6: 静态检查并提交**

```bash
.venv-agent/bin/python -m ruff format smart_reporting/reporting/delivery/report_runtime smart_reporting/reporting/workflow/runtime/publication.py smart_reporting/reporting/tests
.venv-agent/bin/python -m ruff check smart_reporting/reporting/delivery/report_runtime smart_reporting/reporting/workflow/runtime/publication.py smart_reporting/reporting/tests
.venv-agent/bin/python -m mypy smart_reporting
git diff --check
git add smart_reporting/reporting/delivery smart_reporting/reporting/workflow/runtime/publication.py smart_reporting/reporting/tests
git commit -m "refactor: split reporting delivery runtime"
```

---

### Task 5: 全局验收和独立 MR

**Files:**
- Verify: `smart_reporting/`
- Verify: `docs/superpowers/specs/2026-08-26-reporting-module-boundaries-design.md`
- Verify: `docs/superpowers/plans/2026-08-26-reporting-module-boundaries.md`

- [ ] **Step 1: 清零旧路径和失效 monkeypatch**

```bash
! rg -n 'smart_reporting/reporting/(workflow/runtime|tools|delivery/report_runtime)\.py|smart_reporting\.reporting\.(workflow\.runtime|tools|delivery\.report_runtime)\.py' smart_reporting pyproject.toml README.md scripts docs --glob '!docs/superpowers/specs/**' --glob '!docs/superpowers/plans/**'
```

预期：旧单文件路径没有生产、测试、配置或部署引用。

- [ ] **Step 2: 运行完整检查**

```bash
bash scripts/check_agentos.sh
```

预期：Ruff format、Ruff lint、Mypy 和默认非 integration pytest 全部通过。

- [ ] **Step 3: 检查差异和提交图**

```bash
git diff --check
git status --short
git diff --stat main...HEAD
git diff --summary main...HEAD
```

预期：只有四阶段重构、对应测试和设计/计划记录；没有 `.env`、日志、PDF、数据库或临时文件。

- [ ] **Step 4: 推送分支并创建独立 MR**

```bash
git push -u origin1 refactor/reporting-module-boundaries -o merge_request.create -o merge_request.target=main -o merge_request.title="refactor: organize reporting module boundaries"
```

预期：GitLab 创建目标为 `main` 的独立 Merge Request，并返回 MR 地址。
