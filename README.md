# AgentOS 开发服务

本仓库提供基于 Agno 和 PostgreSQL 的 Coding 与 Reporting 后端，不包含浏览器聊天接口或 Odoo 宿主模块。

## Docker 部署

根目录 `docker-compose.yml` 部署 AgentOS 和专用 PostgreSQL，`reporting-db` 向宿主机发布
`127.0.0.1:55432`。报告分析、绘图与文档渲染都在 AgentOS 所在主机的本地工作区中执行
（`REPORTING_HOST_WORKSPACE_ROOT`），不再依赖外部沙箱服务。

AgentOS 的持久化数据使用根目录 `data/`。
其中 `data/reporting-workspaces` 存放报告修订的 Markdown 与图片工作区：编辑上下文和下载
授权在 PostgreSQL 中持久化，若工作区文件随容器重建丢失，打开历史修订会报
`report_editor_revision_missing`（404），必须用备份恢复或重新生成报告，不能用空目录继续。
将仓库部署到 `/u01` 后，服务数据会随项目保存在 `/u01` 文件系统。

生成根目录 `.env` 并启动 AgentOS：

```bash
bash scripts/configure_agentos_env.sh .env
docker compose up -d --build
```

`deepseek`、`qwen` 等 OpenAI-compatible 模型不在 tiktoken 的模型映射中，Agno
会回退到 `o200k_base` 估算上下文 token。Compose 使用可写缓存目录，外网环境首次启动
会自动下载并校验该编码，后续启动直接复用。内网部署前，必须在联网机器生成缓存并随
部署文件一起传到宿主机：

```bash
TIKTOKEN_CACHE_DIR="$PWD/data/tiktoken-cache" \
  .venv/bin/python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'
sha256sum data/tiktoken-cache/fb374d419588a4632f3f557e76b4b70aebbca790
```

校验值必须为
`446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`。
Compose 默认将 `./data/tiktoken-cache` 挂载为容器内 `/opt/tiktoken-cache`；
仓库不在 `/u01` 时，可在 `.env` 中用 `AGENT_TIKTOKEN_CACHE_DIR` 指向实际宿主目录。

内网机器已提前导入 `AGENTOS_REPORTING_IMAGE` 指定的镜像时，可直接挂载当前仓库中的
`smart_reporting/` 覆盖镜像内源码，无需重新构建：

```bash
docker compose up -d --no-build --force-recreate reporting-os
```

后续只修改 Python 源码时，执行 `docker compose restart reporting-os` 即可加载新代码。
若 `pyproject.toml`、`uv.lock`、基础镜像或系统依赖发生变化，仍需在联网环境重新构建并导入镜像。

本地运行：

```bash
UV_PROJECT_ENVIRONMENT=.venv uv sync --python 3.12 --no-install-project
AGENT_ENV_FILE=.env .venv/bin/python -m smart_reporting.app
```

当前服务使用 Agno 3.1.2，部署时必须连接全新数据库。不要复用 Agno 2.x 的 PostgreSQL
数据库或 `data/postgres` 数据目录；本项目不执行 2.x 历史数据迁移或兼容读取。

AgentOS 的 agent、team 和 workflow 新建 run 请求总大小上限为 32 MiB；multipart
请求最多包含 8 个文件，单文件上限为 24 MiB。run continuation 请求上限为 2 MiB。
超过边界的请求会在模型调用或文件读取前被拒绝。

## 数据源管理后台

管理入口为 `/management/login`。首次运行须构建独立管理页面并迁移管理数据表：

```bash
cd smart_reporting/report_editor/frontend
npm ci
npm run build:management
cd ../../..
.venv/bin/python -m alembic -c alembic-management.ini upgrade head
.venv/bin/python -m smart_reporting.management.cli bootstrap-admin
```

`bootstrap-admin` 交互设置密码，不提供默认密码，已有账号不会被覆盖。忘记密码时使用
`reset-admin-password`；该操作撤销全部旧会话。

本机开发可设置 `AGENT_MANAGEMENT_PUBLIC_ORIGIN=http://127.0.0.1:7777` 和
`AGENT_MANAGEMENT_LOCAL_HTTP=true`，随后按本地运行命令启动服务。生产环境使用实际 HTTPS
Origin，并保持 `AGENT_MANAGEMENT_LOCAL_HTTP=false`。前端默认从编辑器静态目录下的
`management/` 读取，也可通过 `AGENT_MANAGEMENT_STATIC_DIR` 指定独立 bundle 目录。Docker
构建会包含管理页面，无需宿主机再次构建。

登录后显式选择组织，可登记组织、分页查看数据源、创建/修改草稿、发布已满足依赖的版本、
修改密码和退出。数据源凭据加密存储且不回显；保存连接前须配置
`AGENT_MANAGEMENT_CREDENTIAL_KEYS=key-id:Fernet-key`。可用以下命令生成 Fernet key，生成值
应保存在部署密钥配置中并备份，不能随服务重启更换：

```bash
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

页面显示的是草稿和发布状态，不是连接测试结论。发布仍要求已发布的业务口径及目录版本，
当前页面不提供业务口径编写与目录同步界面；可沿用现有管理 API 或 CLI 导入既有配置。

管理工作台现采用统一组件与独立路由，支持服务端搜索/过滤、详情深链、保留连接、三方冲突恢复及发布预检。
异常写入不会自动重试；发布事实与连接状态分开展示。
构建、隔离验收、部署及成对回退步骤见 [管理工作台交付说明](smart_reporting/management/README.md)。

## 报告准确性与工具协议

- 数值引用绑定具体事实、期间、分组和公式；金额、人次换算与十进制舍入由服务端统一处理。
- 冲突值、无依据的倍数和被大单位舍入成零的非零值需复核；日期数字不会作为事实值。
- Coding harness 校验调用身份与一对一回执，按顺序执行多工具调用；失败或提交后停止后续执行，并保留 custom 输入与 reasoning 回放。
- 业务复核为软告警。已生成且身份可读取的 PDF/Word 即使验收失败，也返回下载链接与失败原因。

相关回归测试（不调用真实模型服务）：

```bash
uv sync --frozen --group dev
.venv/bin/pytest -q smart_reporting/reporting/tests/{test_numeric_text,test_semantic_bindings,test_trace_subject_validate,test_reporting_code_reasoning_replay}.py
```

引用与“待复核”链路可通过同一份案例进行离线回放：

```bash
.venv/bin/python scripts/check_reference_review.py --output /tmp/report-reference-harness
```

运行前需安装后端开发依赖，以及在 `smart_reporting/report_editor/frontend` 执行 `npm ci`。
Harness 先执行整章、分块两条真实生成函数，使用离线模型响应回放确定性引用对齐与模型纠错，
核对评分、最终正文和冻结引用一致，已自动修正的问题不会回退或留下过期告警。这一阶段固定执行4项
`test_generation_reference_convergence.py` 用例；未通过时不进入后续阶段。
随后按共享案例生成并冻结数值引用，在进程内调用编辑器校验服务，再将本次校验结果交给 ProseMirror，
核对数值标注、告警卡片、问题计数、跳转和恢复行为。共享案例覆盖期间、科室、聚合、复合单位、
十进制舍入、正负号、重复/缺失锚点和原始待核实值。案例位于
`smart_reporting/reporting/tests/fixtures/reference_review_cases.json`。

每次运行保存独立的结果文件与日志，输出目录的 `report.json` 指向最近一次结果。
生成、后端和前端阶段的失败、超时、缺少案例或跳过案例均返回非零退出码，不把未执行视为通过。
普通前端单测未提供后端回放产物时会跳过跨端案例；上述命令要求全部跨端案例实际执行。
生成纠错的 `referenceIssues` 同时提供具体引用、期间、范围和告警，整章与分块路径共用。
业务校验仍为软告警，不影响已有 PDF/Word 下载链接签发。

接口与配置见 [smart_reporting/README.md](smart_reporting/README.md)。

## 报告设计

报告编辑器的“报告设计”支持在 A4 封面上拖动、缩放标题、期间和落款，或输入精确位置，
并提供居中、左对齐预设。字体、字号、颜色、对齐及落款内容均可调整；Word 封面保留可编辑文字。
文字水印支持开关、透明度、角度、居中或平铺，以及是否覆盖封面。正文、三级标题、表格、图注
可分别配置字体、字号、行距和段间距。

设计随报告自动保存，导出时与正文一起固定到新修订，历史恢复同时恢复对应设计。
个人模板可保存、重命名、应用和删除；应用模板时标题、期间和落款重新绑定当前报告，避免沿用旧报告文字。
个人模板存入 PostgreSQL，服务启动时创建所需表；草稿设计保存在报告工作区，需随工作区一起备份。

即时画布用于排版参考，“生成 PDF 预览”会使用真实渲染器生成成品，不发布新修订。
预览保留 30 分钟，修改后需重新生成；分页以 PDF 为准，不同 Word 客户端可能存在排版差异。
溢出、重叠及业务验收问题会显示告警，已生成且身份可读的正式 PDF/Word 仍可下载。
