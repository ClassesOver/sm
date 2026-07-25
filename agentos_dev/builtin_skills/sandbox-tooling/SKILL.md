---
name: sandbox-tooling
description: 提供当前 thread 隔离的 Daytona sandbox-tools 自定义 Snapshot 中的预装命令、Python 库及受限操作方式。用于在沙箱内执行编码、测试、文档与 PDF 处理、数据分析、图表、图像或数据库客户端任务，或需要确认并选择可用本地工具时。
compatibility: Daytona sandbox-tools custom Snapshot
allowed-tools:
  - terminal
  - process
  - patch
  - view_image
  - update_plan
  - finish_task
---

# Daytona 沙箱工具能力

本技能描述当前 Daytona sandbox-tools 自定义 Snapshot 的内置能力。所有命令和文件操作仍受当前用户、thread、Daytona 工作区、路径、进程、超时、输出大小及 `network_block_all` 约束；本技能不扩大权限，也不代表网络可用。

## 使用原则

1. 任务涉及编码、测试、文档转换、数据分析、图表或数据库客户端时，优先复用下列预装能力。
2. 只探测当前任务直接需要的命令或 Python 模块，例如 `command -v rg` 或 `python -c 'import pandas'`；不要枚举或输出完整环境。
3. 下列名称表示镜像构建时安装的能力，不保证用户项目已配置、数据源可访问或运行时服务可用。外部服务和网络仍须以实际命令结果为准。
4. 已有文件的小范围精确修改优先使用 `patch` 的 `mode="replace"`；新增、删除、移动或多文件变更使用 `patch` 的 `mode="patch"` 提交原生补丁。模型无法稳定生成补丁函数参数时，可改用 `terminal` 提交完整、独立的 `apply_patch <<'PATCH'` heredoc；服务端会按同一原子 Patch 语义拦截，不能附加其他命令、`workdir` 或 PTY。命令返回非零 `exit_code`、超时或进程仍在运行时不得交付；最后一次修改后必须重新验证，并以 `finish_task` 验收结果为准。

## 预装命令

- 开发与检索：Bash、GNU coreutils、`find`、`sed`、ripgrep (`rg`)、Git、Git LFS、`diff`、`patch`、`file`、`jq`、OpenSSH client、`curl`、`wget`。
- 归档与进程：`tar`、`gzip`、`xz`、ZIP/UnZIP、`ps`、`pstree`、`timeout`、PTY 相关的 `script` 和 `stty`。
- 文档与 PDF：LibreOffice Writer/Calc/Impress、Pandoc、Poppler (`pdfinfo`、`pdftotext`、`pdftoppm`)、QPDF、Graphviz、CairoSVG、librsvg、WeasyPrint、Noto CJK 字体。
- Python 开发与测试：`pytest`、pytest-asyncio、pytest-cov、pytest-xdist、Hypothesis、Ruff、Mypy、Coverage、Radon、Build、IPython、Jedi 和 Jupyter nbconvert。

## 预装 Python 能力

- 表格与本地分析：pandas、Polars、PyArrow、DuckDB、Dask、NumPy、SciPy、Statsmodels、SymPy、Xarray、HDF5、Zarr、SQLAlchemy 和 SQLGlot。
- 图表与图像：Matplotlib、Seaborn、Plotly、Plotnine、Altair、Bokeh、Pygal、Great Tables、Pillow、OpenCV、scikit-image、Graphviz、WordCloud、GeoPandas 和 Shapely。
- Office、HTML 与 PDF：openpyxl、python-calamine、xlrd、xlsxwriter、python-docx、python-pptx、docxtpl、Beautiful Soup、lxml、Markdown、ReportLab、pypdf、PyMuPDF、pdfplumber、pikepdf 和 WeasyPrint。
- 数据库客户端库：psycopg（PostgreSQL）、PyMySQL 与 mysql-connector-python、clickhouse-connect、PyMongo、Redis、Neo4j、Trino 和 StarRocks。镜像没有因此承诺安装 `psql`、`mysql` 等数据库 CLI。
- 常用结构化与客户端处理：Pydantic、JSON Schema、PyYAML、orjson、jsonlines、xmltodict、RapidFuzz、NetworkX、Requests、HTTPX 和 WebSockets。
