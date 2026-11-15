# Reporting Session Workspace 与 CodeMode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将整个 Reporting Workflow 切换为会话专属的宿主机 Agno Workspace，并让补充分析和 Matplotlib 可视化使用任务专属 Agno CodeMode，同时保持现有 Workflow 状态机、重试、降级和 durable path 契约不变。

**Architecture:** 新增 `ReportingWorkspaceRegistry`，以现有可信 Reporting scope 解析唯一宿主机目录并构造 Agno `Workspace`；新增一个只覆盖程序化二进制读写、哈希、文件检查和生命周期的 `HostReportingWorkspace`，供固定 Workflow 使用。现有 Reporting Toolkit 保留领域命令，但模型文件工具由原生 Workspace 提供；补充分析和可视化脚本通过共享 `CodeMode` 单例按 task session 执行，并在每个任务的 `finally` 中关闭 Kernel。

**Tech Stack:** Python 3.12、Agno 3.0.9 `Workspace`/`CodeMode`、Pydantic、AnyIO、Matplotlib、Pillow、Loguru、pytest。

**Spec:** `docs/superpowers/specs/2026-09-15-matplotlib-code-mode-host-design.md`

## Global Constraints

- 完全宿主机执行，不使用 Daytona、local-sandboxd、bubblewrap、容器或其他隔离运行时。
- `Workspace(root=session_root, allowed=Workspace.ALL_TOOLS, confirm=[])`，Shell 不关闭且不增加 HITL。
- `CodeMode(allow_shell=True, allow_restart=True, snapshot=False)`；每个 Coding task 使用独立 session ID，结束必须 `ashutdown(session_id)`。
- 图表只使用 Matplotlib PNG，并在导入 `pyplot` 前使用 `matplotlib.use("Agg")`。
- 现有 `报表/...`、`analysis/...` 等 durable 相对路径语义不变；`/home/daytona/workspace` 仅是被移除的旧远端物理根，模型继续只接收签发的相对 `workspacePath`。
- 语义业务校验只产生软告警；路径、文件身份、执行和产物错误仍是技术失败。
- 应用日志使用 Loguru，不记录宿主机根绝对路径、环境变量值或完整数据内容。
- 不删除历史 sandbox 实现，不修改非 Reporting 模块的执行策略。
- 不修改已知基线失败 `test_visualization_script_execution_repair_uses_off_then_4k`。
- 禁止重复完整测试；每个任务只运行对应定向测试，最后只运行一次相关测试集合。
- 项目禁止子 Agent，本计划使用 `superpowers:executing-plans` 在当前会话内执行。

---

### Task 1: 宿主机根配置与会话 Workspace 注册表

**Files:**
- Create: `smart_reporting/reporting/host_workspace.py`
- Modify: `smart_reporting/runtime/settings.py`
- Test: `smart_reporting/reporting/tests/test_reporting_host_workspace.py`
- Test: `smart_reporting/runtime/tests/test_settings.py`

**Interfaces:**
- Consumes: `ReportingWorkflowScope` 中的 `database`、`company_id`、`user_id`、`caller_thread_id`、`session_id`、`workspace_key`；现有 `workspace_hmac_secret`。
- Produces: `ReportingWorkspaceIdentity`、`ReportingWorkspaceRegistry.resolve(scope)`、`resolve_run_context(run_context)`、`release(workspace_key)`、`aclose()`；`AgentSettings.reporting_host_workspace_root: str`。

- [ ] **Step 1: 写根目录和注册表失败测试**

```python
def test_reporting_host_workspace_root_must_be_absolute(tmp_path: Path) -> None:
    values = base_environment(REPORTING_HOST_WORKSPACE_ROOT="relative")
    with pytest.raises(ValueError, match="REPORTING_HOST_WORKSPACE_ROOT"):
        AgentSettings.from_environment(values, load_env_file=False)


def test_registry_reuses_workspace_only_inside_same_workflow_session(tmp_path: Path) -> None:
    registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)
    first = registry.resolve(scope(session_id="session-a", workspace_key="run-a"))
    resumed = registry.resolve(scope(session_id="session-a", workspace_key="run-a"))
    second = registry.resolve(scope(session_id="session-b", workspace_key="run-b"))
    assert first.workspace is resumed.workspace
    assert first.root == resumed.root
    assert first.root != second.root
    assert first.workspace is not second.workspace
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_host_workspace.py smart_reporting/runtime/tests/test_settings.py -k 'reporting_host_workspace or registry_reuses'`

Expected: FAIL，模块、字段和环境变量尚不存在。

- [ ] **Step 3: 实现设置校验和注册表**

```python
@dataclass(frozen=True)
class ReportingWorkspaceIdentity:
    workflow_session_id: str
    workspace_key: str
    root: Path
    workspace: Workspace


class ReportingWorkspaceRegistry:
    def __init__(self, root: Path, *, secret: str) -> None:
        self.root = validate_host_workspace_root(root)
        self._secret = secret.encode("utf-8")
        self._entries: dict[str, ReportingWorkspaceIdentity] = {}

    def resolve(self, scope: ReportingWorkflowScope) -> ReportingWorkspaceIdentity:
        digest = hmac.new(
            self._secret,
            json.dumps(
                [scope.database, scope.company_id, scope.user_id,
                 scope.caller_thread_id, scope.session_id, scope.workspace_key],
                separators=(",", ":"),
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        session_root = self.root / "sessions" / digest
        session_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        entry = self._entries.get(scope.workspace_key)
        if entry is not None:
            if entry.root != session_root or entry.workspace_key != scope.workspace_key:
                raise ReportingError("report_host_workspace_scope_mismatch", "Reporting Workspace 作用域不一致。")
            return entry
        workspace = Workspace(root=session_root, allowed=Workspace.ALL_TOOLS, confirm=[])
        entry = ReportingWorkspaceIdentity(scope.session_id, scope.workspace_key, session_root, workspace)
        self._entries[scope.workspace_key] = entry
        return entry
```

`validate_host_workspace_root()` 必须拒绝空值、相对路径、已有普通文件和符号链接；创建成功后用 `lstat()` 再确认目录不是符号链接。`AgentSettings.from_environment()` 从必需环境变量 `REPORTING_HOST_WORKSPACE_ROOT` 读取绝对路径。

- [ ] **Step 4: 运行定向测试确认通过**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_host_workspace.py smart_reporting/runtime/tests/test_settings.py -k 'reporting_host_workspace or registry_reuses'`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/host_workspace.py smart_reporting/runtime/settings.py smart_reporting/reporting/tests/test_reporting_host_workspace.py smart_reporting/runtime/tests/test_settings.py
git commit -m "feat: add reporting session workspace registry"
```

### Task 2: 逻辑路径投影与薄宿主机文件适配

**Files:**
- Modify: `smart_reporting/reporting/host_workspace.py`
- Modify: `smart_reporting/reporting/tools/workspace_port.py`
- Modify: `smart_reporting/reporting/workspace.py`
- Test: `smart_reporting/reporting/tests/test_reporting_host_workspace.py`
- Test: `smart_reporting/reporting/tests/test_reporting_workspace_port.py`

**Interfaces:**
- Consumes: Task 1 的 `ReportingWorkspaceIdentity.root`；现有 durable 相对业务路径。
- Produces: `ReportingPathMapper.normalize(path) -> str`、`to_host_path(path) -> Path`；`HostReportingWorkspace` 的 `afile_bytes`、`aread_text`、`awrite_bytes`、`awrite_text`、`ahash_file`、`abatch_hash_files`、`read_limited_regular_file`、`inspect_chart_file`。

- [ ] **Step 1: 写路径和文件身份失败测试**

```python
def test_path_mapper_preserves_durable_relative_path(tmp_path: Path) -> None:
    mapper = ReportingPathMapper(tmp_path)
    assert mapper.normalize("facts/a.json") == "facts/a.json"
    assert mapper.to_host_path("facts/a.json") == tmp_path / "facts" / "a.json"


@pytest.mark.parametrize("path", ["../x", "a/../../x", "a\x00b", "/etc/passwd"])
def test_path_mapper_rejects_escape(tmp_path: Path, path: str) -> None:
    with pytest.raises(ReportingWorkspaceError):
        ReportingPathMapper(tmp_path).to_host_path(path)


@pytest.mark.anyio
async def test_host_workspace_rejects_symlink_chart(tmp_path: Path) -> None:
    workspace = host_workspace(tmp_path)
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "out.png").symlink_to(tmp_path / "outside.png")
    with pytest.raises(ReportingError, match="普通文件"):
        await workspace.inspect_chart_file("charts/out.png")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_host_workspace.py smart_reporting/reporting/tests/test_reporting_workspace_port.py -k 'path_mapper or host_workspace'`

Expected: FAIL，映射器和宿主机文件适配尚不存在。

- [ ] **Step 3: 实现最小文件适配**

```python
class HostReportingWorkspace:
    def __init__(self, identity: ReportingWorkspaceIdentity) -> None:
        self.identity = identity
        self.paths = ReportingPathMapper(identity.root)

    async def afile_bytes(self, _thread_id: str, path: str) -> tuple[bytes, str]:
        host_path = self.paths.to_host_path(path)
        content = await anyio.to_thread.run_sync(_read_regular_file, host_path, MAX_DOWNLOAD_BYTES)
        return content, mimetypes.guess_type(host_path.name)[0] or "application/octet-stream"

    async def ahash_file(self, _thread_id: str, path: str) -> dict[str, Any]:
        workspace_path = self.paths.normalize(path)
        try:
            content = await self.read_limited_regular_file(
                _thread_id, workspace_path, max_bytes=MAX_DOWNLOAD_BYTES
            )
        except FileNotFoundError:
            return {"path": workspace_path, "missing": True}
        return {"path": workspace_path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
```

所有底层打开操作使用 `lstat()` + `stat.S_ISREG()`，最终路径不跟随符号链接；写入使用同目录临时文件、`os.replace()` 和可选 SHA-256 CAS。`inspect_chart_file()` 复用现有 Pillow 内容检查，但只通过公开适配方法读取。

- [ ] **Step 4: 把 `inspect_report_chart_file()` 改为端口调用**

```python
async def inspect_report_chart_file(workspace: ReportingBinaryWorkspace, *, thread_id: str, path: str) -> dict[str, Any]:
    content = await workspace.read_limited_regular_file(thread_id, path, max_bytes=MAX_REPORT_CHART_BYTES)
    # 保留现有 Pillow 格式、尺寸、空白和扩展名检查。
```

- [ ] **Step 5: 运行定向测试确认通过并提交**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_host_workspace.py smart_reporting/reporting/tests/test_reporting_workspace_port.py -k 'path_mapper or host_workspace or inspect_chart'`

```bash
git add smart_reporting/reporting/host_workspace.py smart_reporting/reporting/tools/workspace_port.py smart_reporting/reporting/workspace.py smart_reporting/reporting/tests/test_reporting_host_workspace.py smart_reporting/reporting/tests/test_reporting_workspace_port.py
git commit -m "feat: add host reporting file adapter"
```

### Task 3: Reporting Runtime 装配脱离 sandbox provider

**Files:**
- Modify: `smart_reporting/runtime/execution.py`
- Modify: `smart_reporting/reporting/bootstrap.py`
- Modify: `smart_reporting/reporting/workflow/runtime/base.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/workflow/controller.py`
- Test: `smart_reporting/reporting/tests/test_reporting_workflow_controller.py`
- Test: `smart_reporting/reporting/tests/test_reporting_host_workspace.py`

**Interfaces:**
- Consumes: Task 1 注册表，`resolve_reporting_workflow_scope()`，Task 2 宿主机适配。
- Produces: `ExecutionContext.reporting_workspace_registry`；`ReportWorkflowRuntime.workspace_for(run_context)`；Task scope 不再依赖真实 `sandbox_id`。

- [ ] **Step 1: 写装配失败测试**

```python
def test_reporting_runtime_creation_does_not_create_sandbox_provider(monkeypatch, settings) -> None:
    monkeypatch.setattr("smart_reporting.runtime.execution.create_sandbox_provider", forbidden)
    context = create_execution_context(settings, reporting_only_host_workspace=True)
    assert isinstance(context.reporting_workspace_registry, ReportingWorkspaceRegistry)


@pytest.mark.anyio
async def test_whole_workflow_resolves_one_workspace_instance(runtime, run_context) -> None:
    first = runtime.workspace_for(run_context)
    second = runtime.workspace_for(run_context)
    assert first.identity.workspace is second.identity.workspace
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_host_workspace.py smart_reporting/reporting/tests/test_reporting_workflow_controller.py -k 'sandbox_provider or one_workspace_instance'`

- [ ] **Step 3: 注入注册表并移除 Reporting 的 sandbox_id 获取**

```python
@dataclass(frozen=True)
class ExecutionContext:
    settings: AgentSettings
    database: AsyncBaseDb
    workspace_service: WorkspaceService
    reporting_workspace_registry: ReportingWorkspaceRegistry
    trace_database: BaseDb | None = None


def workspace_for(self, run_context: RunContext) -> HostReportingWorkspace:
    scope = resolve_reporting_workflow_scope_from_context(run_context)
    return HostReportingWorkspace(self.workspace_registry.resolve(scope))
```

在 Reporting runtime 中用稳定的 `scope.workspace_key` 代替仅用于旧 `TaskExecutionScope` 记录的 `sandbox_id` 字段；不得再调用 `_async_client()` 或 `_asandbox_for()` 获取 provider 句柄。非 Reporting 的应用 Workspace API 暂时保留原有 `WorkspaceService`。

- [ ] **Step 4: 运行定向测试并提交**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_host_workspace.py smart_reporting/reporting/tests/test_reporting_workflow_controller.py -k 'sandbox_provider or one_workspace_instance or workflow_scope'`

```bash
git add smart_reporting/runtime/execution.py smart_reporting/reporting/bootstrap.py smart_reporting/reporting/workflow/runtime/base.py smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/workflow/controller.py smart_reporting/reporting/tests/test_reporting_workflow_controller.py smart_reporting/reporting/tests/test_reporting_host_workspace.py
git commit -m "refactor: bind reporting runtime to host workspace"
```

### Task 4: 收敛整个 Workflow 的程序化文件访问

**Files:**
- Modify: `smart_reporting/reporting/data_sources.py`
- Modify: `smart_reporting/reporting/workspace.py`
- Modify: `smart_reporting/reporting/workflow/runtime/datasets.py`
- Modify: `smart_reporting/reporting/workflow/runtime/planning.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/workflow/runtime/sections.py`
- Modify: `smart_reporting/reporting/workflow/runtime/publication.py`
- Modify: `smart_reporting/reporting/delivery/publishing.py`
- Modify: `smart_reporting/reporting/vision.py`
- Modify: `smart_reporting/reporting/tools/workspace_adapter.py`
- Test: `smart_reporting/reporting/tests/test_reporting_workspace_port.py`
- Test: `smart_reporting/reporting/tests/test_report_data_sources.py`
- Test: `smart_reporting/reporting/tests/test_report_artifact_persistence.py`
- Test: `smart_reporting/reporting/tests/test_report_vision.py`

**Interfaces:**
- Consumes: Task 2 的 `HostReportingWorkspace` 公开方法。
- Produces: Reporting 路径上的调用不再出现 `_async_client`、`_asandbox_for`、`_adownload_file`、`_aensure_directory`、`_ainfo` 或 `_avalidate_existing_path`。

- [ ] **Step 1: 为数据导入、发布和视觉读取写宿主机端口测试**

```python
@pytest.mark.anyio
async def test_artifact_persistence_reads_host_workspace_without_private_sandbox_api(
    tmp_path: Path, artifact_persistence_fixture: ArtifactPersistenceFixture
):
    persistence, repository, workspace = artifact_persistence_fixture.build(tmp_path)
    await workspace.awrite_bytes("reports/report.pdf", b"pdf", overwrite=False)
    await artifact_persistence_fixture.persist_pdf(persistence, "reports/report.pdf")
    assert repository.content == b"pdf"


@pytest.mark.anyio
async def test_vision_reviewer_reads_verified_host_bytes(
    tmp_path: Path, vision_fixture: VisionFixture
):
    reviewer = vision_fixture.reviewer(tmp_path)
    await vision_fixture.write_chart(tmp_path, "charts/chart.png")
    receipt = await reviewer.review("ignored", "charts/chart.png")
    assert receipt["reviewed"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_workspace_port.py smart_reporting/reporting/tests/test_report_data_sources.py smart_reporting/reporting/tests/test_report_artifact_persistence.py smart_reporting/reporting/tests/test_report_vision.py -k 'host_workspace or private_sandbox'`

- [ ] **Step 3: 逐调用点改为公开端口**

```python
content = await workspace.read_limited_regular_file(thread_id, logical_path, max_bytes=limit)
identity = await workspace.ahash_file(thread_id, logical_path)
await workspace.awrite_bytes(logical_path, content, overwrite=True)
await workspace.aensure_directory(logical_directory)
```

保留原有逻辑路径、文件大小限制、哈希和错误码；只替换文件传输实现。`probe_python_modules()` 改为在 API 进程中用 `importlib.util.find_spec()` 探测，不运行通用命令。

- [ ] **Step 4: 扫描确认 Reporting 不再使用旧私有 sandbox API**

Run: `rg -n '_async_client|_asandbox_for|_adownload_file|_aensure_directory|_ainfo|_avalidate_existing_path' smart_reporting/reporting`

Expected: 无运行时代码命中；测试 fake 或迁移说明之外不得存在命中。

- [ ] **Step 5: 运行定向测试并提交**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_workspace_port.py smart_reporting/reporting/tests/test_report_data_sources.py smart_reporting/reporting/tests/test_report_artifact_persistence.py smart_reporting/reporting/tests/test_report_vision.py`

```bash
git add smart_reporting/reporting/data_sources.py smart_reporting/reporting/workspace.py smart_reporting/reporting/workflow/runtime smart_reporting/reporting/delivery/publishing.py smart_reporting/reporting/vision.py smart_reporting/reporting/tools/workspace_adapter.py smart_reporting/reporting/tests
git commit -m "refactor: move reporting files to host workspace"
```

### Task 5: 原生 Workspace 工具装配与重名消除

**Files:**
- Modify: `smart_reporting/reporting/tools/factory.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Modify: `smart_reporting/reporting/agent.py`
- Modify: `smart_reporting/reporting/bootstrap.py`
- Test: `smart_reporting/reporting/tests/test_reporting_agent_execution.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
- Test: `smart_reporting/reporting/tests/test_reporting_host_workspace.py`

**Interfaces:**
- Consumes: Task 1 注册表的 `identity.workspace`；现有 Reporting phase/task-kind callable factory。
- Produces: `build_reporting_tools(workspace_service, task_repository, validator_registry=None, *, state_repository, run_context=None, agent=None, vision_reviewer=None, exclude_file_tools=False)`；文件工具由原生 Workspace 提供；Agent `cache_callables=False`。

- [ ] **Step 1: 写最终工具表失败测试**

```python
def test_reporting_agent_tools_are_session_scoped_without_duplicate_names(
    reporting_agent_fixture: ReportingAgentFixture,
):
    agent, reporting_tools, run_context = reporting_agent_fixture.build()
    tools = reporting_tools(run_context)
    names = [name for toolkit in tools for name in toolkit.functions]
    assert len(names) == len(set(names))
    assert {"read_file", "write_file", "list_files", "search_content", "move_file", "delete_file", "run_command"} <= set(names)
    assert agent.cache_callables is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_agent_execution.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_host_workspace.py -k 'session_scoped or duplicate_names or cache_callables'`

- [ ] **Step 3: 排除领域 Toolkit 文件工具并装配原生 Workspace**

```python
FILE_TOOL_NAMES = frozenset({
    "read_file", "write_file", "list_files", "search_content", "move_file", "delete_file"
})


def build_reporting_tools(
    workspace_service: ReportingProgrammaticWorkspace,
    task_repository: Any,
    validator_registry: Any = None,
    *,
    state_repository: ReportingStateRepository,
    run_context: RunContext | None = None,
    agent: Any | None = None,
    vision_reviewer: ReportVisionReviewer | None = None,
    exclude_file_tools: bool = False,
) -> list[Toolkit]:
    toolkit = ReportingToolkit(
        workspace_service,
        task_repository,
        state_repository=state_repository,
        validator_registry=validator_registry,
        vision_reviewer=vision_reviewer,
        phase=reporting_phase_from_run_context(run_context),
        task_kind=reporting_task_kind_from_run_context(run_context),
    )
    if exclude_file_tools:
        for functions in (toolkit.functions, toolkit.async_functions):
            for name in FILE_TOOL_NAMES:
                functions.pop(name, None)
    return [toolkit]


def reporting_tools(run_context: RunContext) -> list[Toolkit]:
    identity = registry.resolve_run_context(run_context)
    return [
        identity.workspace,
        *build_reporting_tools(
            host_workspace,
            task_repository,
            state_repository=state_repository,
            run_context=run_context,
            vision_reviewer=vision_reviewer,
            exclude_file_tools=True,
        ),
    ]
```

`create_reporting_phase_agent()` 使用 `tools=reporting_tools` 且显式设置 `cache_callables=False`。保留 `view_image` 和领域提交工具；`run_python_script` 从模型工具表移除，正式执行仅由固定 Workflow 调用。

- [ ] **Step 4: 运行测试并提交**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_agent_execution.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_host_workspace.py -k 'session_scoped or duplicate_names or callable or tools'`

```bash
git add smart_reporting/reporting/tools/factory.py smart_reporting/reporting/tools/toolkit.py smart_reporting/reporting/agent.py smart_reporting/reporting/bootstrap.py smart_reporting/reporting/tests
git commit -m "feat: attach native workspace to reporting agents"
```

### Task 6: 共享 CodeMode 运行时与任务生命周期

**Files:**
- Create: `smart_reporting/reporting/code_mode.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `smart_reporting/reporting/bootstrap.py`
- Modify: `smart_reporting/reporting/tools/workspace_adapter.py`
- Test: `smart_reporting/reporting/tests/test_reporting_code_mode.py`

**Interfaces:**
- Consumes: `AgentSettings.report_analysis_concurrency`、`report_section_concurrency` 和宿主机根目录；Task 2 的路径投影。
- Produces: `ReportingCodeModeRuntime.execute(task_session_id: str, workspace: HostReportingWorkspace, code: str) -> CellResult`、`execute_script(task_session_id: str, workspace: HostReportingWorkspace, script_path: str, *, timeout: int, close: bool = False) -> dict[str, Any]`、`shutdown(task_session_id: str) -> None`、`aclose() -> None`；稳定错误 `report_code_mode_bootstrap_failed`、`report_code_mode_execution_failed`、`report_code_mode_timeout`。

- [ ] **Step 1: 增加 Agno CodeMode 运行依赖并写生命周期失败测试**

```python
@pytest.mark.anyio
async def test_code_mode_bootstraps_workspace_and_always_shuts_down(tmp_path: Path) -> None:
    code_mode = FakeCodeMode()
    runtime = ReportingCodeModeRuntime(code_mode)
    await runtime.execute_script("visualization:task-1", host_workspace(tmp_path), "charts.py", timeout=30)
    assert code_mode.cells[0] == ("visualization:task-1", bootstrap_cell(tmp_path, matplotlib_agg=True))
    assert code_mode.shutdowns == ["visualization:task-1"]
```

在 `pyproject.toml` 增加 Agno 官方 `code` extra 所需的 `dill`、`ipykernel` 和 `jupyter-client`，更新锁文件；不得手写 Kernel。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_code_mode.py`

- [ ] **Step 3: 实现共享 CodeMode 薄封装**

```python
class ReportingCodeModeRuntime:
    def __init__(self, code_mode: CodeMode) -> None:
        self.code_mode = code_mode

    async def execute_script(self, session_id: str, workspace: HostReportingWorkspace,
                             script_path: str, *, timeout: int, close: bool = False) -> dict[str, Any]:
        try:
            await self._bootstrap(session_id, workspace, matplotlib_agg=True)
            host_script = workspace.paths.to_host_path(script_path)
            cell = await self.code_mode.arun(session_id, f"exec(compile(open({str(host_script)!r}, 'rb').read(), {str(host_script)!r}, 'exec'))")
            return normalize_cell_result(cell)
        finally:
            if close:
                await self.shutdown(session_id)
```

实际 bootstrap 通过 `os.chdir(session_root)` 和 `os.environ["MPLBACKEND"] = "Agg"` 设置 Kernel 级状态；错误只保留受限 stdout/stderr/traceback。单例 CodeMode 的 `max_kernels=max(report_analysis_concurrency, report_section_concurrency)`，`snapshot=False`、`allow_shell=True`、`allow_restart=True`、`cwd=reporting_host_workspace_root`。

- [ ] **Step 4: 运行测试并提交**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_code_mode.py`

```bash
git add pyproject.toml uv.lock smart_reporting/reporting/code_mode.py smart_reporting/reporting/bootstrap.py smart_reporting/reporting/tools/workspace_adapter.py smart_reporting/reporting/tests/test_reporting_code_mode.py
git commit -m "feat: add reporting code mode runtime"
```

### Task 7: 补充分析迁移到 Workspace + CodeMode

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py`
- Modify: `smart_reporting/reporting/workflow/runtime/base.py`
- Modify: `smart_reporting/reporting/workflow/runtime/code_generation.py`
- Modify: `smart_reporting/reporting/tools/analysis_item.py`
- Test: `smart_reporting/reporting/tests/test_analysis_item_workflow.py`
- Test: `smart_reporting/reporting/tests/test_reporting_code_generation.py`
- Test: `smart_reporting/reporting/tests/test_reporting_code_mode.py`

**Interfaces:**
- Consumes: Task 6 的 `ReportingCodeModeRuntime`，Task 2 的相对 `workspacePath` 规范化。
- Produces: `analysis:<task_id>` Kernel session；补证 Agent 使用 Workspace + CodeMode 生成最终脚本和 evidence；固定 Workflow 仍负责校验和 `complete_analysis_item`。

- [ ] **Step 1: 写补证分支和关闭 Kernel 失败测试**

```python
@pytest.mark.anyio
async def test_analysis_without_gap_never_starts_code_mode(workflow, context) -> None:
    await workflow.run(context_without_gap)
    workflow.code_mode.execute_script.assert_not_awaited()


@pytest.mark.anyio
async def test_analysis_supplement_uses_task_kernel_and_closes_on_failure(workflow, context) -> None:
    workflow.code_mode.execute_script.side_effect = ReportingError("report_code_mode_execution_failed", "failed")
    await workflow.run(context)
    workflow.code_mode.shutdown.assert_awaited_once_with("analysis:task-1")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q smart_reporting/reporting/tests/test_analysis_item_workflow.py smart_reporting/reporting/tests/test_reporting_code_generation.py smart_reporting/reporting/tests/test_reporting_code_mode.py -k 'code_mode or task_kernel or without_gap'`

- [ ] **Step 3: 投影模型路径并接入任务生命周期**

```python
task_payload = normalize_workspace_paths(original_payload, mapper)
code_session_id = f"analysis:{task_id}"
try:
    await self.generate_or_repair_script(task_payload, code_session_id, run_context)
    execution = await self.code_mode.execute_script(
        code_session_id, workspace, task_payload["scriptPath"], timeout=timeout
    )
    await self.validate_evidence(original_logical_paths, execution)
finally:
    await self.code_mode.shutdown(code_session_id)
```

`deterministicFacts`、`datasets[].path`、`scriptPath` 和 `evidencePath` 在模型边界、文件回执和 durable state 中始终是同一个规范化相对 Workspace path。固定事实足够分支不得创建 Kernel。

- [ ] **Step 4: 运行补证定向测试并提交**

Run: `pytest -q smart_reporting/reporting/tests/test_analysis_item_workflow.py smart_reporting/reporting/tests/test_reporting_code_generation.py smart_reporting/reporting/tests/test_reporting_code_mode.py -k 'analysis or supplemental or code_mode'`

```bash
git add smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py smart_reporting/reporting/workflow/runtime/base.py smart_reporting/reporting/workflow/runtime/code_generation.py smart_reporting/reporting/tools/analysis_item.py smart_reporting/reporting/tests
git commit -m "feat: run supplemental analysis with code mode"
```

### Task 8: Matplotlib 可视化迁移到 Workspace + CodeMode

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/workflow/runtime/code_generation.py`
- Modify: `smart_reporting/reporting/tools/visualization.py`
- Test: `smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`
- Test: `smart_reporting/reporting/tests/test_reporting_code_generation.py`
- Test: `smart_reporting/reporting/tests/test_reporting_workspace_port.py`

**Interfaces:**
- Consumes: Task 6 CodeMode、Task 2 图片检查、现有 `VisualizationPlanDraft` 和修复计数。
- Produces: `visualization:<task_id>` Kernel session；计划内全部 PNG 经正式执行、身份检查和视觉审查后提交。

- [ ] **Step 1: 写正式执行、修复和降级失败测试**

```python
@pytest.mark.anyio
async def test_visualization_executes_matplotlib_in_task_code_mode_and_closes(
    visualization_code_mode_fixture: VisualizationCodeModeFixture,
):
    workflow, plan, payload, run_context, code_mode, logical_chart_path = (
        visualization_code_mode_fixture.build()
    )
    result = await workflow.run(plan, payload, run_context)
    code_mode.execute_script.assert_awaited()
    code_mode.shutdown.assert_awaited_once_with("visualization:task-1")
    assert result.charts[0].source_path == logical_chart_path


@pytest.mark.anyio
async def test_invalid_png_enters_existing_repair_then_degrade(
    visualization_code_mode_fixture: VisualizationCodeModeFixture,
):
    workflow, plan, payload, run_context, inspector = (
        visualization_code_mode_fixture.build_with_inspector()
    )
    inspector.side_effect = ReportingError("report_chart_source_invalid", "invalid")
    result = await workflow.run(plan, payload, run_context)
    assert result.status == "degraded"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_reporting_code_generation.py smart_reporting/reporting/tests/test_reporting_workspace_port.py -k 'code_mode or invalid_png or visualization_executes'`

- [ ] **Step 3: 接入路径投影和 CodeMode**

```python
code_session_id = f"visualization:{task_id}"
try:
    generated = await self.generate_script(projected_payload, run_context)
    execution = await self.code_mode.execute_script(
        code_session_id, workspace, mapper.normalize(script_path), timeout=timeout
    )
    inspections = [await workspace.inspect_chart_file(mapper.normalize(chart.source_path))
                   for chart in plan.charts]
    # 保留现有视觉审查、身份检查、修复计数和 submit 顺序。
finally:
    await self.code_mode.shutdown(code_session_id)
```

删除 Flint 分支假设，不引入 HTML/JavaScript；图表生成指令继续要求 Matplotlib `Agg`。修复后 SHA-256 未变化、执行失败、视觉失败和修复耗尽行为保持现状。

- [ ] **Step 4: 运行可视化定向测试并提交**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_reporting_code_generation.py smart_reporting/reporting/tests/test_reporting_workspace_port.py -k 'visualization or chart or code_mode'`

```bash
git add smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/workflow/runtime/code_generation.py smart_reporting/reporting/tools/visualization.py smart_reporting/reporting/tests
git commit -m "feat: render matplotlib charts with code mode"
```

### Task 9: 会话清理、真实宿主机集成测试与部署说明

**Files:**
- Modify: `smart_reporting/reporting/workflow/controller.py`
- Modify: `smart_reporting/runtime/execution.py`
- Modify: `.env.example`
- Modify: `README.md`
- Create: `smart_reporting/reporting/tests/test_reporting_host_workspace_integration.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_workflow_lifecycle.py`

**Interfaces:**
- Consumes: Task 1 registry、Task 6 CodeMode runtime、Workflow 终态。
- Produces: 终态释放内存 Workspace 实例；进程关闭关闭全部 Kernel；真实双会话宿主机验收。

- [ ] **Step 1: 写双会话集成和异常清理失败测试**

```python
@pytest.mark.anyio
async def test_two_reporting_sessions_share_files_only_inside_their_own_workspace(tmp_path: Path):
    first = await run_host_reporting_flow(tmp_path, session_id="session-a")
    second = await run_host_reporting_flow(tmp_path, session_id="session-b")
    assert first.root != second.root
    assert first.analysis_kernel != first.visualization_kernel
    assert second.analysis_kernel != second.visualization_kernel
    assert not first.live_kernels
    assert not second.live_kernels
    assert first.paths == {"datasets", "facts", "evidence", "charts", "reports"}


@pytest.mark.anyio
async def test_terminal_workflow_releases_registry_entry_without_deleting_artifacts(
    terminal_workspace_fixture: TerminalWorkspaceFixture,
):
    controller, registry, workspace_key, report_path = terminal_workspace_fixture.build()
    await controller.run_to_completion()
    assert registry.get(workspace_key) is None
    assert report_path.exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest -q smart_reporting/reporting/tests/test_reporting_host_workspace_integration.py smart_reporting/reporting/tests/test_reporting_workflow_lifecycle.py -k 'host_workspace or releases_registry'`

- [ ] **Step 3: 实现终态和进程关闭生命周期**

Workflow 成功、失败或取消的最外层 `finally` 只调用 `registry.release(workspace_key)`，默认不删除会话目录；`close_execution_resources()` 调用 `ReportingCodeModeRuntime.aclose()` 和 `ReportingWorkspaceRegistry.aclose()`。清理失败使用 Loguru warning 且不得覆盖原始结果。

- [ ] **Step 4: 记录启动配置和信任边界**

```dotenv
REPORTING_HOST_WORKSPACE_ROOT=/absolute/path/to/reporting-workspaces
```

README 明确说明这是完全宿主机、Shell 开启、无安全隔离的受信部署模式；不再要求 Reporting 配置 Daytona/local sandbox，但非 Reporting 历史 Workspace API 的配置不在本次删除范围。

- [ ] **Step 5: 运行一次最终相关测试集合**

Run:

```bash
pytest -q \
  smart_reporting/reporting/tests/test_reporting_host_workspace.py \
  smart_reporting/reporting/tests/test_reporting_code_mode.py \
  smart_reporting/reporting/tests/test_reporting_host_workspace_integration.py \
  smart_reporting/reporting/tests/test_analysis_item_workflow.py \
  smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py \
  smart_reporting/reporting/tests/test_reporting_code_generation.py \
  smart_reporting/reporting/tests/test_reporting_workspace_port.py \
  smart_reporting/reporting/tests/test_report_data_sources.py \
  smart_reporting/reporting/tests/test_report_artifact_persistence.py \
  smart_reporting/reporting/tests/test_report_vision.py \
  smart_reporting/reporting/tests/test_reporting_workflow_controller.py \
  smart_reporting/reporting/tests/test_reporting_workflow_lifecycle.py
```

Expected: 新增和相关定向测试全部通过。不要再次运行完整测试；单独说明基线已知失败未包含在最终集合中。

- [ ] **Step 6: 静态验证和提交**

Run:

```bash
rg -n 'create_sandbox_provider|Daytona|local-sandboxd|_async_client|_asandbox_for' smart_reporting/reporting
git diff --check
git status --short
```

Expected: Reporting 生产运行链不调用 sandbox provider 或私有 sandbox API；`git diff --check` 无输出。

```bash
git add smart_reporting/reporting/workflow/controller.py smart_reporting/runtime/execution.py smart_reporting/reporting/tests/test_reporting_host_workspace_integration.py smart_reporting/reporting/tests/test_reporting_workflow_lifecycle.py .env.example README.md
git commit -m "test: verify host reporting workspace isolation"
```
