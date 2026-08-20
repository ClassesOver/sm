# AgentOS 开发服务

本仓库提供基于 Agno、PostgreSQL 和 Daytona 的 Coding 与 Reporting 后端，不包含浏览器聊天接口或 Odoo 宿主模块。

## Docker 部署

部署分为两个独立项目：

- 根目录 `docker-compose.yml`：AgentOS 和专用 PostgreSQL。
- `docker/docker-compose.yaml`：Daytona OSS 核心栈。

持久化数据使用相对路径：AgentOS 写入根目录 `data/`，Daytona 写入 `docker/data/`。
将仓库部署到 `/u01` 后，两套服务的数据会随项目保存在 `/u01` 文件系统；迁移既有部署时，
必须先停止服务并将原 Docker 命名卷内容复制到对应目录，不能直接以空目录启动数据库。

初始化根目录环境：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example \
  --profile setup run --build --rm env-init
```

初始化并启动 Daytona：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file docker/.env.example \
  -f docker/docker-compose.yaml --profile setup \
  run --build --rm env-init

docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml up -d --remove-orphans
```

在 Daytona Dashboard 创建 API Key 后写入根目录 `.env`，再启动 AgentOS：

```bash
bash scripts/configure_agentos_env.sh .env
docker compose up -d --build
```

本地运行：

```bash
uv venv --python 3.12 .venv-agent
uv pip install --python .venv-agent/bin/python -r smart_reporting/requirements.txt
AGENT_ENV_FILE=.env .venv-agent/bin/python -m smart_reporting.app
```

Daytona 的端口、镜像和运维说明见 [docker/README.md](docker/README.md)。
