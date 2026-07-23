import asyncio
import shlex
import subprocess
import time

import pytest
from agno.models.response import ToolExecution
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.requirement import RunRequirement
from agno.session.agent import AgentSession

from agentos_dev import app
from agentos_dev.agents import create_coding_agent, create_report_agent
from agentos_dev.coding_tools import (
    CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY,
    CODEX_EXEC_SESSION_TTL_SECONDS,
    CODEX_EXEC_SESSIONS_STATE_KEY,
    CODING_TOOLKIT_INSTRUCTIONS,
    DEFAULT_EXEC_TIMEOUT_SECONDS,
    EMPTY_POLL_COOLDOWN_SECONDS,
    MAX_CODEX_SESSION_HANDLES,
    CodingToolkit,
    parse_codex_patch,
)
from agentos_dev.instructions import build_coding_agent_instructions
from agentos_dev.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncMemoryRegistry,
    Info,
    service,
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
    assert all(tool.requires_confirmation is False for tool in tools.values())


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
    assert "*** Add File: path" in patch_description
    assert "禁止 ---/+++" in patch_description
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
    assert "禁止使用 ---/+++" in CODING_TOOLKIT_INSTRUCTIONS
    assert "不是 OS PID" in tools["exec_command"].description
    assert "不是 OS PID" in poll_schema["session_id"]["description"]


def test_report_agent_extends_unregistered_coding_agent(tmp_path):
    workspace_service = service(tmp_path)
    coding_agent = create_coding_agent(app.assistant, workspace_service)
    report_agent = create_report_agent(
        coding_agent,
        workspace_service,
        instructions=["测试报表"],
    )

    assert coding_agent.id == "coding-agent"
    assert coding_agent.instructions is build_coding_agent_instructions
    assert [skill.name for skill in coding_agent.skills.get_all_skills()] == ["sandbox-tooling"]
    assert coding_agent not in app.assistant_team.members(
        RunContext(run_id="run", session_id="thread", session_state={})
    )
    assert report_agent.model is coding_agent.model
    assert report_agent.db is coding_agent.db
    assert report_agent.compression_manager is coding_agent.compression_manager
    assert report_agent.checkpoint == coding_agent.checkpoint == "tool-batch"
    assert report_agent.session_summary_manager is coding_agent.session_summary_manager
    assert [skill.name for skill in report_agent.skills.get_all_skills()] == ["sandbox-tooling"]
    assert [tool.name for tool in report_agent.tools(run_context=context())] == [
        "coding",
        "report_data_sources",
        "workspace_report",
    ]


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
        parse_codex_patch("*** Add File: bad.txt\n+bad")
    with pytest.raises(WorkspaceError, match="末行"):
        parse_codex_patch("*** Begin Patch\n*** Add File: bad.txt\n+bad")
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
    with pytest.raises(WorkspaceError, match="已经终止"):
        await toolkit.stop_process(1, run_context=run_context)


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
async def test_poll_process_pauses_tight_polling_after_two_empty_results(tmp_path, monkeypatch):
    _current, toolkit = async_toolkit(tmp_path)
    run_context = context()
    started = await toolkit.exec_command("long-running", yield_time_ms=0, run_context=run_context)
    poll_calls = 0
    current_time = 1000.0

    async def empty_poll(_entry, *, offset, **_kwargs):
        nonlocal poll_calls
        poll_calls += 1
        return {
            "status": "running",
            "output": "",
            "exitCode": None,
            "offset": offset,
            "nextOffset": offset,
            "totalBytes": offset,
            "hasMore": False,
            "truncated": False,
        }

    monkeypatch.setattr(toolkit, "_poll_process", empty_poll)
    monkeypatch.setattr("agentos_dev.coding_tools.time.time", lambda: current_time)

    first = await toolkit.poll_process(
        started["session_id"], yield_time_ms=0, run_context=run_context
    )
    second = await toolkit.poll_process(
        started["session_id"], yield_time_ms=0, run_context=run_context
    )
    paused = await toolkit.poll_process(
        started["session_id"], yield_time_ms=0, run_context=run_context
    )

    assert first["empty_poll_count"] == 1
    assert "polling_paused" not in first
    assert second["empty_poll_count"] == 2
    assert second["polling_paused"] is True
    assert second["retry_after_seconds"] == EMPTY_POLL_COOLDOWN_SECONDS
    assert paused["polling_paused"] is True
    assert paused["status_is_cached"] is True
    assert paused["session_id"] == started["session_id"]
    assert "本次没有访问远端" in paused["guidance"]
    assert poll_calls == 2

    current_time += EMPTY_POLL_COOLDOWN_SECONDS
    resumed = await toolkit.poll_process(
        started["session_id"], yield_time_ms=0, run_context=run_context
    )

    assert resumed["empty_poll_count"] == 1
    assert "polling_paused" not in resumed
    assert poll_calls == 3


@pytest.mark.anyio
async def test_exec_command_prunes_stale_handles_before_capacity_check(tmp_path):
    _current, toolkit = async_toolkit(tmp_path)
    expired = time.time() - CODEX_EXEC_SESSION_TTL_SECONDS - 1
    state = {
        CODEX_EXEC_SESSIONS_STATE_KEY: {
            str(index): {
                "thread": "thread",
                "user_id": "user",
                "session_id": f"agui-exec-{'0' * 31}{index % 10}",
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
                "session_id": f"agui-exec-{'0' * 31}{index % 10}",
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
            "sessionId": "agui-exec-0123456789abcdef0123456789abcdef",
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


def test_pending_legacy_report_tools_require_explicit_migration():
    pending = ToolExecution(
        tool_name="workspace_write_file",
        requires_confirmation=True,
    )
    running = ToolExecution(
        tool_name="sandbox_exec",
        result=('{"status":"running","sessionId":"agui-exec-old","commandId":"command-1"}'),
    )
    completed = ToolExecution(
        tool_name="sandbox_exec",
        result='{"status":"completed","exitCode":0}',
    )
    removed = ToolExecution(tool_name="report_analyze_dataset")
    new_tool = ToolExecution(tool_name="apply_patch", requires_confirmation=True)

    def session_with(*, requirements=None, tools=None):
        return AgentSession(
            session_id="thread",
            agent_id="report-agent",
            runs=[
                RunOutput(
                    run_id="run",
                    agent_id="report-agent",
                    requirements=requirements,
                    tools=tools,
                )
            ],
        )

    requirement = RunRequirement(pending)
    assert (
        app._pending_legacy_report_tool(session_with(requirements=[requirement]), "run")
        == "workspace_write_file"
    )
    requirement.confirm()
    assert app._pending_legacy_report_tool(session_with(requirements=[requirement]), "run") is None
    assert app._pending_legacy_report_tool(session_with(tools=[running]), "run") == "sandbox_exec"
    assert app._pending_legacy_report_tool(session_with(tools=[completed]), "run") is None
    assert (
        app._pending_legacy_report_tool(session_with(tools=[removed]), "run")
        == "report_analyze_dataset"
    )
    assert app._pending_legacy_report_tool(session_with(tools=[new_tool]), "run") is None
