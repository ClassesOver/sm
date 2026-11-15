# Smart Reporting Directory Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按职责迁移 smart_reporting 顶层模块，保持业务行为、公共协议和部署入口不变。

**Architecture:** 将运行时装配、HTTP 安全边界和外部集成分别归入 `runtime/`、`http/`、`integrations/` 子包；保留 `app.py` 作为稳定 FastAPI 入口，以及跨业务共享的基础设施模块。迁移采用一次性路径更新，不保留旧路径兼容壳。

**Tech Stack:** Python 3.12、FastAPI、Agno、pytest、Ruff、Mypy、uv。

---

### Task 1: 创建职责子包并迁移运行时模块

**Files:**
- Create: `smart_reporting/runtime/__init__.py`
- Rename: `smart_reporting/application.py` → `smart_reporting/runtime/application.py`
- Rename: `smart_reporting/execution_context.py` → `smart_reporting/runtime/execution.py`
- Rename: `smart_reporting/settings.py` → `smart_reporting/runtime/settings.py`
- Rename: `smart_reporting/database.py` → `smart_reporting/runtime/database.py`
- Rename: `smart_reporting/logging_config.py` → `smart_reporting/runtime/logging.py`
- Rename: `smart_reporting/observability.py` → `smart_reporting/runtime/observability.py`
- Modify: all Python imports, tests, Docker/scripts/docs referring to these paths

- [ ] **Step 1: 创建 `runtime/__init__.py`**，只包含包说明，不执行初始化。
- [ ] **Step 2: 使用 `git mv` 执行六个文件迁移**，保持文件内容不变。
- [ ] **Step 3: 更新相对导入**：运行时模块之间改用 `.settings`、`.database` 等同包导入；跨包引用改为 `..runtime...`。
- [ ] **Step 4: 全仓检索旧路径**：`rg -n "smart_reporting\.(application|execution_context|settings|database|logging_config|observability)" .`，结果只允许出现在迁移说明中。
- [ ] **Step 5: 运行定点测试**：`uv run pytest smart_reporting/tests/test_application.py smart_reporting/tests/test_execution_context.py smart_reporting/tests/test_settings.py smart_reporting/tests/test_logging_config.py smart_reporting/tests/test_observability.py -q`，预期全部通过。
- [ ] **Step 6: 提交**：`git add -A smart_reporting docs scripts Dockerfile* docker pyproject.toml && git commit -m "refactor: organize runtime modules"`。

### Task 2: 迁移 HTTP 边界模块

**Files:**
- Create: `smart_reporting/http/__init__.py`
- Rename: `smart_reporting/http_request_limits.py` → `smart_reporting/http/request_limits.py`
- Rename: `smart_reporting/security.py` → `smart_reporting/http/security.py`
- Rename: `smart_reporting/reporting_identity.py` → `smart_reporting/http/identity.py`
- Modify: `smart_reporting/app.py`, tests and all imports

- [ ] **Step 1: 创建 `http/__init__.py`**，不导出内部实现。
- [ ] **Step 2: 使用 `git mv` 迁移三个模块**。
- [ ] **Step 3: 更新 `app.py` 和测试导入**：分别使用 `.http.request_limits`、`.http.security`、`.http.identity`；`identity.py` 对 Workflow controller 的导入改为 `..reporting.workflow.controller`。
- [ ] **Step 4: 检索旧路径**：`rg -n "smart_reporting\.(http_request_limits|security|reporting_identity)" .`，确认无运行时代码引用。
- [ ] **Step 5: 运行定点测试**：`uv run pytest smart_reporting/tests/test_http_request_limits.py smart_reporting/tests/test_security.py smart_reporting/tests/test_reporting_request_identity.py -q`。
- [ ] **Step 6: 提交**：`git add -A smart_reporting && git commit -m "refactor: organize http boundary modules"`。

### Task 3: 迁移 Agno 与模型集成模块

**Files:**
- Create: `smart_reporting/integrations/__init__.py`
- Rename: `smart_reporting/agno_function_arguments.py` → `smart_reporting/integrations/agno_function_arguments.py`
- Rename: `smart_reporting/model_config.py` → `smart_reporting/integrations/model_config.py`
- Modify: all imports, monkeypatch targets and tests

- [ ] **Step 1: 创建 `integrations/__init__.py`**，保持空导出。
- [ ] **Step 2: 使用 `git mv` 迁移两个模块**。
- [ ] **Step 3: 更新导入**：运行时使用 `..integrations.agno_function_arguments`；Reporting 模块使用 `..integrations.model_config`；测试 monkeypatch 字符串同步更新。
- [ ] **Step 4: 检索旧路径**：`rg -n "smart_reporting\.(agno_function_arguments|model_config)" .`，确认为空。
- [ ] **Step 5: 运行定点测试**：`uv run pytest smart_reporting/tests/test_contract.py smart_reporting/reporting/tests/test_reporting_agent_projection.py -q`。
- [ ] **Step 6: 提交**：`git add -A smart_reporting && git commit -m "refactor: organize integration modules"`。

### Task 4: 全量迁移验证与文档检查

**Files:**
- Modify: any remaining import paths in Python, tests, README, Docker and scripts

- [ ] **Step 1: 验证旧路径清零**：对全部 11 个旧模块路径执行 `rg` 检索。
- [ ] **Step 2: 验证入口导入**：`uv run python -c "import smart_reporting.app; print(smart_reporting.app.app)"`。
- [ ] **Step 3: 运行 Ruff**：`uv run ruff check smart_reporting` 和 `uv run ruff format --check smart_reporting`。
- [ ] **Step 4: 运行 Mypy**：`uv run mypy smart_reporting/runtime smart_reporting/http smart_reporting/integrations`。
- [ ] **Step 5: 运行完整非集成测试**：`uv run pytest smart_reporting/tests smart_reporting/reporting/tests -q`。
- [ ] **Step 6: 检查差异**：`git diff --check`、`git status --short`，确认无缓存、日志或其他运行产物。
- [ ] **Step 7: 提交最终修正**：`git add -A && git commit -m "refactor: finalize smart reporting module layout"`。

