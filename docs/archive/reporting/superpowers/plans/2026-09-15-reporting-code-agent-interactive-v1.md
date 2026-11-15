# Reporting Code Agent Interactive V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 快速交付可在正式 Reporting Workspace 内多轮写入、探索、运行、修复并签发 Python 脚本的交互式 Code Agent V1。

**Architecture:** 保留 Agno `Agent.arun` 工具循环，以 `ReportingCodeOpenAIResponses` 薄适配器承接 Responses API 的 custom/function 混合协议；每个 coding task 创建独立 Agent、Toolkit、Function、binding 和 CodeMode session。V1 只实现混合协议、正式 Workspace、CodeMode 与源码/输出身份门禁，并接入 analysis/visualization；Knowledge 索引和 LSP 进程管理在后续计划实现。

**Tech Stack:** Python 3.12、Agno 3.0.9、OpenAI Responses API、Pydantic、AnyIO、Loguru、pytest。

**Spec:** `docs/superpowers/specs/2026-09-15-coding-agent-codemode-enhance-design.md`

## Global Constraints

- 不创建临时 Workspace，不复制数据；`write_script` 直接原子替换正式 Workspace 中绑定的脚本。
- `write_script`、`execute_code` 使用 free-form custom tool；其余 V1 工具使用 JSON function tool。
- Coding Agent 使用非流式 Responses 调用，`parallel_tool_calls=False`，`tool_call_limit=20`。
- 每个 task 独享 Agent、model adapter、Toolkit、Function、binding 和 Kernel，不复用可变停止状态。
- 正式脚本必须通过干净 Python 子进程执行；探索 Kernel 的变量和 import 不得成为脚本依赖。
- `submit_script` 必须同时核对源码和所有声明输出的 `FileIdentity`。
- 不实现兼容分支、恢复、草稿持久化、LSP、Knowledge 索引或 Codex JavaScript nested-tool runtime。
- 语义业务校验仍只产生软告警；技术协议、路径、编译、执行和身份错误失败关闭。
- 应用日志只使用 Loguru。
- 协议、task binding、Toolkit 和 runner 的新增行为集中在 `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`；Workflow 行为改写原有 focused tests。每个任务只运行对应定点 `-k`，最终统一运行一次受影响测试集合，禁止运行完整测试集。

## File Map

- Create `smart_reporting/reporting/code_agent/__init__.py`: V1 公共类型和工厂出口。
- Create `smart_reporting/reporting/code_agent/protocol.py`: custom/function 定义、响应解析和消息重放适配。
- Create `smart_reporting/reporting/code_agent/context.py`: task context、execution receipt、binding 和并发注册表。
- Create `smart_reporting/reporting/code_agent/toolkit.py`: 六个 V1 工具、源码校验、运行及签发门禁。
- Create `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`: 唯一新增测试文件，覆盖协议、工具、runner 和 Workflow 接线。
- Modify `smart_reporting/reporting/agent.py`: 删除旧单轮 custom source provider，改为导入新协议适配器并创建 task 独享 Agent。
- Modify `smart_reporting/reporting/code_mode.py`: 用 `%%bash` 启动干净 Python 子进程并提供 task binding 生命周期。
- Modify `smart_reporting/reporting/workflow/runtime/code_generation.py`: 删除 patch-before-write 和 generate/repair 双入口，改为单一交互 runner。
- Modify `smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py`: 消费已执行的签发回执，不再单独运行脚本。
- Modify `smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py`: 消费已执行的签发回执，保留领域视觉验收后的新 task 修复。
- Modify `smart_reporting/reporting/workflow/runtime/analysis.py`: 为 analysis/visualization 构造 task context、声明输出和统一 diagnostic。
- Modify `smart_reporting/reporting/workflow/runtime/base.py`: 保存 Code Agent factory，不缓存 Code Agent 实例。
- Modify `smart_reporting/reporting/bootstrap.py`: 注入 factory 和共享 CodeMode runtime。
- Modify `smart_reporting/reporting/workflow/runtime/__init__.py`: 导出新的 runner/result 接口。
- Modify `smart_reporting/reporting/tests/test_analysis_item_workflow.py`: 将 generate/repair/execute/load 四回调测试改为单一 `run_code` 回调与签发回执断言。
- Modify `smart_reporting/reporting/tests/test_reporting_generator_agent.py`: 删除已迁入统一测试文件的旧单轮 custom provider 断言。
- Modify `smart_reporting/reporting/tests/test_reporting_code_generation.py`: 删除不再成立的 patch-before-write、generate/repair 和单次源码提交测试；保留并改写限流归一化、有界诊断和 Loguru 日志测试。
- Modify `smart_reporting/reporting/tests/test_reporting_code_mode.py`: 删除已迁入统一测试文件的旧 Kernel 内 `exec` 测试，保留资源构造的无关覆盖。
- Modify `smart_reporting/reporting/tests/test_reporting_code_responses_integration.py`: 将旧 `submit_python_source` smoke test 改为混合工具非流式 smoke test；没有 provider 凭据时继续按现有规则 skip。

## Unified Test Support Contract

以下 helper 按依赖分阶段加入同一个测试文件：Task 1 加入 `SOURCE` 至 `_assistant_and_result_messages`；Task 2 加入 `_task_context`、`_run_context`、`FakeCodeMode` 和 `workspace`；Task 3 再加入 `_valid_source`、`_failed_cell`、`_receipt`、`_write_output`、`ToolkitRuntime`、`binding` 和 `runtime`。后续任务只能使用这里定义的 helper、pytest 内建夹具，或测试函数内部定义的局部 fake。文件首行使用 `from __future__ import annotations`，每个 task 只导入当时已存在的生产类型，保证各任务自己的定点测试可独立收集。Workflow 已有的 `_context()`、`_visualization_plan()`、`_visualization_payload()` 和 `_inspection()` 继续留在 `test_reporting_fixed_phase_workflows.py`，不复制到统一文件。

```python
SOURCE = "from pathlib import Path\nPath('analysis/out.json').write_text('{}')\n"


def _identity(path: str, content: bytes) -> FileIdentity:
    return FileIdentity(path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest())


def _function(name: str) -> Function:
    argument = FREEFORM_TOOL_ARGUMENTS.get(name)
    properties = {argument: {"type": "string"}} if argument else {}
    return Function(
        name=name,
        description=name,
        parameters={
            "type": "object",
            "properties": properties,
            "required": [argument] if argument else [],
            "additionalProperties": False,
        },
        entrypoint=lambda **_kwargs: {"ok": True},
    )


def _code_responses_model() -> ReportingCodeOpenAIResponses:
    return ReportingCodeOpenAIResponses(
        id="test-model", api_key="test-key", base_url="http://localhost"
    )


def _custom_response(name: str, value: str) -> Response:
    return Response.model_validate(
        {
            "id": "resp-1",
            "created_at": 0,
            "model": "test-model",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "item-1",
                    "call_id": "call-1",
                    "name": name,
                    "input": value,
                    "type": "custom_tool_call",
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        }
    )


def _assistant_and_result_messages(call: dict[str, Any], result: object) -> list[Message]:
    return [
        Message(role="assistant", tool_calls=[call]),
        Message(
            role="tool",
            tool_call_id=call["call_id"],
            tool_name=call["function"]["name"],
            content=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        ),
    ]


def _task_context(
    workspace: HostReportingWorkspace,
    *,
    task_id: str = "task-1",
    script_path: str = "analysis/a.py",
) -> ReportingCodingTaskContext:
    return ReportingCodingTaskContext(
        task_id=task_id,
        task_kind="analysis",
        code_mode_session_id=f"code-{task_id}",
        workspace_key=workspace.identity.workspace_key,
        workspace_root=workspace.identity.root,
        script_path=script_path,
        authorized_read_paths=(),
        authorized_write_paths=(script_path, "analysis/out.json"),
        declared_output_paths=("analysis/out.json",),
        max_source_bytes=128 * 1024,
    )


def _run_context(task_id: str = "task-1") -> RunContext:
    return RunContext(run_id=task_id, session_id="session-1")


def _valid_source() -> str:
    return SOURCE


def _failed_cell(traceback: str) -> SimpleNamespace:
    return SimpleNamespace(
        status="error",
        stdout="",
        stderr="",
        result=None,
        traceback=traceback,
        truncated=[],
        execution_count=1,
    )


def _receipt() -> ExecutionReceipt:
    return ExecutionReceipt(
        runId="old-run",
        sourceFile=_identity("analysis/a.py", SOURCE.encode()),
        outputFiles=(_identity("analysis/out.json", b"{}"),),
    )


async def _write_output(workspace: HostReportingWorkspace, path: str) -> None:
    await workspace.awrite_text("task-1", path, "{}", overwrite=False)


class FakeCodeMode:
    def __init__(self) -> None:
        self.cells: list[tuple[str, str]] = []
        self.shutdowns: list[str | None] = []

    async def arun(self, session_id: str, code: str) -> SimpleNamespace:
        self.cells.append((session_id, code))
        return SimpleNamespace(
            status="ok",
            stdout="",
            stderr="",
            result=None,
            traceback=None,
            truncated=[],
            execution_count=len(self.cells),
        )

    async def ashutdown(self, session_id: str | None = None) -> None:
        self.shutdowns.append(session_id)


class ToolkitRuntime:
    def __init__(self) -> None:
        self.next_cell: SimpleNamespace | None = None
        self.shutdowns: list[str] = []

    async def execute(self, _session_id, _workspace, _code, **_kwargs):
        return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

    async def execute_script_process(self, _session_id, workspace, _path, **_kwargs):
        if self.next_cell is not None:
            cell, self.next_cell = self.next_cell, None
            return cell
        await workspace.awrite_text("task-1", "analysis/out.json", "{}")
        return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

    async def shutdown(self, session_id: str) -> None:
        self.shutdowns.append(session_id)


@pytest.fixture
def workspace(tmp_path: Path) -> HostReportingWorkspace:
    scope = ReportingWorkflowScope(
        run_id="run-1",
        external_run_id="external-run-1",
        session_id="session-1",
        caller_thread_id="thread-1",
        user_id="user-1",
        database="database-1",
        company_id="company-1",
        thread_lease_key="lease-1",
        workspace_key="workspace-1",
    )
    identity = ReportingWorkspaceRegistry(tmp_path, secret="0" * 32).resolve(scope)
    return HostReportingWorkspace(identity)


@pytest.fixture
def binding(workspace: HostReportingWorkspace) -> ReportingCodingTaskBinding:
    return ReportingCodingTaskBinding(_task_context(workspace), workspace)


@pytest.fixture
def runtime() -> ToolkitRuntime:
    return ToolkitRuntime()
```

统一测试文件从 `test_reporting_code_mode.py` 复用相同的真实 `HostReportingWorkspace` 构造方式；`ToolkitRuntime` 只替代 Kernel I/O，不替代 Workspace 文件和身份计算。

---

### Task 1: Mixed Responses Protocol Adapter

**Files:**
- Create: `smart_reporting/reporting/code_agent/__init__.py`
- Create: `smart_reporting/reporting/code_agent/protocol.py`
- Modify: `smart_reporting/reporting/agent.py:2590-2937`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`

**Interfaces:**
- Consumes: Agno `OpenAIResponses`, `Message`, `ModelResponse`, `Function`。
- Produces: `FREEFORM_TOOL_ARGUMENTS: Mapping[str, str]`、`ReportingCodeOpenAIResponses`。

- [ ] **Step 1: Write failing mixed-protocol tests in the unified test file**

```python
def test_mixed_protocol_formats_only_large_text_tools_as_custom() -> None:
    model = _code_responses_model()
    tools = model._format_tool_params([], [_function("read_script"), _function("write_script")])
    assert tools[0]["type"] == "function"
    assert tools[1] == {
        "type": "custom",
        "name": "write_script",
        "description": "write_script",
        "format": {"type": "text"},
    }


def test_custom_call_round_trip_uses_custom_output() -> None:
    model = _code_responses_model()
    parsed = model._parse_provider_response(_custom_response("execute_code", "print('ok')"))
    call = parsed.tool_calls[0]
    assert json.loads(call["function"]["arguments"]) == {"code": "print('ok')"}
    assert call["provider_data"]["reporting_wire_type"] == "custom"
    replay = model._format_messages(_assistant_and_result_messages(call, {"ok": True}))
    assert [item["type"] for item in replay[-2:]] == [
        "custom_tool_call",
        "custom_tool_call_output",
    ]


def test_function_call_round_trip_stays_function_protocol() -> None:
    model = _code_responses_model()
    response = Response.model_validate(
        {
            "id": "resp-2",
            "created_at": 0,
            "model": "test-model",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "item-2",
                    "call_id": "call-2",
                    "name": "run_script",
                    "arguments": "{}",
                    "type": "function_call",
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        }
    )
    parsed = model._parse_provider_response(response)
    replay = model._format_messages(
        _assistant_and_result_messages(parsed.tool_calls[0], {"ok": True})
    )
    assert [item["type"] for item in replay[-2:]] == [
        "function_call",
        "function_call_output",
    ]


def test_custom_protocol_rejects_streaming_and_unknown_names() -> None:
    assistant = Message(role="assistant", content="")
    with pytest.raises(ReportingError, match="非流式"):
        _code_responses_model().invoke_stream(
            [], assistant, None, [_function("write_script")]
        )
    with pytest.raises(ReportingError) as caught:
        _code_responses_model()._parse_provider_response(_custom_response("unknown", "x"))
    assert caught.value.code == "report_code_custom_tool_protocol_error"
```

- [ ] **Step 2: Run the protocol tests and verify they fail**

Run: `/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'mixed_protocol or custom_call or function_call or custom_protocol'`

Expected: FAIL because `smart_reporting.reporting.code_agent.protocol` does not exist.

- [ ] **Step 3: Implement the protocol constants and request formatter**

```python
FREEFORM_TOOL_ARGUMENTS: Mapping[str, str] = MappingProxyType(
    {"write_script": "source", "execute_code": "code"}
)


class ReportingCodeOpenAIResponses(OpenAIResponses):
    def _format_tool_params(self, messages, tools=None):
        formatted = super()._format_tool_params(messages, tools)
        result = []
        for tool in formatted:
            name = str(tool.get("name") or "")
            if name not in FREEFORM_TOOL_ARGUMENTS:
                result.append(tool)
                continue
            result.append(
                {
                    "type": "custom",
                    "name": name,
                    "description": str(tool.get("description") or name),
                    "format": {"type": "text"},
                }
            )
        return result
```

- [ ] **Step 4: Implement non-streaming custom call parsing and message replay**

```python
def _synthetic_custom_call(item: Any) -> dict[str, Any]:
    name = _field(item, "name")
    raw_input = _field(item, "input")
    if name not in FREEFORM_TOOL_ARGUMENTS or not isinstance(raw_input, str) or not raw_input:
        raise ReportingError(
            "report_code_custom_tool_protocol_error",
            "Coding Agent custom 工具调用无效。",
        )
    item_id = _required_id(item, "id")
    call_id = _required_id(item, "call_id")
    return {
        "id": item_id,
        "call_id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(
                {FREEFORM_TOOL_ARGUMENTS[name]: raw_input},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
        "provider_data": {
            "reporting_wire_type": "custom",
            "raw_input": raw_input,
        },
    }
```

Override `_parse_provider_response()` to append exactly one actionable custom or function call when `parallel_tool_calls=False`. Override `_format_messages()` by calling Agno first, building a `call_id -> provider_data` map from assistant tool calls, and converting only marked calls/results to `custom_tool_call` and `custom_tool_call_output`. Preserve both provider item id and call id; do not infer type from the latest tool list or a `ContextVar`. Keep `invoke_stream` and `ainvoke_stream` fail-closed whenever either free-form tool is present.

- [ ] **Step 5: Remove the old source-only provider body from `agent.py` and re-export the new class**

```python
from .code_agent.protocol import ReportingCodeOpenAIResponses
```

Delete `_REPORT_CODE_CUSTOM_TOOL_REQUEST`, the unique-tool restriction, source-only response validation, and source-stage thinking removal. Retain existing model routing, projection, error recording and Loguru duration logging by moving those methods into `protocol.py` unchanged except for their custom protocol dependencies.

- [ ] **Step 6: Re-run the protocol tests**

Run: `/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'mixed_protocol or custom_call or function_call or custom_protocol'`

Expected: PASS.

- [ ] **Step 7: Commit the protocol adapter**

```bash
git add smart_reporting/reporting/code_agent/__init__.py smart_reporting/reporting/code_agent/protocol.py smart_reporting/reporting/agent.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git commit -m "refactor: support mixed reporting code tools"
```

### Task 2: Task Binding and Clean CodeMode Execution

**Files:**
- Create: `smart_reporting/reporting/code_agent/context.py`
- Modify: `smart_reporting/reporting/code_mode.py`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`

**Interfaces:**
- Consumes: `HostReportingWorkspace`、`FileIdentity`、Agno `CodeMode`。
- Produces: `ReportingCodingTaskContext`、`ExecutionReceipt`、`ReportingCodingTaskBinding`、`ReportingCodingTaskRegistry.bind()`、`ReportingCodeModeRuntime.execute_script_process()`。

- [ ] **Step 1: Add failing context, conflict and clean-subprocess tests**

```python
async def test_coding_task_registry_rejects_same_script_concurrently(workspace) -> None:
    registry = ReportingCodingTaskRegistry()
    first = _task_context(workspace, task_id="first", script_path="analysis/a.py")
    second = _task_context(workspace, task_id="second", script_path="analysis/a.py")
    async with registry.bind(first, workspace):
        with pytest.raises(ReportingError) as caught:
            async with registry.bind(second, workspace):
                pass
    assert caught.value.code == "report_coding_task_conflict"


async def test_execute_script_uses_clean_python_subprocess(workspace) -> None:
    code_mode = FakeCodeMode()
    runtime = ReportingCodeModeRuntime(code_mode)
    await runtime.execute("task-1", workspace, "leaked = 7")
    await runtime.execute_script_process("task-1", workspace, "analysis/a.py", matplotlib_agg=False)
    assert code_mode.cells[-1][1].startswith("%%bash\n")
    assert "exec(compile(" not in code_mode.cells[-1][1]
    assert "analysis/a.py" in code_mode.cells[-1][1]
```

- [ ] **Step 2: Run the context/runtime tests and verify they fail**

Run: `/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'coding_task_registry or clean_python_subprocess'`

Expected: FAIL because the context types and `execute_script_process` are missing.

- [ ] **Step 3: Implement immutable context and receipt models**

```python
@dataclass(frozen=True, slots=True)
class ReportingCodingTaskContext:
    task_id: str
    task_kind: Literal["analysis", "visualization"]
    code_mode_session_id: str
    workspace_key: str
    workspace_root: Path
    script_path: str
    authorized_read_paths: tuple[str, ...]
    authorized_write_paths: tuple[str, ...]
    declared_output_paths: tuple[str, ...]
    max_source_bytes: int


class ExecutionReceipt(StrictModel):
    run_id: str = Field(alias="runId", min_length=1, max_length=128)
    source_file: FileIdentity = Field(alias="sourceFile")
    output_files: tuple[FileIdentity, ...] = Field(alias="outputFiles", max_length=100)


@dataclass(slots=True)
class ReportingCodingTaskBinding:
    context: ReportingCodingTaskContext
    workspace: HostReportingWorkspace
    execution_receipt: ExecutionReceipt | None = None
```

Validate every path with `WorkspaceService.normalize_path`, require the script in `authorized_write_paths`, require declared outputs in `authorized_write_paths`, require the physical root to equal `workspace.identity.root`, and sort/deduplicate path tuples in `__post_init__`.

- [ ] **Step 4: Implement the process-local binding registry**

```python
@asynccontextmanager
async def bind(self, context, workspace):
    async with self._lock:
        script_key = (context.workspace_key, context.script_path)
        if context.task_id in self._by_task or script_key in self._by_script:
            raise ReportingError("report_coding_task_conflict", "Coding task 与活动脚本冲突。")
        binding = ReportingCodingTaskBinding(context, workspace)
        self._by_task[context.task_id] = binding
        self._by_script[script_key] = context.task_id
    try:
        yield binding
    finally:
        async with self._lock:
            self._by_task.pop(context.task_id, None)
            self._by_script.pop(script_key, None)

@property
def active_count(self) -> int:
    return len(self._by_task)
```

- [ ] **Step 5: Replace Kernel-global script execution with a service-built bash cell**

```python
def _script_process_cell(script_path: str) -> str:
    command = " ".join((shlex.quote(sys.executable), shlex.quote(script_path)))
    return f"%%bash\n{command}\n"


async def execute_script_process(self, session_id, workspace, script_path, *, matplotlib_agg):
    normalized = workspace.paths.normalize(script_path)
    await self._bootstrap(session_id, workspace, matplotlib_agg=matplotlib_agg)
    return await self.code_mode.arun(session_id, _script_process_cell(normalized))
```

Delete `_script_cell()` and make the existing `execute_script()` compatibility-free call site disappear in Task 4. Keep bounded exception conversion and `shutdown()`/`aclose()`.

- [ ] **Step 6: Re-run the context/runtime tests**

Run: `/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'coding_task_registry or clean_python_subprocess'`

Expected: PASS.

- [ ] **Step 7: Commit task binding and runtime**

```bash
git add smart_reporting/reporting/code_agent/context.py smart_reporting/reporting/code_mode.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git commit -m "feat: bind interactive code mode tasks"
```

### Task 3: Workspace Toolkit and Execution Identity Gate

**Files:**
- Create: `smart_reporting/reporting/code_agent/toolkit.py`
- Modify: `smart_reporting/reporting/code_agent/__init__.py`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`

**Interfaces:**
- Consumes: `ReportingCodingTaskBinding`、`ReportingCodeModeRuntime`、workspace `awrite_text`/`read_limited_regular_file`/`ahash_file`/`adelete_file`。
- Produces: `ReportingCodeModeToolkit.tool_functions: tuple[Function, ...]`，固定包含 `read_script`、`write_script`、`execute_code`、`restart_code_mode`、`run_script`、`submit_script`；属性合并 Agno 的 `functions` 与 `async_functions`，不得漏掉 async entrypoint。

- [ ] **Step 1: Add failing tool lifecycle tests**

```python
async def test_run_and_submit_bind_source_and_declared_outputs(binding, runtime) -> None:
    toolkit = ReportingCodeModeToolkit(binding, runtime)
    await toolkit.write_script("from pathlib import Path\nPath('analysis/out.json').write_text('{}')\n")
    run = await toolkit.run_script()
    assert run["ok"] is True
    submitted = await toolkit.submit_script()
    assert submitted["ok"] is True
    assert submitted["executionReceipt"]["sourceFile"]["path"] == "analysis/a.py"
    assert [item["path"] for item in submitted["executionReceipt"]["outputFiles"]] == [
        "analysis/out.json"
    ]


async def test_submit_rejects_source_or_output_changed_after_run(binding, runtime) -> None:
    toolkit = ReportingCodeModeToolkit(binding, runtime)
    await toolkit.write_script(_valid_source())
    assert (await toolkit.run_script())["ok"] is True
    await binding.workspace.awrite_text("task", "analysis/out.json", '{"changed":true}', overwrite=True)
    rejected = await toolkit.submit_script()
    assert rejected["code"] == "report_code_output_modified_after_execution"


async def test_failed_run_clears_old_declared_output_and_receipt(binding, runtime) -> None:
    toolkit = ReportingCodeModeToolkit(binding, runtime)
    binding.execution_receipt = _receipt()
    await _write_output(binding.workspace, "analysis/out.json")
    runtime.next_cell = _failed_cell("ValueError: bad")
    result = await toolkit.run_script()
    assert result["ok"] is False
    assert binding.execution_receipt is None
    assert not await binding.workspace.apath_exists("task", "analysis/out.json")
```

- [ ] **Step 2: Run the toolkit tests and verify they fail**

Run: `/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'run_and_submit or changed_after_run or clears_old_declared_output'`

Expected: FAIL because `ReportingCodeModeToolkit` is missing.

- [ ] **Step 3: Move and simplify the shared source validator**

Move `_validate_python_source_shape`, `_compile_python_source`, authorized literal-path extraction and diagnostic bounding from `workflow/runtime/code_generation.py` into `code_agent/toolkit.py`. Delete `_unwrap_json_encoded_python_source`, `_restore_escaped_python_lines` and `_python_source_patch`; free-form input must be accepted verbatim after LF/trailing-newline/size checks.

```python
def validate_script_source(context: ReportingCodingTaskContext, source: str) -> bytes:
    raw = source.encode("utf-8")
    if not source or "\r" in source or not source.endswith("\n"):
        raise ReportingError("report_code_source_invalid", "Python 源码形状无效。")
    if len(raw) > context.max_source_bytes or any(
        len(line.encode("utf-8")) > MAX_PHYSICAL_LINE_BYTES for line in source.split("\n")
    ):
        raise ReportingError("report_code_source_invalid", "Python 源码超过限制。")
    compile_script_source(context.script_path, source, frozenset(context.authorized_read_paths))
    return raw
```

`write_script` only runs text/path/size/physical-line checks so syntax-invalid drafts can be stored. `run_script` and `submit_script` run AST, compile and authorized-path checks.

- [ ] **Step 4: Implement read, write, execute and restart tools**

```python
async def write_script(self, source: str, run_context: RunContext | None = None) -> dict[str, Any]:
    del run_context
    raw = validate_draft_source(self.context, source)
    exists = await self.workspace.apath_exists(self.context.task_id, self.context.script_path)
    await self.workspace.awrite_text(
        self.context.task_id,
        self.context.script_path,
        source,
        overwrite=exists,
    )
    self.binding.execution_receipt = None
    return {"ok": True, **await self.workspace.ahash_file(self.context.task_id, self.context.script_path)}
```

`read_script` returns `{ok, exists, path, source, size, sha256}` without accepting a path. `execute_code` calls `runtime.execute` and bounds stdout/stderr/traceback to 8 KB total. `restart_code_mode` calls `shutdown(session_id)`, clears no files, and returns `{ok:true}`.

- [ ] **Step 5: Implement authoritative run and submit**

```python
async def run_script(self, run_context: RunContext | None = None) -> dict[str, Any]:
    del run_context
    self.binding.execution_receipt = None
    source_before = await self._validated_source_identity()
    await self._clear_declared_outputs()
    cell = await self.runtime.execute_script_process(
        self.context.code_mode_session_id,
        self.workspace,
        self.context.script_path,
        matplotlib_agg=self.context.task_kind == "visualization",
    )
    if _cell_status(cell) != "ok":
        return _bounded_failure("report_code_mode_execution_failed", cell)
    source_after = await self._validated_source_identity()
    if source_after != source_before:
        return _failure("report_code_script_modified_during_execution")
    outputs = await self._declared_output_identities()
    receipt = ExecutionReceipt(
        runId=uuid4().hex,
        sourceFile=source_after,
        outputFiles=outputs,
    )
    self.binding.execution_receipt = receipt
    return {"ok": True, "executionReceipt": receipt.model_dump(mode="json", by_alias=True)}
```

`submit_script` recomputes source/output identities and compares full Pydantic values with the last receipt. Return recoverable `{ok:false,...}` on no run, missing output or changed output. Its Function uses the same pre/post-hook pattern as `ReportingToolkit`: reset `stop_after_tool_call=False` before each call and set it to true only when `result["ok"] is True`.

`ReportingCodeModeToolkit.__init__` sets `submitted_receipt: ExecutionReceipt | None = None`. `write_script` and every `run_script` attempt clear it; a successful `submit_script` assigns the verified receipt before returning JSON. Expose all registered tools through:

```python
@property
def tool_functions(self) -> tuple[Function, ...]:
    return tuple([*self.functions.values(), *self.async_functions.values()])
```

- [ ] **Step 6: Re-run the toolkit tests**

Run: `/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'run_and_submit or changed_after_run or clears_old_declared_output'`

Expected: PASS.

- [ ] **Step 7: Commit the toolkit**

```bash
git add smart_reporting/reporting/code_agent/__init__.py smart_reporting/reporting/code_agent/toolkit.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git commit -m "feat: add interactive reporting code tools"
```

### Task 4: Single Interactive Runner and Task-Exclusive Agent Factory

**Files:**
- Modify: `smart_reporting/reporting/agent.py:3255-3469`
- Modify: `smart_reporting/reporting/workflow/runtime/code_generation.py`
- Modify: `smart_reporting/reporting/workflow/runtime/__init__.py`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`

**Interfaces:**
- Consumes: `ReportingCodeModeToolkit`、`ReportingCodingTaskRegistry`、`ReportingCodingTaskContext`。
- Produces: `create_reporting_code_agent_factory(...) -> Callable[[Sequence[Function]], Agent]`、`ReportingCodeGenerationRunner.run(...) -> CodeGenerationResult`。

- [ ] **Step 1: Add failing runner tests**

```python
async def test_runner_uses_one_multitool_run_and_returns_submission(workspace) -> None:
    created = []

    class Runtime:
        shutdowns: list[str] = []

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_text("task-1", "analysis/out.json", "{}")
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    runtime = Runtime()

    class ScriptedAgent:
        tool_call_limit = 20
        model = SimpleNamespace(parallel_tool_calls=False)

        def __init__(self, tools: Sequence[Function]) -> None:
            self.tools = {tool.name: tool for tool in tools}

        async def arun(self, _prompt: str, **_kwargs: Any) -> object:
            await self.tools["write_script"].entrypoint(source=SOURCE)
            await self.tools["run_script"].entrypoint()
            return await self.tools["submit_script"].entrypoint()

    def factory(tools: Sequence[Function]) -> ScriptedAgent:
        agent = ScriptedAgent(tools)
        created.append(agent)
        return agent

    result = await ReportingCodeGenerationRunner(factory, runtime).run(
        _task_context(workspace),
        workspace,
        {"fact": 1},
        run_context=_run_context("task-1"),
    )
    assert len(created) == 1
    assert result.script_file.path == "analysis/a.py"
    assert result.execution_receipt.output_files[0].path == "analysis/out.json"
    assert created[0].tool_call_limit == 20
    assert created[0].model.parallel_tool_calls is False


async def test_runner_shuts_down_kernel_on_no_submission(workspace) -> None:
    class Runtime:
        def __init__(self) -> None:
            self.shutdowns: list[str] = []

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    runtime = Runtime()

    class TextOnlyAgent:
        async def arun(self, _prompt: str, **_kwargs: Any) -> str:
            return "done"

    with pytest.raises(ReportingError) as caught:
        await ReportingCodeGenerationRunner(lambda _tools: TextOnlyAgent(), runtime).run(
            _task_context(workspace), workspace, {}, run_context=_run_context("task-1")
        )
    assert caught.value.code == "report_code_generation_no_submission"
    assert runtime.shutdowns == ["code-task-1"]


def test_code_agent_factory_creates_task_exclusive_mutable_objects() -> None:
    factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        name="reporting-code-agent",
    )
    first = factory([_function("read_script")])
    second = factory([_function("read_script")])
    assert first is not second
    assert first.model is not second.model
    assert first.tools[0] is not second.tools[0]
```

- [ ] **Step 2: Run runner tests and verify they fail**

Run: `/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'runner_ or code_agent_factory'`

Expected: FAIL because the runner still exposes `generate` and `repair`.

- [ ] **Step 3: Replace the code agent template with a factory**

```python
CodeAgentFactory = Callable[[Sequence[Function]], Agent]


def create_reporting_code_agent_factory(*, model, name, role=None, instructions=()) -> CodeAgentFactory:
    def create(tools: Sequence[Function]) -> Agent:
        code_model = _reporting_code_model(model)
        code_model.parallel_tool_calls = False
        return Agent(
            id=name,
            name=name,
            role=role or "在正式 Workspace 中交互编写并签发 Reporting Python 脚本。",
            model=code_model,
            reasoning_model=None,
            reasoning_agent=None,
            instructions=[*_INTERACTIVE_CODE_INSTRUCTIONS, *instructions],
            tools=list(tools),
            tool_choice="auto",
            tool_call_limit=20,
            add_history_to_context=False,
            store_history_messages=False,
            retries=0,
            exponential_backoff=False,
            telemetry=False,
        )
    return create
```

Use Responses reasoning/thinking on the main model according to the bound policy; delete the separate `ReportingCodeReasoningAgent` and second-stage non-thinking source request.

- [ ] **Step 4: Replace generate/repair with one runner method**

```python
@dataclass(frozen=True, slots=True)
class CodeGenerationResult:
    script_file: FileIdentity
    execution_receipt: ExecutionReceipt


async def run(self, task_context, workspace, task_facts, *, run_context, diagnostic=None):
    async with self.registry.bind(task_context, workspace) as binding:
        toolkit = ReportingCodeModeToolkit(binding, self.code_mode_runtime)
        agent = self.agent_factory(toolkit.tool_functions)
        prompt = self._prompt(
            {
                "task": asdict(task_context),
                "facts": dict(task_facts),
                "diagnostic": self._short_diagnostic(diagnostic) if diagnostic else None,
            }
        )
        try:
            output = await agent.arun(prompt, run_context=run_context)
            receipt = toolkit.submitted_receipt
            if receipt is None:
                raise self._no_submission(agent, output)
        finally:
            await self.code_mode_runtime.shutdown(task_context.code_mode_session_id)
        await toolkit.require_current_receipt(receipt)
        return CodeGenerationResult(
            script_file=receipt.source_file,
            execution_receipt=receipt,
        )
```

`require_current_receipt()` 复用 `submit_script` 的源码和输出 identity 比较，但失败时抛不可恢复 `ReportingError("report_phase_artifact_changed", ...)`；它在 Kernel 关闭后执行，确保关闭期间的文件变化不会被返回给 Workflow。

Remove patch callbacks, source unwrapping, single-call counters, `_python_source_patch`, `generate`, `repair`, and script recovery reads. Preserve bounded diagnostics, model rate-limit normalization and Loguru duration/base identity logs.

- [ ] **Step 5: Re-run runner tests**

Run: `/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'runner_ or code_agent_factory'`

Expected: PASS.

- [ ] **Step 6: Commit the runner**

```bash
git add smart_reporting/reporting/agent.py smart_reporting/reporting/workflow/runtime/code_generation.py smart_reporting/reporting/workflow/runtime/__init__.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git commit -m "refactor: run reporting code interactively"
```

### Task 5: Analysis and Visualization Workflow Integration

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py`
- Modify: `smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/workflow/runtime/base.py`
- Modify: `smart_reporting/reporting/bootstrap.py`
- Test: `smart_reporting/reporting/tests/test_analysis_item_workflow.py`
- Test: `smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`

**Interfaces:**
- Consumes: `ReportingCodeGenerationRunner.run()` and signed `ExecutionReceipt` output identities。
- Produces: analysis/visualization flows that do not execute a signed script a second time。

- [ ] **Step 1: Rewrite the existing Workflow contract tests to the single callback**

```python
async def test_visualization_review_failure_starts_new_interactive_run() -> None:
    plan = _visualization_plan()
    initial = CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64),
        execution_receipt=_execution_receipt(
            "charts/charts.py", 1, "a" * 64, ("charts/chart.png",)
        ),
    )
    repaired = CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=2, sha256="b" * 64),
        execution_receipt=_execution_receipt(
            "charts/charts.py", 2, "b" * 64, ("charts/chart.png",)
        ),
    )
    run_code = AsyncMock(side_effect=[initial, repaired])
    failed = _inspection().model_copy(
        update={"visual_review_status": "failed", "requires_revision": True}
    )
    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=plan),
        run_code=run_code,
        inspect_chart=AsyncMock(side_effect=[failed, _inspection()]),
        submit=AsyncMock(return_value={"status": "accepted"}),
    )
    result = await workflow.run(_visualization_payload(), _context())
    assert result.status == "accepted"
    assert run_code.await_count == 2
    assert run_code.await_args_list[1].kwargs["diagnostic"]["code"] == "report_visualization_review_failed"
```

在两个 Workflow 测试文件中加入同一个小 helper，然后把现有 `test_analysis_item_workflow_executes_all_five_stages_in_order` 改为 `run_code=AsyncMock(return_value=CodeGenerationResult(...))`，并将事件断言从 `generate, execute` 收敛为一次 `run_code`；保留随后通过 `read_file` 校验证据 JSON 的断言。

```python
def _execution_receipt(
    script_path: str,
    script_size: int,
    script_sha256: str,
    output_paths: tuple[str, ...],
) -> ExecutionReceipt:
    return ExecutionReceipt(
        runId="run-1",
        sourceFile=FileIdentity(
            path=script_path,
            size=script_size,
            sha256=script_sha256,
        ),
        outputFiles=tuple(
            FileIdentity(path=path, size=1, sha256=str(index) * 64)
            for index, path in enumerate(output_paths, start=1)
        ),
    )
```

- [ ] **Step 2: Run Workflow integration tests and verify they fail**

Run: `/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_analysis_item_workflow.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py -k 'executes_all_five_stages_in_order or visualization_review_failure_starts_new_interactive_run'`

Expected: FAIL because both workflows still own separate generate/execute/repair callbacks.

- [ ] **Step 3: Collapse analysis script callbacks into `run_code`**

```python
class RunAnalysisCode(Protocol):
    def __call__(
        self,
        *,
        script_path: str,
        task_facts: Mapping[str, Any],
        diagnostic: Mapping[str, Any] | None,
        run_context: RunContext,
    ) -> Awaitable[CodeGenerationResult]: ...


class RunVisualizationCode(Protocol):
    def __call__(
        self,
        plan: VisualizationPlanDraft,
        run_context: RunContext,
        /,
        *,
        diagnostic: Mapping[str, Any] | None,
        task_facts: Mapping[str, Any] | None = None,
    ) -> Awaitable[CodeGenerationResult]: ...


class AnalysisItemWorkflow:
    def __init__(self, *, decide_evidence, run_code: RunAnalysisCode, summarize, read_file, complete):
        self.run_code = run_code
```

In `_execute_script`, call `run_code(script_path=..., task_facts=..., diagnostic=...)`, store `script_file` and `execution_receipt`, and mark execution complete. Remove `generate_script`, `repair_script`, `run_script`, `load_script`, generation counters and recovery loading. Keep the outer evidence-validation loop so a domain validation failure starts a new task-exclusive Agent with the bounded diagnostic.

- [ ] **Step 4: Collapse visualization script callbacks into `run_code`**

```python
class VisualizationSectionWorkflow:
    def __init__(self, *, generate_plan, run_code: RunVisualizationCode, inspect_chart, submit, degrade=None, **policy):
        self.run_code = run_code
```

Call `run_code` once before inspection. On `report_visualization_review_failed`, preserve existing execution/visual repair budgets but call `run_code` again with `_repair_diagnostic(...)`; do not call a separate executor. Before inspection, require each `plan.charts[].source_path` identity to exist in `result.execution_receipt.output_files`.

- [ ] **Step 5: Build trusted task contexts in `analysis.py`**

```python
task_context = ReportingCodingTaskContext(
    task_id=task_id,
    task_kind="analysis",
    code_mode_session_id=f"analysis:{task_id}",
    workspace_key=task_workspace.identity.workspace_key,
    workspace_root=task_workspace.identity.root,
    script_path=script_path,
    authorized_read_paths=tuple(sorted(dataset_paths)),
    authorized_write_paths=(script_path, evidence_path),
    declared_output_paths=(evidence_path,),
    max_source_bytes=_ANALYSIS_SCRIPT_MAX_BYTES,
)
```

For visualization, derive `declared_output_paths` exactly from `plan.charts[].source_path`, include the script path in authorized writes, and include frozen fact paths in authorized reads. Replace every `generate`/`repair`/`execute_script` closure with one `run_code` closure invoking `ReportingCodeGenerationRunner.run`.

- [ ] **Step 6: Change runtime/bootstrap ownership from Agent instances to factories**

Store `_analysis_script_agent_factory` and `visualization_code_agent_factory`; call them only inside `ReportingCodeGenerationRunner`. Update constructor annotations and tests that inspect the old cached Agent. Continue injecting the existing shared `ReportingCodeModeRuntime`; each runner still creates and shuts down a distinct session.

- [ ] **Step 7: Re-run Workflow integration tests**

Run: `/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_analysis_item_workflow.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py -k 'executes_all_five_stages_in_order or visualization_review_failure_starts_new_interactive_run'`

Expected: PASS.

- [ ] **Step 8: Commit Workflow integration**

```bash
git add smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/workflow/runtime/base.py smart_reporting/reporting/bootstrap.py smart_reporting/reporting/tests/test_analysis_item_workflow.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py
git commit -m "refactor: integrate interactive code workflows"
```

### Task 6: Remove Obsolete Contracts and Run One Unified Regression Suite

**Files:**
- Modify: `smart_reporting/reporting/tests/test_reporting_generator_agent.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_code_mode.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_code_generation.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_code_responses_integration.py`
- Modify: `smart_reporting/reporting/tests/test_analysis_item_workflow.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_planner_contracts.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_workflow_lifecycle.py`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`

**Interfaces:**
- Consumes: all V1 public interfaces from Tasks 1-5。
- Produces: one coherent V1 regression suite with no assertions for removed compatibility behavior。

- [ ] **Step 1: Add the final acceptance and cleanup tests to the unified file**

```python
async def test_interactive_v1_write_fail_fix_run_submit(workspace) -> None:
    binding = ReportingCodingTaskBinding(_task_context(workspace), workspace)

    class Runtime:
        async def execute(self, _session_id, _workspace, _code, **_kwargs):
            return SimpleNamespace(status="ok", stdout="probe\n", stderr="", traceback=None)

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            source = await received.aread_text("task-1", "analysis/a.py")
            if "broken" in source:
                return _failed_cell("SyntaxError: invalid syntax")
            exists = await received.apath_exists("task-1", "analysis/out.json")
            await received.awrite_text(
                "task-1", "analysis/out.json", "{}", overwrite=exists
            )
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def shutdown(self, _session_id):
            return None

    runtime = Runtime()
    toolkit = ReportingCodeModeToolkit(binding, runtime)
    await toolkit.write_script("if True print('broken')\n")
    assert (await toolkit.run_script())["ok"] is False
    await toolkit.write_script(SOURCE)
    assert (await toolkit.execute_code("print('probe')"))["ok"] is True
    assert (await toolkit.run_script())["ok"] is True
    submitted = await toolkit.submit_script()
    assert submitted["ok"] is True
    receipt = ExecutionReceipt.model_validate(submitted["executionReceipt"])
    assert receipt.source_file == binding.execution_receipt.source_file
    assert receipt.output_files == binding.execution_receipt.output_files


async def test_interactive_v1_releases_all_task_resources(workspace) -> None:
    registry = ReportingCodingTaskRegistry()

    class Runtime:
        def __init__(self) -> None:
            self.shutdowns: list[str] = []

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_text("task-1", "analysis/out.json", "{}")
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    runtime = Runtime()

    class SubmitAgent:
        tool_call_limit = 20
        model = SimpleNamespace(parallel_tool_calls=False)

        def __init__(self, tools: Sequence[Function]) -> None:
            self.tools = {tool.name: tool for tool in tools}

        async def arun(self, _prompt: str, **_kwargs: Any) -> object:
            await self.tools["write_script"].entrypoint(source=SOURCE)
            await self.tools["run_script"].entrypoint()
            return await self.tools["submit_script"].entrypoint()

    runner = ReportingCodeGenerationRunner(
        lambda tools: SubmitAgent(tools), runtime, registry=registry
    )
    result = await runner.run(
        _task_context(workspace), workspace, {}, run_context=_run_context()
    )
    assert result.script_file == result.execution_receipt.source_file
    assert registry.active_count == 0
    assert runtime.shutdowns == ["code-task-1"]
```

- [ ] **Step 2: Remove obsolete tests and imports**

Delete tests for `submit_python_source`, JSON source unwrapping, escaped-line restoration, patch construction, generate/repair, source call limit one, source-only custom choice and cached Code Agent instances. Retain model routing, bounded errors, Loguru duration/base identity logging and global `aclose()` in their existing focused files, rewriting only their construction and call signatures for the V1 runner.

- [ ] **Step 3: Update existing Workflow fixtures to the `run_code` callback**

```python
async def run_code(*, script_path, task_facts, diagnostic, run_context):
    del task_facts, diagnostic, run_context
    return CodeGenerationResult(
        script_file=_identity(script_path, SOURCE.encode()),
        execution_receipt=_execution_receipt(
            script_path,
            len(SOURCE.encode()),
            hashlib.sha256(SOURCE.encode()).hexdigest(),
            tuple(declared_outputs),
        ),
    )
```

Do not preserve adapter shims for `generate_script`, `repair_script`, `execute_script` or `load_script`.

- [ ] **Step 4: Run the single unified affected regression command**

Run exactly once after all focused red/green loops:

```bash
/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q \
  smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py \
  smart_reporting/reporting/tests/test_reporting_generator_agent.py \
  smart_reporting/reporting/tests/test_reporting_code_mode.py \
  smart_reporting/reporting/tests/test_reporting_code_generation.py \
  smart_reporting/reporting/tests/test_reporting_code_responses_integration.py \
  smart_reporting/reporting/tests/test_analysis_item_workflow.py \
  smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py \
  smart_reporting/reporting/tests/test_reporting_planner_contracts.py \
  smart_reporting/reporting/tests/test_reporting_workflow_lifecycle.py
```

Expected: all selected tests PASS with zero failures; do not run `pytest` over the entire repository.

- [ ] **Step 5: Verify deletion and protocol invariants**

Run:

```bash
rg -n 'submit_python_source|_python_source_patch|ReportingCodeGenerationRunner\([^\n]*\)\.(generate|repair)\(' \
  smart_reporting/reporting/agent.py \
  smart_reporting/reporting/code_agent \
  smart_reporting/reporting/workflow/runtime
git diff --check
```

Expected: `rg` returns no obsolete Coding Agent contract references; `git diff --check` exits 0。

- [ ] **Step 6: Commit the V1 cleanup**

```bash
git add smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py smart_reporting/reporting/tests/test_reporting_generator_agent.py smart_reporting/reporting/tests/test_reporting_code_mode.py smart_reporting/reporting/tests/test_reporting_code_generation.py smart_reporting/reporting/tests/test_reporting_code_responses_integration.py smart_reporting/reporting/tests/test_analysis_item_workflow.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py smart_reporting/reporting/tests/test_reporting_workflow_lifecycle.py
git commit -m "test: unify interactive code agent coverage"
```

## Deferred After V1

- Knowledge SQLite/FTS5 索引、动态成功修复记录和短查询回退。
- `python-lsp-server` 生命周期、diagnostic version、hover/definition/reference/document symbols。
- 流式 `custom_tool_call_input.delta` 解析。
- Codex JavaScript runtime、nested-tool broker、容器隔离和中断恢复。
