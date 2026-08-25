# AgentOS 开发服务

本仓库提供基于 Agno、PostgreSQL 和 Daytona 的 Coding 与 Reporting 后端，不包含浏览器聊天接口或 Odoo 宿主模块。

## Docker 部署

部署分为两个独立项目：

- 根目录 `docker-compose.yml`：AgentOS 和专用 PostgreSQL。
- `docker/docker-compose.yaml`：Daytona OSS 核心栈。

持久化数据使用相对路径：AgentOS 写入根目录 `data/`，Daytona 写入 `docker/data/`。
将仓库部署到 `/u01` 后，两套服务的数据会随项目保存在 `/u01` 文件系统；迁移既有部署时，
必须先停止服务并将原 Docker 命名卷内容复制到对应目录，不能直接以空目录启动数据库。

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

`deepseek`、`qwen` 等 OpenAI-compatible 模型不在 tiktoken 的模型映射中，Agno
会回退到 `o200k_base` 估算上下文 token。该编码首次加载默认访问公网；内网部署前，
必须在联网机器生成缓存并随部署文件一起传到宿主机：

```bash
TIKTOKEN_CACHE_DIR="$PWD/data/tiktoken-cache" \
  .venv-agent/bin/python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'
sha256sum data/tiktoken-cache/fb374d419588a4632f3f557e76b4b70aebbca790
```

校验值必须为
`446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`。
Compose 默认将 `./data/tiktoken-cache` 只读挂载为容器内 `/opt/tiktoken-cache`；
仓库不在 `/u01` 时，可在 `.env` 中用 `AGENT_TIKTOKEN_CACHE_DIR` 指向实际宿主目录。
缓存目录不包含 Registry 数据，调整该变量不会迁移或修改 Registry。

内网机器已提前导入 `AGENTOS_REPORTING_IMAGE` 指定的镜像时，可直接挂载当前仓库中的
`smart_reporting/` 覆盖镜像内源码，无需重新构建：

```bash
docker compose up -d --no-build --force-recreate reporting-os
```

后续只修改 Python 源码时，执行 `docker compose restart reporting-os` 即可加载新代码。
若 `smart_reporting/requirements.txt`、基础镜像或系统依赖发生变化，仍需在联网环境重新构建并导入镜像。

本地运行：

```bash
uv venv --python 3.12 .venv-agent
uv pip install --python .venv-agent/bin/python -r smart_reporting/requirements.txt
AGENT_ENV_FILE=.env .venv-agent/bin/python -m smart_reporting.app
```

AgentOS 的 agent、team 和 workflow 新建 run 请求总大小上限为 32 MiB；multipart
请求最多包含 8 个文件，单文件上限为 24 MiB。run continuation 请求上限为 2 MiB。
超过边界的请求会在模型调用或文件读取前被拒绝。

Daytona 的端口、镜像和运维说明见 [docker/README.md](docker/README.md)。
