# local-sandboxd 部署

`local-sandboxd` 是独立宿主服务，不是 AgentOS 容器的 sidecar。AgentOS 仅通过 Unix socket
或 mTLS HTTPS 访问它；禁止向 AgentOS 挂载 Docker、iSulad、containerd socket、D-Bus 或宿主目录。

部署前由管理员离线准备只读 rootfs、Python 3.12 dependency bundle、SBOM、manifest、
seccomp BPF 和 Ed25519 签名 catalog。生产节点必须启用 user namespace、cgroup v2 和 seccomp，
并安装 bubblewrap；任一项预检失败时 daemon 不启动。

支持的宿主基线为 Ubuntu 22.04/24.04 和 openEuler 22.03 LTS SP4/24.03 LTS，架构按 catalog
分别发布 `x86_64` 或 `aarch64` 制品。内核至少需要 `CONFIG_USER_NS`、`CONFIG_NAMESPACES`、
`CONFIG_CGROUPS`、`CONFIG_SECCOMP` 和 `CONFIG_SECCOMP_FILTER`。profile 名不改变隔离协议，
也不会在预检失败时自动切换发行版或降级为宿主进程执行。

dependency bundle 必须包含与 AgentOS 完全相同的
`smart_reporting.reporting.delivery.report_runtime` 包，以及锁定版本的 pandas、numpy、polars、
matplotlib、pypdf、WeasyPrint、python-docx 等 Reporting 依赖。rootfs 还必须包含 Poppler
`pdftoppm`、LibreOffice/soffice、WeasyPrint 所需动态库和经审核的中英文字体。运行器固定使用
`python3 -I -B`；`-I` 会忽略 `PYTHONPATH`，因此 rootfs 的系统 site-packages 必须通过管理员
创建的只读 `.pth` 文件暴露 `/opt/reporting-deps`。启动后报表运行时会逐文件复算摘要，版本不一致
直接拒绝，不会上传代码、联网安装依赖或回退到宿主 site-packages。

配置文件需包含 `node_id`、`profile`、`arch`、`catalog_path`、`artifact_root`、
`catalog_public_key`、`workspace_root`、`cgroup_root`、`seccomp_path` 和 `listener`。
UDS 示例为 `unix:///run/local-sandboxd/local-sandboxd.sock`。HTTPS 必须同时配置服务端证书、
私钥与客户端 CA，并要求客户端证书。

安装流程：

1. 创建不可登录的 `local-sandboxd` 用户，并准备上述只读制品与可写 workspace 目录。
   cgroup v2 根必须由 systemd `Delegate=yes` 委派给该服务，不能通过放宽整个宿主 cgroup 树权限替代。
2. 将配置写入 `/etc/local-sandboxd/config.json`，权限设为 `0600`。
3. 安装 `local-sandboxd.service`，执行 `systemctl daemon-reload && systemctl enable --now local-sandboxd`。
4. AgentOS 配置 `SANDBOX_PROVIDER=local` 及对应 profile、endpoint、rootfs digest；内网不执行 `pip install`。

每次执行使用独立 pid/net/mount/user namespace 和私有 `tmpfs /tmp`，workspace 是唯一业务可写
挂载。当前 cgroup 以 workspace 为资源单元，因此同一 workspace 的脚本由 daemon 串行执行，
不同 workspace 可并行。网络固定关闭，请求不能传入解释器、环境变量、rootfs、bundle ID 或宿主路径。

AgentOS 本身运行在 Docker 中时，推荐让容器通过内网 HTTPS+mTLS 访问宿主或专用节点上的 daemon；
不得使用 `--privileged`，不得挂载 Docker/iSulad/containerd socket、D-Bus 或 workspace 宿主目录。
UDS 模式只可挂载 `/run/local-sandboxd/local-sandboxd.sock` 这一个权限受限的 socket。

当前实现是单 endpoint、node-scoped，节点故障不会自动恢复 workspace。跨节点 HA 需要另行提供
多副本 control plane、共享存储或已验证快照、generation 恢复、PostgreSQL leader election 和
审计链路；在这些条件落地前，企业 HA 应选择 DaytonaProvider。进程级 namespace 隔离也不等同于
虚拟机安全边界，高风险或跨信任域租户仍应选择 DaytonaProvider。
