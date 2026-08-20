# Daytona 精简 Docker Compose 部署

本目录基于 Daytona OSS `v0.189.0` 官方
[Open Source Deployment](https://github.com/daytonaio/daytona/blob/v0.189.0/apps/docs/src/content/docs/en/oss-deployment.mdx)
和 [docker/docker-compose.yaml](https://github.com/daytonaio/daytona/blob/v0.189.0/docker/docker-compose.yaml)
维护满足登录、沙箱生命周期、命令与文件操作、Toolbox、HTTP 预览、镜像和对象存储的
Daytona 核心栈，不包含 SSH Gateway、MailDev、Jaeger、OpenTelemetry Collector、PgAdmin 和
Registry UI。它与根目录的 AgentOS Compose 相互独立，不共享容器网络、项目名或数据卷。

外层 `daytona-network` 固定使用 `172.31.0.0/16`，避免与 Runner 创建 sandbox 时使用的
`172.20.0.0/16` bridge 路由重叠。部署前仍须确认宿主机及其上游网络未占用该网段。

Daytona 使用 AGPL-3.0 许可证。官方将这套 Compose 定位为本地部署基线；直接暴露到公网前，
必须增加 TLS、访问控制、防火墙和备份策略。

## 服务与端口

| 端口 | 服务 | 用途 |
| --- | --- | --- |
| `33043` | Caddy → API / Dashboard | Daytona API 和管理界面 |
| `33044` | Caddy → Proxy | 沙箱 HTTPS 预览和 Toolbox |
| `33047` | Caddy → Dex | OIDC 登录 |

API、Proxy、Dex、Runner、PostgreSQL、Redis、Registry 和 MinIO 仅在 Daytona 项目网络内提供。
宿主机默认只暴露 Caddy 的三个 HTTPS 端口。
默认 Sandbox 镜像使用 `docker.m.daocloud.io/daytonaio/sandbox:0.5.0-slim`，仅为解决
Docker Hub 在受限网络中的拉取超时；Daytona API、Runner 和 Proxy 仍使用官方 Docker Hub
镜像。可在 `docker/.env` 中将 `DAYTONA_DEFAULT_SNAPSHOT` 改回其他可访问的完整镜像地址。

## 首次启动

在仓库根目录生成独立的 `docker/.env`：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file docker/.env.example \
  -f docker/docker-compose.yaml --profile setup \
  run --build --rm env-init
```

脚本会生成 Daytona 服务密钥、12 位服务密码及 Dex 密码哈希。Dex 明文登录密码只显示一次，
默认账号为 `admin@example.com`，应立即保存。初始化容器以 root 运行，完成后根据
`HOST_UID`、`HOST_GID` 恢复环境文件的宿主所有权；配置只有在全部密钥生成成功后才会一次性替换。

启动 Daytona 核心栈：

```bash
docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml config

docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml up -d --remove-orphans
```

`--remove-orphans` 会清理同一 Daytona Compose 项目中已从精简配置删除的辅助容器，但不会删除
`docker/data/` 下 PostgreSQL、Redis、Registry、MinIO、Runner 或 Dex 的持久化数据。

首次启动后，将 `docker/data/caddy/caddy/pki/authorities/local/root.crt` 导入浏览器或操作系统的
受信任根证书颁发机构。局域网部署还需将 `docker/.env` 的 `DAYTONA_PUBLIC_HOST` 改为宿主机
局域网 IP，然后重新创建服务。打开 `https://<DAYTONA_PUBLIC_HOST>:33043/dashboard`，登录后激活默认 Snapshot，并创建具有沙箱创建、
写入和删除权限的 API Key。该 Key 属于 AgentOS 客户端，应写入根目录 `.env` 的
`DAYTONA_API_KEY`，不要写入 `docker/.env`。

```bash
bash scripts/configure_agentos_env.sh .env
docker compose up -d --build
```

## 构建工具镜像

`sandbox-tools` 在默认镜像上增加 curl、wget、ripgrep、Git、Git LFS、SSH、diff/patch、jq、压缩归档、进程查看、`script` PTY、文档转 Markdown、
PDF/Office/HTML/XML/RST、Notebook 执行与导出、出版级表格、Excel 公式、图像与地理空间处理、
离线图表与 SVG 渲染、统计、SQL、本地结构化数据、并行与多维数据、压缩处理，以及 Python
测试、构建、类型检查和源码分析工具。依赖清单按功能拆分为
`docker/sandbox-tools/requirements-*.in`。镜像保留
requests、HTTPX 和 SQLAlchemy 能力，但不内置数据库服务端，也不改变沙箱的网络隔离。

```bash
docker build \
  --platform linux/amd64 \
  -f docker/sandbox-tools/Dockerfile \
  -t daytona/sandbox:0.5.0-tools \
  .
```

将工具镜像导入 Runner，标记并推送到内置 Registry：

```bash
docker save daytona/sandbox:0.5.0-tools | \
  docker compose --env-file docker/.env \
    -f docker/docker-compose.yaml \
    exec -T runner docker load

docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml exec runner \
  docker tag daytona/sandbox:0.5.0-tools \
  registry:6000/daytona/sandbox:0.5.0-tools

docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml exec runner \
  docker push registry:6000/daytona/sandbox:0.5.0-tools
```

然后设置：

```dotenv
DAYTONA_DEFAULT_SNAPSHOT=registry:6000/daytona/sandbox:0.5.0-tools
```

推送新镜像后，需要在 Daytona 中重新创建并激活自定义 Snapshot
`sandbox-tools-20260722`。Registry tag 更新不会刷新既有 Snapshot 的固定镜像引用；继续使用旧
Snapshot 时，Base Toolkit 的搜索、Git、PTY、stat、目录树、哈希和大文件分段读取会因缺少
`rg`、`git`、`script` 或对应 coreutils 命令而失败。

## 导入 Sandbox 镜像

Runner 使用独立的内置 Docker，宿主机已经拉取或导入的镜像不会自动共享给 Runner。网络较慢时，
可先在宿主机准备镜像，再导入 Runner 并推送到 Daytona 内置 Registry。内置 Registry 数据保存在
`docker/data/registry/` 中。

宿主机已有镜像时直接导入：

```bash
docker save docker.m.daocloud.io/daytonaio/sandbox:0.5.0-slim | \
  docker compose --env-file docker/.env \
    -f docker/docker-compose.yaml \
    exec -T runner docker load
```

如果镜像来自其他机器，先按 Runner 的架构拉取并导出。当前默认架构为 `linux/amd64`：

```bash
docker pull --platform linux/amd64 \
  docker.m.daocloud.io/daytonaio/sandbox:0.5.0-slim

docker save \
  -o daytona-sandbox-0.5.0-slim-amd64.tar \
  docker.m.daocloud.io/daytonaio/sandbox:0.5.0-slim
```

将 tar 文件传到 Daytona 宿主机后导入 Runner。`-T` 用于关闭伪终端，避免破坏镜像数据流：

```bash
docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml \
  exec -T runner docker load < daytona-sandbox-0.5.0-slim-amd64.tar
```

为导入的镜像增加内部地址并推送到内置 Registry：

```bash
docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml exec runner \
  docker tag \
  docker.m.daocloud.io/daytonaio/sandbox:0.5.0-slim \
  registry:6000/daytona/sandbox:0.5.0-slim

docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml exec runner \
  docker push registry:6000/daytona/sandbox:0.5.0-slim
```

将 `docker/.env` 中的默认 Snapshot 改为内部地址：

```dotenv
DAYTONA_DEFAULT_SNAPSHOT=registry:6000/daytona/sandbox:0.5.0-slim
```

重新创建 API 和 Runner，并验证内部镜像可以直接拉取：

```bash
docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml \
  up -d --force-recreate api runner

docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml exec runner \
  docker pull registry:6000/daytona/sandbox:0.5.0-slim
```

`registry:6000` 是 Daytona Compose 内部服务地址，不要替换为 `localhost:6000`。Registry 默认
不发布到宿主机，只能由 Daytona 项目网络中的容器访问。

## 远程访问

从其他机器访问时，在 `docker/.env` 中增加或修改：

```dotenv
DAYTONA_PUBLIC_SCHEME=https
DAYTONA_PUBLIC_HOST=192.168.1.50
```

Caddy 会为该 IP 或域名签发内部证书。将
`docker/data/caddy/caddy/pki/authorities/local/root.crt` 复制到客户端，在 Firefox 的
“设置 → 隐私与安全 → 证书 → 查看证书 → 证书颁发机构 → 导入”中导入，并信任其标识网站。
然后访问 `https://192.168.1.50:33043/dashboard`。更换 `DAYTONA_PUBLIC_HOST` 后必须重新创建
`api`、`proxy`、`dex` 和 `caddy`，否则 Dex 会继续使用旧的 issuer 和回调地址。

## 运维

查看状态与日志：

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yaml ps
docker compose --env-file docker/.env -f docker/docker-compose.yaml logs --tail=100 api runner
```

停止服务但保留数据：

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yaml down
```

不要在未备份的情况下删除 `docker/data/`。需要备份的目录包括 PostgreSQL、Redis、Registry、
MinIO、Runner、Dex 和 Caddy 数据。
