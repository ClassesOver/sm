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

1. 通过一次性 Compose 服务生成 `.env`：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example --profile setup run --rm env-init
```

`HOST_UID` 和 `HOST_GID` 让生成文件归当前宿主用户所有，`--rm` 在脚本退出后删除这次临时
容器，不会删除生成的 `.env`。

2. 编辑 `.env`，至少填写真实的 `OPENAI_API_KEY`、`DEX_ADMIN_EMAIL` 和
   `DEX_STATIC_PASSWORD_HASH`。生成 Dex bcrypt hash 时保留 `.env` 中的单引号：

```bash
htpasswd -BinC 10 admin | cut -d: -f2
```

3. 创建外部网络并检查配置。`.env` 不会自动导出为当前 Shell 变量；若修改了
   `AGUI_SHARED_NETWORK`，请把命令中的 `hrp_network` 换成相同值：

```bash
docker network create hrp_network
docker compose --profile daytona config
```

4. 仅运行 AgentOS 与 PostgreSQL 时执行 `docker compose up -d`。首次启用 Daytona 时，
   先按[生产部署指南](docs/agui_chat_production.md#first-start)启动 Daytona、在 Dashboard
   创建 `DAYTONA_API_KEY` 并回填 `.env`，再启动 AgentOS。备份和许可证要求也见该指南。

收藏筛选和当前筛选可在管理员启用 `odoo.business.report.filters` 并配置逐模型读取策略后，
导出到同一对话工作区，再由受控 Pandas 工具分析和生成图表。

集成开发环境可直接启动仓库内的最小 AgentOS 应用：

```bash
# 先完成上面的 .env 初始化和 hrp_network 创建
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
