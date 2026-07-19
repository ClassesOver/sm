# Daytona 完整 Docker Compose 部署

本目录基于 Daytona OSS `v0.189.0` 官方
[Open Source Deployment](https://github.com/daytonaio/daytona/blob/v0.189.0/apps/docs/src/content/docs/en/oss-deployment.mdx)
和 [docker/docker-compose.yaml](https://github.com/daytonaio/daytona/blob/v0.189.0/docker/docker-compose.yaml)
维护完整的 Daytona 栈。它与根目录的 AgentOS Compose 相互独立，不共享容器网络、项目名或数据卷。

Daytona 使用 AGPL-3.0 许可证。官方将这套 Compose 定位为本地部署基线；直接暴露到公网前，
必须增加 TLS、访问控制、防火墙和备份策略。

## 服务与端口

| 端口 | 服务 | 用途 |
| --- | --- | --- |
| `33043` | API / Dashboard | Daytona API 和管理界面 |
| `33044` | Proxy | 沙箱 HTTP 预览和 Toolbox |
| `33047` | Dex | OIDC 登录 |

Runner、SSH Gateway、PostgreSQL、Redis、Registry、MinIO、MailDev、Jaeger、PgAdmin 和
OpenTelemetry Collector 仅在 Daytona 项目网络内提供。宿主机默认只暴露 API、Proxy 和 Dex。

## 首次启动

在仓库根目录生成独立的 `docker/.env`：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file docker/.env.example \
  -f docker/docker-compose.yaml --profile setup \
  run --build --rm env-init
```

脚本会生成 Daytona 服务密钥、12 位服务密码、Dex 密码哈希及 SSH Gateway 密钥。Dex
明文登录密码只显示一次，默认账号为 `admin@example.com`，应立即保存。

启动完整 Daytona 栈：

```bash
docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml config

docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml up -d
```

需要从宿主机通过 SSH 进入沙箱时，再加载 SSH 端口 override：

```bash
docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml -f docker/docker-compose.ssh.yaml up -d
```

打开 `http://127.0.0.1:33043/dashboard`，登录后激活默认 Snapshot，并创建具有沙箱创建、
写入和删除权限的 API Key。该 Key 属于 AgentOS 客户端，应写入根目录 `.env` 的
`DAYTONA_API_KEY`，不要写入 `docker/.env`。

```bash
bash scripts/configure_agentos_env.sh .env
docker compose up -d --build
```

## 远程访问

从其他机器访问时，在 `docker/.env` 中增加或修改：

```dotenv
DAYTONA_PUBLIC_HOST=daytona.example.com
```

浏览器在普通远程 HTTP 页面中不能使用 `Crypto.subtle`。公网或跨机器部署应在 API、Dex、
Proxy 和通配沙箱域名前配置 HTTPS，并同步设置 `DAYTONA_PUBLIC_SCHEME=https`、
`DAYTONA_PROXY_DOMAIN` 及相应 DNS。不要只修改 Dashboard URL，否则 Dex 会拒绝未注册的
`redirect_uri`。

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

不要在未备份的情况下使用 `down -v`。需要备份的具名卷包括 PostgreSQL、Redis、Registry、
MinIO、Runner、Dex 和 PgAdmin 数据。
