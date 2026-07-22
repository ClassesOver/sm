# 最小 AgentOS 开发应用

该应用提供两个 HRP 集成端点：

- `POST /agui`：标准 AG-UI SSE 运行端点。
- `GET /config`：`agui.odoo.v2` 协议握手声明。

启动：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example --profile setup run --build --rm env-init
# 脚本自动生成服务密码；只需将 .env 中的 OPENAI_API_KEY 改为真实值
docker compose up -d agent-db
uv venv --python 3.12 .venv-agent
uv pip install --python .venv-agent/bin/python -r agentos_dev/requirements.txt
AGENT_ENV_FILE=.env .venv-agent/bin/python -m agentos_dev.app
```

开发检查与测试：

```bash
uv pip install --python .venv-agent/bin/python -r agentos_dev/requirements-test.txt
bash scripts/check_agentos.sh

# 启动 PostgreSQL 后单独运行集成测试
.venv-agent/bin/python -m pytest -m integration
```

初始化命令中的 `HOST_UID`/`HOST_GID` 用于保持 `.env` 的宿主文件所有权，`--rm` 只在
脚本结束后删除临时初始化容器。Compose 会在启动数据库时自动创建项目默认网络。
Daytona 使用独立的 `docker/docker-compose.yaml` 部署；宿主机运行本应用时默认通过
`http://127.0.0.1:33043/api` 访问 Daytona。

默认监听 `127.0.0.1:7777`。HRP 只需配置
`http://127.0.0.1:7777/agui` 并开启“允许跨域开发服务”。

`workspace_read_file` 禁止读取 `报表/原始数据/*/分片/*.jsonl` 和历史
`reports/data/*.jsonl`，但用户仍可通过工作区下载接口取得本人 thread 中的文件。读取、新建
文件和移动到空闲路径不需要确认；覆盖、删除和执行可信技能脚本仍要求确认，且不提供任意
Shell 或 Python 执行工具。

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

普通 `/agui` 请求只接收当前用户消息，页面工具续跑只接收末尾连续工具结果；最近 10 次
运行的对话历史由 AgentOS PostgreSQL 加载。历史回答重生成使用受控 branch 元数据和源、
目标 thread 双 capability，在新 thread 中复制截至目标 run 的历史并调用 Agno 原生
`regenerate=True, replace_original=True`。分支工作区复制源会话当前文件，限制为 2000 个
普通文件、总计 256 MiB、单文件 25 MiB，符号链接或任一超限会整体拒绝。

使用自定义 `AGENT_SKILLS_DIR` 时，目录和资源不得包含符号链接或越出技能根目录。
