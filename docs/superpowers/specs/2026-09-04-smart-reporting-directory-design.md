# Smart Reporting 目录结构整理设计

## 目标

在不改变业务行为、公共协议、数据库结构和部署入口的前提下，按职责归属整理 `smart_reporting` 顶层模块，降低顶层文件拥挤和跨职责耦合。

## 目标结构

```text
smart_reporting/
├── app.py
├── README.md
├── runtime/
│   ├── application.py
│   ├── execution.py
│   ├── settings.py
│   ├── database.py
│   ├── logging.py
│   └── observability.py
├── http/
│   ├── request_limits.py
│   ├── security.py
│   └── identity.py
├── integrations/
│   ├── agno_function_arguments.py
│   └── model_config.py
├── agent_control.py
├── async_utils.py
├── context_management.py
└── workspace.py
```

## 迁移映射

- `application.py` → `runtime/application.py`
- `execution_context.py` → `runtime/execution.py`
- `settings.py` → `runtime/settings.py`
- `database.py` → `runtime/database.py`
- `logging_config.py` → `runtime/logging.py`
- `observability.py` → `runtime/observability.py`
- `http_request_limits.py` → `http/request_limits.py`
- `security.py` → `http/security.py`
- `reporting_identity.py` → `http/identity.py`
- `agno_function_arguments.py` → `integrations/agno_function_arguments.py`
- `model_config.py` → `integrations/model_config.py`

## 保留顶层的模块

- `app.py`：稳定的 FastAPI/Uvicorn 应用入口。
- `agent_control.py`：`reporting` 与 `task_execution` 共享的状态契约。
- `async_utils.py`：多个基础设施和 Workflow 使用的清理原语。
- `context_management.py`、`workspace.py`：大型且边界明确的基础设施模块，暂不拆分。
- `README.md`：包级文档。

## 不变量与兼容性

目录迁移只改变模块所有权和导入路径，不改变函数行为、HTTP 路由、Workflow ID、错误码、数据库 schema 或环境变量名称。不得增加长期兼容转发模块；所有内部调用方、测试、monkeypatch 目标、文档和部署脚本一次性迁移到新路径。

## 验证标准

1. 全仓检索旧模块路径为零。
2. `smart_reporting` 包及应用入口可导入。
3. 相关 pytest 能收集并通过。
4. 迁移文件通过 Ruff 和必要的 Mypy 检查。
5. README、Docker、脚本中的入口和路径保持正确。
6. `git diff --check` 通过，Git 将文件识别为 rename，且没有临时产物进入提交。

