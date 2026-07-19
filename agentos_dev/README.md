# 最小 AgentOS 开发应用

该应用提供两个 Odoo 集成端点：

- `POST /agui`：标准 AG-UI SSE 运行端点。
- `GET /config`：`agui.odoo.v2` 协议握手声明。

启动：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example --profile setup run --build --rm env-init
# 脚本自动生成服务密码；只需将 .env 中的 OPENAI_API_KEY 改为真实值
# 自定义网络名时同步修改下一条命令
docker network create hrp_network
docker compose up -d agent-db
uv venv .venv-agent
uv pip install --python .venv-agent/bin/python -r agentos_dev/requirements.txt
AGENT_ENV_FILE=.env .venv-agent/bin/python -m agentos_dev.app
```

初始化命令中的 `HOST_UID`/`HOST_GID` 用于保持 `.env` 的宿主文件所有权，`--rm` 只在
脚本结束后删除临时初始化容器。已存在的网络再次创建会报错，可直接继续启动数据库。

默认监听 `127.0.0.1:7777`。Odoo 只需配置
`http://127.0.0.1:7777/agui` 并开启“允许跨域开发服务”。

应用还注册五个受控 Pandas 报表工具，支持当前 thread 工作区内的 CSV、XLSX、JSON 和
JSONL。它们不暴露任意 DataFrame operation；图表自动写入 `reports/` 下的 UUID PNG 与
独立 HTML，其他工作区写入仍要求确认。

应用默认读取 `/home/junge/pros/agents_app/.env`，复用其中的 `MODEL`、
`OPENAI_BASE_URL` 和 `OPENAI_API_KEY`。可通过 `AGENT_ENV_FILE` 指向其他
环境文件；已存在的进程环境变量优先于文件内容。

开发会话和 workspace 注册表统一保存在 PostgreSQL。连接配置优先读取
`AGENT_DB_URL`，其次读取 `DATABASE_URL`；未提供完整 URL 时，根据
`AGENT_POSTGRES_HOST`、`AGENT_POSTGRES_PORT`、`AGENT_POSTGRES_DB`、
`AGENT_POSTGRES_USER` 和 `AGENT_POSTGRES_PASSWORD` 生成连接串。统一 Compose 将专用
PostgreSQL 绑定到 `127.0.0.1:55432`，容器内 AgentOS 则通过 `agent-db:5432` 连接。
外部 PostgreSQL 首次使用时仍可运行 `bash scripts/init_agent_db.sh` 安全创建数据库；
认证沿用环境变量或 `.pgpass`。
