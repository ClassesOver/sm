---
name: sandbox-tooling
description: 说明 Reporting Worker 的隔离 Daytona 环境与受限脚本执行方式。仅在分析或可视化任务需要本地执行时读取。
---

# Reporting 沙箱

当前 Task 实际注册的工具是唯一的工具契约；本技能只说明 Reporting Worker 的本地运行环境，不扩大文件、进程、网络或服务权限。

## 执行边界

- 只读取任务 JSON 签发的工作区路径。首次写入分析脚本、evidence 和图表相关文件只使用 `create_analysis_file`；覆盖已有文件只使用 `overwrite_analysis_file`，并传入当前 `expected_sha256`。
- `terminal` 只执行已经写入的受信脚本。`process` 仅轮询同一 Task 启动的运行进程；不得借此枚举环境、访问外部服务或执行未签发脚本。
- 所有操作仍受 thread、工作区、路径、超时、输出大小及 `network_block_all` 约束。镜像预装不代表项目、数据源或外部服务可用，必须以实际执行结果为准。

## 按需能力

- 数据与图表：Python、pandas、Polars、PyArrow、DuckDB、NumPy、SciPy、Matplotlib、Seaborn、Plotly、Pillow、OpenCV。
- 报告产物：LibreOffice、Pandoc、Poppler、WeasyPrint、python-docx、openpyxl、pypdf、PyMuPDF。
- 检索与质量：`rg`、`jq`、`pytest`、Ruff、Mypy、Jupyter nbconvert。
