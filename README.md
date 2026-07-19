# Odoo 12 AG-UI 智能助手

本插件在 Odoo 12 中挂载 React AG-UI 聊天运行时，并通过 `agui.odoo.v2`
暴露当前原生 FormController/ListController 状态。Odoo BasicModel 始终是页面状态的
唯一权威来源。

生产环境流量路径如下：

```text
浏览器 -> 同源反向代理 -> AgentOS AG-UI POST/SSE
```

Odoo 提供 `/agui_chat/config`、v2 界面会话、浏览器宿主命令策略，以及仅允许已注册命令的
同步业务命令端点。Odoo 不代理 SSE，也不开放通用 RPC 或 CRUD。

配置 `runtime_url` 后，Odoo 会根据其中的 `/agui` 路径推导对应的 `/config` 握手地址。
部署匹配的 `12.0.8.6.0` 声明后，再启用灰度开关。详情参见
[协议说明](docs/agui_odoo_protocol.md)和[生产部署指南](docs/agui_chat_production.md)。

前端验证：

```bash
cd agui_chat/react_widget
npm run typecheck
npm run test
npm run build
```

按对话隔离的附件、工作区文件和经确认的代码执行，使用
`docker-compose.yml` 中锁定版本的 Daytona 部署。默认 Compose 服务是 AgentOS 和专用
PostgreSQL；增加 `--profile daytona` 可启动完整 Daytona 基础设施。首次配置按以下顺序执行。
通用容器镜像默认使用 `docker.m.daocloud.io` 国内源；Daytona 和 Dex 镜像使用官方
Docker Hub，因为当前国内源不提供所需标签。可通过 `.env` 中的
`DOCKER_REGISTRY_MIRROR`、`DAYTONA_IMAGE_REGISTRY`、`DAYTONA_IMAGE_ARCH`、
`DAYTONA_DEFAULT_SNAPSHOT`、`DEX_IMAGE` 和 `PYTHON_IMAGE` 覆盖；镜像内 APT 和
Python 包默认分别使用阿里云 Debian、PyPI 镜像。

1. 通过一次性 Compose 服务生成 `.env`：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example --profile setup run --build --rm env-init
```

`HOST_UID` 和 `HOST_GID` 让生成文件归当前宿主用户所有，`--rm` 在脚本退出后删除这次临时
容器，不会删除生成的 `.env`。脚本会生成全部服务密码、加密密钥和 Dex 登录密码；请立即
记录终端中只显示一次的 Dex 密码，登录账号默认为 `.env` 中的 `admin@example.com`。

2. 编辑 `.env`，只需把 `OPENAI_API_KEY` 改为真实的模型 API Key。需要时可同时修改
   `OPENAI_BASE_URL`、`MODEL` 和 `DEX_ADMIN_EMAIL`：

```bash
vi .env
```

3. 检查 Compose 配置。运行服务时，Compose 会自动创建项目默认网络：

```bash
docker compose --profile daytona config
```

4. 仅运行 AgentOS 与 PostgreSQL 时执行 `docker compose up -d`。首次启用 Daytona 时，
   先按[生产部署指南](docs/agui_chat_production.md#first-start)启动 Daytona、在 Dashboard
   创建 `DAYTONA_API_KEY` 并回填 `.env`，再启动 AgentOS。Daytona 不支持在未认证状态下
   自动创建首个 API Key，这是模型 API Key 之外唯一需要回填的凭据。备份和许可证要求也见该指南。

   Daytona 集成直接参考锁定版本的官方
   [部署教程](https://github.com/daytonaio/daytona/blob/v0.189.0/apps/docs/src/content/docs/en/oss-deployment.mdx)
   和 [Compose](https://github.com/daytonaio/daytona/blob/v0.189.0/docker/docker-compose.yaml)。Runner 使用镜像内置
   Docker，不挂载宿主机 Docker Socket；相关差异和安全说明见生产部署指南。

收藏筛选和当前筛选可在管理员启用 `odoo.business.report.filters` 并配置逐模型读取策略后，
导出到同一对话工作区，再由受控 Pandas 工具分析和生成图表。

集成开发环境可直接启动仓库内的最小 AgentOS 应用：

```bash
# 先完成上面的 .env 初始化
docker compose up -d agent-db
uv venv .venv-agent
uv pip install --python .venv-agent/bin/python -r agentos_dev/requirements.txt
AGENT_ENV_FILE=.env .venv-agent/bin/python -m agentos_dev.app
```

新配置默认关闭聊天且不预填运行地址。配置 `/agui` 地址后，Odoo 会自动推导
同路径下的 `/config` 完成 v2 握手。开发智能体默认复用
`/home/junge/pros/agents_app/.env` 中的模型配置。

目前仅支持停靠面板和 WebClient 内浮动窗口两种界面形态。两者移动的是同一个 React DOM
根节点，因此不会中断当前 Odoo 操作。停靠面板支持视口四边；在窄屏上，两种形态都会覆盖
整个视口，而不会压缩 Odoo WebClient。
