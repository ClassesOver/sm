import asyncio
import shlex
import subprocess
import time

import pytest
from agno.run import RunContext
from agno.tools.daytona import DaytonaTools

from agentos_dev import app
from agentos_dev.coding import CodingEvent
from agentos_dev.coding.agent import create_coding_facade_agent
from agentos_dev.coding.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncMemoryRegistry,
    Info,
    service,
)
from agentos_dev.task_execution.tools import (
    CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY,
    CODEX_EXEC_SESSION_TTL_SECONDS,
    CODEX_EXEC_SESSIONS_STATE_KEY,
    CODING_TOOLKIT_INSTRUCTIONS,
    DEFAULT_EXEC_TIMEOUT_SECONDS,
    MAX_CODEX_SESSION_HANDLES,
    PURE_CODING_TOOLKIT_INSTRUCTIONS,
    CodingToolkit,
    HermesCodingToolkit,
    parse_unified_diff,
)
from agentos_dev.workspace import (
    WORKSPACE_ROOT,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceProcessNotFound,
    WorkspaceService,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def context(
    *,
    thread: str = "thread",
    user_id: str = "user",
    state: dict | None = None,
) -> RunContext:
    return RunContext(
        run_id="run",
        session_id=thread,
        user_id=user_id,
        session_state={} if state is None else state,
    )


def async_toolkit(tmp_path):
    current = service(tmp_path)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    return current, CodingToolkit(async_service)


def test_coding_tool_contract_uses_codex_names_and_json_patch(tmp_path):
    toolkit = CodingToolkit(service(tmp_path))
    tools = {**toolkit.functions, **toolkit.async_functions}

    assert set(tools) == {
        "exec_command",
        "poll_process",
        "write_stdin",
        "stop_process",
        "apply_patch",
        "view_image",
        "update_plan",
    }
    assert tools["exec_command"].parameters["required"] == ["cmd"]
    assert set(tools["exec_command"].parameters["properties"]) == {
        "cmd",
        "workdir",
        "tty",
        "timeout_seconds",
        "yield_time_ms",
        "max_output_tokens",
        "shell",
        "login",
    }
    assert tools["poll_process"].parameters["required"] == ["session_id"]
    assert tools["write_stdin"].parameters["required"] == ["session_id", "chars"]
    assert tools["write_stdin"].parameters["properties"]["chars"]["minLength"] == 1
    assert tools["stop_process"].parameters["required"] == ["session_id"]
    assert tools["apply_patch"].parameters["required"] == ["patch"]
    assert tools["apply_patch"].parameters["properties"]["patch"]["type"] == "string"
    assert "apply_changes" not in tools
    assert all(tool.requires_confirmation is False for tool in tools.values())


def test_hermes_coding_toolkit_is_independent_and_keeps_supported_contract(tmp_path):
    coding = CodingToolkit(service(tmp_path))
    toolkit = HermesCodingToolkit(coding)
    tools = {**toolkit.functions, **toolkit.async_functions}

    assert isinstance(coding, DaytonaTools)
    assert isinstance(toolkit, DaytonaTools)
    assert toolkit.name == "hermes_coding"
    assert toolkit.coding is coding
    assert set(tools) == {"terminal", "process", "patch"}
    assert tools["terminal"].parameters["required"] == ["command"]
    assert set(tools["terminal"].parameters["properties"]) == {
        "command",
        "background",
        "timeout",
        "workdir",
        "pty",
        "shell",
    }
    assert tools["process"].parameters["properties"]["action"]["enum"] == [
        "list",
        "poll",
        "wait",
        "kill",
        "write",
        "submit",
    ]
    assert tools["process"].parameters["required"] == ["action"]
    assert tools["patch"].parameters["required"] == ["mode"]
    assert tools["patch"].parameters["properties"]["mode"]["enum"] == [
        "replace",
        "patch",
    ]
    assert all(tool.requires_confirmation is False for tool in tools.values())

    forbidden_brand = "co" + "dex"
    visible_tool_text = "\n".join(
        [
            toolkit.instructions,
            *[tool.description or "" for tool in tools.values()],
            *[str(tool.parameters) for tool in tools.values()],
        ]
    )
    assert forbidden_brand not in visible_tool_text.lower()
    assert "patch 的 replace 模式" in toolkit.instructions
    assert "未暴露的日志回溯、关闭 stdin 和异步通知能力不可假定存在" in (toolkit.instructions)
    assert "read_tool_output" in PURE_CODING_TOOLKIT_INSTRUCTIONS
    assert "受控只读工具" in PURE_CODING_TOOLKIT_INSTRUCTIONS
    assert "create" in PURE_CODING_TOOLKIT_INSTRUCTIONS
    assert "overwrite" in PURE_CODING_TOOLKIT_INSTRUCTIONS
    assert "expected_sha256" in PURE_CODING_TOOLKIT_INSTRUCTIONS
    assert "必须调用 verify" in PURE_CODING_TOOLKIT_INSTRUCTIONS
    assert "terminal 不计为验证" in PURE_CODING_TOOLKIT_INSTRUCTIONS
    assert "terminal 默认从工作区根目录执行" in PURE_CODING_TOOLKIT_INSTRUCTIONS
    assert "每个相对路径都以该 workdir 为基准" in PURE_CODING_TOOLKIT_INSTRUCTIONS
    assert "用 terminal 得到成功验证回执" not in PURE_CODING_TOOLKIT_INSTRUCTIONS


def test_coding_tool_contract_explains_limits_patch_format_and_persistent_services(tmp_path):
    toolkit = CodingToolkit(service(tmp_path))
    tools = {**toolkit.functions, **toolkit.async_functions}
    exec_schema = tools["exec_command"].parameters["properties"]
    poll_schema = tools["poll_process"].parameters["properties"]
    patch_description = tools["apply_patch"].parameters["properties"]["patch"]["description"]

    assert exec_schema["yield_time_ms"]["maximum"] == 30000
    assert exec_schema["timeout_seconds"]["default"] == DEFAULT_EXEC_TIMEOUT_SECONDS
    assert exec_schema["timeout_seconds"]["maximum"] == 86400
    assert "0 至 30000" in exec_schema["yield_time_ms"]["description"]
    assert "0 至 30000" in poll_schema["yield_time_ms"]["description"]
    assert "--- /dev/null" in patch_description
    assert "@@ hunk" in patch_description
    assert "heredoc" in patch_description
    assert "标准 unified diff" in patch_description
    assert "独立 exec_command" in CODING_TOOLKIT_INSTRUCTIONS
    assert "按需或定时用 poll_process" in CODING_TOOLKIT_INSTRUCTIONS
    assert "write_stdin 只用于" in CODING_TOOLKIT_INSTRUCTIONS
    assert "stop_process 用于终止" in CODING_TOOLKIT_INSTRUCTIONS
    assert "全部工具直接执行，不会请求确认" in CODING_TOOLKIT_INSTRUCTIONS
    assert "不要在同一轮中紧密轮询" in CODING_TOOLKIT_INSTRUCTIONS
    assert "不要把 pip 输出管道到 tail" in CODING_TOOLKIT_INSTRUCTIONS
    assert "shell 后台符号 &" in CODING_TOOLKIT_INSTRUCTIONS
    assert "sed -i" in CODING_TOOLKIT_INSTRUCTIONS
    assert "不能改用标准库" in CODING_TOOLKIT_INSTRUCTIONS
    assert "确认缺失后才安装" in CODING_TOOLKIT_INSTRUCTIONS
    assert "不要无目的枚举完整环境" in CODING_TOOLKIT_INSTRUCTIONS
    assert "默认最多运行 900 秒" in CODING_TOOLKIT_INSTRUCTIONS
    assert "最长 86400 秒" in CODING_TOOLKIT_INSTRUCTIONS
    assert "明确 timeout" in CODING_TOOLKIT_INSTRUCTIONS
    assert "连续两次轮询" in CODING_TOOLKIT_INSTRUCTIONS
    assert "不得继续盲目轮询" in CODING_TOOLKIT_INSTRUCTIONS
    assert "0 至 30000" in CODING_TOOLKIT_INSTRUCTIONS
    assert "标准 unified diff" in CODING_TOOLKIT_INSTRUCTIONS
    assert "不是 OS PID" in tools["exec_command"].description
    assert "apply_patch 的兼容兜底" in tools["exec_command"].description
    assert "apply_patch <<'PATCH'" in exec_schema["cmd"]["description"]
    assert "不会在 Daytona 中查找或执行 apply_patch" in CODING_TOOLKIT_INSTRUCTIONS
    assert "不得附加其他 Shell 命令、workdir 或 PTY" in CODING_TOOLKIT_INSTRUCTIONS
    assert "不是 OS PID" in poll_schema["session_id"]["description"]
    forbidden_brand = "co" + "dex"
    visible_tool_text = "\n".join(
        [
            CODING_TOOLKIT_INSTRUCTIONS,
            *[tool.description or "" for tool in tools.values()],
            *[str(tool.parameters) for tool in tools.values()],
        ]
    )
    assert forbidden_brand not in visible_tool_text.lower()


@pytest.mark.anyio
async def test_coding_facade_only_forwards_acceptance_contract_from_dependency(tmp_path):
    synchronous = service(tmp_path)
    workspace_service = WorkspaceService(
        synchronous.secret,
        client=synchronous.client,
        registry=synchronous.registry,
        async_client=AsyncFakeClient(synchronous.client),
        async_registry=AsyncMemoryRegistry(synchronous.registry.values),
    )
    captured = []

    class Supervisor:
        async def start_task(
            self,
            scope,
            instruction,
            predecessor_task_id=None,
            *,
            acceptance_contract=None,
        ):
            captured.append((scope, instruction, predecessor_task_id, acceptance_contract))

        async def run_task(self, scope):
            yield CodingEvent(
                f"{scope.external_run_id}:final", "final_message", {"content": "完成"}
            )
            yield CodingEvent(
                f"{scope.external_run_id}:terminal",
                "terminal",
                {"state": "completed"},
            )

    facade = create_coding_facade_agent(
        app.coding_agent,
        Supervisor(),  # type: ignore[arg-type]
        workspace_service,
    )
    acceptance_contract = {
        "version": 1,
        "requirements": [
            {
                "id": "report",
                "validatorId": "analysis:report",
                "parameters": {},
                "artifactPatterns": ["reports/*.json"],
            }
        ],
    }
    run_context = RunContext(
        run_id="external",
        session_id="thread",
        user_id="user",
        session_state={},
        dependencies={
            "AgentOS 编码任务": {
                "externalRunId": "external",
                "acceptanceContract": acceptance_contract,
            }
        },
    )

    _events = [
        event
        async for event in facade.tools[0].entrypoint(
            instruction="实现目标",
            run_context=run_context,
        )
    ]

    assert facade.tools[0].parameters["properties"] == {
        "instruction": {"type": "string", "minLength": 1}
    }
    assert captured[0][1:] == ("实现目标", None, acceptance_contract)


@pytest.mark.anyio
async def test_hermes_terminal_maps_foreground_and_background_to_managed_commands(
    tmp_path, monkeypatch
):
    coding = CodingToolkit(service(tmp_path))
    toolkit = HermesCodingToolkit(coding)
    calls = []

    async def execute(command, **kwargs):
        calls.append((command, kwargs))
        return {"status": "completed", "output": "ok\n", "exit_code": 0}

    monkeypatch.setattr(coding, "exec_command", execute)

    foreground = await toolkit.terminal(
        "python3 check.py",
        timeout=120,
        workdir="scripts",
        pty=True,
        run_context=context(),
    )
    await toolkit.terminal(
        "python3 server.py",
        background=True,
        shell="/bin/bash",
        run_context=context(),
    )

    assert foreground["exit_code"] == 0
    assert calls[0][0] == "python3 check.py"
    assert calls[0][1]["timeout_seconds"] == 120
    assert calls[0][1]["workdir"] == "scripts"
    assert calls[0][1]["tty"] is True
    assert calls[0][1]["yield_time_ms"] == 30000
    assert calls[1][0] == "python3 server.py"
    assert calls[1][1]["timeout_seconds"] == DEFAULT_EXEC_TIMEOUT_SECONDS
    assert calls[1][1]["yield_time_ms"] == 0
    assert calls[1][1]["shell"] == "/bin/bash"


@pytest.mark.anyio
async def test_hermes_process_lists_accepts_string_handle_and_manages_input(tmp_path):
    current, coding = async_toolkit(tmp_path)
    toolkit = HermesCodingToolkit(coding)
    run_context = context()
    started = await toolkit.terminal(
        "python3 interactive.py",
        background=True,
        pty=True,
        run_context=run_context,
    )
    handle = started["session_id"]

    listed = await toolkit.process("list", run_context=run_context)
    written = await toolkit.process(
        "write",
        session_id=str(handle),
        data="answer",
        run_context=run_context,
    )
    submitted = await toolkit.process(
        "submit",
        session_id=handle,
        data="confirm",
        run_context=run_context,
    )
    killed = await toolkit.process("kill", session_id=str(handle), run_context=run_context)
    repeated = await toolkit.process("kill", session_id=handle, run_context=run_context)

    assert listed["processes"] == [
        {
            "session_id": str(handle),
            "status": "running",
            "started_at": pytest.approx(listed["processes"][0]["started_at"]),
            "timeout_seconds": DEFAULT_EXEC_TIMEOUT_SECONDS,
        }
    ]
    assert written["session_id"] == handle
    assert submitted["session_id"] == handle
    process = current.sandbox_for("thread").process
    assert process.input_calls[-2]["data"] == "answer"
    assert process.input_calls[-1]["data"] == "confirm\n"
    assert killed["status"] == repeated["status"] == "terminated"
    assert repeated["status_is_cached"] is True


@pytest.mark.anyio
async def test_hermes_process_wait_collects_incremental_output(tmp_path, monkeypatch):
    coding = CodingToolkit(service(tmp_path))
    toolkit = HermesCodingToolkit(coding)
    results = [
        {"status": "running", "output": "first\n", "session_id": 1},
        {"status": "completed", "output": "second\n", "exit_code": 0},
    ]

    async def poll_process(*_args, **_kwargs):
        return results.pop(0)

    monkeypatch.setattr(coding, "poll_process", poll_process)

    result = await toolkit.process("wait", session_id="1", timeout=1, run_context=context())

    assert result["status"] == "completed"
    assert result["output"] == "first\nsecond\n"
    assert results == []


def test_hermes_patch_supports_replace_and_native_patch_modes(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "notes.txt", b"one two one\n")
    toolkit = HermesCodingToolkit(CodingToolkit(current))
    run_context = context()

    replaced = toolkit.patch(
        "replace",
        path="notes.txt",
        old_string="one",
        new_string="three",
        replace_all=True,
        run_context=run_context,
    )
    patched = toolkit.patch(
        "patch",
        patch="""*** Begin Patch
*** Update File: notes.txt
@@
-three two three
+done
*** End Patch""",
        run_context=run_context,
    )

    assert replaced["replacements"] == 2
    assert patched["operations"] == 1
    assert current.read_text("thread", "notes.txt") == "done\n"


def test_hermes_patch_rejects_missing_or_mixed_mode_parameters(tmp_path):
    toolkit = HermesCodingToolkit(CodingToolkit(service(tmp_path)))
    run_context = context()

    with pytest.raises(WorkspaceError, match="replace 模式"):
        toolkit.patch("replace", path="notes.txt", run_context=run_context)
    with pytest.raises(WorkspaceError, match="patch 模式"):
        toolkit.patch(
            "patch",
            path="notes.txt",
            patch="*** Begin Patch\n*** End Patch",
            run_context=run_context,
        )


def test_hermes_replace_rechecks_sha_before_write(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "notes.txt", b"before\n")
    toolkit = HermesCodingToolkit(CodingToolkit(current))
    original_apply_patch = current.apply_patch

    def race(thread, path, old_text, new_text, expected_sha256, replace_all=False):
        current.replace_file(thread, path, b"concurrent\n")
        return original_apply_patch(
            thread,
            path,
            old_text,
            new_text,
            expected_sha256,
            replace_all,
        )

    monkeypatch.setattr(current, "apply_patch", race)

    with pytest.raises(WorkspacePathConflict, match="内容已变化"):
        toolkit.patch(
            "replace",
            path="notes.txt",
            old_string="before",
            new_string="after",
            run_context=context(),
        )
    assert current.read_text("thread", "notes.txt") == "concurrent\n"


def test_apply_patch_add_update_delete_move_and_multiple_files(tmp_path):
    current = service(tmp_path)
    toolkit = CodingToolkit(current)
    run_context = context()

    added = toolkit.apply_patch(
        """*** Begin Patch
*** Add File: scripts/report.py
+value = 1
+print(value)
*** Add File: notes.txt
+draft
*** End Patch""",
        run_context=run_context,
    )
    assert added["operations"] == 2
    assert current.read_text("thread", "scripts/report.py") == "value = 1\nprint(value)\n"

    updated = toolkit.apply_patch(
        """*** Begin Patch
*** Update File: scripts/report.py
@@
-value = 1
+value = 2
 print(value)
*** Update File: notes.txt
*** Move to: archive/notes.txt
*** End Patch""",
        run_context=run_context,
    )
    assert updated["operations"] == 2
    assert current.read_text("thread", "scripts/report.py") == "value = 2\nprint(value)\n"
    assert current.read_text("thread", "archive/notes.txt") == "draft\n"

    toolkit.apply_patch(
        """*** Begin Patch
*** Delete File: archive/notes.txt
*** End Patch""",
        run_context=run_context,
    )
    with pytest.raises(WorkspaceError, match="不存在"):
        current.read_text("thread", "archive/notes.txt")


def test_apply_patch_accepts_safe_model_formatting_fallbacks(tmp_path):
    current = service(tmp_path)

    result = CodingToolkit(current).apply_patch(
        """```patch
*** Begin Patch
*** Add File: notes.txt
+first

+last
*** End Patch
```""",
        run_context=context(),
    )

    assert result["operations"] == 1
    assert current.read_text("thread", "notes.txt") == "first\n\nlast\n"


def test_apply_patch_supports_codex_update_semantics_and_heredoc_fallback(tmp_path):
    current = service(tmp_path)
    current.create_file(
        "thread",
        "module.py",
        "def value():   \n    return 1\n\nmessage = “old”".encode(),
    )
    current.create_file("thread", "tail.txt", b"before\n")

    result = CodingToolkit(current).apply_patch(
        """<<'EOF'
*** Begin Patch
*** Update File: module.py
 def value():
-    return 1
+    return 2
@@
-message = "old"
+message = "new"
*** Update File: tail.txt
@@
-before
+after
*** End of File

*** End Patch
EOF""",
        run_context=context(),
    )

    assert result["operations"] == 2
    assert current.read_text("thread", "module.py") == (
        'def value():\n    return 2\n\nmessage = "new"\n'
    )
    assert current.read_text("thread", "tail.txt") == "after\n"


def test_apply_patch_move_with_update_is_atomic(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "before.py", b"value = 1\n")

    result = CodingToolkit(current).apply_patch(
        """*** Begin Patch
*** Update File: before.py
*** Move to: after.py
@@
-value = 1
+value = 2
*** End Patch""",
        run_context=context(),
    )

    assert result["operations"] == 2
    assert current.read_text("thread", "after.py") == "value = 2\n"
    with pytest.raises(WorkspaceError, match="不存在"):
        current.read_text("thread", "before.py")


def test_apply_patch_rejects_invalid_syntax_paths_symlinks_and_hunks(tmp_path):
    current = service(tmp_path)
    toolkit = CodingToolkit(current)
    run_context = context()
    current.create_file("thread", "notes.txt", b"before\n")

    with pytest.raises(WorkspaceError, match="首行"):
        parse_unified_diff("*** Add File: bad.txt\n+bad")
    with pytest.raises(WorkspaceError, match="末行"):
        parse_unified_diff("*** Begin Patch\n*** Add File: bad.txt\n+bad")
    with pytest.raises(WorkspaceError, match=r"每一行.*\+"):
        toolkit.apply_patch(
            "*** Begin Patch\n*** Add File: bad.txt\n+first\nmissing prefix\n*** End Patch",
            run_context=run_context,
        )
    with pytest.raises(WorkspaceError, match="首行"):
        parse_unified_diff("说明：\n*** Begin Patch\n*** Add File: bad.txt\n+bad\n*** End Patch")
    with pytest.raises(WorkspaceError, match="首行"):
        parse_unified_diff("--- /dev/null\n+++ b/bad.txt\n@@\n+bad")
    with pytest.raises(WorkspaceError, match="首行"):
        parse_unified_diff(
            "```patch\n*** Begin Patch\n*** Add File: bad.txt\n+bad\n*** End Patch\n```\n说明"
        )
    with pytest.raises(WorkspaceError, match="首行"):
        parse_unified_diff(
            "<<'EOF'\n*** Begin Patch\n*** Add File: bad.txt\n+bad\n*** End Patch\nNOT_EOF"
        )
    with pytest.raises(WorkspaceError, match="绝对路径"):
        toolkit.apply_patch(
            "*** Begin Patch\n*** Add File: /tmp/bad.txt\n+bad\n*** End Patch",
            run_context=run_context,
        )
    with pytest.raises(WorkspaceError, match="目录穿越"):
        toolkit.apply_patch(
            "*** Begin Patch\n*** Add File: ../bad.txt\n+bad\n*** End Patch",
            run_context=run_context,
        )
    with pytest.raises(WorkspaceError, match="未找到 hunk 原文"):
        toolkit.apply_patch(
            """*** Begin Patch
*** Update File: notes.txt
@@
-missing
+after
*** End Patch""",
            run_context=run_context,
        )

    sandbox = current.sandbox_for("thread")
    sandbox.fs.entries[f"{WORKSPACE_ROOT}/link.txt"] = (
        Info("link.txt", mode="lrwxrwxrwx"),
        b"target",
    )
    with pytest.raises(WorkspaceError, match="符号链接"):
        toolkit.apply_patch(
            """*** Begin Patch
*** Update File: link.txt
@@
-target
+changed
*** End Patch""",
            run_context=run_context,
        )


def test_apply_patch_rechecks_sha_and_keeps_multi_file_changes_atomic(tmp_path, monkeypatch):
    current = service(tmp_path)
    toolkit = CodingToolkit(current)
    current.create_file("thread", "notes.txt", b"before\n")
    original_apply = current.apply_changes

    def race(thread, changes):
        current.replace_file(thread, "notes.txt", b"concurrent\n")
        return original_apply(thread, changes)

    monkeypatch.setattr(current, "apply_changes", race)
    with pytest.raises(WorkspacePathConflict, match="内容已变化"):
        toolkit.apply_patch(
            """*** Begin Patch
*** Update File: notes.txt
@@
-before
+after
*** End Patch""",
            run_context=context(),
        )
    assert current.read_text("thread", "notes.txt") == "concurrent\n"

    monkeypatch.setattr(current, "apply_changes", original_apply)
    current.create_file("thread", "existing.txt", b"exists\n")
    with pytest.raises(WorkspacePathConflict, match="已经存在"):
        toolkit.apply_patch(
            """*** Begin Patch
*** Add File: new.txt
+new
*** Add File: existing.txt
+replace
*** End Patch""",
            run_context=context(),
        )
    with pytest.raises(WorkspaceError, match="不存在"):
        current.read_text("thread", "new.txt")


@pytest.mark.anyio
async def test_exec_command_intercepts_codex_apply_patch_without_remote_shell(
    tmp_path, monkeypatch
):
    current, toolkit = async_toolkit(tmp_path)
    current.create_file("thread", "existing.sh", b"echo before\n")

    async def unexpected_exec(*_args, **_kwargs):
        pytest.fail("apply_patch fallback reached the remote shell")

    monkeypatch.setattr(toolkit._workspace, "sandbox_exec", unexpected_exec)
    result = await toolkit.exec_command(
        """apply_patch <<'PATCH'
*** Begin Patch
*** Add File: added.sh
+echo "A & B"
+sed -i 's/a/b/' example.txt
*** Update File: existing.sh
@@
-echo before
+echo after
*** End Patch
PATCH""",
        yield_time_ms=0,
        run_context=context(),
    )

    assert result == {
        "status": "completed",
        "output": "补丁已应用。\n",
        "exit_code": 0,
        "outcome": "success",
        "wall_time_seconds": 0.0,
        "truncated": False,
        "timeout_seconds": DEFAULT_EXEC_TIMEOUT_SECONDS,
        "ok": True,
        "message": "补丁已应用。",
        "operations": 2,
        "files": result["files"],
        "intercepted_tool": "apply_patch",
    }
    assert [item["operation"] for item in result["files"]] == ["create", "update"]
    assert current.read_text("thread", "added.sh") == (
        "echo \"A & B\"\nsed -i 's/a/b/' example.txt\n"
    )
    assert current.read_text("thread", "existing.sh") == "echo after\n"


@pytest.mark.anyio
async def test_exec_command_intercepts_single_quoted_apply_patch_argument(tmp_path, monkeypatch):
    current, toolkit = async_toolkit(tmp_path)

    async def unexpected_exec(*_args, **_kwargs):
        pytest.fail("quoted apply_patch fallback reached the remote shell")

    monkeypatch.setattr(toolkit._workspace, "sandbox_exec", unexpected_exec)
    result = await toolkit.exec_command(
        """apply_patch '*** Begin Patch
*** Add File: quoted.txt
+quoted fallback
*** End Patch'""",
        yield_time_ms=0,
        run_context=context(),
    )

    assert result["status"] == "completed"
    assert result["outcome"] == "success"
    assert result["intercepted_tool"] == "apply_patch"
    assert current.read_text("thread", "quoted.txt") == "quoted fallback\n"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "command",
    [
        """apply_patch <<'PATCH'
*** Begin Patch
*** Add File: rejected.txt
+missing delimiter
*** End Patch""",
        """apply_patch <<'PATCH'
*** Begin Patch
*** Add File: rejected.txt
+trailing command
*** End Patch
PATCH
printf unsafe""",
        """apply_patch <<'PATCH' && printf unsafe
*** Begin Patch
*** Add File: rejected.txt
+chained opener
*** End Patch
PATCH""",
        """apply_patch '*** Begin Patch
*** Add File: rejected.txt
+quoted chain
*** End Patch' && printf unsafe""",
        """apply_patch
'*** Begin Patch
*** Add File: rejected.txt
+separate command
*** End Patch'""",
    ],
)
async def test_exec_command_rejects_malformed_or_chained_apply_patch_without_writes(
    tmp_path, monkeypatch, command
):
    current, toolkit = async_toolkit(tmp_path)

    async def unexpected_exec(*_args, **_kwargs):
        pytest.fail("malformed apply_patch reached the remote shell")

    monkeypatch.setattr(toolkit._workspace, "sandbox_exec", unexpected_exec)
    with pytest.raises(WorkspaceError, match="apply_patch"):
        await toolkit.exec_command(command, yield_time_ms=0, run_context=context())

    with pytest.raises(WorkspaceError, match="不存在"):
        current.read_text("thread", "rejected.txt")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"workdir": "src"}, "workdir"),
        ({"tty": True}, "PTY"),
    ],
)
async def test_exec_command_apply_patch_fallback_rejects_ignored_execution_options(
    tmp_path, options, message
):
    current, toolkit = async_toolkit(tmp_path)
    command = """apply_patch <<'PATCH'
*** Begin Patch
*** Add File: rejected.txt
+content
*** End Patch
PATCH"""

    with pytest.raises(WorkspaceError, match=message):
        await toolkit.exec_command(
            command,
            yield_time_ms=0,
            run_context=context(),
            **options,
        )

    with pytest.raises(WorkspaceError, match="不存在"):
        current.read_text("thread", "rejected.txt")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"login": 1}, "登录模式"),
        ({"shell": "/bin/zsh"}, "shell"),
        ({"tty": 1}, "伪终端标志"),
        ({"timeout_seconds": True}, "执行超时"),
        ({"yield_time_ms": True}, "命令等待时间"),
        ({"max_output_tokens": True}, "输出 token"),
    ],
)
async def test_exec_command_apply_patch_fallback_keeps_runtime_validation(
    tmp_path, options, message
):
    current, toolkit = async_toolkit(tmp_path)
    command = """apply_patch <<'PATCH'
*** Begin Patch
*** Add File: rejected.txt
+content
*** End Patch
PATCH"""

    with pytest.raises(WorkspaceError, match=message):
        await toolkit.exec_command(command, run_context=context(), **options)

    with pytest.raises(WorkspaceError, match="不存在"):
        current.read_text("thread", "rejected.txt")


@pytest.mark.anyio
async def test_exec_command_completes_in_foreground_and_uses_requested_shell(tmp_path):
    current, toolkit = async_toolkit(tmp_path)
    current.sandbox_for("thread")
    process = current.sandbox_for("thread").process
    original_execute = process.execute_session_command
    commands = []

    def complete(session_id, request, timeout=None):
        commands.append(request.command)
        result = original_execute(session_id, request, timeout=timeout)
        command = process.get_session_command(session_id, result.cmd_id)
        command.exit_code = 0
        command.output = "done\n"
        result.exit_code = 0
        return result

    process.execute_session_command = complete
    result = await toolkit.exec_command(
        "printf done",
        workdir="scripts",
        shell="/bin/bash",
        login=False,
        yield_time_ms=0,
        run_context=context(),
    )

    assert result["status"] == "completed"
    assert result["output"] == "done\n"
    assert result["exit_code"] == 0
    assert "session_id" not in result
    assert "exec /bin/bash" in commands[0]
    assert "/home/daytona/workspace/scripts" in commands[0]


@pytest.mark.anyio
async def test_exec_command_uses_explicit_long_timeout_and_matching_handle_expiry(tmp_path):
    current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    started_before = time.time()

    result = await toolkit.exec_command(
        "python3 long_build.py",
        timeout_seconds=3600,
        yield_time_ms=0,
        run_context=run_context,
    )

    assert result["status"] == "running"
    assert result["timeout_seconds"] == 3600
    entry = run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY][str(result["session_id"])]
    assert entry["timeout_seconds"] == 3600
    assert entry["expires_at"] >= started_before + 3900
    remote = current.sandbox_for("thread").process.get_session_command(
        entry["session_id"], entry["command_id"]
    )
    assert "timeout --signal=TERM --kill-after=5s 3600s" in remote.command

    with pytest.raises(WorkspaceError, match="后台命令.*86400"):
        await toolkit.exec_command(
            "too-long",
            timeout_seconds=86401,
            yield_time_ms=0,
            run_context=run_context,
        )


def test_process_result_distinguishes_timeout_from_failure(tmp_path):
    toolkit = CodingToolkit(service(tmp_path))

    ordinary_failure = toolkit._format_process_result(
        {"status": "completed", "output": "partial\n", "exitCode": 124},
        max_output_tokens=100,
    )
    timed_out = toolkit._format_process_result(
        {
            "status": "completed",
            "output": "partial\n",
            "exitCode": 124,
            "timedOut": True,
        },
        max_output_tokens=100,
    )

    assert ordinary_failure["outcome"] == "failed"
    assert timed_out["outcome"] == "timed_out"
    assert "timeout_seconds" in timed_out["guidance"]


@pytest.mark.anyio
async def test_exec_command_rejects_feedback_loss_and_unmanaged_shell_patterns(tmp_path):
    _current, toolkit = async_toolkit(tmp_path)
    run_context = context()

    blocked = [
        ("pip3 install fastapi 2>&1 | tail -50", "pip 输出"),
        ("python3 -m pip install fastapi | grep error", "pip 输出"),
        ("nohup python3 server.py", "nohup"),
        ("python3 server.py > /tmp/server.log 2>&1 &", "后台符号"),
        ("sed -i 's/a/b/' app.py", "apply_patch"),
        ("perl -pi -e 's/a/b/' app.py", "apply_patch"),
        ("source .venv/bin/activate", "source"),
    ]
    for command, message in blocked:
        with pytest.raises(WorkspaceError, match=message):
            await toolkit.exec_command(command, yield_time_ms=0, run_context=run_context)

    result = await toolkit.exec_command(
        "source .venv/bin/activate",
        shell="/bin/bash",
        yield_time_ms=0,
        run_context=run_context,
    )
    assert result["status"] in {"running", "completed"}


@pytest.mark.parametrize(
    ("command", "shell"),
    [
        (
            """cat <<'EOF'
A & B
nohup python3 server.py
sed -i 's/a/b/' app.py
pip install example | tail -1
EOF""",
            "/bin/sh",
        ),
        ("echo ok 2>&1", "/bin/sh"),
        ("echo ok # A & B", "/bin/sh"),
        ("echo ok &>status.log", "/bin/bash"),
        ("false |& cat", "/bin/bash"),
        ("echo $((1 & 2))", "/bin/bash"),
    ],
)
def test_command_policy_ignores_non_background_ampersands(command, shell):
    CodingToolkit._validate_command_policy(command, shell)


def test_command_policy_still_checks_heredoc_opening_command():
    command = "pip install example <<'EOF' | tail -1\ndata\nEOF"

    with pytest.raises(WorkspaceError, match="pip 输出"):
        CodingToolkit._validate_command_policy(command, "/bin/sh")


@pytest.mark.parametrize(
    "command",
    [
        "sleep 1 &",
        "sleep 1 & echo done",
        "(sleep 1 &)",
        "if true; then sleep 1 & fi",
        'echo "$(sleep 1 & echo done)"',
    ],
)
def test_command_policy_rejects_nested_shell_background_operators(command):
    with pytest.raises(WorkspaceError, match="后台符号"):
        CodingToolkit._validate_command_policy(command, "/bin/bash")


def test_command_policy_rejects_unclosed_heredoc():
    with pytest.raises(WorkspaceError, match="Shell 命令语法"):
        CodingToolkit._validate_command_policy("cat <<'EOF'\nunclosed", "/bin/sh")


@pytest.mark.anyio
async def test_python_script_can_be_created_executed_fixed_and_rerun(tmp_path):
    current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    toolkit.apply_patch(
        """*** Begin Patch
*** Add File: analyze.py
+raise RuntimeError("broken")
*** End Patch""",
        run_context=run_context,
    )
    process = current.sandbox_for("thread").process
    original_execute = process.execute_session_command

    def execute_script(session_id, request, timeout=None):
        result = original_execute(session_id, request, timeout=timeout)
        command = process.get_session_command(session_id, result.cmd_id)
        if "RuntimeError" in current.read_text("thread", "analyze.py"):
            command.exit_code = 1
            command.output = "RuntimeError: broken\n"
        else:
            command.exit_code = 0
            command.output = "analysis-ok\n"
        result.exit_code = command.exit_code
        return result

    process.execute_session_command = execute_script
    failed = await toolkit.exec_command(
        "python3 analyze.py",
        yield_time_ms=0,
        run_context=run_context,
    )
    assert failed["exit_code"] == 1
    assert failed["outcome"] == "failed"
    assert "exit_code 非零" in failed["guidance"]
    assert "RuntimeError" in failed["output"]

    toolkit.apply_patch(
        """*** Begin Patch
*** Update File: analyze.py
@@
-raise RuntimeError("broken")
+print("analysis-ok")
*** End Patch""",
        run_context=run_context,
    )
    succeeded = await toolkit.exec_command(
        "python3 analyze.py",
        yield_time_ms=0,
        run_context=run_context,
    )
    assert succeeded["exit_code"] == 0
    assert succeeded["outcome"] == "success"
    assert succeeded["output"] == "analysis-ok\n"


@pytest.mark.anyio
async def test_exec_command_integer_handle_poll_input_interrupt_and_completion(tmp_path):
    current, toolkit = async_toolkit(tmp_path)
    run_context = context()

    started = await toolkit.exec_command(
        "python3 interactive.py",
        tty=True,
        yield_time_ms=0,
        run_context=run_context,
    )
    assert started["status"] == "running"
    assert started["outcome"] == "running"
    assert started["session_id"] == 1
    assert isinstance(started["session_id"], int)

    session = run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY]["1"]
    process = current.sandbox_for("thread").process
    command = process.get_session_command(session["session_id"], session["command_id"])
    command.output = "startedready\n"

    polled = await toolkit.poll_process(1, yield_time_ms=0, run_context=run_context)
    assert polled["output"] == "ready\n"
    assert polled["session_id"] == 1

    written = await toolkit.write_stdin(
        1,
        "continue\n",
        yield_time_ms=0,
        run_context=run_context,
    )
    assert written["session_id"] == 1
    assert process.input_calls[-1]["data"] == "continue\n"

    interrupted = await toolkit.write_stdin(1, "\x03", yield_time_ms=0, run_context=run_context)
    assert interrupted["session_id"] == 1
    assert process.input_calls[-1]["data"] == "\x03"

    legacy_poll = await toolkit.write_stdin(1, "", yield_time_ms=0, run_context=run_context)
    assert legacy_poll["session_id"] == 1

    command.output += "done\n"
    command.exit_code = 130
    completed = await toolkit.poll_process(1, yield_time_ms=0, run_context=run_context)
    assert completed["status"] == "completed"
    assert completed["exit_code"] == 130
    assert completed["outcome"] == "failed"
    assert "exit_code 非零" in completed["guidance"]
    assert completed["output"] == "done\n"
    assert "session_id" not in completed
    assert run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY] == {}
    with pytest.raises(WorkspaceError, match="已经完成"):
        await toolkit.poll_process(1, yield_time_ms=0, run_context=run_context)


@pytest.mark.anyio
async def test_stop_process_terminates_default_non_pty_command_and_closes_handle(tmp_path):
    current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    started = await toolkit.exec_command(
        "python3 server.py",
        tty=False,
        yield_time_ms=0,
        run_context=run_context,
    )
    entry = run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY]["1"]
    process = current.sandbox_for("thread").process

    result = await toolkit.stop_process(started["session_id"], run_context=run_context)

    assert result == {"status": "terminated", "outcome": "terminated", "session_id": 1}
    assert entry["session_id"] in process.deleted_sessions
    assert run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY] == {}
    assert run_context.session_state[CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY]["1"]["reason"] == (
        "terminated"
    )
    repeated = await toolkit.stop_process(1, run_context=run_context)
    assert repeated == {
        "status": "terminated",
        "outcome": "terminated",
        "session_id": 1,
        "status_is_cached": True,
    }
    assert process.deleted_sessions.count(entry["session_id"]) == 1


@pytest.mark.anyio
async def test_timeout_marker_distinguishes_managed_timeout_from_exit_124(tmp_path):
    current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    await toolkit.exec_command("long-running", yield_time_ms=0, run_context=run_context)
    entry = run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY]["1"]
    process = current.sandbox_for("thread").process
    command = process.get_session_command(entry["session_id"], entry["command_id"])
    marker = toolkit._workspace._managed_timeout_marker(command)
    assert marker is not None
    command.output += "partial\n" + toolkit._workspace._timeout_output_marker(marker)
    command.exit_code = 124

    result = await toolkit.poll_process(1, yield_time_ms=0, run_context=run_context)

    assert result["output"] == "partial\n"
    assert result["exit_code"] == 124
    assert result["outcome"] == "timed_out"


@pytest.mark.anyio
async def test_managed_timeout_wrapper_marks_only_actual_timeouts(tmp_path):
    current, toolkit = async_toolkit(tmp_path)
    run_context = context()

    async def wrapper_for(command_text):
        started = await toolkit.exec_command(
            command_text,
            timeout_seconds=1,
            yield_time_ms=0,
            run_context=run_context,
        )
        entry = run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY][str(started["session_id"])]
        command = current.sandbox_for("thread").process.get_session_command(
            entry["session_id"], entry["command_id"]
        )
        marker = toolkit._workspace._managed_timeout_marker(command)
        assert marker is not None
        return shlex.split(command.command)[-1], toolkit._workspace._timeout_output_marker(marker)

    exit_wrapper, exit_marker = await wrapper_for("exit 124")
    timeout_wrapper, timeout_marker = await wrapper_for("sleep 2")

    exited = subprocess.run(
        ["/bin/sh", "-lc", exit_wrapper],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    timed_out = subprocess.run(
        ["/bin/sh", "-lc", timeout_wrapper],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert exited.returncode == 124
    assert exit_marker not in exited.stderr
    assert timed_out.returncode == 124
    assert timeout_marker in timed_out.stderr


@pytest.mark.anyio
async def test_exec_command_truncation_keeps_unread_running_output(tmp_path):
    current, toolkit = async_toolkit(tmp_path)
    current.sandbox_for("thread")
    process = current.sandbox_for("thread").process
    original_execute = process.execute_session_command

    def verbose(session_id, request, timeout=None):
        result = original_execute(session_id, request, timeout=timeout)
        command = process.get_session_command(session_id, result.cmd_id)
        command.output = "abcdefghij"
        result.output = command.output
        return result

    process.execute_session_command = verbose
    run_context = context()
    started = await toolkit.exec_command(
        "long-running",
        yield_time_ms=0,
        max_output_tokens=1,
        run_context=run_context,
    )
    assert started["output"] == "abcd"
    assert started["truncated"] is True

    polled = await toolkit.poll_process(
        started["session_id"],
        yield_time_ms=0,
        max_output_tokens=2,
        run_context=run_context,
    )
    assert polled["output"] == "efghij"


@pytest.mark.anyio
async def test_poll_process_serializes_the_same_handle(tmp_path, monkeypatch):
    _current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    started = await toolkit.exec_command("long-running", yield_time_ms=0, run_context=run_context)
    observed_offsets = []
    active = 0
    maximum_active = 0

    async def poll(_entry, *, offset, **_kwargs):
        nonlocal active, maximum_active
        observed_offsets.append(offset)
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1
        return {
            "status": "running",
            "output": "x",
            "exitCode": None,
            "offset": offset,
            "nextOffset": offset + 1,
            "totalBytes": offset + 1,
            "hasMore": False,
            "truncated": False,
        }

    monkeypatch.setattr(toolkit, "_poll_process", poll)
    first, second = await asyncio.gather(
        toolkit.poll_process(started["session_id"], yield_time_ms=0, run_context=run_context),
        toolkit.poll_process(started["session_id"], yield_time_ms=0, run_context=run_context),
    )

    assert maximum_active == 1
    assert observed_offsets == [7, 8]
    assert first["output"] == second["output"] == "x"


@pytest.mark.parametrize(
    ("result", "message"),
    [
        ({"output": "x", "nextOffset": "1"}, "输出偏移"),
        ({"output": "x", "nextOffset": True}, "输出偏移"),
        ({"output": "x", "nextOffset": -1}, "输出偏移"),
        ({"output": "x", "nextOffset": 2}, "输出偏移"),
        ({"output": "x", "nextOffset": 1, "totalBytes": 0}, "总字节数"),
    ],
)
def test_next_offset_rejects_invalid_metadata(tmp_path, result, message):
    toolkit = CodingToolkit(service(tmp_path))

    with pytest.raises(WorkspaceError, match=message):
        toolkit._next_offset(result, 0)


@pytest.mark.anyio
async def test_poll_process_removes_missing_handle_and_keeps_invalid_offset_retryable(
    tmp_path, monkeypatch
):
    _current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    started = await toolkit.exec_command("long-running", yield_time_ms=0, run_context=run_context)

    async def invalid_offset(_entry, *, offset, **_kwargs):
        return {
            "status": "running",
            "output": "x",
            "offset": offset,
            "nextOffset": "bad",
            "totalBytes": offset + 1,
            "hasMore": False,
        }

    monkeypatch.setattr(toolkit, "_poll_process", invalid_offset)
    with pytest.raises(WorkspaceError, match="输出偏移"):
        await toolkit.poll_process(started["session_id"], run_context=run_context)
    assert str(started["session_id"]) in run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY]

    async def missing(_entry, **_kwargs):
        raise WorkspaceProcessNotFound("missing")

    monkeypatch.setattr(toolkit, "_poll_process", missing)
    with pytest.raises(WorkspaceError, match="已经结束或丢失"):
        await toolkit.poll_process(started["session_id"], run_context=run_context)
    assert run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY] == {}
    with pytest.raises(WorkspaceError, match="已经结束或丢失"):
        await toolkit.poll_process(started["session_id"], run_context=run_context)


@pytest.mark.anyio
async def test_running_process_result_guides_persistent_service_health_check(tmp_path):
    _current, toolkit = async_toolkit(tmp_path)
    run_context = context()

    started = await toolkit.exec_command("long-running", yield_time_ms=0, run_context=run_context)

    assert started["status"] == "running"
    assert started["session_id"] == 1
    assert "独立 exec_command" in started["guidance"]
    assert "按需或定时使用 poll_process" in started["guidance"]
    assert "不要在同一轮中紧密轮询" in started["guidance"]
    assert "连续两次轮询没有新输出" in started["guidance"]


@pytest.mark.anyio
async def test_poll_process_refreshes_after_consecutive_empty_results(tmp_path, monkeypatch):
    _current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    started = await toolkit.exec_command("long-running", yield_time_ms=0, run_context=run_context)
    poll_calls = 0

    async def empty_poll(_entry, *, offset, **_kwargs):
        nonlocal poll_calls
        poll_calls += 1
        return {
            "status": "completed" if poll_calls == 3 else "running",
            "output": "",
            "exitCode": 0 if poll_calls == 3 else None,
            "offset": offset,
            "nextOffset": offset,
            "totalBytes": offset,
            "hasMore": False,
            "truncated": False,
        }

    monkeypatch.setattr(toolkit, "_poll_process", empty_poll)

    first = await toolkit.poll_process(
        started["session_id"], yield_time_ms=0, run_context=run_context
    )
    second = await toolkit.poll_process(
        started["session_id"], yield_time_ms=0, run_context=run_context
    )
    completed = await toolkit.poll_process(
        started["session_id"], yield_time_ms=0, run_context=run_context
    )

    assert first["status"] == second["status"] == "running"
    assert first["session_id"] == second["session_id"] == started["session_id"]
    assert completed["status"] == "completed"
    assert completed["outcome"] == "success"
    assert "session_id" not in completed
    assert poll_calls == 3


@pytest.mark.anyio
@pytest.mark.parametrize("yield_time_ms", [True, -1, 30001, 1.5])
async def test_poll_process_rejects_invalid_yield_time_before_remote_call(
    tmp_path, monkeypatch, yield_time_ms
):
    _current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    started = await toolkit.exec_command("long-running", yield_time_ms=0, run_context=run_context)

    async def unexpected_poll(*_args, **_kwargs):
        pytest.fail("invalid yield_time_ms reached the remote poll")

    monkeypatch.setattr(toolkit, "_poll_process", unexpected_poll)

    with pytest.raises(WorkspaceError, match="命令等待时间"):
        await toolkit.poll_process(
            started["session_id"],
            yield_time_ms=yield_time_ms,
            run_context=run_context,
        )


@pytest.mark.anyio
async def test_exec_command_prunes_stale_handles_before_capacity_check(tmp_path):
    _current, toolkit = async_toolkit(tmp_path)
    expired = time.time() - CODEX_EXEC_SESSION_TTL_SECONDS - 1
    state = {
        CODEX_EXEC_SESSIONS_STATE_KEY: {
            str(index): {
                "thread": "thread",
                "user_id": "user",
                "session_id": f"agent-exec-{'0' * 31}{index % 10}",
                "command_id": "command-1",
                "offset": 0,
                "started_at": expired,
                **({"expires_at": "invalid"} if index == 1 else {}),
            }
            for index in range(1, MAX_CODEX_SESSION_HANDLES + 1)
        }
    }
    run_context = context(state=state)

    started = await toolkit.exec_command("long-running", yield_time_ms=0, run_context=run_context)

    assert started["session_id"] == 1
    assert list(state[CODEX_EXEC_SESSIONS_STATE_KEY]) == ["1"]
    assert state[CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY]["2"]["reason"] == "expired"
    with pytest.raises(WorkspaceError, match="已过期"):
        await toolkit.poll_process(2, run_context=run_context)


@pytest.mark.anyio
async def test_exec_command_stops_remote_session_before_pruning_expired_handle(tmp_path):
    current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    started = await toolkit.exec_command("first", yield_time_ms=0, run_context=run_context)
    entry = run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY]["1"]
    remote_session_id = entry["session_id"]
    entry["expires_at"] = time.time() - 1
    process = current.sandbox_for("thread").process

    replacement = await toolkit.exec_command("second", yield_time_ms=0, run_context=run_context)

    assert replacement["session_id"] == 2
    assert remote_session_id in process.deleted_sessions
    assert remote_session_id not in process.sessions
    assert (
        str(started["session_id"]) not in run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY]
    )
    assert run_context.session_state[CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY]["1"]["reason"] == (
        "expired"
    )


@pytest.mark.anyio
async def test_expired_remote_cleanup_failure_preserves_handle_for_retry(tmp_path, monkeypatch):
    _current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    await toolkit.exec_command("first", yield_time_ms=0, run_context=run_context)
    entry = run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY]["1"]
    entry["expires_at"] = time.time() - 1

    async def fail_cleanup(*_args, **_kwargs):
        raise RuntimeError("daytona unavailable")

    monkeypatch.setattr(toolkit._workspace, "sandbox_process_stop", fail_cleanup)

    with pytest.raises(WorkspaceError, match="清理过期进程失败"):
        await toolkit.exec_command("second", yield_time_ms=0, run_context=run_context)
    assert "1" in run_context.session_state[CODEX_EXEC_SESSIONS_STATE_KEY]


@pytest.mark.anyio
async def test_exec_command_reserves_last_handle_before_starting_remote_process(
    tmp_path, monkeypatch
):
    _current, toolkit = async_toolkit(tmp_path)
    started_at = time.time()
    state = {
        CODEX_EXEC_SESSIONS_STATE_KEY: {
            str(index): {
                "thread": "thread",
                "user_id": "user",
                "session_id": f"agent-exec-{'0' * 31}{index % 10}",
                "command_id": "command-1",
                "offset": 0,
                "started_at": started_at,
            }
            for index in range(1, MAX_CODEX_SESSION_HANDLES)
        }
    }
    run_context = context(state=state)
    remote_started = asyncio.Event()
    release_remote = asyncio.Event()
    calls = 0

    async def delayed_exec(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        remote_started.set()
        await release_remote.wait()
        return {
            "status": "running",
            "output": "",
            "exitCode": None,
            "sessionId": "agent-exec-0123456789abcdef0123456789abcdef",
            "commandId": "command-1",
            "offset": 0,
            "nextOffset": 0,
            "totalBytes": 0,
            "hasMore": False,
        }

    monkeypatch.setattr(toolkit._workspace, "sandbox_exec", delayed_exec)
    first = asyncio.create_task(
        toolkit.exec_command("first", yield_time_ms=0, run_context=run_context)
    )
    await remote_started.wait()

    with pytest.raises(WorkspaceError, match="句柄过多"):
        await toolkit.exec_command("second", yield_time_ms=0, run_context=run_context)
    assert calls == 1

    release_remote.set()
    result = await first
    assert result["session_id"] == MAX_CODEX_SESSION_HANDLES


@pytest.mark.anyio
async def test_poll_process_rejects_invalid_cross_thread_and_cross_user_handles(tmp_path):
    _current, toolkit = async_toolkit(tmp_path)
    state = {}
    owner = context(thread="thread-a", user_id="user-a", state=state)
    started = await toolkit.exec_command("sleep 1", yield_time_ms=0, run_context=owner)

    with pytest.raises(WorkspaceError, match="正整数"):
        await toolkit.poll_process(True, run_context=owner)
    with pytest.raises(WorkspaceError, match="不存在或已经结束"):
        await toolkit.poll_process(999, run_context=owner)
    with pytest.raises(WorkspaceError, match="不属于"):
        await toolkit.poll_process(
            started["session_id"],
            run_context=context(thread="thread-b", user_id="user-a", state=state),
        )
    with pytest.raises(WorkspaceError, match="不属于"):
        await toolkit.poll_process(
            started["session_id"],
            run_context=context(thread="thread-a", user_id="user-b", state=state),
        )


def test_view_image_and_update_plan_keep_workspace_and_plan_boundaries(tmp_path):
    current = service(tmp_path)
    toolkit = CodingToolkit(current)
    run_context = context()
    current.create_file(
        "thread",
        "chart.png",
        b"\x89PNG\r\n\x1a\n" + b"content",
    )

    image = toolkit.view_image("chart.png", "original", run_context=run_context)
    assert image.images
    with pytest.raises(WorkspaceError, match="detail"):
        toolkit.view_image("chart.png", "low", run_context=run_context)

    result = toolkit.update_plan(
        [
            {"step": "创建脚本", "status": "completed"},
            {"step": "运行验证", "status": "in_progress"},
        ],
        "开始验证",
        run_context=run_context,
    )
    assert result["ok"] is True
    with pytest.raises(ValueError, match="最多只能有一个"):
        toolkit.update_plan(
            [
                {"step": "A", "status": "in_progress"},
                {"step": "B", "status": "in_progress"},
            ],
            run_context=run_context,
        )


def test_coding_state_keys_are_removed_from_client_state():
    assert CODEX_EXEC_SESSIONS_STATE_KEY in app.SERVER_SESSION_STATE_KEYS
    assert CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY in app.SERVER_SESSION_STATE_KEYS
    assert "agentos_codex_exec_next_session" in app.SERVER_SESSION_STATE_KEYS
