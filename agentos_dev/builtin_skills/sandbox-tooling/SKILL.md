---
name: sandbox-tooling
description: 在当前 thread 隔离的 Daytona sandbox-tools 镜像中执行编码、代码检查、测试、文档处理、数据分析和数据库客户端任务；需要选择预装工具或判断能力边界时使用。
compatibility: Daytona sandbox-tools custom Snapshot
allowed-tools:
  - exec_command
  - poll_process
  - write_stdin
  - apply_patch
  - view_image
  - update_plan
---

# Daytona 沙箱工具能力

本技能描述当前 Daytona sandbox-tools 自定义 Snapshot 的内置能力。所有命令和文件操作仍受当前用户、thread、Daytona 工作区、路径、进程、超时、输出大小及 `network_block_all` 约束；本技能不扩大权限，也不代表网络可用。

## 使用原则

1. 任务涉及编码、测试、文档转换、数据分析、图表或数据库客户端时，优先复用下列预装能力。
2. 只探测当前任务直接需要的命令或 Python 模块，例如 `command -v rg` 或 `python -c 'import pandas'`；不要枚举或输出完整环境。
3. 下列名称表示镜像构建时安装的能力，不保证用户项目已配置、数据源可访问或运行时服务可用。外部服务和网络仍须以实际命令结果为准。
4. 文件修改只使用 `apply_patch`。命令返回非零 `exit_code`、超时或后台进程仍在运行时，不得声称任务完成。

## 代码任务检查

1. 修改前读取工作区内适用的项目规则、相关实现、测试和文档，并用 `git status` 确认已有改动；不得覆盖、回退或格式化与任务无关的用户修改。
2. 从项目规则、构建配置、依赖文件或 CI 配置识别项目既有检查入口，不凭语言或框架名称猜测命令。
3. 修改后先运行与改动直接相关的最小检查，再执行项目要求的格式检查、lint、类型检查和测试。只运行与任务范围相称的检查，不为通过检查而放宽配置或改动无关代码。
4. 检查失败时读取完整错误，判断是否由本次改动引起；修复本次引入的问题后重新运行。既有失败不得掩盖，也不得擅自修改任务范围外的代码。
5. 完成前检查实际差异和 `git diff --check`。最终响应列出已执行检查及结果、未执行检查及原因，以及仍存在的风险；不得声称运行过未执行的检查。

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

## 明确未预装

镜像构建会拒绝 Playwright、Selenium、Pyppeteer、Chromium 自动化依赖，以及 scikit-learn、XGBoost、LightGBM、CatBoost、TensorFlow、PyTorch、JAX、Transformers、spaCy、NLTK、Kaleido、云对象存储 SDK 和 `yfinance`。任务需要这些能力时，先说明当前镜像不提供；只有用户任务确实需要且运行时策略允许时才尝试安装，并以安装命令的实际结果为准。
