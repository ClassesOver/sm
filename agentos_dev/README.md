# 最小 AgentOS 开发应用

该应用提供两个 Odoo 集成端点：

- `POST /agui`：标准 AG-UI SSE 运行端点。
- `GET /config`：`agui.odoo.v2` 协议握手声明。

启动：

```bash
uv venv .venv-agent
uv pip install --python .venv-agent/bin/python -r agentos_dev/requirements.txt
OPENAI_API_KEY=sk-... .venv-agent/bin/python -m agentos_dev.app
```

默认监听 `127.0.0.1:7777`。Odoo 只需配置
`http://127.0.0.1:7777/agui` 并开启“允许跨域开发服务”。

应用默认读取 `/home/junge/pros/agents_app/.env`，复用其中的 `MODEL`、
`OPENAI_BASE_URL` 和 `OPENAI_API_KEY`。可通过 `AGENT_ENV_FILE` 指向其他
环境文件；已存在的进程环境变量优先于文件内容。

开发会话和 workspace 注册表统一保存在 PostgreSQL。连接配置优先读取
`AGENT_DB_URL`，其次读取 `DATABASE_URL`，默认连接
`postgresql+psycopg://odoo@127.0.0.1:55432/dev`。首次启动前可运行
`bash scripts/init_agent_db.sh` 安全创建 `dev` 数据库；认证沿用 libpq 环境变量或
`.pgpass`。
