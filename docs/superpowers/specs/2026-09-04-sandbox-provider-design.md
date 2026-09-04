# Sandbox Provider 抽象设计

## 状态

设计已更新为内网 LocalProvider 方案，待用户审阅后进入实现计划。

## 背景

当前 Reporting Workflow 通过 `WorkspaceService` 直接调用 Daytona SDK。工作区的创建、复用、销毁、文件操作和前后台进程会话都依赖 Daytona 的对象模型，导致执行后端和工作流业务逻辑耦合。目标是在不拆分 Workflow 的前提下，引入可替换的 Daytona 与内网自托管本地进程沙箱后端，并覆盖 Ubuntu 和 openEuler 的生产部署。

本设计借鉴了 PandasAI DockerSandbox 的长期 workspace、exec 和文件归档传输契约，但不复用容器实现；本地后端改为由 `local-sandboxd` 使用 Linux namespaces、cgroup v2 和 seccomp 创建进程沙箱。参考资料只用于确认运行时边界，业务安全策略仍以本仓库现有 WorkspaceService 契约为准。

## 目标与非目标

目标：

- Workflow、Reporting 状态机和工具契约不按 provider 分叉。
- `WorkspaceService` 继续作为路径校验、权限边界、大小限制、哈希、幂等和验收逻辑的唯一业务门面。
- Daytona 和自托管本地进程沙箱使用统一的 sandbox、文件系统、执行和后台会话契约。
- Ubuntu 和 openEuler 通过 Linux 内核进程沙箱提供生产可用的自托管模式。
- provider 资源可持久化、可恢复、可观测，并在后端不可用时失败关闭。

非目标：

- 不在 AgentOS 业务进程内直接执行宿主机命令；命令只能经 `local-sandboxd` 受控执行。
- 不把 Docker、iSulad、containerd 或 Docker-in-Docker 作为本地沙箱实现。
- 不复制三套 Workflow 或三套 WorkspaceService 安全逻辑。
- 不因某个 provider 暂时不可用而静默切换到另一个 provider。

## 术语与分层

顶层只保留两个真正不同的控制面后端：

```text
SandboxProvider
  - DaytonaProvider
  - LocalProvider
```

`LocalProvider` 直接内置 Ubuntu 和 openEuler 两个生产 profile；两者都使用同一个本地
进程沙箱适配器，profile 只固定发行版支持矩阵、内核预检和根文件系统包：

```text
LocalProvider
  - UbuntuProfile
      - LinuxProcessSandboxAdapter
      - Ubuntu rootfs bundle
  - OpenEulerProfile
      - LinuxProcessSandboxAdapter
      - openEuler rootfs bundle
```

`Local` 表示内网自托管、本地基础设施部署形态，不表示在 Python 进程内执行本机
`subprocess`。`LocalProvider` 只通过内网 mTLS 或受限 Unix socket 调用
`local-sandboxd`；发行版 profile 固定内核能力、沙箱工具链和 rootfs，不允许部署方自由组合。

## 架构

```text
Reporting Workflow
        |
  WorkspaceService
  路径、权限、哈希、幂等、验收
        |
  SandboxProvider
        |
  +----------------------+----------------------+
  | DaytonaProvider      | LocalProvider        |
  | Daytona SDK/API      | local-sandboxd API   |
  +----------------------+----------------------+
                                  |
                         Linux process sandbox
                    (namespaces + cgroup v2 + seccomp)
```

Workflow 不得看到 Daytona SDK、本机路径、`Popen`、容器 API 或 sandboxd 对象。provider 返回不透明的领域引用和规范化结果。

## 领域契约

### 资源引用

```text
SandboxRef:
  provider: daytona | local
  isolation: provider_managed | linux_process
  node: optional
  resource_id
  generation

SessionRef:
  sandbox_ref
  provider_session_id
```

`resource_id` 和 `provider_session_id` 只能由对应 provider 解释。持久化状态不得使用 `daytona_session_id` 等后端专属字段。

### Provider 端口

必需操作：

- `ensure_workspace`：按 thread 绑定幂等创建或恢复 workspace。
- `get_workspace`：根据持久化引用取得当前资源并检查状态。
- `destroy_workspace`：幂等销毁资源及其会话。
- `health_check`：只读检查控制面、内核能力和必要 sandbox 工具是否可用。
- `capabilities`：声明持久会话、PTY、网络策略、分支复制、资源限制和快照能力。

`SandboxHandle` 按职责提供：

- filesystem：`stat`、`list`、`read`、`write`、`delete`、`copy`、`move`。
- execution：受超时、输出和工作目录约束的同步命令。
- sessions：后台命令启动、轮询、输入、PTY 中断和停止。

不支持的能力必须返回统一的 `SandboxCapabilityUnsupported`，不得隐式降级到宿主机执行。

## Provider 设计

### DaytonaProvider

- 封装现有 Daytona client、sandbox state、thread label 和 PostgreSQL registry。
- 保持当前 sandbox 恢复、隔离、清理和重建语义。
- 将 `DaytonaNotFoundError` 等 SDK 异常转换为统一 provider 错误。
- 作为远程生产 HA 的默认 provider。

现有 Daytona Compose 是单套部署基线，不自动等于 HA。HA 部署需要多副本 API/Runner、共享 PostgreSQL、Redis、对象存储和 Registry。

### LinuxProcessSandboxAdapter

`LocalProvider` 的唯一执行适配器。每个 thread 对应一个长期存活的 sandbox 进程组，文件和会话契约沿用现有 `WorkspaceService` 约束：

- `local-sandboxd` 为每个 workspace 创建独立的 user、mount、pid 和 net namespace。
- 使用固定摘要的 rootfs bundle 和工具链；rootfs 只读，workspace 是唯一可写目录。
- 通过 cgroup v2 限制 CPU、内存、PIDs、文件描述符、磁盘和输出；通过 seccomp 过滤系统调用。
- 命令经受控 exec/attach 通道执行，支持同步命令、后台会话和 PTY。
- 默认无网络；需要访问内网服务时，只能走显式 allowlist 的 egress proxy。

`local-sandboxd` 是唯一可以创建沙箱进程的组件。它不得接受任意 shell、任意宿主路径或未注册的环境变量，并且必须把 workspace、进程和审计事件绑定到 `thread` 与 `generation`。

进程级沙箱不等同于 Kata/VM。对最高风险的任意不可信代码，应继续使用 Daytona 或其他经过独立验证的强隔离后端；LocalProvider 的适用范围必须由租户策略显式控制。

## 内网部署边界

```text
reporting-os (container)
        |
  LocalProvider
        |  mTLS / restricted Unix socket
        v
  local-sandboxd (dedicated node service)
        |
  Linux process sandbox
```

AgentOS 及其业务容器不直接执行宿主机命令，也不挂载 Docker、iSulad、containerd、D-Bus 或任意宿主目录。`local-sandboxd` 可部署为专用 systemd 服务；若基础设施要求所有服务均容器化，只允许使用单独的受限服务容器，并通过用户命名空间和 cgroup delegation 访问宿主机内核能力，不得使用 `--privileged`。

内网接口只允许服务身份认证、最小权限和固定 API schema。会话流优先使用带 mTLS 的 gRPC；健康检查和管理接口使用独立的只读端点。禁止公网暴露，禁止 provider 不可用时回退到 AgentOS 容器内的本地 `subprocess`。

## 配置模板与操作系统 profile

`LocalProvider` 直接提供两个固定生产 profile，不要求部署方自由组合沙箱工具和安全策略：

| profile | 内核与工具链基线 | rootfs | 选择理由 |
| --- | --- | --- | --- |
| `ubuntu` | Ubuntu 22.04/24.04；user/mount/pid/net namespace、cgroup v2、seccomp；bubblewrap 或等效受控启动器 | Ubuntu 固定版本 rootfs bundle | 社区工具链成熟，便于现有 Ubuntu 节点开箱部署。 |
| `openeuler` | openEuler 22.03 LTS SP4/24.03 LTS；同等 namespace、cgroup v2、seccomp 能力；优先使用发行版提供的 bubblewrap | openEuler 固定版本 rootfs bundle | 满足国产系统和 x86_64/aarch64 适配要求，不绑定容器引擎。 |

配置模板只暴露稳定的控制面、profile 和 rootfs 字段：

```text
SANDBOX_PROVIDER=daytona|local
SANDBOX_LOCAL_PROFILE=ubuntu|openeuler       # provider=local 时必填
SANDBOX_LOCAL_ENDPOINT=unix:///run/local-sandboxd.sock  # 或内网 mTLS 地址
SANDBOX_ROOTFS_DIGEST=sha256:...              # 固定 rootfs bundle
```

字段约束：

- `SANDBOX_PROVIDER=daytona` 时使用现有 Daytona 配置；Local 专属字段不得参与资源创建。
- `SANDBOX_PROVIDER=local` 时，`SANDBOX_LOCAL_PROFILE`、`SANDBOX_LOCAL_ENDPOINT` 和 `SANDBOX_ROOTFS_DIGEST` 必须存在并通过格式校验。
- `SANDBOX_LOCAL_PROFILE=ubuntu` 或 `openeuler` 只决定受支持的发行版、工具链和内核预检集合；执行协议保持一致。
- namespace、cgroup、seccomp、网络禁用、rootfs 只读和资源上限由 profile 与策略文件固定，不能通过环境变量覆盖。
- profile 预检失败时启动失败关闭，不自动切换另一发行版、启动器或安全策略。

`nsjail` 和 bubblewrap 仅是沙箱构造工具，不代表完整安全策略。没有官方预构建包或未完成独立验证的工具不得进入默认 profile；不得在运行时静默降级到裸 `subprocess`。

## 持久化、幂等与恢复

现有 registry 从 `thread_hash -> sandbox_id` 扩展为包含 `provider`、`isolation`、`node`、`resource_id` 和 `generation` 的绑定记录。具体数据库迁移必须保持 PostgreSQL-only 约束。

规则：

- provider、isolation 和 node placement 在绑定期间固定。
- 切换后端必须显式迁移或销毁重建。
- 数据库锁是 thread 资源绑定的并发权威；内存缓存只用于加速。
- 创建、销毁、恢复和清理使用幂等键。
- 资源丢失时执行确定性的重建或隔离，不能复用未知资源。
- 进程会话引用与 sandbox generation 绑定，防止跨 workspace 重放。

## 安全基线

所有本地沙箱进程都必须在创建前完成预检并失败关闭：

- user/mount/pid/net namespaces、cgroup v2、seccomp 和 user namespace delegation 可用。
- `local-sandboxd` 不使用 `--privileged`，不挂载 Docker/iSulad/containerd socket、D-Bus 或任意宿主目录。
- 默认关闭网络；allowlist 只能通过已验证的 egress proxy 策略实现。
- rootfs bundle 只读，workspace 是唯一业务可写区域。
- 限制 CPU、内存、PIDs、文件描述符、磁盘和输出大小。
- 使用 rootfs digest、非特权用户、capability drop 和 provider 默认 seccomp。
- `local-sandboxd` 使用 TLS/mTLS 或权限受限 Unix socket，并记录结构化审计事件。
- 节点必须启用 `CONFIG_USER_NS`、`CONFIG_NAMESPACES`、`CONFIG_CGROUPS`、`CONFIG_SECCOMP` 和 `CONFIG_SECCOMP_FILTER`；缺失任一能力时拒绝创建。

无法满足隔离基线时不得回退到宿主机或无保护模式。对需要 VM 级隔离的租户，必须显式选择 Daytona 等强隔离 provider。

## 高可用模型

### 远程 HA

DaytonaProvider 使用外部控制面和共享持久化组件，AgentOS 可以多副本部署。workspace 资源由 provider 负责恢复和清理。

### 内网 LocalProvider HA

LocalProvider 需要内网 control plane 或等价 placement service：

```text
AgentOS 多副本
  -> LocalProvider control plane
    -> 多个 Ubuntu/openEuler 节点
      -> local-sandboxd
        -> Linux process sandbox
```

workspace 使用共享存储或对象存储快照；rootfs bundle 在节点间按 digest 分发。节点故障时恢复文件状态并重建 sandbox；运行中的进程和 PTY 会话不承诺跨节点迁移。

单节点 `local-sandboxd` 只能标记为 `node_scoped`，不得宣称企业 HA。LocalProvider control plane、registry、共享存储和审计链路均需多副本或明确的 RPO/RTO。

## 迁移和实施顺序

1. 定义 provider 领域类型、能力模型、统一错误和引用结构。
2. 添加 fake provider 与 provider contract tests。
3. 将现有 Daytona 逻辑封装为 DaytonaProvider，行为保持不变。
4. 迁移 Workflow 中直接访问 Daytona SDK 对象的调用。
5. 实现 LocalProvider 与 `local-sandboxd` 的受限 API。
6. 实现 `LinuxProcessSandboxAdapter`，覆盖 rootfs、归档传输、exec、后台会话和 PTY 模型。
7. 实现 Ubuntu profile 的内核预检、namespace/cgroup/seccomp 策略和节点部署包。
8. 实现 openEuler profile 的内核预检、工具链适配和 x86_64/aarch64 节点部署包。
9. 增加 workspace 快照、节点放置、reconciler 和内网 HA 故障恢复。
10. 删除 Daytona 专属的上层字段、旧入口和无效适配代码。

## 验证策略

- provider contract tests 覆盖正常、超时、资源丢失、能力不支持、重复创建和重复销毁。
- Daytona 和 `local-sandboxd` 场景使用隔离集成测试并标记 `integration`。
- PostgreSQL registry 的迁移、锁、重启恢复和并发绑定使用 PostgreSQL 集成测试。
- Local 预检覆盖 namespace/cgroup/seccomp 能力缺失、rootfs digest 不匹配、网络策略不可用、权限错误和内网 mTLS 失败。
- 迁移期间先运行现有 WorkspaceService、task_execution 和 Reporting Workflow 定点测试，再按跨模块风险扩大。

## 参考资料

- PandasAI Docker sandbox（仅参考 workspace、exec 和归档契约，不采用容器实现）：`https://github.com/sinaptik-ai/pandas-ai/tree/main/extensions/sandbox/docker`
- Bubblewrap（仅作为 namespace 构造工具）：`https://github.com/containers/bubblewrap`
- NsJail（候选工具，未列入默认 profile）：`https://github.com/google/nsjail`
