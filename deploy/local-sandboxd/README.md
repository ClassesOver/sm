# local-sandboxd 部署

`local-sandboxd` 是独立宿主服务，不是 AgentOS 容器的 sidecar。AgentOS 仅通过 Unix socket
或 mTLS HTTPS 访问它；禁止向 AgentOS 挂载 Docker、iSulad、containerd socket、D-Bus 或宿主目录。

部署前由管理员离线准备只读 rootfs、Python 3.12 dependency bundle、SBOM、manifest、
seccomp BPF 和 Ed25519 签名 catalog。生产节点必须启用 user namespace、cgroup v2 和 seccomp，
并安装 bubblewrap；任一项预检失败时 daemon 不启动。

配置文件需包含 `node_id`、`profile`、`arch`、`catalog_path`、`artifact_root`、
`catalog_public_key`、`workspace_root`、`cgroup_root`、`seccomp_path` 和 `listener`。
UDS 示例为 `unix:///run/local-sandboxd/local-sandboxd.sock`。HTTPS 必须同时配置服务端证书、
私钥与客户端 CA，并要求客户端证书。

安装流程：

1. 创建不可登录的 `local-sandboxd` 用户，并准备上述只读制品与可写 workspace/cgroup 目录。
2. 将配置写入 `/etc/local-sandboxd/config.json`，权限设为 `0600`。
3. 安装 `local-sandboxd.service`，执行 `systemctl daemon-reload && systemctl enable --now local-sandboxd`。
4. AgentOS 配置 `SANDBOX_PROVIDER=local` 及对应 profile、endpoint、rootfs digest；内网不执行 `pip install`。

进程级 namespace 隔离不等同于虚拟机安全边界。高风险或不可信租户仍应选择 DaytonaProvider。
