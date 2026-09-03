# Reporting Worker Patch Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用单一 unified diff 工具稳定完成 Reporting 分析脚本修改，并阻止图表检查回执引用已变化的文件。

**Architecture:** 复用现有 Reporting durable write intent、WorkspaceService 路径/边界校验和 Daytona 文件 API。Patch 在临时副本内由 `git apply` 校验/应用，成功后调用现有原子 Workspace mutation；图表提交仅增加检查回执 SHA 的当前文件核对。

**Tech Stack:** Python 3.12、FastAPI/Agno 3.0.1、Daytona WorkspaceService、标准 unified diff、pytest、Ruff。

---

### Task 1: 验证基线并锁定工具契约

**Files:**
- Modify: `smart_reporting/reporting/tools/validation.py`
- Modify: `smart_reporting/reporting/tools/capabilities.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Modify: `smart_reporting/reporting/phase.py`
- Test: `smart_reporting/reporting/tests/test_reporting_worker_execution.py`
- Test: `smart_reporting/reporting/tests/test_reporting_planner_contracts.py`

- [ ] 写工具面失败测试：两个旧工具不存在，`apply_analysis_patch` 在分析项和图表章节可见。
- [ ] 运行定点测试确认因旧契约仍存在而失败。
- [ ] 添加 patch schema（path、patch、expected_sha256 基线映射/约束）并更新能力矩阵、注册描述和阶段工具名单。
- [ ] 更新 Reporting 指令中旧工具名称为统一 patch 流程。
- [ ] 运行定点测试确认工具面通过。

### Task 2: 实现 unified diff 解析与 Git 能力探测

**Files:**
- Modify: `smart_reporting/task_execution/changes.py`
- Modify: `smart_reporting/task_execution/execution.py`
- Test: `smart_reporting/task_execution/tests/test_repository_execution.py`
- Test: `smart_reporting/reporting/tests/test_analysis_item_workflow.py`

- [ ] 先添加修改、新建、删除、冲突和绝对路径拒绝测试。
- [ ] 运行测试确认失败。
- [ ] 使用 `git apply --check` / `git apply` 在临时副本执行；禁止初始化用户工作区 Git 仓库。
- [ ] 保留现有 WorkspaceService 路径、大小、文件数量和 UTF-8 边界校验；Git 不可用时失败关闭。
- [ ] 运行 patch 内核定点测试确认通过。

### Task 3: 迁移 Reporting 写入流程与幂等恢复

**Files:**
- Modify: `smart_reporting/reporting/tools/analysis.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py`
- Modify: `smart_reporting/reporting/instructions.py`
- Test: `smart_reporting/reporting/tests/test_analysis_item_workflow.py`
- Test: `smart_reporting/reporting/tests/test_reporting_planner_contracts.py`

- [ ] 添加 patch 后返回 before/after artifacts、冲突不落盘和相同意图重放测试。
- [ ] 运行测试确认失败。
- [ ] 将 `_write_analysis_file` 合并为 `apply_analysis_patch` 入口，保留 durable intent、Python 语法预检和目标路径约束。
- [ ] 删除旧入口、旧 schema、旧 workflow 参数和无效导入/指令。
- [ ] 运行 Reporting 写入定点测试确认通过。

### Task 4: 选择性强化图表检查回执

**Files:**
- Modify: `smart_reporting/reporting/workspace.py`
- Modify: `smart_reporting/reporting/tools/sections.py`
- Test: `smart_reporting/reporting/tests/test_reporting_worker_execution.py`
- Test: `smart_reporting/reporting/tests/test_reporting_state.py`

- [ ] 添加图表文件变化后旧 inspect 回执拒绝、当前 SHA 回执提交成功测试。
- [ ] 运行测试确认失败。
- [ ] 在 inspect 回执中保留检查时 SHA，并在 submit 前重新计算并比较。
- [ ] 不引入通用 read/query revision 或新的终态门禁。
- [ ] 运行图表链路定点测试确认通过。

### Task 5: 格式、静态检查与最终验证

**Files:**
- Modify: only files from Tasks 1-4

- [ ] 运行 `uv run pytest` 对改动相关测试。
- [ ] 运行 `uv run ruff format --check` 与 `uv run ruff check`。
- [ ] 必要时运行 `uv run mypy` 对实现文件。
- [ ] 运行 `git diff --check`，检查工具面、旧名称检索和工作区状态。
- [ ] 汇总实际通过项、未执行项及环境限制。
