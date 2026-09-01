---
name: sandbox-tooling
description: 说明 thread 隔离 Daytona Snapshot 的运行时能力与边界。用于选择沙箱内可用的命令或 Python 库。
---

# Daytona 沙箱环境

本技能只描述当前 Daytona Snapshot 的内置运行时能力。当前 Task 实际注册的工具是唯一的工具契约；不得从本技能推断某个文件、进程或验证工具可用。

所有命令与文件操作仍受用户、thread、工作区、路径、进程、超时、输出大小及 `network_block_all` 约束。本技能不扩大权限，也不代表网络或外部服务可用。

只探测当前任务所需的命令或模块，例如 `command -v rg` 或 `python -c 'import pandas'`；不要枚举完整环境。镜像预装不代表项目、数据源或外部服务已可用，必须以实际执行结果为准。

## 常用能力

- 检索与开发：Bash、`rg`、Git、`jq`、`find`、`sed`、`diff`、`patch`。
- 测试与质量：`pytest`、Ruff、Mypy、Hypothesis、Jedi、Jupyter nbconvert。
- 数据与图表：pandas、Polars、PyArrow、DuckDB、NumPy、SciPy、Matplotlib、Seaborn、Plotly、Pillow、OpenCV。
- 文档与 PDF：LibreOffice、Pandoc、Poppler、WeasyPrint、python-docx、openpyxl、pypdf、PyMuPDF。
- 数据库客户端库：psycopg（PostgreSQL）、PyMySQL、clickhouse-connect、PyMongo、Redis、Neo4j、Trino、StarRocks；不保证存在数据库 CLI。
- 结构化处理：Pydantic、JSON Schema、PyYAML、orjson、HTTPX、WebSockets。
