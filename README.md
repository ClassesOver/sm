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

按对话隔离的附件、工作区文件和经确认的代码执行使用 Daytona。部署已拆成两个独立项目：

- 根目录 `docker-compose.yml`：AgentOS 和专用 PostgreSQL。
- `docker/docker-compose.yaml`：基于 Daytona OSS `v0.189.0` 官方配置的完整 Daytona 栈。

两套 Compose 不共享容器网络和数据卷。AgentOS 通过 Daytona 发布到宿主机的 `33043`
端口调用 API。

1. 通过一次性 Compose 服务生成 `.env`：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example --profile setup run --build --rm env-init
```

`HOST_UID` 和 `HOST_GID` 让生成文件归当前宿主用户所有。该脚本只生成 AgentOS 数据库密码
和工作区 HMAC，不生成 Daytona 服务端凭据。

2. 编辑 `.env`，只需把 `OPENAI_API_KEY` 改为真实的模型 API Key。需要时可同时修改
   `OPENAI_BASE_URL` 和 `MODEL`；Daytona 登录邮箱在 `docker/.env` 的
   `DEX_ADMIN_EMAIL` 中修改：

```bash
vi .env
```

3. 按 [Daytona 完整部署说明](docker/README.md)生成 `docker/.env` 并启动 Daytona，在
   Dashboard 创建 API Key 后写入根目录 `.env`：

```bash
bash scripts/configure_agentos_env.sh .env
```

4. 单独启动 AgentOS：

```bash
docker compose config
docker compose up -d --build
```

Daytona 不支持未认证客户端自动创建首个 API Key，因此这是模型 API Key 之外唯一需要在
首次引导后回填的值。完整命令、端口和备份要求见
[生产部署指南](docs/agui_chat_production.md#first-start)。

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
