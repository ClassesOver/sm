# AG-UI Chat v2 生产部署

## 拓扑

浏览器将标准 AG-UI 输入直接提交到同源 AgentOS 代理并消费 SSE。HRP 提供配置、
界面会话、宿主命令策略和具名同步业务命令，但不代理 SSE。

只配置一个公开运行地址：

- `runtime_url`：AgentOS AG-UI POST 端点，例如 `/contract-review/agui`。

HRP 根据该值推导协议握手地址 `/contract-review/config`。AgentOS 必须公开推导出的
JSON 声明端点。

声明必须包含已部署的 `agui.odoo.v2` 协议、前端包版本和 HRP 命令目录哈希。Nginx
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

需要支持用户不使用 `@` 直接要求打开菜单时，必须同时将 `odoo.search_menu` 和
`odoo.open_menu` 加入 `enabled_commands`。前者只搜索当前用户可见菜单，后者只接受
本轮同一页面、目录版本和 Run 的唯一搜索结果或用户明确 `@` 选择的菜单；升级不会自动
扩大现有命令白名单。菜单目录独立于页面快照，普通 Run 不发送完整目录；只有原词搜索无
结果后的紧邻续跑才按 128 KiB 预算发送不含导航 ID 的完整路径。目录不完整时智能体必须
停止并要求用户使用 `@`，不能基于残缺路径猜测。

模块内置只读的 `odoo.apply_filter` 和 `odoo.apply_group` 策略，将 `hr.employee` 的筛选与
分组限制为内部用户。策略只作用于当前绑定的列表或看板视图；HRP 访问权限、记录规则以及
快照中的 `filterFields`、`groupFields` 白名单仍决定可操作范围。分组最多三级，日期和时间
字段支持日、周、月、季度和年，完整数组会替换当前分组，空数组只用于明确清除分组。
升级不会自动把新命令加入现有配置；启用时应将 `odoo.apply_group` 加入
`enabled_commands`，需要额外用户组或字段限制时增加逐模型策略。

### One2many 导入

启用 `agui_chat_import` 时，业务模块必须用
`register_x2many_import_profile()` 精确注册父模型、One2many 字段、允许的源列和目标字段，
并在修改 converter 或 `row_prepare` 行为时提升 profile 版本。导入文件限制为 CSV/XLSX、
10 MB、2,000 行、50 列和 80 字符表头。Chat 预览限制为 96 KiB，通常显示服务端生成的
前 20 行，宽表或长文本会减少返回行数。不要给 profile 回调增加网络访问、额外写入或
其他副作用。

导入预览和测试通过同步 JSON 请求完成，最终确认后同步执行，不依赖 queue worker 或导入
cron。升级到 `agui_chat_import` 12.0.8.8.1 会删除旧的 One2many 导入执行 cron，并把遗留的
`validating/queued` 任务退回预览状态，要求按新协议重新映射和测试；不会修改 `agui_chat`
统一审计保留 cron。终态任务会立即删除源文件副本和完整转换行；所有超期任务（包括未完成预览）
及其源文件、错误报告由现有 `audit_retention_days` 统一清理。升级后应确认旧 XML ID
`agui_chat_import.ir_cron_process_x2many_import_jobs` 已不存在。

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
在该状态下不可用。必须使用非管理员账号测试每条策略，因为 HRP ACL、记录规则、当前
公司、筛选可见性和菜单可见性仍然生效。

当前 List/Kanban 报表不要求用户创建 `@筛选` 引用。浏览器会在命令准备前通过
`/agui_chat/report/source/bind` 绑定当前 BasicModel 的完整范围；AgentOS 只看到范围类型、
勾选数量、schema、统计和有界样例。绑定请求最多 256 KiB，勾选最多 5000 条；明细数据集
最多 100000 行、30 字段、16 个 8 MiB 分片、100 MiB 原始内容和 128 MiB 估算展开内存。
超过限制时应缩小页面筛选或取消勾选；只有用户明确接受时才改用 Odoo 聚合模式。

生产部署需包含 `deploy/agentos/skills/odoo-current-view-report/`，并保持技能目录及资源不可被
组或其他用户写入。Daytona Snapshot 必须使用仓库 `docker/sandbox-tools` 镜像，其中锁定
Matplotlib、WeasyPrint 和 Noto CJK 字体。最终脚本经一次确认执行，按
`agui.odoo.report.skill.v1` 写入
`报表/生成结果/<report-uuid>/分析报告.pdf`；PDF 只在完整成功后原子出现。历史
`reports/...` 文件不迁移。原始 JSONL 禁止通过模型文本读取工具读取，但所属用户仍可通过
工作区下载接口下载。

## 部署

Python 模块和带版本的 React 前端包必须一起部署，随后清理旧资源缓存。模块与前端包
版本不匹配时，握手失败并保持聊天关闭。

AgentOS 保留内置 `/health` 存活端点。流量就绪检查使用 `/ready`，只有 PostgreSQL
可访问、沙箱注册表初始化完成且 HMAC 密钥至少为 32 字节时才返回成功。Compose 使用
`/ready`，并自动重启 Agent 服务。

Agent 镜像安装 pandas、openpyxl、matplotlib 和 Plotly；Daytona sandbox-tools 镜像安装
最终 PDF 报表所需的 Matplotlib、WeasyPrint 和 Noto CJK 字体。
`agentos_dev/requirements.txt` 变化后必须重建镜像，不要在运行中的生产容器内交互安装
这些依赖。

<a id="isolated-workspaces"></a>

## 隔离部署

AgentOS 与 Daytona 现在是两个独立 Compose 项目，不共享容器网络、项目名或数据卷：

- 根目录 `docker-compose.yml` 只运行 AgentOS 和 `agent-db`。
- `docker/docker-compose.yaml` 按 Daytona OSS `v0.189.0` 官方 Compose 运行完整 Daytona
  服务，包括 SSH Gateway、PgAdmin、Registry UI、MailDev、Jaeger 和 OTel Collector。

<a id="compose-volume-migration"></a>

### 旧 Compose 数据卷

两套 Compose 为数据卷设置了稳定前缀，默认分别为 `agentos_` 和 `daytona_`。从默认项目名为
`agui-daytona` 的旧统一 Compose 升级时，在首次启动拆分后的服务前设置：

```dotenv
# 根目录 .env
AGENTOS_VOLUME_PREFIX=agui-daytona_

# docker/.env
DAYTONA_VOLUME_PREFIX=agui-daytona_
```

这样 AgentOS 和 Daytona 会直接复用旧具名卷，而不是创建空数据库。旧部署使用自定义
`COMPOSE_PROJECT_NAME` 时，将 `agui-daytona_` 替换为原项目名加下划线。确认备份和卷内容后
再启动；PgAdmin 是新增服务，没有旧卷时会正常创建自己的卷。

复用旧卷时还必须从旧 `.env` 保留相匹配的 AgentOS 数据库密码，以及全部 Daytona 加密密钥、
Runner Token、数据库/Redis/Registry/MinIO 密码、Dex 哈希和服务密钥。将 Daytona 变量复制到
新的 `docker/.env`，不要对已有卷运行持久化凭据轮换；只改环境文件不会更新卷内数据库用户或
已加密数据。凭据不完整时应先恢复旧环境备份，不能用新生成的密码尝试启动旧卷。

Daytona 使用 AGPL-3.0 许可证。通过网络向用户提供修改后的 Daytona 服务时，需要按
AGPL-3.0 向这些用户提供对应源代码，并保存源码修订版本和容器来源。

### 要求与密钥

至少分配 4 GB 内存，运行沙箱生命周期前建议使用 8 GB。Runner 使用特权 DinD，仍具有较高
宿主机权限，应部署在专用主机或虚拟机上。默认只把 API/Dashboard、Proxy 和 Dex 发布到
宿主机；已发布端口监听 `0.0.0.0`，公网部署必须增加防火墙、TLS 和访问控制。

AgentOS 根目录 `.env` 包含模型 API Key、AgentOS PostgreSQL 密码、工作区 HMAC、宿主与
容器使用的 Daytona API 地址、技能目录可信 UID 和 Dashboard 创建的 `DAYTONA_API_KEY`。
Daytona 的独立凭据全部位于 `docker/.env`。
HMAC、加密、Proxy、健康检查、Runner 和 SSH Gateway API Key 使用 32 字节随机值，服务密码
使用 12 位 Base64URL 值；SSH 密钥长度由算法决定。

两套环境分别初始化：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example --profile setup \
  run --build --rm env-init

HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file docker/.env.example \
  -f docker/docker-compose.yaml --profile setup \
  run --build --rm env-init
```

两个 setup 容器均只挂载项目目录并使用 `network_mode: none`；`--rm` 只删除临时容器，不
删除环境文件或数据卷。已有环境文件会备份到各自的 `.env.backups/` 目录；不要在已有数据卷
运行时盲目轮换 Daytona 加密密钥、Runner Token 或数据库密码。

AgentOS setup 会移除默认技能目录的组写和其他用户写权限，并把目录所有者写入
`AGENT_SKILLS_TRUSTED_UID`。自定义技能目录必须由运维方执行同等权限约束，并显式配置其
所有者 UID；校验失败时 AgentOS 会拒绝启动。

在 HRP 中，将 AgentOS HMAC 配置为仅服务端可见的系统参数，并将 AgentOS 地址设置为
`http://127.0.0.1:7777` 或宿主机可访问的实际地址。

<a id="first-start"></a>

### 首次启动

先验证并启动 Daytona：

```bash
docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml config
docker compose --env-file docker/.env \
  -f docker/docker-compose.yaml up -d
```

打开 `http://127.0.0.1:33043/dashboard`，使用配置的 Dex 用户登录，激活默认 Snapshot，
创建具有沙箱创建、写入和删除权限的 API Key，将它写入根目录 `.env` 的 `DAYTONA_API_KEY`。

然后启动独立 AgentOS：

```bash
docker compose config
docker compose up -d --build
```

AgentOS 容器通过 `host.docker.internal:33043` 访问 Daytona API，根目录宿主 Python 进程则
使用 `.env` 中的 `http://127.0.0.1:33043/api`。AgentOS Compose 会将 `host.docker.internal`
和 `proxy.localhost` 映射到宿主机网关，因此不需要加入 Daytona 网络。

远程部署必须在 `docker/.env` 设置 `DAYTONA_PUBLIC_HOST`；跨机器访问还需设置
`DAYTONA_PUBLIC_SCHEME=https`、`DAYTONA_PROXY_DOMAIN`，并为 Proxy 配置通配 DNS 和证书。
普通远程 HTTP 页面无法使用 `Crypto.subtle`，不能把关闭 TLS 当作生产方案。

端口、辅助服务和运维命令见 [Daytona 完整部署说明](../docker/README.md)。

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
- 业务命令处理器始终使用当前 HRP 用户，不使用 `sudo`，并在保存点内执行。处理失败时
  回滚业务写入。
- 宿主快照不发送二进制字段和密钥。审计详情会递归脱敏并限制大小。
- 会话保存使用 `expectedSessionRevision` 和 `SELECT ... FOR UPDATE`。

## 故障验收

注入 AgentOS 401、403、429、500、非 SSE 响应、异常或超大事件、连接中断和超时。
同时测试前端包缺失、握手不匹配、onchange 或保存失败、过期控制器、重复工具事件、重放
令牌和多标签页会话冲突。

所有情况下，HRP 导航、表单编辑、onchange、校验、保存和丢弃都必须保持可用。
WebClient 启动不得等待聊天。系统必须始终只有一个 React 根节点、一个活动 run 和一个
会话保存队列。

使用以下命令运行负载基线：

```bash
node scripts/agui_sse_load.js https://odoo.example.com/contract-review/agui 200
```

生产目标是传输错误率低于 1%，且浏览器中止的 run 能及时释放上游连接。
