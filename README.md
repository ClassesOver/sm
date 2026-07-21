# HRP 12 AG-UI 智能助手

本插件在 HRP 12 中挂载聊天运行时，并通过 `agui.odoo.v2`
暴露当前原生 FormController/ListController 状态。HRP BasicModel 始终是页面状态的
唯一权威来源。

生产环境流量路径如下：

```text
浏览器 -> 同源反向代理 -> AgentOS AG-UI POST/SSE
```

HRP 提供 `/agui_chat/config`、v2 界面会话、浏览器宿主命令策略，以及仅允许已注册命令的
同步业务命令端点。HRP 不代理 SSE，也不开放通用 RPC 或 CRUD。

可选的 `agui_chat_import` 在 Chat 内提供 Odoo ImportView 风格的 CSV/XLSX 预览、profile
字段映射和测试导入；最终 One2many 写入仍使用具名业务命令的确认、幂等和原子事务链路，
不开放通用导入执行接口。

配置 `runtime_url` 后，HRP 会根据其中的 `/agui` 路径推导对应的 `/config` 握手地址。
部署匹配的 `12.0.8.8.6` 声明后，再启用灰度开关。详情参见
[协议说明](docs/agui_odoo_protocol.md)和[生产部署指南](docs/agui_chat_production.md)。

前端验证：

```bash
cd agui_chat/react_widget
pnpm typecheck
pnpm test
pnpm build
```

`agui_chat_test/` 是不纳入 Git 的本地 HRP 测试夹具。运行 `pnpm test:e2e:odoo` 时，
Playwright 仅在该目录存在时加载依赖它的用例；远端 HRP 已安装同一夹具时，可设置
`ODOO_E2E_WITH_AGUI_CHAT_TEST=1` 显式启用。其余 QUnit 宿主集成测试仍会正常运行。

## Docker 首次部署

按对话隔离的附件、工作区文件和经确认的代码执行使用 Daytona。部署分为两个独立项目：

- 根目录 `docker-compose.yml`：AgentOS 和专用 PostgreSQL。
- `docker/docker-compose.yaml`：基于 Daytona OSS `v0.189.0` 官方配置的完整 Daytona 栈。

两套 Compose 不共享容器网络、项目名或数据卷。请按下面的顺序分别初始化和启动。
从旧统一 Compose 升级时，必须先按[生产部署指南](docs/agui_chat_production.md#compose-volume-migration)
配置旧数据卷前缀，避免新项目创建空数据卷。

1. 生成根目录 `.env`：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example \
  --profile setup run --build --rm env-init
```

该脚本生成 AgentOS PostgreSQL 密码和工作区 HMAC，同时移除默认技能目录的组写权限并记录
其宿主 UID。编辑 `.env`，只需手工填写模型 `OPENAI_API_KEY`；需要时可增加
`OPENAI_BASE_URL` 和 `MODEL`。

2. 生成独立的 Daytona `docker/.env`：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file docker/.env.example \
  -f docker/docker-compose.yaml --profile setup \
  run --build --rm env-init
```

脚本会生成 Daytona 服务密钥、12 位服务密码、Dex 密码哈希和 SSH 密钥。Dex 明文密码只在
终端显示一次，默认登录邮箱为 `admin@example.com`，应立即保存。

3. 检查并启动 Daytona：

```bash
docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml config

docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml up -d
```

打开 `http://127.0.0.1:33043/dashboard`，使用 Dex 账号登录，激活默认 Snapshot，并创建具有
沙箱创建、写入和删除权限的 API Key。运行下面的脚本，在提示时保留现有 HMAC，并写入该
API Key：

```bash
bash scripts/configure_agentos_env.sh .env
```

4. 启动 AgentOS：

```bash
docker compose config
docker compose up -d --build
```

Daytona 基础 Compose 默认只向宿主机发布以下必要端口：

| 端口 | 服务 | 用途 |
| --- | --- | --- |
| `33043` | API / Dashboard | Daytona API 和管理界面 |
| `33044` | Proxy | 沙箱 HTTP 预览和 Toolbox |
| `33047` | Dex | OIDC 登录 |

Runner、SSH Gateway、PostgreSQL、Redis、Registry、MinIO、MailDev、Jaeger、PgAdmin 和
OpenTelemetry Collector 只在 Daytona 内部网络提供。SSH 入口按需通过独立 override 开放。
完整命令、远程 HTTPS、端口和备份要求见 [Daytona 部署说明](docker/README.md)与
[生产部署指南](docs/agui_chat_production.md#first-start)。

收藏筛选和当前筛选可在管理员启用 `odoo.business.report.filters` 并配置逐模型读取策略后，
导出到同一对话工作区，再由受控 Pandas 工具分析和生成图表。当前 List/Kanban 还可通过
`odoo-current-view-report` 技能按完整 BasicModel 范围或勾选交集生成标准 PDF 报表；查询条件
和记录 ID 仅在浏览器与 Odoo 的短期来源绑定中使用，不进入 AgentOS 上下文。

集成开发环境可直接启动仓库内的最小 AgentOS 应用：

```bash
# 先完成上面的 .env 初始化
docker compose up -d agent-db
uv venv --python 3.12 .venv-agent
uv pip install --python .venv-agent/bin/python -r agentos_dev/requirements.txt
AGENT_ENV_FILE=.env .venv-agent/bin/python -m agentos_dev.app
```

新配置默认关闭聊天且不预填运行地址。配置 `/agui` 地址后，HRP 会自动推导
同路径下的 `/config` 完成 v2 握手。开发智能体默认复用
`/home/junge/pros/agents_app/.env` 中的模型配置。

目前仅支持停靠面板和 WebClient 内浮动窗口两种界面形态。两者移动的是同一个 React DOM
根节点，因此不会中断当前 HRP 操作。停靠面板支持视口四边；在窄屏上，两种形态都会覆盖
整个视口，而不会压缩 HRP WebClient。
