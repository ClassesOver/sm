# AgentOS 开发服务

本仓库提供基于 Agno 和 PostgreSQL 的 Office 文档服务：DOCX、XLSX、PPTX、PDF 原生在线编辑、文件内 AI，
以及数据源、指标与统计口径管理后台。报告工作流与旧 Markdown/幻灯片/工作簿编辑器已退役。

## Docker 部署

根目录 `docker-compose.yml` 部署 AgentOS 和专用 PostgreSQL，`reporting-db` 向宿主机发布
`127.0.0.1:55432`。Office 文件、修订与历史报告产物都保存在 AgentOS 所在主机的本地工作区
（`REPORTING_HOST_WORKSPACE_ROOT`，Office 文件位于其 `native/` 子目录）。

AgentOS 的持久化数据使用根目录 `data/`。其中 `data/reporting-workspaces` 存放 Office 文件修订
与已签发的历史报告产物：编辑授权和下载授权在 PostgreSQL 中持久化，工作区文件必须随容器重建
保留并纳入备份，否则对应的打开或下载会因文件身份无法核验而失败。
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

Office 原生编辑与文件内 AI 按能力独立灰度（`AGENT_NATIVE_*_ENABLED`）；复杂场景编码任务
（`AGENT_OFFICE_CODEX_ENABLED`，基于 Agno `CodexAgent`）默认关闭，须在部署镜像实测沙箱写入边界后开启。
详见 [smart_reporting/report_editor/README.md](smart_reporting/report_editor/README.md)。

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

接口与配置见 [smart_reporting/README.md](smart_reporting/README.md)。
