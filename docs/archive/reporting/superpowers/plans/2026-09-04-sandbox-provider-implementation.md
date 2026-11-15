# Sandbox Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Reporting Workflow 提供 Daytona-compatible Provider SDK、DaytonaProvider 和可在 Ubuntu/openEuler 内网部署的 LocalProvider，使模型生成的 Python 脚本只能通过受控 PythonScriptRunner 执行。

**Architecture:** `WorkspaceService` 继续负责路径、权限、大小、哈希、幂等和验收；新的 `smart_reporting.sandbox` 包负责统一 DTO、Provider 生命周期、文件/进程 handle 和错误。DaytonaProvider 适配现有 SDK，LocalProvider 通过 UDS 或 mTLS HTTP 调用独立 `local-sandboxd`；daemon 使用固定 rootfs、只读 dependency bundle、namespace/cgroup/seccomp launcher 执行脚本，任何缺失能力都失败关闭。

**Tech Stack:** Python 3.12、Pydantic v2、FastAPI、HTTPX、Uvicorn、Daytona SDK 0.189.0、PostgreSQL、pytest/anyio、Ruff、Mypy、bubblewrap、cgroup v2、seccomp BPF。

---

## 文件结构

- `smart_reporting/sandbox/contracts.py`：Provider DTO、能力、状态与异步 Protocol。
- `smart_reporting/sandbox/errors.py`：统一稳定错误码及后端异常映射基类。
- `smart_reporting/sandbox/daytona.py`：Daytona 0.189.0 生命周期、文件与进程适配器。
- `smart_reporting/sandbox/factory.py`：根据已校验配置装配唯一 Provider。
- `smart_reporting/sandbox/local/config.py`：Local endpoint、profile、TLS、rootfs 和资源策略。
- `smart_reporting/sandbox/local/client.py`：UDS/mTLS 控制面客户端及 Daytona-compatible handle。
- `smart_reporting/sandbox/local/catalog.py`：离线 dependency bundle 清单、签名摘要和 ABI 选择。
- `smart_reporting/sandbox/local/preflight.py`：Ubuntu/openEuler 内核、launcher、cgroup、seccomp 和制品预检。
- `smart_reporting/sandbox/local/runtime.py`：工作区、进程、日志游标和固定 Python argv 管理。
- `smart_reporting/sandbox/local/app.py`：`local-sandboxd` FastAPI 控制面。
- `smart_reporting/sandbox/local/__main__.py`：daemon 命令入口。
- `smart_reporting/workspace.py`：只把生命周期和 handle 来源切换到 Provider，保留现有安全逻辑。
- `smart_reporting/runtime/settings.py`、`smart_reporting/runtime/execution.py`、`smart_reporting/app.py`：失败关闭的 Provider 配置与装配。
- `smart_reporting/reporting/tools/toolkit.py`、`smart_reporting/reporting/tools/base.py`：模型工具由 `terminal` 收敛为 `run_python_script`。
- `smart_reporting/reporting/workflow/runtime/analysis.py`、`analysis_item_workflow.py`、`visualization_section_workflow.py`：结构化传递脚本路径或源码，不拼 shell 命令。
- `deploy/local-sandboxd/`：systemd、Ubuntu/openEuler 配置样例和 profile JSON。
- `smart_reporting/tests/sandbox/`：Provider、Local daemon、策略和契约单元测试。

### Task 1: Provider 领域契约和统一错误

**Files:**
- Create: `smart_reporting/sandbox/__init__.py`
- Create: `smart_reporting/sandbox/contracts.py`
- Create: `smart_reporting/sandbox/errors.py`
- Create: `smart_reporting/tests/sandbox/test_contracts.py`

- [ ] **Step 1: 写失败的 DTO 与错误契约测试**

```python
def test_workspace_binding_rejects_missing_scope() -> None:
    with pytest.raises(ValidationError):
        WorkspaceBinding.model_validate({"thread_id": "thread"})


def test_unsupported_capability_has_stable_code() -> None:
    error = SandboxCapabilityUnsupported("snapshot")
    assert error.code == "sandbox_capability_unsupported"
    assert error.details == {"capability": "snapshot"}
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `uv run pytest smart_reporting/tests/sandbox/test_contracts.py -q`
Expected: FAIL，`ModuleNotFoundError: smart_reporting.sandbox`。

- [ ] **Step 3: 实现最小领域类型和异步 Protocol**

```python
class WorkspaceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str = Field(min_length=1, max_length=256)
    user_id: str = Field(min_length=1, max_length=256)
    company_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=16, max_length=256)
    profile: str | None = Field(default=None, max_length=64)


class SandboxProvider(Protocol):
    async def ensure_workspace(self, binding: WorkspaceBinding) -> SandboxHandle: ...
    async def get_workspace(self, ref: SandboxRef, binding: WorkspaceBinding) -> SandboxHandle: ...
    async def destroy_workspace(self, ref: SandboxRef, binding: WorkspaceBinding) -> DestroyResult: ...
    async def health_check(self) -> ProviderHealth: ...
    async def capabilities(self) -> ProviderCapabilities: ...
```

- [ ] **Step 4: 验证测试和静态检查**

Run: `uv run pytest smart_reporting/tests/sandbox/test_contracts.py -q`
Expected: PASS。

Run: `uv run ruff check smart_reporting/sandbox smart_reporting/tests/sandbox/test_contracts.py`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/sandbox smart_reporting/tests/sandbox/test_contracts.py
git commit -m "feat: define sandbox provider contracts"
```

### Task 2: DaytonaProvider 适配现有 SDK

**Files:**
- Create: `smart_reporting/sandbox/daytona.py`
- Create: `smart_reporting/tests/sandbox/test_daytona_provider.py`
- Modify: `smart_reporting/sandbox/__init__.py`

- [ ] **Step 1: 写失败的生命周期、文件、会话和错误映射测试**

```python
@pytest.mark.anyio
async def test_daytona_provider_ensures_one_workspace_per_binding() -> None:
    provider = DaytonaProvider(client=FakeDaytonaClient(), snapshot="sandbox-tools")
    first = await provider.ensure_workspace(BINDING)
    second = await provider.ensure_workspace(BINDING)
    assert first.ref == second.ref
    assert first.ref.provider == "daytona"


@pytest.mark.anyio
async def test_daytona_not_found_is_normalized() -> None:
    provider = DaytonaProvider(client=MissingDaytonaClient(), snapshot="sandbox-tools")
    with pytest.raises(SandboxNotFound):
        await provider.get_workspace(REF, BINDING)
```

- [ ] **Step 2: 运行测试并确认缺少 DaytonaProvider**

Run: `uv run pytest smart_reporting/tests/sandbox/test_daytona_provider.py -q`
Expected: FAIL，无法导入 `DaytonaProvider`。

- [ ] **Step 3: 实现 Daytona 生命周期与 handle adapter**

```python
class DaytonaProvider:
    async def ensure_workspace(self, binding: WorkspaceBinding) -> SandboxHandle:
        label = self._binding_label(binding)
        sandbox = await self._find_or_create(label)
        return DaytonaSandboxHandle(sandbox, self._ref(sandbox, binding))

    async def destroy_workspace(self, ref: SandboxRef, binding: WorkspaceBinding) -> DestroyResult:
        self._require_binding(ref, binding)
        try:
            sandbox = await self._client.get(ref.resource_id)
            await self._client.delete(sandbox)
        except DaytonaNotFoundError:
            return DestroyResult(deleted=False)
        return DestroyResult(deleted=True)
```

适配器必须保留 `get_file_info/list_files/create_folder/upload_file/download_file_stream`、`exec/code_run` 和 session API 的 Daytona 语义，但只返回本仓库 DTO；任何 Daytona 类型和异常不能越过该文件。

- [ ] **Step 4: 验证 Daytona provider 定点测试**

Run: `uv run pytest smart_reporting/tests/sandbox/test_daytona_provider.py -q`
Expected: PASS。

Run: `uv run mypy smart_reporting/sandbox/daytona.py smart_reporting/sandbox/contracts.py`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/sandbox smart_reporting/tests/sandbox/test_daytona_provider.py
git commit -m "feat: add daytona sandbox provider"
```

### Task 3: Provider 配置、工厂和 PostgreSQL 绑定

**Files:**
- Create: `smart_reporting/sandbox/factory.py`
- Modify: `smart_reporting/runtime/settings.py`
- Modify: `smart_reporting/runtime/execution.py`
- Modify: `smart_reporting/app.py`
- Modify: `smart_reporting/workspace.py`
- Modify: `.env.example`
- Modify: `smart_reporting/.env.example`
- Test: `smart_reporting/tests/test_settings.py`
- Test: `smart_reporting/tests/test_workspace.py`
- Create: `smart_reporting/tests/sandbox/test_factory.py`

- [ ] **Step 1: 写失败的配置和绑定持久化测试**

```python
def test_local_provider_requires_profile_endpoint_and_digest() -> None:
    with pytest.raises(ValueError, match="SANDBOX_LOCAL_PROFILE"):
        settings(SANDBOX_PROVIDER="local")


def test_daytona_configuration_ignores_local_fields() -> None:
    current = settings(SANDBOX_PROVIDER="daytona", SANDBOX_LOCAL_PROFILE="invalid")
    assert current.sandbox_provider == "daytona"
```

PostgreSQL integration test additionally verifies registry rows persist `provider`、`isolation`、`node`、`resource_id`、`generation` and `dependency_bundle_digest`，且旧 `sandbox_id` 行只迁移为 `daytona`。

- [ ] **Step 2: 运行测试并确认新字段不存在**

Run: `uv run pytest smart_reporting/tests/test_settings.py smart_reporting/tests/sandbox/test_factory.py -q`
Expected: FAIL，`AgentSettings` 没有 sandbox provider 字段。

- [ ] **Step 3: 实现失败关闭配置与工厂**

```python
def create_sandbox_provider(settings: AgentSettings, registry: AsyncSandboxRegistry):
    if settings.sandbox_provider == "daytona":
        return DaytonaProvider(snapshot=settings.workspace_snapshot, registry=registry)
    assert settings.sandbox_local is not None
    return LocalProvider(settings.sandbox_local, registry=registry)
```

`SANDBOX_PROVIDER` 默认 `daytona`；local 必须同时提供 `SANDBOX_LOCAL_PROFILE`、`SANDBOX_LOCAL_ENDPOINT` 和 `SANDBOX_ROOTFS_DIGEST`。远程 endpoint 还必须提供 CA、客户端证书和私钥；UDS endpoint 必须是绝对 socket 路径。

- [ ] **Step 4: 扩展 PostgreSQL-only registry 并保持旧行迁移确定性**

初始化事务内使用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 增加字段，随后把旧行填充为 `provider='daytona'`、`isolation='provider_managed'`、`resource_id=sandbox_id`，最后添加非空约束。禁止增加 SQLite 分支。

- [ ] **Step 5: 验证配置、registry 与 Compose 配置**

Run: `uv run pytest smart_reporting/tests/test_settings.py smart_reporting/tests/test_workspace.py smart_reporting/tests/sandbox/test_factory.py -q`
Expected: PASS。

Run: `docker compose config >/dev/null`
Expected: exit 0。

- [ ] **Step 6: 提交**

```bash
git add smart_reporting/sandbox/factory.py smart_reporting/runtime/settings.py smart_reporting/runtime/execution.py smart_reporting/app.py smart_reporting/workspace.py smart_reporting/tests/test_settings.py smart_reporting/tests/test_workspace.py smart_reporting/tests/sandbox/test_factory.py .env.example smart_reporting/.env.example
git commit -m "feat: configure sandbox providers"
```

### Task 4: WorkspaceService 切换到 Provider handle

**Files:**
- Modify: `smart_reporting/workspace.py`
- Modify: `smart_reporting/task_execution/execution.py`
- Modify: `smart_reporting/skills/core.py`
- Modify: `smart_reporting/reporting/delivery/publishing.py`
- Test: `smart_reporting/tests/test_workspace.py`
- Test: `smart_reporting/task_execution/tests/test_execution.py`
- Test: `smart_reporting/reporting/tests/test_report_artifact_persistence.py`

- [ ] **Step 1: 写失败的 Provider handle 恢复、销毁和异常测试**

```python
@pytest.mark.anyio
async def test_workspace_service_uses_provider_handle_without_daytona_types() -> None:
    provider = FakeSandboxProvider()
    service = WorkspaceService(SECRET, provider=provider, async_registry=AsyncMemoryRegistry({}))
    await service.ahash_file("thread", "result.json")
    assert provider.ensure_calls == ["thread"]


@pytest.mark.anyio
async def test_provider_timeout_fails_closed() -> None:
    service = WorkspaceService(SECRET, provider=TimeoutProvider())
    with pytest.raises(WorkspaceError, match="工作区服务超时"):
        await service.ahash_file("thread", "result.json")
```

- [ ] **Step 2: 运行定点测试并确认 WorkspaceService 不接受 provider**

Run: `uv run pytest smart_reporting/tests/test_workspace.py -q -k 'provider_handle or provider_timeout'`
Expected: FAIL，构造器参数或 provider 调用不存在。

- [ ] **Step 3: 最小迁移异步生命周期**

`WorkspaceService` 新增 `_provider_workspace(thread, create=True)`，生成绑定并调用 `SandboxProvider`；现有路径、文件、哈希、branch、隔离、清理和 TaskExecution 继续消费 `SandboxHandle.fs/process`。同步公共方法通过专用同步 facade 调用同一 Provider，不允许在运行中的事件循环上 `asyncio.run()`。

- [ ] **Step 4: 清零上层 Daytona 导入**

Run: `rg -n 'from daytona|import daytona|DaytonaNotFoundError|SessionExecuteRequest' smart_reporting --glob '*.py' --glob '!sandbox/daytona.py' --glob '!**/tests/**'`
Expected: 无输出。

- [ ] **Step 5: 验证 Workspace 与执行内核回归**

Run: `uv run pytest smart_reporting/tests/test_workspace.py smart_reporting/task_execution/tests/test_execution.py smart_reporting/reporting/tests/test_report_artifact_persistence.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add smart_reporting/workspace.py smart_reporting/task_execution/execution.py smart_reporting/skills/core.py smart_reporting/reporting/delivery/publishing.py smart_reporting/tests/test_workspace.py smart_reporting/task_execution/tests/test_execution.py smart_reporting/reporting/tests/test_report_artifact_persistence.py
git commit -m "refactor: route workspaces through sandbox providers"
```

### Task 5: PythonScriptRunner 与 Reporting 工具收敛

**Files:**
- Create: `smart_reporting/sandbox/python_runner.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Modify: `smart_reporting/reporting/tools/base.py`
- Modify: `smart_reporting/reporting/tools/capabilities.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py`
- Modify: `smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py`
- Modify: `smart_reporting/reporting/instructions.py`
- Test: `smart_reporting/tests/sandbox/test_python_runner.py`
- Test: `smart_reporting/reporting/tests/test_reporting_agent_execution.py`
- Test: `smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`
- Test: `smart_reporting/reporting/tests/test_analysis_item_workflow.py`

- [ ] **Step 1: 写失败的结构化 Python 执行和工具投影测试**

```python
@pytest.mark.anyio
async def test_runner_never_forwards_script_as_shell_command() -> None:
    process = RecordingProcess()
    runner = PythonScriptRunner(process, dependency_bundle_digest="sha256:" + "a" * 64)
    result = await runner.run(RunPythonScriptRequest(script="print('ok')", cwd="analysis"))
    assert process.exec_requests[0].command_id == "python-script-runner"
    assert "print('ok')" not in process.exec_requests[0].argv
    assert result.script_hash == hashlib.sha256(b"print('ok')").hexdigest()


def test_reporting_model_has_python_tool_but_no_terminal() -> None:
    tools = tools_for_task("analysis", "analysis_item")
    assert "run_python_script" in tools
    assert "terminal" not in tools
```

- [ ] **Step 2: 运行测试并确认 runner/tool 不存在**

Run: `uv run pytest smart_reporting/tests/sandbox/test_python_runner.py smart_reporting/reporting/tests/test_reporting_agent_execution.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现一次性 runner**

```python
class PythonScriptRunner:
    async def run(self, request: RunPythonScriptRequest) -> RunPythonScriptResult:
        script_hash = hashlib.sha256(request.script.encode()).hexdigest()
        return await self._execution.run_python_script(request, script_hash=script_hash)
```

Provider 在 sandbox 内创建随机临时 `.py` 文件，以固定解释器 argv 执行并在 finally 清理；请求不含 network、解释器、bundle ID、环境变量或宿主路径。缺失 import 映射为 `dependency_unavailable`，超时杀死整个 cgroup/process group，stdout/stderr 分别截断并标注。

- [ ] **Step 4: 将 Workflow 改为结构化调用**

`VisualizationSectionWorkflow.execute_script` 和 `AnalysisItemWorkflow.run_script` 接收 `script_path` 或脚本内容，不再构造 `python3 <path>`；模型工具 schema 只暴露 `script_path`、`timeout` 和可选 `background`。`TaskExecutionKernel.terminal` 保留为受信内部兼容原语，但不注册到 Reporting 模型。

- [ ] **Step 5: 验证 Reporting 定点测试**

Run: `uv run pytest smart_reporting/tests/sandbox/test_python_runner.py smart_reporting/reporting/tests/test_reporting_agent_execution.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_analysis_item_workflow.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add smart_reporting/sandbox/python_runner.py smart_reporting/reporting/tools smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py smart_reporting/reporting/instructions.py smart_reporting/tests/sandbox/test_python_runner.py smart_reporting/reporting/tests/test_reporting_agent_execution.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_analysis_item_workflow.py
git commit -m "feat: execute reporting python through controlled runner"
```

### Task 6: LocalProvider 控制面客户端与 daemon API

**Files:**
- Create: `smart_reporting/sandbox/local/__init__.py`
- Create: `smart_reporting/sandbox/local/config.py`
- Create: `smart_reporting/sandbox/local/client.py`
- Create: `smart_reporting/sandbox/local/app.py`
- Create: `smart_reporting/tests/sandbox/test_local_client.py`
- Create: `smart_reporting/tests/sandbox/test_local_app.py`

- [ ] **Step 1: 写失败的 UDS、mTLS、身份绑定和错误响应测试**

```python
@pytest.mark.anyio
async def test_local_client_sends_binding_on_every_workspace_request() -> None:
    transport = RecordingTransport(response=workspace_response())
    provider = LocalProvider(CONFIG, transport=transport)
    await provider.get_workspace(LOCAL_REF, BINDING)
    assert transport.requests[0].headers["x-sandbox-binding"] == binding_digest(BINDING)


@pytest.mark.anyio
async def test_daemon_rejects_resource_from_other_thread(client) -> None:
    response = await client.get("/v1/workspaces/local-1", headers=OTHER_BINDING_HEADERS)
    assert response.status_code == 403
    assert response.json()["code"] == "sandbox_policy_denied"
```

- [ ] **Step 2: 运行测试并确认 local 模块不存在**

Run: `uv run pytest smart_reporting/tests/sandbox/test_local_client.py smart_reporting/tests/sandbox/test_local_app.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现固定 API schema 和传输**

UDS 使用 `httpx.AsyncHTTPTransport(uds=...)`；HTTPS 使用 `verify=ca_path` 和 `(cert_path, key_path)`，固定 `trust_env=False`、连接池、总超时和响应大小。API 只接受相对 workspace 路径、领域 DTO、绑定 digest 与幂等键；不接受 shell、宿主路径、解释器路径和任意环境变量。

- [ ] **Step 4: 实现 Daytona-compatible 文件与 session endpoint**

文件下载使用流式响应，上传在读取 body 前校验绑定与 `Content-Length`。命令 API 只接受 `runner_id` 和结构化参数；未知 runner 返回 `sandbox_policy_denied`。异常返回统一 `{code, message, retryable, details}`，客户端映射到 Provider 错误。

- [ ] **Step 5: 验证客户端和 API 测试**

Run: `uv run pytest smart_reporting/tests/sandbox/test_local_client.py smart_reporting/tests/sandbox/test_local_app.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add smart_reporting/sandbox/local smart_reporting/tests/sandbox/test_local_client.py smart_reporting/tests/sandbox/test_local_app.py
git commit -m "feat: add local sandbox control plane"
```

### Task 7: 离线依赖 catalog、预检和 Linux runtime

**Files:**
- Create: `smart_reporting/sandbox/local/catalog.py`
- Create: `smart_reporting/sandbox/local/preflight.py`
- Create: `smart_reporting/sandbox/local/runtime.py`
- Create: `smart_reporting/tests/sandbox/test_local_catalog.py`
- Create: `smart_reporting/tests/sandbox/test_local_preflight.py`
- Create: `smart_reporting/tests/sandbox/test_local_runtime.py`

- [ ] **Step 1: 写失败的 bundle 选择和失败关闭测试**

```python
def test_catalog_selects_exact_profile_arch_and_python_abi(tmp_path: Path) -> None:
    catalog = DependencyCatalog.load(tmp_path / "catalog.json", verifier=VALID_SIGNATURE)
    bundle = catalog.resolve("openeuler", "aarch64", "cp312", "reporting")
    assert bundle.digest == EXPECTED_DIGEST


@pytest.mark.parametrize("missing", ["user_ns", "cgroup_v2", "seccomp", "rootfs", "bundle"])
def test_preflight_fails_closed_when_required_capability_is_missing(missing: str) -> None:
    with pytest.raises(SandboxPreflightFailed, match=missing):
        run_preflight(PROFILE.with_missing(missing))
```

- [ ] **Step 2: 运行测试并确认实现缺失**

Run: `uv run pytest smart_reporting/tests/sandbox/test_local_catalog.py smart_reporting/tests/sandbox/test_local_preflight.py smart_reporting/tests/sandbox/test_local_runtime.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现签名 catalog 和 AST import 预检**

catalog JSON 必须包含 profile、arch、python ABI、tenant policy、bundle path、digest、manifest digest、SBOM digest 和 detached signature。加载时逐项解析、校验绝对管理员路径位于固定制品根、拒绝符号链接、验证摘要和签名；脚本 AST 只做未知顶层 import 的提前提示，不能作为安全边界。

- [ ] **Step 4: 实现 launcher、cgroup 和日志游标**

```python
argv = (
    bwrap,
    "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-uts", "--unshare-ipc",
    "--die-with-parent", "--new-session", "--ro-bind", rootfs, "/",
    "--ro-bind", bundle, "/opt/reporting-deps", "--bind", workspace, "/workspace",
    "--proc", "/proc", "--dev", "/dev", "--seccomp", str(seccomp_fd),
    "/usr/bin/python3", "-I", "-B", script_path,
)
```

runtime 只能从经过预检的 profile 构造 argv；cgroup v2 设置 `cpu.max`、`memory.max`、`pids.max` 并在超时写入 `cgroup.kill`。工作区使用 `openat2`/等价逐段 `O_NOFOLLOW` 校验，日志以有界文件和 byte offset 读取。任何内核、挂载、cgroup、seccomp 或 digest 失败都拒绝启动，不回退裸 subprocess。

- [ ] **Step 5: 验证策略负向测试**

Run: `uv run pytest smart_reporting/tests/sandbox/test_local_catalog.py smart_reporting/tests/sandbox/test_local_preflight.py smart_reporting/tests/sandbox/test_local_runtime.py -q`
Expected: PASS，覆盖绝对路径、符号链接、digest 不匹配、未知模块、网络、子进程、超时和输出上限。

- [ ] **Step 6: 提交**

```bash
git add smart_reporting/sandbox/local smart_reporting/tests/sandbox/test_local_catalog.py smart_reporting/tests/sandbox/test_local_preflight.py smart_reporting/tests/sandbox/test_local_runtime.py
git commit -m "feat: enforce local linux sandbox policy"
```

### Task 8: Ubuntu/openEuler 部署模板和 daemon 入口

**Files:**
- Create: `smart_reporting/sandbox/local/__main__.py`
- Create: `deploy/local-sandboxd/local-sandboxd.service`
- Create: `deploy/local-sandboxd/profiles/ubuntu.json`
- Create: `deploy/local-sandboxd/profiles/openeuler.json`
- Create: `deploy/local-sandboxd/catalog.example.json`
- Create: `deploy/local-sandboxd/README.md`
- Modify: `.env.example`
- Modify: `smart_reporting/.env.example`
- Modify: `README.md`
- Test: `smart_reporting/tests/sandbox/test_local_entrypoint.py`

- [ ] **Step 1: 写失败的 profile 与 CLI 配置测试**

```python
@pytest.mark.parametrize("profile", ["ubuntu", "openeuler"])
def test_built_in_profile_is_complete(profile: str) -> None:
    value = json.loads((PROFILE_ROOT / f"{profile}.json").read_text())
    assert value["network"] == "disabled"
    assert value["require_cgroup_v2"] is True
    assert value["require_seccomp"] is True
```

- [ ] **Step 2: 运行测试并确认模板不存在**

Run: `uv run pytest smart_reporting/tests/sandbox/test_local_entrypoint.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 CLI 与服务模板**

CLI 只读取管理员配置文件路径和 UDS/TLS listener，启动前完整执行 preflight。systemd unit 使用专用用户、`NoNewPrivileges=yes`、最小 capability、`ProtectSystem=strict`、`PrivateTmp=yes` 和显式可写 workspace/cgroup 目录；不能挂载 Docker/iSulad/containerd socket 或 D-Bus。

- [ ] **Step 4: 验证模板和文档**

Run: `uv run pytest smart_reporting/tests/sandbox/test_local_entrypoint.py -q`
Expected: PASS。

Run: `git diff --check`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/sandbox/local/__main__.py deploy/local-sandboxd .env.example smart_reporting/.env.example README.md smart_reporting/tests/sandbox/test_local_entrypoint.py
git commit -m "docs: add local sandbox deployment profiles"
```

### Task 9: 多节点放置、恢复和 HA 行为

**Files:**
- Create: `smart_reporting/sandbox/local/placement.py`
- Create: `smart_reporting/sandbox/local/reconciler.py`
- Create: `smart_reporting/tests/sandbox/test_local_placement.py`
- Create: `smart_reporting/tests/sandbox/test_local_reconciler.py`
- Modify: `smart_reporting/sandbox/local/client.py`
- Modify: `smart_reporting/runtime/application.py`

- [ ] **Step 1: 写失败的确定性放置和节点故障恢复测试**

```python
def test_existing_binding_never_silently_moves_nodes() -> None:
    placement = PlacementService(nodes=(NODE_A, NODE_B), registry=BOUND_TO_A)
    assert placement.resolve(BINDING).node_id == "node-a"


@pytest.mark.anyio
async def test_reconciler_creates_new_generation_after_node_loss() -> None:
    result = await reconciler.reconcile(BINDING, unavailable_node="node-a")
    assert result.ref.generation == OLD_REF.generation + 1
    assert result.sessions_restored is False
```

- [ ] **Step 2: 运行测试并确认 placement/reconciler 不存在**

Run: `uv run pytest smart_reporting/tests/sandbox/test_local_placement.py smart_reporting/tests/sandbox/test_local_reconciler.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现数据库权威放置和恢复状态机**

仅未绑定 workspace 可在健康节点间选择；已绑定 workspace 固定 node。节点丢失时先把 generation 标记 quarantined，再从共享 workspace 或已验证快照在新节点创建 `generation + 1`；旧 session 全部标记 lost，不承诺 PTY/进程迁移。相同 idempotency key 只能得到已有结果或明确冲突。

- [ ] **Step 4: 接入应用生命周期 reconciler**

应用启动时创建单个后台 reconcile loop，关闭时先取消并等待，再关闭 Provider。leader 通过 PostgreSQL advisory lock 选举，避免多副本重复恢复；审计日志使用 Loguru 稳定英文事件名和脱敏字段。

- [ ] **Step 5: 验证 HA 定点测试**

Run: `uv run pytest smart_reporting/tests/sandbox/test_local_placement.py smart_reporting/tests/sandbox/test_local_reconciler.py smart_reporting/tests/test_application.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add smart_reporting/sandbox/local smart_reporting/runtime/application.py smart_reporting/tests/sandbox/test_local_placement.py smart_reporting/tests/sandbox/test_local_reconciler.py smart_reporting/tests/test_application.py
git commit -m "feat: reconcile local sandbox nodes"
```

### Task 10: 全面验证与迁移清理

**Files:**
- Modify: `smart_reporting/README.md`
- Modify: `docs/superpowers/specs/2026-09-04-sandbox-provider-design.md`（仅同步实现事实）
- Modify: direct-import callers found by the searches below

- [ ] **Step 1: 验证旧 Daytona 上层耦合已清零**

Run: `rg -n 'DaytonaNotFoundError|SessionExecuteRequest|daytona_session_id|from daytona|import daytona' smart_reporting --glob '*.py' --glob '!sandbox/daytona.py' --glob '!**/tests/**'`
Expected: 无输出。

Run: `rg -n 'name="terminal"|"terminal"' smart_reporting/reporting/tools smart_reporting/reporting/phase.py --glob '*.py'`
Expected: 模型工具注册和 capability 中无通用 terminal；仅允许明确标注的内部兼容文本。

- [ ] **Step 2: 运行格式、lint 和类型检查**

Run: `uv run ruff format --check smart_reporting/sandbox smart_reporting/workspace.py smart_reporting/runtime smart_reporting/reporting/tools smart_reporting/reporting/workflow/runtime`
Expected: PASS。

Run: `uv run ruff check smart_reporting/sandbox smart_reporting/workspace.py smart_reporting/runtime smart_reporting/reporting/tools smart_reporting/reporting/workflow/runtime`
Expected: PASS。

Run: `uv run mypy smart_reporting`
Expected: PASS。

- [ ] **Step 3: 运行非集成完整回归**

Run: `AGENT_REPORT_PUBLIC_BASE_URL=http://127.0.0.1:33046 uv run pytest -q`
Expected: PASS，零失败。

- [ ] **Step 4: 运行外部配置验证**

Run: `docker compose config >/dev/null`
Expected: exit 0。

Run: `docker compose --env-file docker/.env -f docker/docker-compose.yaml config >/dev/null`
Expected: exit 0；若 `docker/.env` 不存在，使用仓库外临时文件从 `docker/.env.example` 生成，不写入仓库。

- [ ] **Step 5: 记录未能在当前主机执行的真实隔离验证**

真实 namespace/cgroup/seccomp、Ubuntu/openEuler 双架构、mTLS、多节点 PostgreSQL 恢复和 Daytona API 验收必须作为 `integration` 测试运行。当前主机缺少相应节点或凭据时，只报告未执行及原因，不把 mock 单元测试声明为生产验收。

- [ ] **Step 6: 最终提交**

```bash
git add smart_reporting/README.md docs/superpowers/specs/2026-09-04-sandbox-provider-design.md
git commit -m "docs: document sandbox provider operations"
```
