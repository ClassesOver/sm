# Sandbox Provider 抽象设计

## 状态

设计已确认，待实现计划和代码实现。

## 背景

当前 Reporting Workflow 通过 `WorkspaceService` 直接调用 Daytona SDK。工作区的创建、复用、销毁、文件操作和前后台进程会话都依赖 Daytona 的对象模型，导致执行后端和工作流业务逻辑耦合。目标是在不拆分 Workflow 的前提下，引入可替换的 Daytona 与自托管容器后端，并覆盖 Ubuntu 和 openEuler 的生产部署。

本设计参考了 PandasAI DockerSandbox 的长期容器、exec 和文件归档传输模型；参考 openEuler 官方 iSulad、CRI、Kata Containers 和 StratoVirt 的本地安全容器能力。参考资料只用于确认运行时边界，业务安全策略仍以本仓库现有 WorkspaceService 契约为准。

## 目标与非目标

目标：

- Workflow、Reporting 状态机和工具契约不按 provider 分叉。
- `WorkspaceService` 继续作为路径校验、权限边界、大小限制、哈希、幂等和验收逻辑的唯一业务门面。
- Daytona 和自托管容器使用统一的 sandbox、文件系统、执行和后台会话契约。
- Ubuntu 和 openEuler 通过本机容器引擎提供生产可用的自托管模式。
- provider 资源可持久化、可恢复、可观测，并在后端不可用时失败关闭。

非目标：

- 不在 AgentOS 业务进程内直接执行宿主机命令。
- 不使用 Docker-in-Docker 作为生产架构。
- 不复制三套 Workflow 或三套 WorkspaceService 安全逻辑。
- 不因某个 provider 暂时不可用而静默切换到另一个 provider。

## 术语与分层

顶层只保留两个真正不同的控制面后端：

```text
SandboxProvider
  - DaytonaProvider
  - ContainerProvider
```

Docker、iSulad 和 containerd 是 `ContainerProvider` 的引擎适配器，而不是同级业务 provider：

```text
ContainerProvider
  - DockerEngineAdapter
  - ISuladEngineAdapter
  - ContainerdEngineAdapter
```

`Local` 表示自托管、本地基础设施部署形态，不表示在 Python 进程内执行本机 `subprocess`。历史上若需要保留 `docker` 配置值，可以将其作为 `container + engine=docker` 的兼容别名，但不得保留第二套生命周期实现。

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
  | DaytonaProvider      | ContainerProvider    |
  | Daytona SDK/API      | Engine Adapter       |
  +----------------------+----------------------+
                                  |
                    Docker / iSulad / containerd
                                  |
                    runc / Kata / gVisor / StratoVirt
```

Workflow 不得看到 Daytona SDK、Docker SDK、iSulad API、本机路径、`Popen` 或容器对象。provider 返回不透明的领域引用和规范化结果。

## 领域契约

### 资源引用

```text
SandboxRef:
  provider: daytona | container
  engine: optional
  runtime: optional
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
- `health_check`：只读检查控制面、引擎和必要 runtime 是否可用。
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

### DockerEngineAdapter

参考 PandasAI DockerSandbox：

- 每个 thread 使用一个长期运行的 sandbox 容器。
- 使用固定 digest 的工具镜像，容器以待执行状态运行。
- 文件通过受控容器 API 或归档流传输。
- 命令通过 exec/attach 执行，支持同步命令、后台会话和 PTY。
- 默认无网络、只读 rootfs、独立 workspace、丢弃 capabilities 和资源限制。

Docker socket 不得直接挂入 AgentOS 或 sandbox 容器。

### ISuladEngineAdapter

openEuler 本地后端优先使用 iSulad 的 gRPC/REST/CRI 能力，安全容器使用 Kata 或 StratoVirt runtime。iSulad 官方文档覆盖 CRI、Exec、Attach、资源限制、TLS 和 authz-broker。

该适配器需要验证目标 openEuler 版本、CPU 架构、iSulad API、CNI、存储驱动和 Kata/StratoVirt 的 KVM 条件，不假设所有版本具有相同默认配置。

### ContainerdEngineAdapter

作为 Ubuntu 和 Kubernetes 部署的优先本地引擎适配器。隔离 runtime 可按部署选择 runc、Kata 或 gVisor；Kata/gVisor 的具体能力由 provider capability 预检结果决定。

## 容器化部署边界

```text
reporting-os
  -> sandbox-gateway
    -> Docker / iSulad / containerd
      -> thread sandbox container
```

gateway 可以是受保护的 sidecar 或宿主机服务。只有 gateway 持有容器引擎凭据或 socket，并且只暴露类型化 sandbox API；AgentOS 不获得任意容器 API 权限。会话流式传输优先使用带认证的 gRPC，健康和管理接口可以提供受限 HTTP API。

不采用 Docker-in-Docker。AgentOS 容器中的 provider 只访问 gateway，隔离运行时由宿主机容器引擎创建。

## 操作系统部署 profile

Ubuntu：

```text
ContainerProvider
  engine=containerd 或 docker
  runtime=kata 或 gvisor
```

openEuler：

```text
ContainerProvider
  engine=isulad 或 containerd
  runtime=kata 或 stratovirt
```

openEuler 官方仓库在 22.03 LTS SP4 和 24.03 LTS 的 x86_64/aarch64 索引中提供 bubblewrap、runc、crun、containerd、Kata、StratoVirt 和 Docker 相关包。Docker Engine 版本需要单独进行 API 和安全验证。nsjail 未发现官方预构建包，不作为 openEuler 的开箱默认。

## 持久化、幂等与恢复

现有 registry 从 `thread_hash -> sandbox_id` 扩展为包含 `provider`、`engine`、`runtime`、`node`、`resource_id` 和 `generation` 的绑定记录。具体数据库迁移必须保持 PostgreSQL-only 约束。

规则：

- provider、engine 和 runtime 在绑定期间固定。
- 切换后端必须显式迁移或销毁重建。
- 数据库锁是 thread 资源绑定的并发权威；内存缓存只用于加速。
- 创建、销毁、恢复和清理使用幂等键。
- 资源丢失时执行确定性的重建或隔离，不能复用未知资源。
- 进程会话引用与 sandbox generation 绑定，防止跨 workspace 重放。

## 安全基线

所有容器引擎都必须在创建前完成预检并失败关闭：

- namespaces、cgroups（优先 cgroup v2）、seccomp 和 overlayfs 可用。
- sandbox 不使用 privileged，不挂载 Docker/iSulad socket、D-Bus 或任意宿主目录。
- 默认关闭网络；allowlist 只能通过已验证的 egress proxy/CNI 策略实现。
- rootfs 只读，workspace 是唯一业务可写区域。
- 限制 CPU、内存、PIDs、文件描述符、磁盘和输出大小。
- 使用镜像 digest、非特权用户、capability drop 和 provider 默认 seccomp。
- gateway 使用 TLS/mTLS 或权限受限 Unix socket，并记录结构化审计事件。

Kata/StratoVirt 还必须检查 `/dev/kvm`、guest kernel、VMM、存储驱动和目标架构。无法满足隔离基线时不得回退到宿主机或无保护模式。

## 高可用模型

### 远程 HA

DaytonaProvider 使用外部控制面和共享持久化组件，AgentOS 可以多副本部署。workspace 资源由 provider 负责恢复和清理。

### 自托管 HA

ContainerProvider 需要 Kubernetes 或等价 placement control plane：

```text
AgentOS 多副本
  -> ContainerProvider control plane
    -> 多个 Ubuntu/openEuler 节点
      -> Docker/containerd/iSulad
        -> sandbox Pod/container
```

openEuler 可以利用 iSulad 的 CRI 接入 Kubernetes。workspace 使用 PVC、共享存储或对象存储快照。节点故障时恢复文件状态并重建 sandbox；运行中的进程和 PTY 会话不承诺跨节点迁移。

单节点 Docker/iSulad 只能标记为 `node_scoped`，不得宣称企业 HA。

## 迁移和实施顺序

1. 定义 provider 领域类型、能力模型、统一错误和引用结构。
2. 添加 fake provider 与 provider contract tests。
3. 将现有 Daytona 逻辑封装为 DaytonaProvider，行为保持不变。
4. 迁移 Workflow 中直接访问 Daytona SDK 对象的调用。
5. 实现 ContainerProvider 和 sandbox-gateway。
6. 实现 DockerEngineAdapter，覆盖 PandasAI 生命周期、归档传输和 exec 模型。
7. 实现 Ubuntu 的 Docker/containerd 后端和 Kata/gVisor 预检。
8. 实现 openEuler 的 iSulad + Kata/StratoVirt 后端。
9. 增加 workspace 快照、节点放置、reconciler 和 HA 故障恢复。
10. 删除 Daytona 专属的上层字段、旧入口和无效适配代码。

## 验证策略

- provider contract tests 覆盖正常、超时、资源丢失、能力不支持、重复创建和重复销毁。
- Daytona、Docker、iSulad、containerd 场景使用隔离集成测试并标记 `integration`。
- PostgreSQL registry 的迁移、锁、重启恢复和并发绑定使用 PostgreSQL 集成测试。
- Local/Container 预检覆盖内核能力缺失、`/dev/kvm` 缺失、runtime 不匹配、网络策略不可用和权限错误。
- 迁移期间先运行现有 WorkspaceService、task_execution 和 Reporting Workflow 定点测试，再按跨模块风险扩大。

## 参考资料

- PandasAI Docker sandbox：`https://github.com/sinaptik-ai/pandas-ai/tree/main/extensions/sandbox/docker`
- openEuler Secure Container：`https://github.com/openeuler-mirror/docs/blob/master/docs/en/docs/Container/secure-container.md`
- openEuler CRI：`https://github.com/openeuler-mirror/docs/blob/master/docs/en/docs/Container/cri.md`
- openEuler iSulad：`https://github.com/openeuler-mirror/iSulad`
- Kata Containers：`https://github.com/kata-containers/kata-containers`
- Bubblewrap：`https://github.com/containers/bubblewrap`
- NsJail：`https://github.com/google/nsjail`
