# AG-UI Chat v2 生产部署

## 拓扑

浏览器将标准 AG-UI 输入直接提交到同源 AgentOS 代理并消费 SSE。Odoo 提供配置、
界面会话、宿主命令策略和具名同步业务命令，但不代理 SSE。

只配置一个公开运行地址：

- `runtime_url`：AgentOS AG-UI POST 端点，例如 `/contract-review/agui`。

Odoo 根据该值推导协议握手地址 `/contract-review/config`。AgentOS 必须公开推导出的
JSON 声明端点。

声明必须包含已部署的 `agui.odoo.v2` 协议、前端包版本和 Odoo 命令目录哈希。Nginx
不得重试 AG-UI POST。SSE 必须关闭代理缓冲、缓存和压缩，并按至少 200 条并发流配置
连接上限。

## 灰度控制

新配置记录默认关闭聊天，不设置运行地址，并关闭跨域开发。升级不会改写现有记录。
先配置共享 HMAC 密钥和两个运行地址，再按以下顺序启用：

1. `chat_enabled`
2. `host_tools_enabled`
3. `enabled_commands` 中的精确条目
4. `enabled_business_commands` 中的精确条目
5. 需要写命令时启用 `write_tools_enabled`

命令列表为空时不启用任何命令。匹配的工具策略会限制精确命令、用户组、模型、字段和
可见按钮白名单。暂存、修改、保存、丢弃，受保护对象的创建、删除、状态控件，以及所有
`odoo.business.*` 命令在缺少策略时均默认拒绝。没有策略的只读和导航页面命令不附加
模型限制，但仍绑定当前可见快照。紧急开关只禁用对应功能，不允许回退到 RPC、CRUD 或
模拟状态。

模块内置一个只读 `odoo.apply_filter` 策略，将 `hr.employee` 筛选限制为内部用户。
该策略只作用于当前绑定的列表或看板视图；Odoo 访问权限、记录规则和快照中的
`filterFields` 白名单仍决定可筛选的记录与字段。需要额外用户组或字段限制时，应增加
逐模型策略。

### 报表管理

筛选报表命令会作为命令主数据安装，但不会自动加入 `enabled_business_commands`。
启用报表时：

1. 将 `odoo.business.report.filters` 加入现有的已启用业务命令选择。
2. 按允许的模型和用户组范围分别创建 `agui.chat.tool.policy`。
3. 将访问级别设为 `read`，填写精确的 `model_name`，并提供非空的逗号分隔
   `field_names` 白名单。
4. 不要将敏感字段、二进制字段、one2many 或 many2many 字段加入白名单；保存此类
   策略会被拒绝。
5. 货币字段可能参与聚合时，同时加入对应币种字段，通常为 `currency_id`。

关闭 `write_tools_enabled` 时，该命令仍然可用。现有业务命令默认访问级别为 `write`，
在该状态下不可用。必须使用非管理员账号测试每条策略，因为 Odoo ACL、记录规则、当前
公司、筛选可见性和菜单可见性仍然生效。

## 部署

Python 模块和带版本的 React 前端包必须一起部署，随后清理旧资源缓存。模块与前端包
版本不匹配时，握手失败并保持聊天关闭。

AgentOS 保留内置 `/health` 存活端点。流量就绪检查使用 `/ready`，只有 PostgreSQL
可访问、沙箱注册表初始化完成且 HMAC 密钥至少为 32 字节时才返回成功。Compose 使用
`/ready`，并自动重启 Agent 服务。

Agent 镜像安装 pandas、openpyxl、matplotlib、Plotly 和 Noto CJK 字体。
`agentos_dev/requirements.txt` 变化后必须重建镜像，不要在运行中的生产容器内交互安装
这些依赖。

<a id="isolated-workspaces"></a>

## 隔离工作区

仓库在 `docker-compose.yml` 中提供完整的 AgentOS、PostgreSQL 和 Daytona 拓扑，
基于 Daytona OSS `v0.189.0` 官方 Compose 基线。这是本项目所用且仍包含受支持 OSS
Compose 基线的最后一个上游版本。上游此后已停止本地部署支持，因此运维方需要自行维护
并修补这套锁定版本的软件。

默认 Compose 项目名保持为 `agui-daytona`，与原双文件生产部署一致，并保留其具名卷。
如果旧部署只运行基础文件且使用其他项目名，首次启动统一栈前必须将
`COMPOSE_PROJECT_NAME` 设为原项目名，或迁移 `agent_db_data`。

两个 PostgreSQL 18 服务都将具名卷挂载到 `/var/lib/postgresql`，这是 PostgreSQL 18
镜像布局要求的父数据路径。旧文件使用 PostgreSQL 18 之前的
`/var/lib/postgresql/data` 挂载目标。替换由旧文件创建的运行中部署前，必须对两个数据库
执行逻辑备份并验证恢复；不要假定旧具名卷中一定包含 PostgreSQL 18 数据集群。

Daytona 使用 AGPL-3.0 许可证。通过网络向用户提供修改后的 Daytona 服务时，需要按
AGPL-3.0 向这些用户提供包含修改内容的对应源代码。部署记录应保存精确的源码修订版本和
容器来源。本段仅为运维说明，不构成法律意见。

项目只部署以下 Daytona 服务：

- `api`、`runner`、`db`、`redis`、`minio`、`registry` 和 `dex`
- `dashboard`，仅监听本机，作为 API 界面和 Dex 的 Nginx 入口
- `proxy`，仅监听本机，提供沙箱端口预览
- 现有的 `agent` 服务，包含 AgentOS 和 Agno
- `agent-db`，作为 Agno 会话和工作区沙箱注册表的专用 PostgreSQL 后端；同时发布到
  本机 `55432` 端口，供宿主机上的 `agentos_dev` 使用；Daytona 的 `db` 仍仅供
  Daytona 内部使用

部署有意不包含 SSH Gateway、PgAdmin、Jaeger 和 OpenTelemetry Collector。AgentOS
Toolbox 流量使用 `PROXY_TOOLBOX_BASE_URL=http://api:3000/api`；Proxy 只用于沙箱
HTTP 预览。

### 要求与密钥

至少分配 4 GB 内存，实际运行沙箱生命周期前建议使用 8 GB。并发代码执行可能需要更多
资源。Docker 和 Daytona Runner 要求支持 cgroup 的 Linux 宿主机。Runner 以特权模式运行
镜像内置 Docker（DinD），仍具有较高的宿主机权限；应部署在专用宿主机或虚拟机上，并限制
管理员访问。

将所有 Compose 必需变量写入受保护的环境文件。生产环境不得使用示例密码或默认密码。
必要配置包括：

- `AGUI_WORKSPACE_HMAC_SECRET`，至少 32 个随机字节，并与 Odoo 系统参数
  `agui_chat.workspace_hmac_secret` 完全一致
- Daytona 加密密钥和盐、Runner Token、Proxy Key 与健康检查 Key
- PostgreSQL、Redis、Registry 和 MinIO 凭据
- Dex 管理员邮箱和 bcrypt 密码哈希
- 安装管理员维护的技能时设置 `AGENT_SKILLS_DIR`；默认空目录以只读方式挂载
- AgentOS 专用 PostgreSQL 服务使用的 `AGENT_POSTGRES_PASSWORD`
- 本机开发连接使用的 `AGENT_POSTGRES_BIND` 和 `AGENT_POSTGRES_PORT`，默认值为
  `127.0.0.1:55432`
- Dashboard 和 Dex 对外使用的 `DAYTONA_PUBLIC_HOST`；默认值为 `127.0.0.1`，从其他
  机器访问时必须改为宿主机 IP 或域名。协议默认使用 `http`，TLS 部署可增加
  `DAYTONA_PUBLIC_SCHEME=https`
- 通用容器仓库前缀 `DOCKER_REGISTRY_MIRROR`，默认值为 `docker.m.daocloud.io`，也可设为
  `docker.io` 或内部镜像仓库
- Daytona 镜像仓库 `DAYTONA_IMAGE_REGISTRY`，默认值为 `docker.io`；当前国内源不提供
  所需的 Daytona 标签，因此不强制使用国内源
- Daytona 镜像架构 `DAYTONA_IMAGE_ARCH`，默认值为 `amd64`；ARM64 宿主机设置为 `arm64`
- Dex 镜像 `DEX_IMAGE`，默认使用官方 `docker.io/dexidp/dex:v2.42.0`；当前国内源对该
  镜像返回 403，因此不使用国内代理
- 构建 AgentOS 时使用的 Debian 软件源 `APT_MIRROR_HOST`，默认值为
  `mirrors.aliyun.com`
- 构建 AgentOS 时使用的 Python 软件源 `PIP_INDEX_URL`，默认使用阿里云 PyPI 镜像

可在宿主机交互初始化或更新配置：

```bash
bash scripts/configure_daytona_env.sh
```

直接在宿主机执行需要 `openssl` 和 `htpasswd`。下面的 Compose 初始化镜像已包含这两个
工具。

在 `.env` 不存在时，也可以通过一次性 Compose setup profile 运行同一脚本。传入宿主机
用户标识，使生成的权限为 `600` 的文件仍归当前操作员所有：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example --profile setup run --build --rm env-init
```

初始化容器没有运行时网络，只挂载项目工作目录。Compose 仅使用 `.env.example` 解析服务
配置，随后由脚本写入真实 `.env`；不会使用占位值启动其他服务。`HOST_UID` 和
`HOST_GID` 使生成文件归调用命令的宿主用户所有。`--rm` 只删除已经停止的一次性容器，
不会删除 `.env` 或任何运行时数据卷。

脚本以原子方式写入文件并设置权限为 `600`。已有文件会备份到被忽略的
`.env.backups/` 目录。对于现有部署，脚本将运行时密钥轮换与加密密钥、Runner 凭据和
存储凭据轮换分开处理；后者不能在未迁移对应服务或重建 Daytona 数据卷的情况下修改。

新建 `.env` 时，脚本会生成运行时和持久化随机密钥、12 位 Base64URL 服务密码和
12 位 Dex 登录密码。Dex bcrypt 哈希写入 `.env`，明文登录密码只显示一次，必须立即
记录。已有文件只有在确认对应提示后才轮换密钥。验证前只需替换 `OPENAI_API_KEY`；
`OPENAI_BASE_URL`、`MODEL` 和默认 `DEX_ADMIN_EMAIL` 可按需修改。

HMAC、加密、Proxy、健康检查和 Runner 使用 32 字节随机值，编码为约 43 位 Base64URL
字符串。它们有意长于服务密码，同时避免旧的 64 位十六进制表示。
`DAYTONA_API_KEY` 仅允许在首次 Dashboard 引导期间为空；Daytona 不允许未认证客户端
创建首个 API Key。如需生成其他独立密钥，可使用 `openssl rand -hex 32`。

在 Odoo 中，将同一 HMAC 密钥配置为仅服务端可见的系统参数，并将
`AgentOS 内部服务地址` 设为 Odoo 可访问的地址，例如 `http://127.0.0.1:7777`。
该内部地址绝不会由 `/agui_chat/config` 返回。

归档或删除聊天会话时，会在同一数据库事务中提交沙箱清理任务。定时任务每五分钟最多
处理 50 个任务；失败任务按指数退避重试，上限为 24 小时。HTTP 200、204 和 404 都视为
幂等成功。

在清理任务模型创建前已删除原始 thread ID 的历史沙箱无法自动重建关联。应按
`agui-thread` 标签审计 Daytona 沙箱，并与 AgentOS 注册表和 Odoo 清理任务对比。
手工删除不匹配的沙箱前先保留导出，并记录沙箱 ID、标签哈希、复核时间和操作员。

<a id="first-start"></a>

### 首次启动

启动前验证变量插值：

```bash
docker compose --profile daytona config
```

启动时 Compose 会自动创建项目默认 bridge 网络，并将 AgentOS、两个 PostgreSQL 服务和
Daytona 基础设施连接到该网络。不要把不受信任的工作负载加入此网络；需要更强租户隔离时，
应使用独立 Compose 项目。

首次启动先运行 Daytona，不启动 AgentOS。只有在本次引导期间，`DAYTONA_API_KEY` 可以
为空：

```bash
docker compose --profile daytona up -d \
  api runner db redis minio registry dex proxy dashboard
```

打开 `http://127.0.0.1:33043/dashboard`，使用配置的 Dex 用户登录，激活默认 Snapshot，
并创建具有沙箱写入和删除权限的 API Key。将其保存为 `DAYTONA_API_KEY`，再启动 AgentOS：

```bash
docker compose --profile daytona up -d agent
```

Dashboard 默认在宿主机监听 `0.0.0.0:33043`，Proxy 默认监听 `0.0.0.0:33044`。本地预览
使用 `*.proxy.localhost`。远程部署必须设置 `DAYTONA_PUBLIC_HOST`；如需远程沙箱预览，
还要设置 `DAYTONA_PROXY_DOMAIN`，并为该域名配置通配 DNS 记录和证书。公开部署应将两个
端点置于 TLS 后方，并设置 `DAYTONA_PUBLIC_SCHEME=https`。

Runner 按 Daytona 官方 Compose 使用镜像内置 Docker（DinD），不要向 Runner 挂载宿主机
`/var/run/docker.sock`。镜像会在内部 Docker 中创建 `172.20.0.0/16` 的 `runner-bridge`；
该网络与 Compose 自动创建的项目网络相互独立。

本部署以 Daytona `v0.189.0` 的官方
[Open Source Deployment](https://github.com/daytonaio/daytona/blob/v0.189.0/apps/docs/src/content/docs/en/oss-deployment.mdx)
和 [Docker Compose](https://github.com/daytonaio/daytona/blob/v0.189.0/docker/docker-compose.yaml)
为基线，省略 PgAdmin、MailDev、Jaeger、OpenTelemetry 和 SSH Gateway 等当前集成不需要的服务。

### 备份与恢复

备份 `agent_db_data`、Daytona 的 `daytona_db_data` 卷、MinIO、Registry、Runner 和 Dex
数据。AgentOS 专用 PostgreSQL 数据库同时包含 Agno 会话和工作区注册表。PostgreSQL 与
对象存储、镜像仓库数据必须来自同一恢复点。HMAC、加密密钥、API Key、Runner 和 Proxy
密钥应单独保护；未执行迁移就丢失或轮换这些密钥，可能导致现有数据或能力不可用。依赖备份
前，应使用相同的锁定版 `v0.189.0` 镜像验证恢复。

## 安全

- 生产运行地址必须同源。绝对地址仅允许在显式开启开发标志且凭据化 CORS Origin 精确匹配
  时使用。
- 每个修改型浏览器命令都使用绑定载荷的授权，以及由用户、公司、thread、run 和工具调用
  派生的幂等键。
- 业务命令处理器始终使用当前 Odoo 用户，不使用 `sudo`，并在保存点内执行。处理失败时
  回滚业务写入。
- 宿主快照不发送二进制字段和密钥。审计详情会递归脱敏并限制大小。
- 会话保存使用 `expectedSessionRevision` 和 `SELECT ... FOR UPDATE`。

## 故障验收

注入 AgentOS 401、403、429、500、非 SSE 响应、异常或超大事件、连接中断和超时。
同时测试前端包缺失、握手不匹配、onchange 或保存失败、过期控制器、重复工具事件、重放
令牌和多标签页会话冲突。

所有情况下，Odoo 导航、表单编辑、onchange、校验、保存和丢弃都必须保持可用。
WebClient 启动不得等待聊天。系统必须始终只有一个 React 根节点、一个活动 run 和一个
会话保存队列。

使用以下命令运行负载基线：

```bash
node scripts/agui_sse_load.js https://odoo.example.com/contract-review/agui 200
```

生产目标是传输错误率低于 1%，且浏览器中止的 run 能及时释放上游连接。
