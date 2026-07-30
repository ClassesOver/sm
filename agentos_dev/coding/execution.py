from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import re
import shlex
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Any

from agno.run import RunContext
from agno.tools import Function
from daytona import SessionExecuteRequest
from daytona.common.errors import DaytonaNotFoundError

from ..agent_control import AGENT_PLAN_STATE_KEY, AgentControlToolkit, validated_agent_plan
from ..skills import (
    CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY,
    SkillAcceptanceError,
    SkillValidator,
    SkillValidatorRegistry,
    lock_sandbox_paths,
)
from ..workspace import (
    MANAGED_PROCESS_PREFIX,
    MAX_BACKGROUND_EXECUTION_TIMEOUT,
    MAX_PATCH_FILES,
    MAX_PROCESS_INPUT_BYTES,
    MAX_TOOL_OUTPUT_BYTES,
    WORKSPACE_ROOT,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceProcessNotFound,
    WorkspaceService,
    WorkspaceToolkit,
    _thread,
)
from .acceptance import AcceptancePolicy, requirement_digest
from .executor import CODING_FINISH_FAILURE_STATE_KEY
from .models import CodingScope, Lease, TaskSnapshot
from .repository_impl import (
    TERMINAL_EXECUTION_STATUSES,
    CodingExecution,
    CodingRepositoryError,
    CodingTask,
    CodingTaskRepository,
    utcnow,
)
from .tools import (
    CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY,
    CODEX_EXEC_SESSIONS_STATE_KEY,
    PURE_CODING_TOOLKIT_INSTRUCTIONS,
    CodingToolkit,
    _extract_apply_patch_command,
    _ManagedDaytonaTools,
    build_workspace_changes,
)

CODING_TASK_DEPENDENCY = "AgentOS 编码任务"
CODING_FINISH_STATE_KEY = "agentos_coding_finish"
CODING_EXECUTION_MIGRATION_STATE_KEY = "agentos_coding_execution_migrated"
DEFAULT_TERMINAL_TIMEOUT = 900
MAX_FINISH_ARTIFACTS = 50
MAX_VERIFICATION_IDS = 20
MAX_TERMINAL_COMMAND_BYTES = 32 * 1024
MAX_TOOL_PREVIEW_BYTES = 48 * 1024
MAX_TOOL_OUTPUT_RESOURCE_BYTES = 16 * 1024 * 1024
MAX_TASK_TOOL_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_TOOL_OUTPUT_READ_BYTES = 64 * 1024
MAX_PARALLEL_READ_TOOLS = 4
MAX_TERMINAL_RUNTIME_CACHE_ENTRIES = 1024
CODING_TOOL_OUTPUT_STATE_KEY = "agentos_coding_tool_outputs"
CODING_TOOL_PROGRESS_STATE_KEY = "agentos_coding_tool_progress"
CODING_TOOL_FAILURE_STATE_KEY = "agentos_coding_tool_failures"
CODING_REWORK_STATE_KEY = "agentos_coding_rework"
TOOL_OUTPUT_ROOT = "/home/daytona/.agentos/tool-output"
VALIDATOR_ROOT = "/home/daytona/.agentos/validators"
READONLY_RUNTIME_ROOT = "/home/daytona/.agentos/runtime"
MAX_VALIDATOR_REQUEST_BYTES = 256 * 1024
MAX_VALIDATOR_RESULT_BYTES = 32 * 1024
MAX_VALIDATOR_DETAIL_BYTES = 512
READONLY_SCRIPT_RUNTIME = Path(__file__).with_name("readonly_script_runtime.py").read_bytes()
READONLY_SCRIPT_RUNTIME_SHA256 = hashlib.sha256(READONLY_SCRIPT_RUNTIME).hexdigest()


def _create_files_patch(files: list[dict[str, str]]) -> str:
    lines = ["*** Begin Patch"]
    for item in files:
        lines.append(f"*** Add File: {item['path']}")
        content_lines = item["content"].replace("\r\n", "\n").replace("\r", "\n").splitlines()
        lines.extend(f"+{line}" for line in (content_lines or [""]))
    lines.append("*** End Patch")
    return "\n".join(lines)


@dataclass(frozen=True)
class ToolSpec:
    effect: str
    parallel_safe: bool
    output_policy: str = "bounded_text"


@dataclass(frozen=True)
class _InstalledValidator:
    directory: str
    script_path: str
    request_path: str
    runtime_path: str
    runtime_sha256: str


TOOL_SPECS = {
    "terminal": ToolSpec("workspace_write", False),
    "process": ToolSpec("process_control", False),
    "create_file": ToolSpec("workspace_write", False),
    "create_files": ToolSpec("workspace_write", False),
    "overwrite_file": ToolSpec("workspace_write", False),
    "replace_text": ToolSpec("workspace_write", False),
    "apply_patch": ToolSpec("workspace_write", False),
    "patch": ToolSpec("workspace_write", False),
    "verify": ToolSpec("verification", False),
    "finish_task": ToolSpec("finish", False),
    "update_plan": ToolSpec("workspace_write", False),
    "view_image": ToolSpec("read", True, "media"),
    "read_tool_output": ToolSpec("read", True, "paged_text"),
    "list_files": ToolSpec("read", True),
    "read_file": ToolSpec("read", True),
    "read_lines": ToolSpec("read", True),
    "search_text": ToolSpec("read", True),
    "tree": ToolSpec("read", True),
    "git_status": ToolSpec("read", True),
    "git_diff": ToolSpec("read", True),
}

NO_PROGRESS_EXEMPT_TOOLS = frozenset(
    {"read_tool_output", "view_image", "process:list", "process:poll", "process:wait"}
)
MAX_TOOL_PROGRESS_ENTRIES = 16
MAX_TOOL_FAILURE_ENTRIES = 16
ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.-])/(?:[\w.-]+/)*[\w.-]+")
COMMAND_NOT_FOUND_RE = re.compile(
    r"(?im)^(?:/bin/)?(?:ba)?sh:\s*\d+:\s*[^:\n]+:\s*(?:command\s+)?not found\s*$"
)
PYTHON_TRACEBACK_RE = re.compile(r"(?m)^Traceback \(most recent call last\):\s*$")
PYTHON_EXCEPTION_RE = re.compile(
    r"^(?:builtins\.)?(?:AssertionError|NameError|ModuleNotFoundError|ImportError|SyntaxError|"
    r"TypeError|ValueError|KeyError|FileNotFoundError|PermissionError|OSError|RuntimeError)"
    r"(?:\s*:\s*.*)?$"
)
READ_ONLY_TERMINAL_COMMANDS = frozenset(
    {
        "cat",
        "cut",
        "du",
        "echo",
        "file",
        "find",
        "grep",
        "head",
        "ls",
        "printf",
        "pwd",
        "rg",
        "sha256sum",
        "stat",
        "tail",
        "tree",
        "tr",
        "wc",
    }
)
READ_ONLY_GIT_COMMANDS = frozenset({"diff", "log", "ls-files", "rev-parse", "show", "status"})
VOLATILE_PROGRESS_RESULT_KEYS = frozenset(
    {"commandId", "command_id", "execution_id", "sessionId", "session_id"}
)


def _stable_progress_result(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable_progress_result(item)
            for key, item in value.items()
            if key not in VOLATILE_PROGRESS_RESULT_KEYS
        }
    if isinstance(value, list):
        return [_stable_progress_result(item) for item in value]
    return value


def _absolute_paths(value: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            paths.update(_absolute_paths(item))
        return paths
    if isinstance(value, list):
        for item in value:
            paths.update(_absolute_paths(item))
        return paths
    return set(ABSOLUTE_PATH_RE.findall(value)) if isinstance(value, str) else set()


def _paths_related(first: str, second: str) -> bool:
    first_parts = tuple(part for part in first.split("/") if part)
    second_parts = tuple(part for part in second.split("/") if part)
    shorter = min(len(first_parts), len(second_parts))
    return first_parts[:shorter] == second_parts[:shorter]


def _suggested_workspace_path(arguments: dict[str, Any]) -> str | None:
    for path in sorted(_absolute_paths(arguments), key=len, reverse=True):
        for root in (WORKSPACE_ROOT, "/workspace"):
            if path == root:
                return ""
            if path.startswith(f"{root}/"):
                return path[len(root) + 1 :]
    return None


def _deterministic_output_error(output: str) -> tuple[str, str] | None:
    command_error = COMMAND_NOT_FOUND_RE.search(output)
    if command_error is not None:
        return "command_not_found", command_error.group(0)[:500]
    if PYTHON_TRACEBACK_RE.search(output) is None:
        return None
    last_line = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "")
    if PYTHON_EXCEPTION_RE.fullmatch(last_line) is None:
        return None
    return "python_traceback", last_line[:500]


def _failed_result_resources(arguments: dict[str, Any], result: Any) -> list[str]:
    if not isinstance(result, dict):
        return []
    exit_code = result.get("exit_code")
    failed = (
        (isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0)
        or result.get("ok") is False
        or result.get("status") in {"failed", "lost", "terminated"}
    )
    if not failed:
        return []
    output = result.get("output") or result.get("message") or ""
    argument_paths = _absolute_paths(arguments)
    output_paths = _absolute_paths(output)
    resources = {
        output_path
        for argument_path in argument_paths
        for output_path in output_paths
        if _paths_related(argument_path, output_path)
        and output_path != WORKSPACE_ROOT
        and not output_path.startswith(f"{WORKSPACE_ROOT}/")
    }
    return sorted(resources)[:4]


def _is_read_only_terminal_command(command: str) -> bool:
    if not isinstance(command, str) or not command.strip():
        return False
    if any(marker in command for marker in ("\n", "\r", "`", "$", "\\\n")):
        return False
    parsed_command = re.sub(r"(?<!\S)2>>?/dev/null(?=\s|$)", "", command)
    lexer = shlex.shlex(parsed_command, posix=True, punctuation_chars=";&|<>()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    if not tokens or any(
        token in {";", "&", "||", "<", ">", "<<", ">>", "(", ")"} for token in tokens
    ):
        return False
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"&&", "|"}:
            if not segments[-1]:
                return False
            segments.append([])
        else:
            segments[-1].append(token)
    if not segments[-1]:
        return False
    for segment in segments:
        executable = segment[0].rsplit("/", 1)[-1]
        arguments = segment[1:]
        if executable == "git":
            if arguments[:1] == ["-C"] and len(arguments) >= 3:
                arguments = arguments[2:]
            if not arguments or arguments[0] not in READ_ONLY_GIT_COMMANDS:
                return False
            if any(
                value in {"--ext-diff", "--textconv", "--output"} or value.startswith("--output=")
                for value in arguments
            ):
                return False
            continue
        if executable not in READ_ONLY_TERMINAL_COMMANDS:
            return False
        if executable == "find" and any(
            value
            in {
                "-delete",
                "-exec",
                "-execdir",
                "-ok",
                "-okdir",
                "-fls",
                "-fprint",
                "-fprint0",
                "-fprintf",
            }
            for value in arguments
        ):
            return False
        if executable == "rg" and any(
            value == "--pre" or value.startswith("--pre=") for value in arguments
        ):
            return False
    return True


_PARALLEL_SKILL_TOOLS = frozenset({"get_skill_instructions", "get_skill_reference"})
_PARALLEL_REPORT_TOOLS = frozenset({"report_list_data_sources", "report_describe_data_source"})
_CODING_TOOL_SCHEDULER_MARKER = "_agentos_coding_tool_scheduler"


def _task_tool_parallel_safe(function_name: str, arguments: dict[str, Any]) -> bool:
    if function_name in _PARALLEL_SKILL_TOOLS or function_name in _PARALLEL_REPORT_TOOLS:
        return True
    return function_name == "get_skill_script" and arguments.get("execute", False) is False


class _AsyncRWLock:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._state_lock = asyncio.Lock()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0
        self._leases = 0

    @asynccontextmanager
    async def read(self):
        async with self._condition:
            await self._condition.wait_for(
                lambda: (
                    not self._writer
                    and self._waiting_writers == 0
                    and self._readers < MAX_PARALLEL_READ_TOOLS
                )
            )
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                self._condition.notify_all()

    @asynccontextmanager
    async def write(self):
        async with self._condition:
            self._waiting_writers += 1
            try:
                await self._condition.wait_for(lambda: not self._writer and self._readers == 0)
                self._writer = True
            finally:
                self._waiting_writers -= 1
                self._condition.notify_all()
        try:
            yield
        finally:
            async with self._condition:
                self._writer = False
                self._condition.notify_all()

    @asynccontextmanager
    async def state(self):
        async with self._state_lock:
            yield


_TASK_TOOL_SCHEDULERS: dict[tuple[int, str], _AsyncRWLock] = {}


@asynccontextmanager
async def _task_tool_scheduler(
    repository: Any, external_run_id: str
) -> AsyncIterator[_AsyncRWLock]:
    key = (id(repository), external_run_id)
    scheduler = _TASK_TOOL_SCHEDULERS.setdefault(key, _AsyncRWLock())
    scheduler._leases += 1
    try:
        yield scheduler
    finally:
        scheduler._leases -= 1
        if scheduler._leases == 0 and _TASK_TOOL_SCHEDULERS.get(key) is scheduler:
            del _TASK_TOOL_SCHEDULERS[key]


def _bound_external_run_id(run_context: RunContext | None) -> str | None:
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, dict)
        else {}
    )
    binding = dependencies.get(CODING_TASK_DEPENDENCY)
    external_run_id = binding.get("externalRunId") if isinstance(binding, dict) else None
    return external_run_id if isinstance(external_run_id, str) and external_run_id else None


def create_coding_tool_scheduler_hook(
    repository: CodingTaskRepository,
) -> Callable[
    [RunContext, str, Callable[..., Any], dict[str, Any]],
    Coroutine[Any, Any, Any],
]:
    async def coding_tool_scheduler_hook(
        run_context: RunContext,
        function_name: str,
        function_call: Callable[..., Any],
        arguments: dict[str, Any],
    ) -> Any:
        async def invoke() -> Any:
            result = function_call(**arguments)
            return await result if isawaitable(result) else result

        # WorkspaceCodingToolkit applies the same scheduler after it resolves the Task scope.
        if function_name in TOOL_SPECS:
            return await invoke()
        external_run_id = _bound_external_run_id(run_context)
        if external_run_id is None:
            return await invoke()
        async with _task_tool_scheduler(repository, external_run_id) as scheduler:
            lock = (
                scheduler.read()
                if _task_tool_parallel_safe(function_name, arguments)
                else scheduler.write()
            )
            async with lock:
                return await invoke()

    setattr(coding_tool_scheduler_hook, _CODING_TOOL_SCHEDULER_MARKER, True)
    return coding_tool_scheduler_hook


def is_coding_tool_scheduler_hook(hook: Callable[..., Any]) -> bool:
    return getattr(hook, _CODING_TOOL_SCHEDULER_MARKER, False) is True


@dataclass(frozen=True)
class CodingTaskScope:
    task: CodingTask | TaskSnapshot
    external_run_id: str
    internal_run_id: str
    owner_user_id: str
    thread_id: str
    sandbox_id: str
    lease_owner: str
    lease_epoch: int
    attempt_no: int
    lease: Lease | None = None


class CodingExecutionKernel:
    _task_locks = _TASK_TOOL_SCHEDULERS

    def __init__(
        self,
        service: WorkspaceService,
        repository: CodingTaskRepository,
        *,
        completion_evidence: Callable[[RunContext], Awaitable[dict[str, Any] | None]] | None = None,
        validator_registry: SkillValidatorRegistry | None = None,
    ):
        self.service = service
        self.repository = repository
        self.completion_evidence = completion_evidence
        self.validator_registry = validator_registry or SkillValidatorRegistry()
        self.acceptance_policy = AcceptancePolicy()
        self.workspace = WorkspaceToolkit(service)
        self.plan = AgentControlToolkit(service)
        self._migration_lock = asyncio.Lock()
        self._terminal_runtimes: OrderedDict[tuple[str, str], str] = OrderedDict()

    def task_scheduler(self, external_run_id: str):
        return _task_tool_scheduler(self.repository, external_run_id)

    @staticmethod
    def bound_external_run_id(run_context: RunContext | None) -> str:
        if run_context is None or not run_context.run_id or not run_context.user_id:
            raise CodingRepositoryError("task_context_missing", "缺少编码任务运行上下文。")
        dependencies = (
            run_context.dependencies
            if run_context is not None and isinstance(run_context.dependencies, dict)
            else {}
        )
        binding = dependencies.get(CODING_TASK_DEPENDENCY)
        external_run_id = binding.get("externalRunId") if isinstance(binding, dict) else None
        if not isinstance(external_run_id, str) or not external_run_id:
            raise CodingRepositoryError("task_binding_missing", "当前运行没有绑定编码任务。")
        return external_run_id

    @staticmethod
    def _preview_text(raw: bytes) -> str:
        if len(raw) <= MAX_TOOL_PREVIEW_BYTES:
            return raw.decode("utf-8", errors="replace")
        marker = (
            f"\n[TOOL_OUTPUT_TRUNCATED omitted_bytes={len(raw) - MAX_TOOL_PREVIEW_BYTES}]\n"
        ).encode()
        available = MAX_TOOL_PREVIEW_BYTES - len(marker)
        head_size = available // 2
        tail_size = available - head_size
        head = raw[:head_size].decode("utf-8", errors="ignore")
        tail = raw[-tail_size:].decode("utf-8", errors="ignore")
        return head + marker.decode() + tail

    async def bound_tool_result(
        self,
        scope: CodingTaskScope,
        result: Any,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        serialized = json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        candidates = (
            [
                (key, value)
                for key, value in result.items()
                if key in {"output", "content", "diff"} and isinstance(value, str)
            ]
            if isinstance(result, dict)
            else []
        )
        if candidates:
            key, value = max(candidates, key=lambda item: len(item[1].encode("utf-8")))
            if (
                len(value.encode("utf-8")) <= MAX_TOOL_PREVIEW_BYTES
                and len(serialized.encode("utf-8")) > MAX_TOOL_PREVIEW_BYTES
            ):
                result = {"output": serialized, "outputFormat": "json"}
                key, value = "output", serialized
        else:
            if len(serialized.encode("utf-8")) <= MAX_TOOL_PREVIEW_BYTES:
                return result
            result = {"output": serialized, "outputFormat": "json"}
            key, value = "output", serialized
        raw = value.encode("utf-8")
        if len(raw) <= MAX_TOOL_PREVIEW_BYTES:
            return result
        state = (
            run_context.session_state
            if run_context is not None and isinstance(run_context.session_state, dict)
            else None
        )
        if state is None:
            return {
                **result,
                key: self._preview_text(raw),
                "outputBytes": len(raw),
                "outputSha256": hashlib.sha256(raw).hexdigest(),
                "outputTruncated": True,
                "outputStored": False,
            }
        async with self.task_scheduler(scope.external_run_id) as scheduler:
            handle = uuid.uuid4().hex
            path = f"{TOOL_OUTPUT_ROOT}/{hashlib.sha256(scope.external_run_id.encode()).hexdigest()[:24]}/{handle}"
            now = time.time()
            async with scheduler.state():
                root = state.setdefault(CODING_TOOL_OUTPUT_STATE_KEY, {"handles": {}, "tasks": {}})
                handles = root.setdefault("handles", {})
                tasks = root.setdefault("tasks", {})
                task_state = tasks.setdefault(scope.external_run_id, {"bytes": 0, "handles": []})
                remaining = max(0, MAX_TASK_TOOL_OUTPUT_BYTES - int(task_state.get("bytes", 0)))
                stored_bytes = min(len(raw), MAX_TOOL_OUTPUT_RESOURCE_BYTES, remaining)
                metadata = {
                    "task": scope.external_run_id,
                    "attempt": scope.attempt_no,
                    "path": path,
                    "bytes": len(raw),
                    "storedBytes": stored_bytes,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
                handles[handle] = metadata
                task_state["bytes"] = int(task_state.get("bytes", 0)) + stored_bytes
                task_state.setdefault("handles", []).append(handle)
                cleanup_due = now - float(root.get("lastCleanup", 0) or 0) >= 86_400
                if cleanup_due:
                    root["lastCleanup"] = now
            try:
                if stored_bytes:
                    async for sandbox in self._sandbox(scope):
                        parent = path.rsplit("/", 1)[0]
                        for directory in (
                            "/home/daytona/.agentos",
                            TOOL_OUTPUT_ROOT,
                            parent,
                        ):
                            try:
                                await sandbox.fs.create_folder(directory, "700")
                            except Exception:
                                pass
                        if cleanup_due:
                            await sandbox.process.exec(
                                "/bin/sh -c "
                                + shlex.quote(
                                    f"find {shlex.quote(TOOL_OUTPUT_ROOT)} -mindepth 1 -maxdepth 1 "
                                    "-type d -mtime +7 -exec rm -rf -- {} +"
                                ),
                                timeout=60,
                            )
                        await sandbox.fs.upload_file(raw[:stored_bytes], path)
            except Exception:
                async with scheduler.state():
                    current_root = state.get(CODING_TOOL_OUTPUT_STATE_KEY, {})
                    current_handles = (
                        current_root.get("handles", {}) if isinstance(current_root, dict) else {}
                    )
                    current_tasks = (
                        current_root.get("tasks", {}) if isinstance(current_root, dict) else {}
                    )
                    current_task = (
                        current_tasks.get(scope.external_run_id)
                        if isinstance(current_tasks, dict)
                        else None
                    )
                    if isinstance(current_handles, dict):
                        current_handles.pop(handle, None)
                    if isinstance(current_task, dict):
                        current_task["bytes"] = max(
                            0, int(current_task.get("bytes", 0)) - stored_bytes
                        )
                        task_handles = current_task.get("handles")
                        if isinstance(task_handles, list) and handle in task_handles:
                            task_handles.remove(handle)
                raise
        return {
            **result,
            key: self._preview_text(raw),
            "outputHandle": handle,
            "outputBytes": len(raw),
            "outputStoredBytes": stored_bytes,
            "outputSha256": metadata["sha256"],
            "outputTruncated": True,
            "outputDiscarded": stored_bytes < len(raw),
        }

    async def read_tool_output(
        self,
        handle: str,
        offset: int,
        max_bytes: int,
        run_context: RunContext | None,
        *,
        _scope: CodingTaskScope | None = None,
    ) -> dict[str, Any]:
        if not isinstance(handle, str) or not handle:
            raise WorkspaceError("output handle 无效。")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise WorkspaceError("output offset 必须是大于等于 0 的整数。")
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 1 <= max_bytes <= MAX_TOOL_OUTPUT_READ_BYTES
        ):
            raise WorkspaceError(
                f"output max_bytes 必须是 1 至 {MAX_TOOL_OUTPUT_READ_BYTES} 之间的整数。"
            )
        scope = _scope or await self.scope(run_context)
        state = run_context.session_state if run_context is not None else None
        root = state.get(CODING_TOOL_OUTPUT_STATE_KEY, {}) if isinstance(state, dict) else {}
        metadata = root.get("handles", {}).get(handle) if isinstance(root, dict) else None
        if (
            not isinstance(metadata, dict)
            or metadata.get("task") != scope.external_run_id
            or metadata.get("attempt") != scope.attempt_no
        ):
            raise WorkspaceError("output handle 不属于当前 Task/Attempt。")
        stored_bytes = int(metadata.get("storedBytes", 0))
        if offset > stored_bytes:
            raise WorkspaceError("output offset 超过已保存内容大小。")
        async for sandbox in self._sandbox(scope):
            raw = await sandbox.fs.download_file(metadata["path"]) if stored_bytes else b""
        end = min(stored_bytes, offset + max_bytes)
        while end > offset:
            try:
                content = raw[offset:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            content = ""
        if not content and offset < stored_bytes:
            raise WorkspaceError("max_bytes 不足以读取下一个 UTF-8 字符。")
        return {
            "outputHandle": handle,
            "offset": offset,
            "nextOffset": end,
            "content": content,
            "storedBytes": stored_bytes,
            "outputBytes": metadata["bytes"],
            "outputSha256": metadata["sha256"],
            "hasMore": end < stored_bytes,
            "outputDiscarded": stored_bytes < int(metadata["bytes"]),
        }

    async def cleanup_tool_outputs(
        self, scope: CodingTaskScope, run_context: RunContext | None
    ) -> None:
        state = run_context.session_state if run_context is not None else None
        root = state.get(CODING_TOOL_OUTPUT_STATE_KEY) if isinstance(state, dict) else None
        if isinstance(root, dict):
            task_state = root.get("tasks", {}).pop(scope.external_run_id, None)
            handles = root.get("handles", {})
            if isinstance(task_state, dict):
                for handle in task_state.get("handles", []):
                    handles.pop(handle, None)
        task_dir = (
            f"{TOOL_OUTPUT_ROOT}/{hashlib.sha256(scope.external_run_id.encode()).hexdigest()[:24]}"
        )
        try:
            async for sandbox in self._sandbox(scope):
                await sandbox.fs.delete_file(task_dir, recursive=True)
        except Exception:
            pass

    async def cleanup_old_epoch(self, scope: CodingScope, current_epoch: int) -> None:
        await self._cleanup_executions(scope, current_epoch, old_only=True)

    async def cleanup_disconnect(self, scope: CodingScope, current_epoch: int) -> None:
        await self._cleanup_executions(scope, current_epoch, old_only=False)

    async def cleanup_task_outputs(self, scope: CodingScope) -> None:
        task_dir = (
            f"{TOOL_OUTPUT_ROOT}/{hashlib.sha256(scope.external_run_id.encode()).hexdigest()[:24]}"
        )
        try:
            async with self.service._async_client() as client:
                sandbox = await self.service._asandbox_for(client, scope.thread_id, create=False)
                if sandbox is None or str(getattr(sandbox, "id", "") or "") != scope.sandbox_id:
                    return
                await sandbox.fs.delete_file(task_dir, recursive=True)
        except (DaytonaNotFoundError, WorkspaceError):
            pass

    async def _cleanup_executions(
        self, scope: CodingScope, current_epoch: int, *, old_only: bool
    ) -> None:
        executions = await self.repository.list_executions(scope.external_run_id)
        for execution in executions:
            if execution.status in TERMINAL_EXECUTION_STATUSES or execution.retained_service:
                continue
            if old_only and execution.lease_epoch >= current_epoch:
                continue
            if not old_only and execution.lease_epoch != current_epoch:
                continue
            if execution.kind == "patch" and execution.operation_receipt:
                coordinated = await self._coordinate_patch(execution)
                if coordinated == "indeterminate":
                    await self.repository.fail_indeterminate_mutation(scope, current_epoch)
                    return
                await self.repository.update_execution(
                    execution.execution_id,
                    status="completed" if coordinated == "applied" else "cancelled",
                    exit_code=0 if coordinated == "applied" else None,
                )
                continue
            try:
                async with self.service._async_client() as client:
                    sandbox = await self.service._asandbox_for(client, scope.thread_id)
                    await sandbox.process.delete_session(execution.daytona_session_id)
                status = "terminated"
            except DaytonaNotFoundError:
                status = "lost"
            await self.repository.update_execution(execution.execution_id, status=status)

    async def _coordinate_patch(self, execution: CodingExecution) -> str:
        receipt = execution.operation_receipt or {}
        files = receipt.get("files")
        if not isinstance(files, list) or not files:
            return "indeterminate"
        states: list[str] = []
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                return "indeterminate"
            try:
                current = await self.service.ahash_file(execution.thread_id, item["path"])
                digest = current["sha256"]
            except (WorkspaceError, DaytonaNotFoundError):
                digest = None
            if digest == item.get("after_sha256"):
                states.append("after")
            elif digest == item.get("before_sha256"):
                states.append("before")
            else:
                states.append("other")
        if all(state == "after" for state in states):
            return "applied"
        if all(state == "before" for state in states):
            return "not_applied"
        return "indeterminate"

    async def scope(self, run_context: RunContext | None) -> CodingTaskScope:
        if run_context is None or not run_context.run_id or not run_context.user_id:
            raise CodingRepositoryError("task_context_missing", "缺少编码任务运行上下文。")
        dependencies = (
            run_context.dependencies if isinstance(run_context.dependencies, dict) else {}
        )
        binding = dependencies.get(CODING_TASK_DEPENDENCY)
        if not isinstance(binding, dict):
            raise CodingRepositoryError("task_binding_missing", "当前运行没有绑定编码任务。")
        external_run_id = binding.get("externalRunId")
        lease_owner = binding.get("leaseOwner")
        lease_epoch = binding.get("leaseEpoch")
        bound_thread_id = binding.get("threadId")
        bound_sandbox_id = binding.get("sandboxId")
        if (
            not isinstance(external_run_id, str)
            or not external_run_id
            or not isinstance(lease_owner, str)
            or not lease_owner
            or (
                lease_epoch is not None
                and (isinstance(lease_epoch, bool) or not isinstance(lease_epoch, int))
            )
            or (
                bound_thread_id is not None
                and (not isinstance(bound_thread_id, str) or not bound_thread_id)
            )
            or (
                bound_sandbox_id is not None
                and (not isinstance(bound_sandbox_id, str) or not bound_sandbox_id)
            )
        ):
            raise CodingRepositoryError("task_binding_invalid", "当前编码任务绑定无效。")
        snapshot = await self.repository.get_task_snapshot(external_run_id)
        task: CodingTask | TaskSnapshot | None = snapshot
        if task is None:
            task = await self.repository.get_task(external_run_id)
        if task is None:
            raise CodingRepositoryError("task_not_found", "编码任务必须由 Supervisor 创建。")
        task_sandbox_id = (
            task.scope.sandbox_id if isinstance(task, TaskSnapshot) else task.sandbox_id
        )
        sandbox_id = bound_sandbox_id or task_sandbox_id
        thread_id = bound_thread_id or _thread(run_context)
        active_lease: Lease | None
        if isinstance(task, TaskSnapshot):
            if (
                task.scope.owner_user_id != str(run_context.user_id)
                or task.scope.thread_id != thread_id
                or task.scope.sandbox_id != sandbox_id
            ):
                raise CodingRepositoryError("task_scope_mismatch", "编码任务范围不匹配。")
        else:
            self.repository._assert_scope(task, str(run_context.user_id), thread_id, sandbox_id)
        internal_run_id = str(run_context.run_id)
        if not isinstance(task, TaskSnapshot) and task.current_internal_run_id is None:
            task = await self.repository.bind_initial_run(external_run_id, internal_run_id)
        elif internal_run_id != task.current_internal_run_id:
            raise CodingRepositoryError(
                "task_run_mismatch", "当前内部运行不是编码任务的活动 checkpoint。"
            )
        if isinstance(task, TaskSnapshot):
            if (
                lease_epoch is None
                or task.lease_owner != lease_owner
                or task.lease_epoch != lease_epoch
                or task.lease_expires_at is None
                or task.lease_expires_at <= utcnow()
            ):
                raise CodingRepositoryError("task_lease_binding_invalid", "编码任务租约绑定无效。")
            active_lease = Lease(lease_owner, lease_epoch, task.lease_expires_at)
        else:
            claimed = await self.repository.claim_lease(external_run_id, lease_owner)
            if not claimed:
                raise CodingRepositoryError("task_lease_conflict", "编码任务正在由另一连接处理。")
            active_lease = claimed if isinstance(claimed, Lease) else None
        scope = CodingTaskScope(
            task=task,
            external_run_id=external_run_id,
            internal_run_id=internal_run_id,
            owner_user_id=str(run_context.user_id),
            thread_id=thread_id,
            sandbox_id=sandbox_id,
            lease_owner=lease_owner,
            lease_epoch=active_lease.epoch if active_lease is not None else 0,
            attempt_no=(
                task.current_attempt_no
                if isinstance(task, TaskSnapshot)
                else task.continuation_count
            ),
            lease=active_lease,
        )
        await self._migrate_legacy_executions(scope, run_context)
        return scope

    async def _migrate_legacy_executions(
        self,
        scope: CodingTaskScope,
        run_context: RunContext,
    ) -> None:
        async with self._migration_lock:
            await self._migrate_legacy_executions_locked(scope, run_context)

    async def _migrate_legacy_executions_locked(
        self,
        scope: CodingTaskScope,
        run_context: RunContext,
    ) -> None:
        state = run_context.session_state if isinstance(run_context.session_state, dict) else None
        if state is None or state.get(CODING_EXECUTION_MIGRATION_STATE_KEY) is True:
            return
        active = state.get(CODEX_EXEC_SESSIONS_STATE_KEY)
        closed = state.get(CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY)
        for kind, entries in (("active", active), ("closed", closed)):
            if not isinstance(entries, dict):
                continue
            for legacy_handle, raw_entry in entries.items():
                if not isinstance(raw_entry, dict):
                    continue
                if (
                    str(raw_entry.get("thread") or "") != scope.thread_id
                    or str(raw_entry.get("user_id") or "") != scope.owner_user_id
                ):
                    raise CodingRepositoryError(
                        "legacy_execution_scope_mismatch",
                        "旧执行句柄不属于当前用户或对话。",
                    )
                remote_session_id = raw_entry.get("session_id")
                command_id = raw_entry.get("command_id")
                if kind == "active" and (
                    not isinstance(remote_session_id, str)
                    or not remote_session_id.startswith(MANAGED_PROCESS_PREFIX)
                    or not isinstance(command_id, str)
                    or not command_id
                ):
                    continue
                execution_id = hashlib.sha256(
                    f"{scope.external_run_id}:{kind}:{legacy_handle}".encode()
                ).hexdigest()[:32]
                if await self.repository.get_execution(execution_id) is not None:
                    continue
                synthetic_session_id = (
                    remote_session_id
                    if isinstance(remote_session_id, str)
                    else f"legacy-{execution_id}"
                )
                execution = await self.repository.reserve_execution(
                    execution_id=execution_id,
                    external_run_id=scope.external_run_id,
                    internal_run_id=scope.internal_run_id,
                    owner_user_id=scope.owner_user_id,
                    thread_id=scope.thread_id,
                    sandbox_id=scope.sandbox_id,
                    daytona_session_id=synthetic_session_id,
                    mutation_sequence=scope.task.mutation_sequence,
                )
                if kind == "active":
                    offset = raw_entry.get("offset", 0)
                    await self.repository.update_execution(
                        execution.execution_id,
                        status="running",
                        command_id=command_id,
                        output_cursor=(
                            offset
                            if isinstance(offset, int)
                            and not isinstance(offset, bool)
                            and offset >= 0
                            else 0
                        ),
                    )
                    continue
                reason = str(raw_entry.get("reason") or "lost")
                terminal_status = {
                    "completed": "completed",
                    "terminated": "terminated",
                    "timed_out": "failed",
                }.get(reason, "lost")
                await self.repository.update_execution(
                    execution.execution_id,
                    status=terminal_status,
                    exit_code=(
                        0
                        if terminal_status == "completed"
                        else 124
                        if reason == "timed_out"
                        else None
                    ),
                )
        state[CODING_EXECUTION_MIGRATION_STATE_KEY] = True

    async def _sandbox(self, scope: CodingTaskScope):
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, scope.thread_id)
            if str(getattr(sandbox, "id", "") or "") != scope.sandbox_id:
                raise CodingRepositoryError(
                    "task_sandbox_mismatch", "当前 Daytona 工作区与编码任务绑定不一致。"
                )
            yield sandbox

    async def _check_fence(self, scope: CodingTaskScope, execution_id: str) -> None:
        if scope.lease is not None:
            await self.repository.validate_execution_fence(execution_id, scope.lease)

    @staticmethod
    def _public_execution(execution: CodingExecution, *, cached: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "execution_id": execution.execution_id,
            "status": execution.status,
            "output": execution.terminal_output,
            "exit_code": execution.exit_code,
            "output_cursor": execution.output_cursor,
            "mutation_sequence": execution.mutation_sequence,
        }
        if execution.status not in TERMINAL_EXECUTION_STATUSES:
            result["session_id"] = execution.execution_id
        if cached:
            result["status_is_cached"] = True
        output_error = (
            _deterministic_output_error(execution.terminal_output)
            if execution.status == "completed" and execution.exit_code == 0
            else None
        )
        if output_error is not None:
            failure_code, diagnostics = output_error
            result.update(
                {
                    "ok": False,
                    "code": "execution_output_error",
                    "message": "命令输出包含确定性的执行错误。",
                    "details": {
                        "failureCode": failure_code,
                        "diagnostics": diagnostics,
                    },
                    "requiredActions": ["修复输出中的执行错误后重新运行命令。"],
                    "retryable": True,
                }
            )
        return result

    async def _scoped_execution(
        self,
        execution_id: str,
        run_context: RunContext | None,
        scope: CodingTaskScope | None = None,
    ) -> tuple[CodingTaskScope, CodingExecution]:
        scope = scope or await self.scope(run_context)
        execution = await self.repository.scoped_execution(
            execution_id,
            owner_user_id=scope.owner_user_id,
            thread_id=scope.thread_id,
            sandbox_id=scope.sandbox_id,
        )
        if execution.external_run_id != scope.external_run_id:
            raise CodingRepositoryError("execution_scope_mismatch", "执行句柄不属于当前编码任务。")
        return scope, execution

    @staticmethod
    def _validate_terminal_arguments(
        command: str,
        background: bool,
        timeout: int,
        pty: bool,
    ) -> None:
        if not isinstance(background, bool) or not isinstance(pty, bool):
            raise WorkspaceError("terminal 的 background 和 pty 必须是布尔值。")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86_400:
            raise WorkspaceError("terminal timeout 必须是 1 至 86400 之间的整数秒。")
        CodingToolkit._validate_command_policy(command, "/bin/sh")
        if len(command.encode("utf-8")) > MAX_TERMINAL_COMMAND_BYTES:
            raise WorkspaceError(
                f"terminal command 超过 {MAX_TERMINAL_COMMAND_BYTES} 字节；"
                "请用 patch 创建或修改脚本，再用短命令执行。"
            )

    @staticmethod
    def _managed_command(command: str, workdir: str | None, timeout: int, pty: bool) -> str:
        remote_cwd = WORKSPACE_ROOT
        if workdir is not None:
            _relative, remote_cwd = WorkspaceService.normalize_path(workdir)
        executed = f"exec {shlex.join(['/bin/sh', '-l', '-c', command])}"
        if pty:
            pty_command = f"export TERM=xterm-256color; stty rows 24 cols 80 -echo; {executed}"
            executed = shlex.join(
                ["script", "--quiet", "--return", "--command", pty_command, "/dev/null"]
            )
        timed = (
            f"timeout --signal=TERM --kill-after=5s {timeout}s /bin/sh -lc {shlex.quote(executed)}"
        )
        return f"cd -- {shlex.quote(remote_cwd)} && {timed}"

    async def _read_remote(
        self,
        process: Any,
        execution: CodingExecution,
        *,
        wait_ms: int = 0,
    ) -> dict[str, Any]:
        assert execution.command_id is not None
        deadline = asyncio.get_running_loop().time() + wait_ms / 1000
        while True:
            command = await self.workspace._managed_command(
                process,
                execution.daytona_session_id,
                execution.command_id,
            )
            exit_code = getattr(command, "exit_code", None)
            if exit_code is not None or asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(min(0.1, max(0.0, deadline - asyncio.get_running_loop().time())))
        logs = await process.get_session_command_logs(
            execution.daytona_session_id,
            execution.command_id,
        )
        return self.workspace._session_output(
            logs,
            session_id=execution.daytona_session_id,
            command_id=execution.command_id,
            status="completed" if exit_code is not None else "running",
            exit_code=exit_code,
            offset=execution.output_cursor,
            max_bytes=MAX_TOOL_OUTPUT_BYTES,
            timeout_marker=self.workspace._managed_timeout_marker(command),
        )

    async def _persist_result(
        self,
        process: Any,
        execution: CodingExecution,
        result: dict[str, Any],
    ) -> CodingExecution:
        remote_status = result.get("status")
        has_more = bool(result.get("hasMore"))
        exit_code = result.get("exitCode")
        status = (
            "running"
            if remote_status == "running"
            else "draining"
            if has_more
            else "completed"
            if exit_code == 0
            else "failed"
        )
        try:
            updated = await self.repository.update_execution(
                execution.execution_id,
                status=status,
                output_cursor=int(result.get("nextOffset", execution.output_cursor)),
                output=str(result.get("output", "") or ""),
                exit_code=exit_code if isinstance(exit_code, int) else None,
                expected_output_cursor=execution.output_cursor,
            )
        except CodingRepositoryError as error:
            if error.code != "execution_cas_conflict":
                raise
            latest = await self.repository.get_execution(execution.execution_id)
            assert latest is not None
            return latest
        if status in TERMINAL_EXECUTION_STATUSES:
            try:
                await process.delete_session(execution.daytona_session_id)
            except DaytonaNotFoundError:
                pass
        return updated

    async def terminal(
        self,
        command: str,
        *,
        background: bool = False,
        timeout: int = DEFAULT_TERMINAL_TIMEOUT,
        workdir: str | None = None,
        pty: bool = False,
        run_context: RunContext | None = None,
        _verification: bool = False,
        _artifact_paths: list[str] | None = None,
        _read_only: bool | None = None,
        _scope: CodingTaskScope | None = None,
    ) -> dict[str, Any]:
        patch = _extract_apply_patch_command(command) if isinstance(command, str) else None
        if patch is None:
            self._validate_terminal_arguments(command, background, timeout, pty)
        elif workdir not in (None, "") or pty:
            raise WorkspaceError("apply_patch heredoc 不支持 workdir 或 PTY。")
        scope = _scope or await self.scope(run_context)
        patch_changes = (
            await asyncio.to_thread(build_workspace_changes, self.service, scope.thread_id, patch)
            if patch is not None
            else None
        )
        if patch_changes is not None:
            self._reject_writable_skill_script_copy(patch_changes, run_context)
        terminal_runtime = (
            None if patch is not None else await self._install_terminal_runtime(scope)
        )
        patch_receipt = self._patch_receipt(patch_changes) if patch_changes is not None else None
        read_only = (
            _read_only
            if _read_only is not None
            else patch is None and _is_read_only_terminal_command(command)
        )
        deferred_mutation = bool(
            patch is None and not read_only and not background and not _verification
        )
        fingerprint_before: str | None = None
        if deferred_mutation:
            try:
                fingerprint_before = await self.service.aworkspace_fingerprint(scope.thread_id)
            except WorkspaceError:
                pass
        if read_only or deferred_mutation or _verification:
            mutation_sequence = scope.task.mutation_sequence
        else:
            mutation_sequence = await self.repository.increment_mutation(
                scope.external_run_id,
                lease=scope.lease,
                internal_run_id=scope.internal_run_id,
            )
        execution_id = uuid.uuid4().hex
        daytona_session_id = (
            "patch-"
            + hashlib.sha256(
                f"{scope.external_run_id}:{scope.attempt_no}:{mutation_sequence}".encode()
            ).hexdigest()[:32]
            if patch is not None
            else f"{MANAGED_PROCESS_PREFIX}{execution_id}"
        )
        execution = await self.repository.reserve_execution(
            execution_id=execution_id,
            external_run_id=scope.external_run_id,
            internal_run_id=scope.internal_run_id,
            owner_user_id=scope.owner_user_id,
            thread_id=scope.thread_id,
            sandbox_id=scope.sandbox_id,
            daytona_session_id=daytona_session_id,
            mutation_sequence=mutation_sequence,
            is_verification=_verification,
            kind="patch" if patch is not None else "verify" if _verification else "terminal",
            attempt_no=scope.attempt_no,
            lease_epoch=scope.lease_epoch,
            operation_receipt=patch_receipt,
            lease=scope.lease,
        )
        await self._check_fence(scope, execution_id)
        if patch is not None:
            try:
                assert patch_changes is not None
                applied = await asyncio.to_thread(
                    self.service.apply_changes, scope.thread_id, patch_changes
                )
                result = {**applied, "ok": True, "message": "补丁已应用。"}
                await self._check_fence(scope, execution_id)
                execution = await self.repository.update_execution(
                    execution_id,
                    status="completed",
                    output=str(result["message"]),
                    exit_code=0,
                )
                return {**self._public_execution(execution), **result, "intercepted_tool": "patch"}
            except Exception as error:
                message = (
                    str(error)
                    if isinstance(error, (CodingRepositoryError, WorkspaceError))
                    else "补丁执行失败。"
                )
                execution = await self.repository.update_execution(
                    execution_id,
                    status="failed",
                    output=message,
                    exit_code=1,
                )
                return {
                    **self._public_execution(execution),
                    "ok": False,
                    "code": "execution_failed",
                    "message": message,
                    "intercepted_tool": "patch",
                }

        assert terminal_runtime is not None
        protected_command = shlex.join(
            [
                "python3",
                "-I",
                "-B",
                terminal_runtime,
                "--write-root",
                WORKSPACE_ROOT,
                "--write-root",
                "/tmp",
                "--write-root",
                "/home/daytona/.cache",
                "--write-root",
                "/home/daytona/.config",
                "--write-root",
                "/dev/null",
                "--shell-command",
                command,
            ]
        )
        managed_command = self._managed_command(protected_command, workdir, timeout, pty)
        try:
            async for sandbox in self._sandbox(scope):
                session_id, command_id, _value = await self.workspace._start_managed_session(
                    sandbox.process,
                    scope.thread_id,
                    SessionExecuteRequest(
                        command=managed_command,
                        run_async=True,
                        suppress_input_echo=pty,
                    ),
                    session_id=daytona_session_id,
                )
                assert session_id == daytona_session_id
                await self._check_fence(scope, execution_id)
                execution = await self.repository.update_execution(
                    execution_id,
                    status="running",
                    command_id=command_id,
                )
                result = await self._read_remote(
                    sandbox.process,
                    execution,
                    wait_ms=0 if background else 30_000,
                )
                execution = await self._persist_result(sandbox.process, execution, result)
                await self._check_fence(scope, execution_id)
                if deferred_mutation:
                    execution = await self._record_terminal_mutation(
                        scope, execution, fingerprint_before
                    )
                return self._public_execution(execution)
        except Exception as error:
            current = await self.repository.get_execution(execution_id)
            if current is not None and current.status not in TERMINAL_EXECUTION_STATUSES:
                status = (
                    "lost"
                    if isinstance(error, (DaytonaNotFoundError, WorkspaceProcessNotFound))
                    else "failed"
                )
                try:
                    message = (
                        "Daytona 执行会话已丢失。"
                        if status == "lost"
                        else "命令启动或输出读取失败。"
                    )
                    current = await self.repository.update_execution(
                        execution_id,
                        status=status,
                        output=message,
                        exit_code=1 if status == "failed" else None,
                        expected_status=current.status,
                    )
                except CodingRepositoryError as conflict:
                    if conflict.code != "execution_cas_conflict":
                        raise
                    current = await self.repository.get_execution(execution_id)
                    assert current is not None
                if current.command_id is not None:
                    try:
                        async for sandbox in self._sandbox(scope):
                            await sandbox.process.delete_session(current.daytona_session_id)
                    except (CodingRepositoryError, DaytonaNotFoundError, WorkspaceError):
                        pass
            assert current is not None
            if deferred_mutation and current.mutation_sequence == scope.task.mutation_sequence:
                current = await self._record_terminal_mutation(scope, current, fingerprint_before)
            if current.status not in {"failed", "lost"}:
                return self._public_execution(current, cached=True)
            code = "execution_lost" if current.status == "lost" else "execution_failed"
            message = (
                "Daytona 执行会话已丢失。"
                if current.status == "lost"
                else "命令启动或输出读取失败。"
            )
            return {
                **self._public_execution(current),
                "ok": False,
                "code": code,
                "message": message,
            }
        raise AssertionError("Daytona 客户端上下文未返回 sandbox。")

    async def _record_terminal_mutation(
        self,
        scope: CodingTaskScope,
        execution: CodingExecution,
        fingerprint_before: str | None,
    ) -> CodingExecution:
        fingerprint_after: str | None = None
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            try:
                fingerprint_after = await self.service.aworkspace_fingerprint(scope.thread_id)
            except WorkspaceError:
                pass
        if fingerprint_before is not None and fingerprint_after == fingerprint_before:
            return execution
        await self.repository.record_execution_mutation(
            scope.external_run_id,
            execution.execution_id,
            execution.mutation_sequence,
            lease=scope.lease,
            internal_run_id=scope.internal_run_id,
        )
        updated = await self.repository.get_execution(execution.execution_id)
        assert updated is not None
        return updated

    async def _install_terminal_runtime(self, scope: CodingTaskScope) -> str:
        runtime_dir = f"{READONLY_RUNTIME_ROOT}/{READONLY_SCRIPT_RUNTIME_SHA256}"
        runtime_path = f"{runtime_dir}/readonly_script_runtime.py"
        cache_key = (scope.sandbox_id, READONLY_SCRIPT_RUNTIME_SHA256)
        cached = self._terminal_runtimes.get(cache_key)
        if cached is not None:
            self._terminal_runtimes.move_to_end(cache_key)
            return cached
        lock_key = f"readonly-runtime-install:{scope.sandbox_id}"
        async for sandbox in self._sandbox(scope):
            async with self.service.async_registry.locked(lock_key):
                cached = self._terminal_runtimes.get(cache_key)
                if cached is not None:
                    self._terminal_runtimes.move_to_end(cache_key)
                    return cached
                current = ""
                for part in runtime_dir.strip("/").split("/"):
                    current = f"{current}/{part}"
                    try:
                        info = await sandbox.fs.get_file_info(current)
                    except DaytonaNotFoundError:
                        await sandbox.fs.create_folder(current, "700")
                        continue
                    if self.service._is_symlink(info) or not bool(getattr(info, "is_dir", False)):
                        raise WorkspaceError("只读执行 runtime 安装目录不是安全普通目录。")
                try:
                    info = await sandbox.fs.get_file_info(runtime_path)
                except DaytonaNotFoundError:
                    await sandbox.fs.upload_file(READONLY_SCRIPT_RUNTIME, runtime_path)
                else:
                    if not self.service._is_regular_file(info):
                        raise WorkspaceError("只读执行 runtime 安装路径不是普通文件。")
                installed = await sandbox.fs.download_file(runtime_path)
                if hashlib.sha256(installed).hexdigest() != READONLY_SCRIPT_RUNTIME_SHA256:
                    raise WorkspaceError("只读执行 runtime 摘要验证失败。")
                await lock_sandbox_paths(
                    sandbox,
                    {runtime_path: "555", runtime_dir: "555"},
                )
                self._terminal_runtimes[cache_key] = runtime_path
                self._terminal_runtimes.move_to_end(cache_key)
                while len(self._terminal_runtimes) > MAX_TERMINAL_RUNTIME_CACHE_ENTRIES:
                    self._terminal_runtimes.popitem(last=False)
                return runtime_path
        raise AssertionError("Daytona 客户端上下文未返回 sandbox。")

    async def poll(
        self,
        execution_id: str,
        run_context: RunContext | None,
        *,
        wait_ms: int = 0,
        _scope: CodingTaskScope | None = None,
    ) -> dict[str, Any]:
        scope, execution = await self._scoped_execution(execution_id, run_context, _scope)
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return self._public_execution(execution, cached=True)
        if execution.command_id is None:
            return self._public_execution(execution)
        try:
            async for sandbox in self._sandbox(scope):
                result = await self._read_remote(sandbox.process, execution, wait_ms=wait_ms)
                updated = await self._persist_result(sandbox.process, execution, result)
                return self._public_execution(updated)
        except (DaytonaNotFoundError, WorkspaceProcessNotFound):
            latest = await self.repository.get_execution(execution_id)
            if latest is not None and latest.status in TERMINAL_EXECUTION_STATUSES:
                return self._public_execution(latest, cached=True)
            try:
                lost = await self.repository.update_execution(
                    execution_id,
                    status="lost",
                    expected_status=execution.status,
                )
            except CodingRepositoryError as error:
                if error.code != "execution_cas_conflict":
                    raise
                latest_execution = await self.repository.get_execution(execution_id)
                assert latest_execution is not None
                lost = latest_execution
            return {**self._public_execution(lost), "code": "execution_lost"}
        raise AssertionError("Daytona 客户端上下文未返回 sandbox。")

    async def process(
        self,
        action: str,
        execution_id: str | None,
        data: str,
        timeout: int,
        run_context: RunContext | None,
        *,
        _scope: CodingTaskScope | None = None,
    ) -> dict[str, Any]:
        scope = _scope or await self.scope(run_context)
        if action == "list":
            executions = await self.repository.list_executions(scope.external_run_id)
            return {
                "processes": [
                    self._public_execution(execution)
                    for execution in executions
                    if execution.kind == "terminal"
                    if execution.owner_user_id == scope.owner_user_id
                    and execution.thread_id == scope.thread_id
                    and execution.sandbox_id == scope.sandbox_id
                ]
            }
        if action not in {"poll", "wait", "kill", "write", "submit"}:
            raise WorkspaceError("process action 只支持 list、poll、wait、kill、write 或 submit。")
        if not isinstance(execution_id, str) or not execution_id:
            raise WorkspaceError("process 操作必须提供 terminal 返回的 session_id。")
        if action == "poll":
            return await self.poll(execution_id, run_context, _scope=scope)
        if action == "wait":
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, int)
                or not 1 <= timeout <= 86_400
            ):
                raise WorkspaceError("process wait timeout 必须是 1 至 86400 之间的整数秒。")
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                remaining = max(0.0, deadline - asyncio.get_running_loop().time())
                result = await self.poll(
                    execution_id,
                    run_context,
                    wait_ms=min(30_000, int(remaining * 1000)),
                    _scope=scope,
                )
                if result["status"] in TERMINAL_EXECUTION_STATUSES or remaining <= 0:
                    return result
        scope, execution = await self._scoped_execution(execution_id, run_context, scope)
        if action == "kill":
            if execution.status in TERMINAL_EXECUTION_STATUSES:
                return self._public_execution(execution, cached=True)
            remote_process = None
            async for sandbox in self._sandbox(scope):
                remote_process = sandbox.process
            try:
                terminated = await self.repository.update_execution(
                    execution_id,
                    status="terminated",
                    expected_status=execution.status,
                )
            except CodingRepositoryError as error:
                if error.code != "execution_cas_conflict":
                    raise
                latest_execution = await self.repository.get_execution(execution_id)
                assert latest_execution is not None
                terminated = latest_execution
            try:
                assert remote_process is not None
                await remote_process.delete_session(execution.daytona_session_id)
            except DaytonaNotFoundError:
                pass
            return self._public_execution(terminated)

        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return {
                **self._public_execution(execution, cached=True),
                "code": "execution_terminal",
                "message": "执行已结束，不能继续写入。",
            }
        if not isinstance(data, str) or len(data.encode("utf-8")) > MAX_PROCESS_INPUT_BYTES:
            raise WorkspaceError("process 输入必须是不超过 8 KiB 的字符串。")
        if execution.command_id is None:
            raise WorkspaceError("执行尚未创建远端命令，不能写入。")
        payload = data if action == "write" else f"{data}\n"
        mutation_sequence = await self.repository.increment_mutation(
            scope.external_run_id,
            lease=scope.lease,
            internal_run_id=scope.internal_run_id,
        )
        operation_id = uuid.uuid4().hex
        await self.repository.reserve_execution(
            execution_id=operation_id,
            external_run_id=scope.external_run_id,
            internal_run_id=scope.internal_run_id,
            owner_user_id=scope.owner_user_id,
            thread_id=scope.thread_id,
            sandbox_id=scope.sandbox_id,
            daytona_session_id=f"process-input-{operation_id}",
            mutation_sequence=mutation_sequence,
            kind=f"process_{action}",
            attempt_no=scope.attempt_no,
            lease_epoch=scope.lease_epoch,
            operation_receipt={
                "target_execution_id": execution_id,
                "input_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "input_bytes": len(payload.encode()),
            },
            lease=scope.lease,
        )
        await self._check_fence(scope, operation_id)
        try:
            async for sandbox in self._sandbox(scope):
                await self.workspace._managed_command(
                    sandbox.process,
                    execution.daytona_session_id,
                    execution.command_id,
                )
                await sandbox.process.send_session_command_input(
                    execution.daytona_session_id,
                    execution.command_id,
                    payload,
                )
                await self._check_fence(scope, operation_id)
                await self.repository.update_execution(
                    operation_id,
                    status="completed",
                    exit_code=0,
                )
                return await self.poll(execution_id, run_context)
        except (DaytonaNotFoundError, WorkspaceProcessNotFound):
            await self.repository.update_execution(operation_id, status="lost")
            latest = await self.repository.get_execution(execution_id)
            if latest is not None and latest.status in TERMINAL_EXECUTION_STATUSES:
                return self._public_execution(latest, cached=True)
            try:
                lost = await self.repository.update_execution(
                    execution_id,
                    status="lost",
                    expected_status=execution.status,
                )
            except CodingRepositoryError as error:
                if error.code != "execution_cas_conflict":
                    raise
                latest_execution = await self.repository.get_execution(execution_id)
                assert latest_execution is not None
                lost = latest_execution
            return {**self._public_execution(lost), "code": "execution_lost"}
        raise AssertionError("Daytona 客户端上下文未返回 sandbox。")

    def apply_patch_sync(self, scope: CodingTaskScope, patch: str) -> dict[str, Any]:
        changes = build_workspace_changes(self.service, scope.thread_id, patch)
        result = self.service.apply_changes(scope.thread_id, changes)
        return {**result, "ok": True, "message": "补丁已应用。"}

    @staticmethod
    def _reject_writable_skill_script_copy(
        changes: list[dict[str, Any]], run_context: RunContext | None
    ) -> None:
        state = (
            run_context.session_state
            if run_context is not None and isinstance(run_context.session_state, dict)
            else {}
        )
        receipts = state.get(CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY)
        if not isinstance(receipts, dict):
            return
        script_digests = {
            receipt.get("sha256")
            for receipt in receipts.values()
            if isinstance(receipt, dict) and isinstance(receipt.get("sha256"), str)
        }
        for change in changes:
            content = change.get("content")
            if not isinstance(content, str):
                continue
            if hashlib.sha256(content.encode("utf-8")).hexdigest() in script_digests:
                raise WorkspaceError(
                    "Skill 脚本只能使用 get_skill_script 返回的 readonly_path，"
                    "不能在项目目录创建可写副本。"
                )

    @staticmethod
    def _patch_receipt(changes: list[dict[str, Any]]) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        for change in changes:
            operation = change["operation"]
            content = change.get("content")
            after_sha = (
                hashlib.sha256(content.encode("utf-8")).hexdigest()
                if isinstance(content, str)
                else None
            )
            files.append(
                {
                    "path": change["path"],
                    "before_sha256": change.get("expected_sha256"),
                    "after_sha256": None if operation in {"delete", "move"} else after_sha,
                }
            )
            if operation == "move":
                files.append(
                    {
                        "path": change["destination"],
                        "before_sha256": None,
                        "after_sha256": change.get("expected_sha256"),
                    }
                )
        return {"files": files}

    async def patch(
        self,
        mode: str,
        path: str | None,
        old_string: str | None,
        new_string: str | None,
        replace_all: bool,
        patch: str | None,
        run_context: RunContext | None,
        *,
        content: str | None = None,
        expected_sha256: str | None = None,
        _scope: CodingTaskScope | None = None,
    ) -> dict[str, Any]:
        scope = _scope or await self.scope(run_context)
        if mode == "patch":
            if not isinstance(patch, str) or not patch.strip():
                raise WorkspaceError("patch 模式必须提供完整补丁。")
            changes = await asyncio.to_thread(
                build_workspace_changes, self.service, scope.thread_id, patch
            )
        elif mode == "replace":
            if not isinstance(path, str) or not isinstance(old_string, str) or not old_string:
                raise WorkspaceError("replace 模式必须提供 path 和非空 old_string。")
            if not isinstance(new_string, str) or not isinstance(replace_all, bool):
                raise WorkspaceError("replace 模式参数无效。")

            def replacement() -> tuple[list[dict[str, Any]], int]:
                content, _mime = self.service.file_bytes(scope.thread_id, path)
                try:
                    original = content.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise WorkspaceError("replace 模式只支持 UTF-8 文本文件。") from error
                count = original.count(old_string)
                if count == 0:
                    raise WorkspaceError("old_string 在目标文件中不存在。")
                if count != 1 and not replace_all:
                    raise WorkspaceError(
                        "old_string 在目标文件中不唯一；请扩大上下文或启用 replace_all。"
                    )
                updated = original.replace(old_string, new_string, -1 if replace_all else 1)
                return (
                    [
                        {
                            "operation": "update",
                            "path": path,
                            "content": updated,
                            "expected_sha256": hashlib.sha256(content).hexdigest(),
                        }
                    ],
                    count if replace_all else 1,
                )

            changes, replacements = await asyncio.to_thread(replacement)
        elif mode == "create":
            if not isinstance(path, str) or not isinstance(content, str):
                raise WorkspaceError("create 模式必须提供 path 和 content。")
            changes = [{"operation": "create", "path": path, "content": content}]
        elif mode == "overwrite":
            if not isinstance(path, str) or not isinstance(content, str):
                raise WorkspaceError("overwrite 模式必须提供 path 和 content。")
            if expected_sha256 is None:
                raise WorkspaceError("overwrite 模式必须提供 expected_sha256。")
            changes = [
                {
                    "operation": "update",
                    "path": path,
                    "content": content,
                    "expected_sha256": self.service._validate_patch_hash(expected_sha256),
                }
            ]
        else:
            raise WorkspaceError("patch mode 只支持 create、overwrite、replace 或 patch。")
        self._reject_writable_skill_script_copy(changes, run_context)
        mutation_sequence = await self.repository.increment_mutation(
            scope.external_run_id,
            lease=scope.lease,
            internal_run_id=scope.internal_run_id,
        )
        execution_id = uuid.uuid4().hex
        receipt = self._patch_receipt(changes)
        patch_session_id = (
            "patch-"
            + hashlib.sha256(
                f"{scope.external_run_id}:{scope.attempt_no}:{mutation_sequence}".encode()
            ).hexdigest()[:32]
        )
        await self.repository.reserve_execution(
            execution_id=execution_id,
            external_run_id=scope.external_run_id,
            internal_run_id=scope.internal_run_id,
            owner_user_id=scope.owner_user_id,
            thread_id=scope.thread_id,
            sandbox_id=scope.sandbox_id,
            daytona_session_id=patch_session_id,
            mutation_sequence=mutation_sequence,
            kind="patch",
            attempt_no=scope.attempt_no,
            lease_epoch=scope.lease_epoch,
            operation_receipt=receipt,
            lease=scope.lease,
        )
        await self._check_fence(scope, execution_id)
        applied = False
        try:
            result = await asyncio.to_thread(self.service.apply_changes, scope.thread_id, changes)
            applied = True
            await self._check_fence(scope, execution_id)
            await self.repository.update_execution(
                execution_id,
                status="completed",
                exit_code=0,
                operation_receipt=receipt,
            )
        except Exception:
            if not applied:
                await self.repository.update_execution(
                    execution_id,
                    status="failed",
                    exit_code=1,
                    operation_receipt=receipt,
                )
            raise
        return {
            **result,
            "ok": True,
            "execution_id": execution_id,
            "mutation_sequence": mutation_sequence,
            **({"replacements": replacements} if mode == "replace" else {}),
        }

    async def verify(
        self,
        command: str | None,
        artifact_paths: list[str] | None,
        run_context: RunContext | None,
        *,
        validator_id: str | None = None,
        timeout: int = DEFAULT_TERMINAL_TIMEOUT,
        _scope: CodingTaskScope | None = None,
    ) -> dict[str, Any]:
        scope = _scope or await self.scope(run_context)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= MAX_BACKGROUND_EXECUTION_TIMEOUT
        ):
            raise WorkspaceError("verify timeout 必须是 1 至 86400 之间的整数秒。")
        command_mode = isinstance(command, str) and bool(command)
        validator_mode = isinstance(validator_id, str) and bool(validator_id)
        if command_mode == validator_mode:
            raise WorkspaceError("verify 必须且只能提供 command 或 validator_id。")
        if command is not None and not command_mode:
            raise WorkspaceError("verify command 必须是非空字符串。")
        if validator_id is not None and not validator_mode:
            raise WorkspaceError("verify validator_id 必须是非空字符串。")
        if not isinstance(artifact_paths, list) or any(
            not isinstance(path, str) or not path for path in artifact_paths
        ):
            raise WorkspaceError("verify artifact_paths 必须是工作区相对路径数组。")
        if len(artifact_paths) > MAX_FINISH_ARTIFACTS or len(set(artifact_paths)) != len(
            artifact_paths
        ):
            raise WorkspaceError("verify artifact_paths 不能超过 50 项且不能重复。")
        if validator_mode:
            assert validator_id is not None
            return await self._verify_validator(validator_id, artifact_paths, run_context, scope)
        assert command is not None
        if isinstance(command, str) and _extract_apply_patch_command(command) is not None:
            raise WorkspaceError("verify 不接受 apply_patch；请提交真实验证命令。")
        provenance_error = await self._skill_script_verification_error(command, run_context, scope)
        if provenance_error is not None:
            return provenance_error
        result = await self.terminal(
            command,
            background=False,
            timeout=timeout,
            run_context=run_context,
            _verification=True,
            _artifact_paths=artifact_paths,
            _scope=scope,
        )
        if result["status"] not in TERMINAL_EXECUTION_STATUSES:
            result = await self.process(
                "wait",
                result["execution_id"],
                "",
                timeout,
                run_context,
                _scope=scope,
            )
        artifacts = (
            await self.service.abatch_hash_files(scope.thread_id, artifact_paths)
            if artifact_paths
            else []
        )
        receipt = {
            "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
            "exit_code": result.get("exit_code"),
            "mutation_sequence": result["mutation_sequence"],
            "artifacts": artifacts,
        }
        output = str(result.get("output") or "")
        output_error = _deterministic_output_error(output)
        receipt["valid"] = bool(
            result.get("status") == "completed"
            and result.get("exit_code") == 0
            and output_error is None
        )
        if output_error is not None:
            failure_code, diagnostics = output_error
            receipt["failure_code"] = failure_code
            receipt["diagnostics"] = diagnostics
        execution = await self.repository.update_execution(
            result["execution_id"], operation_receipt=receipt
        )
        public = {**self._public_execution(execution), "artifacts": artifacts}
        if output_error is not None:
            public.update(
                {
                    "ok": False,
                    "code": "verification_output_error",
                    "message": "验证输出包含确定性的命令执行错误。",
                    "details": {
                        "failureCode": failure_code,
                        "diagnostics": diagnostics,
                    },
                    "requiredActions": ["安装或替换缺失命令后重新运行验证。"],
                    "retryable": True,
                }
            )
        return public

    async def _verify_validator(
        self,
        validator_id: str,
        artifact_paths: list[str],
        run_context: RunContext | None,
        scope: CodingTaskScope | None = None,
    ) -> dict[str, Any]:
        scope = scope or await self.scope(run_context)
        task = await self.repository.get_task(scope.external_run_id)
        if task is None:
            raise CodingRepositoryError("task_not_found", "编码任务不存在。")
        contract = task.acceptance_contract
        if contract is None:
            return self._verification_error(
                "verification_validator_not_required",
                "当前任务没有验收契约，不能运行服务端 validator。",
                required_actions=["使用 command 模式执行通用验证。"],
            )
        try:
            normalized_contract = self.validator_registry.validate_contract(contract)
            validator = self.validator_registry.require(validator_id)
        except SkillAcceptanceError:
            return self._verification_error(
                "verification_validator_unavailable",
                "任务验收契约引用的服务端 validator 不可用。",
                details={"validatorId": validator_id},
                required_actions=["恢复任务契约绑定的服务端 Skill validator。"],
            )
        requirements = [
            requirement
            for requirement in normalized_contract["requirements"]
            if requirement["validatorId"] == validator_id
        ]
        if not requirements:
            return self._verification_error(
                "verification_validator_not_required",
                "validator_id 不属于当前任务验收契约。",
                details={"validatorId": validator_id},
                required_actions=["使用任务验收契约声明的 validator_id。"],
            )

        normalized_paths = [
            WorkspaceService.normalize_path(path, allow_root=False)[0] for path in artifact_paths
        ]
        artifacts = (
            await self.service.abatch_hash_files(scope.thread_id, normalized_paths)
            if normalized_paths
            else []
        )
        missing_paths = [item["path"] for item in artifacts if item.get("missing")]
        if missing_paths:
            return self._verification_error(
                "verification_artifact_missing",
                "validator 所需产物不存在。",
                details={"missingPaths": missing_paths[:MAX_FINISH_ARTIFACTS]},
                required_actions=["创建缺失产物后重新运行 validator_id。"],
            )
        uncovered_paths = [
            path
            for path in normalized_paths
            if not any(
                fnmatch.fnmatchcase(path, pattern)
                for requirement in requirements
                for pattern in requirement["artifactPatterns"]
            )
        ]
        missing_patterns = [
            {"requirementId": requirement["id"], "pattern": pattern}
            for requirement in requirements
            for pattern in requirement["artifactPatterns"]
            if not any(fnmatch.fnmatchcase(path, pattern) for path in normalized_paths)
        ]
        if uncovered_paths or missing_patterns:
            return self._verification_error(
                "verification_artifact_contract_mismatch",
                "artifact_paths 未满足任务验收契约的固定产物规则。",
                details={
                    "uncoveredPaths": uncovered_paths[:MAX_FINISH_ARTIFACTS],
                    "missingPatterns": missing_patterns[:MAX_FINISH_ARTIFACTS],
                },
                required_actions=["按契约 artifactPatterns 提交完整且无额外项的 artifact_paths。"],
            )

        request = {
            "version": 1,
            "validatorId": validator_id,
            "workspaceRoot": WORKSPACE_ROOT,
            "mutationSequence": task.mutation_sequence,
            "requirements": [
                {
                    "id": requirement["id"],
                    "parameters": requirement["parameters"],
                    "artifactPatterns": requirement["artifactPatterns"],
                    "artifacts": [
                        {
                            **artifact,
                            "absolutePath": f"{WORKSPACE_ROOT}/{artifact['path']}",
                        }
                        for artifact in artifacts
                        if any(
                            fnmatch.fnmatchcase(artifact["path"], pattern)
                            for pattern in requirement["artifactPatterns"]
                        )
                    ],
                }
                for requirement in requirements
            ],
        }
        request_bytes = json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(request_bytes) > MAX_VALIDATOR_REQUEST_BYTES:
            return self._verification_error(
                "verification_validator_request_too_large",
                "validator JSON 请求超过 256 KiB。",
                required_actions=["减少契约参数或产物数量后重新创建任务。"],
                retryable=False,
            )

        installed = await self._install_validator(scope, validator, request_bytes)
        command = shlex.join(
            [
                "python3",
                "-I",
                "-B",
                installed.runtime_path,
                "--write-root",
                WORKSPACE_ROOT,
                "--write-root",
                "/tmp",
                installed.script_path,
                installed.request_path,
            ]
        )
        scripts_unchanged = False
        try:
            result = await self.terminal(
                command,
                background=False,
                timeout=validator.timeout,
                run_context=run_context,
                _verification=True,
                _artifact_paths=artifact_paths,
                _read_only=True,
                _scope=scope,
            )
            if result["status"] not in TERMINAL_EXECUTION_STATUSES:
                result = await self.process(
                    "wait",
                    result["execution_id"],
                    "",
                    validator.timeout,
                    run_context,
                    _scope=scope,
                )
        finally:
            try:
                scripts_unchanged = await self._validator_scripts_unchanged(
                    scope, installed, validator.script_sha256
                )
            finally:
                await self._delete_validator_install(scope, installed.directory)

        if not scripts_unchanged:
            receipt = {
                "validator_id": validator_id,
                "validator_sha256": validator.script_sha256,
                "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
                "exit_code": result.get("exit_code"),
                "mutation_sequence": result["mutation_sequence"],
                "timeout": validator.timeout,
                "artifacts": artifacts,
                "valid": False,
                "failure_code": "validator_script_modified",
            }
            execution = await self.repository.update_execution(
                result["execution_id"], operation_receipt=receipt
            )
            return {
                **self._public_execution(execution),
                **self._verification_error(
                    "verification_validator_script_modified",
                    "服务端 validator 或只读执行 runtime 的摘要发生变化。",
                    required_actions=["修复 Daytona 只读脚本保护后重新验证。"],
                    retryable=False,
                ),
            }

        current_artifacts = (
            await self.service.abatch_hash_files(scope.thread_id, normalized_paths)
            if normalized_paths
            else []
        )
        base_receipt = {
            "validator_id": validator_id,
            "validator_sha256": validator.script_sha256,
            "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
            "exit_code": result.get("exit_code"),
            "mutation_sequence": result["mutation_sequence"],
            "timeout": validator.timeout,
            "artifacts": artifacts,
        }
        if current_artifacts != artifacts:
            await self.repository.increment_mutation(
                scope.external_run_id,
                lease=scope.lease,
                internal_run_id=scope.internal_run_id,
            )
            receipt = {
                **base_receipt,
                "valid": False,
                "failure_code": "validator_artifact_changed",
            }
            execution = await self.repository.update_execution(
                result["execution_id"], operation_receipt=receipt
            )
            return {
                **self._public_execution(execution),
                **self._verification_error(
                    "verification_validator_mutated_artifact",
                    "服务端 validator 修改了受检产物，证据已拒绝。",
                    required_actions=["修复只读 validator 后在当前 mutation 重新验证。"],
                    retryable=False,
                ),
            }
        if result.get("status") != "completed" or result.get("exit_code") != 0:
            receipt = {
                **base_receipt,
                "valid": False,
                "failure_code": "validator_execution_failed",
            }
            execution = await self.repository.update_execution(
                result["execution_id"], operation_receipt=receipt
            )
            return {
                **self._public_execution(execution),
                **self._verification_error(
                    "verification_validator_failed",
                    "服务端 validator 执行失败。",
                    required_actions=["根据 validator 输出修复产物后重新验证。"],
                ),
            }

        output = str(result.get("output") or "")
        try:
            validator_results = self._parse_validator_result(output, requirements)
        except ValueError:
            receipt = {
                **base_receipt,
                "valid": False,
                "failure_code": "validator_result_invalid",
            }
            execution = await self.repository.update_execution(
                result["execution_id"], operation_receipt=receipt
            )
            return {
                **self._public_execution(execution),
                **self._verification_error(
                    "verification_validator_result_invalid",
                    "服务端 validator 未返回严格且有界的 JSON 结果。",
                    required_actions=["修复服务端 Skill validator 的 JSON 输出协议。"],
                    retryable=False,
                ),
            }
        acceptance = {
            "version": 1,
            "validatorId": validator_id,
            "validatorSha256": validator.script_sha256,
            "mutationSequence": result["mutation_sequence"],
            "artifacts": artifacts,
            "requirements": validator_results,
        }
        receipt = {
            **base_receipt,
            "result_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "valid": True,
            "acceptance": acceptance,
        }
        execution = await self.repository.update_execution(
            result["execution_id"], operation_receipt=receipt
        )
        passed = all(item["passed"] is True for item in validator_results)
        failed_requirements = []
        for item in validator_results:
            if item["passed"] is True:
                continue
            message = item.get("message")
            failed_requirements.append(
                {
                    "id": item["id"],
                    "message": (
                        message if isinstance(message, str) and message else "requirement 未通过。"
                    ),
                    **({"details": item["details"]} if "details" in item else {}),
                }
            )
        passed_requirements = [
            {"id": item["id"]} for item in validator_results if item["passed"] is True
        ]
        return {
            **self._public_execution(execution),
            "ok": passed,
            "acceptance": acceptance,
            **(
                {}
                if passed
                else {
                    "code": "verification_acceptance_failed",
                    "message": "validator 已执行，但至少一个 requirement 未通过。",
                    "failedRequirements": failed_requirements,
                    "passedRequirements": passed_requirements,
                    "requiredActions": [
                        "仅修复 failedRequirements 列出的失败能力；"
                        "保持 passedRequirements 已通过行为不变。",
                        "先运行与失败项对应的公开测试或局部验证，再重新运行 "
                        f"validator_id={validator_id}。",
                    ],
                    "retryable": True,
                }
            ),
        }

    async def _install_validator(
        self,
        scope: CodingTaskScope,
        validator: SkillValidator,
        request: bytes,
    ) -> _InstalledValidator:
        validator_dir = f"{VALIDATOR_ROOT}/{validator.install_digest}/{uuid.uuid4().hex}"
        request_path = f"{validator_dir}/request.json"
        script_path = f"{validator_dir}/validator.py"
        runtime_path = f"{validator_dir}/readonly_script_runtime.py"
        async for sandbox in self._sandbox(scope):
            current = ""
            for part in validator_dir.strip("/").split("/"):
                current = f"{current}/{part}"
                try:
                    info = await sandbox.fs.get_file_info(current)
                except DaytonaNotFoundError:
                    await sandbox.fs.create_folder(current, "755")
                    continue
                if self.service._is_symlink(info) or not bool(getattr(info, "is_dir", False)):
                    raise WorkspaceError("validator 安装目录不是安全普通目录。")
            await sandbox.fs.upload_file(validator.script_content, script_path)
            await sandbox.fs.upload_file(READONLY_SCRIPT_RUNTIME, runtime_path)
            await sandbox.fs.upload_file(request, request_path)
            for path, digest in (
                (script_path, validator.script_sha256),
                (runtime_path, READONLY_SCRIPT_RUNTIME_SHA256),
            ):
                content = await sandbox.fs.download_file(path)
                if hashlib.sha256(content).hexdigest() != digest:
                    raise WorkspaceError("validator 只读脚本摘要验证失败。")
            await lock_sandbox_paths(
                sandbox,
                {
                    script_path: "555",
                    runtime_path: "555",
                    request_path: "444",
                    validator_dir: "555",
                },
            )
        return _InstalledValidator(
            directory=validator_dir,
            script_path=script_path,
            request_path=request_path,
            runtime_path=runtime_path,
            runtime_sha256=READONLY_SCRIPT_RUNTIME_SHA256,
        )

    async def _validator_scripts_unchanged(
        self,
        scope: CodingTaskScope,
        installed: _InstalledValidator,
        script_sha256: str,
    ) -> bool:
        try:
            async for sandbox in self._sandbox(scope):
                for path, digest in (
                    (installed.script_path, script_sha256),
                    (installed.runtime_path, installed.runtime_sha256),
                ):
                    content = await sandbox.fs.download_file(path)
                    if hashlib.sha256(content).hexdigest() != digest:
                        return False
                return True
        except (CodingRepositoryError, DaytonaNotFoundError, WorkspaceError):
            return False
        return False

    async def _delete_validator_install(self, scope: CodingTaskScope, validator_dir: str) -> None:
        if not validator_dir.startswith(f"{VALIDATOR_ROOT}/"):
            return
        try:
            async for sandbox in self._sandbox(scope):
                result = await sandbox.process.exec(
                    shlex.join(["sudo", "rm", "-rf", "--", validator_dir]),
                    timeout=30,
                )
                if getattr(result, "exit_code", None) != 0:
                    raise WorkspaceError("validator 临时目录清理失败。")
                try:
                    await sandbox.fs.delete_file(validator_dir, recursive=True)
                except DaytonaNotFoundError:
                    pass
        except (CodingRepositoryError, DaytonaNotFoundError, WorkspaceError):
            pass

    @staticmethod
    def _parse_validator_result(
        output: str,
        requirements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        encoded = output.encode("utf-8")
        if not encoded or len(encoded) > MAX_VALIDATOR_RESULT_BYTES:
            raise ValueError("validator_result_size")

        def reject_constant(_value: str) -> None:
            raise ValueError("validator_result_constant")

        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("validator_result_duplicate_key")
                value[key] = item
            return value

        try:
            parsed = json.loads(
                output,
                parse_constant=reject_constant,
                object_pairs_hook=unique_object,
            )
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("validator_result_json") from error
        if not isinstance(parsed, dict) or set(parsed) != {"version", "requirements"}:
            raise ValueError("validator_result_fields")
        if isinstance(parsed["version"], bool) or parsed["version"] != 1:
            raise ValueError("validator_result_version")
        raw_results = parsed["requirements"]
        if not isinstance(raw_results, list) or len(raw_results) != len(requirements):
            raise ValueError("validator_result_requirements")
        results_by_id: dict[str, dict[str, Any]] = {}
        for raw in raw_results:
            if (
                not isinstance(raw, dict)
                or not {"id", "passed"}.issubset(raw)
                or not set(raw).issubset({"id", "passed", "message", "details"})
            ):
                raise ValueError("validator_result_requirement_fields")
            requirement_id = raw["id"]
            if not isinstance(requirement_id, str) or requirement_id in results_by_id:
                raise ValueError("validator_result_requirement_id")
            if not isinstance(raw["passed"], bool):
                raise ValueError("validator_result_passed")
            message = raw.get("message")
            if message is not None and (not isinstance(message, str) or len(message) > 512):
                raise ValueError("validator_result_message")
            details = raw.get("details")
            if details is not None:
                if not isinstance(details, dict):
                    raise ValueError("validator_result_details")
                try:
                    details_bytes = json.dumps(
                        details,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                except (TypeError, ValueError) as error:
                    raise ValueError("validator_result_details") from error
                if len(details_bytes) > MAX_VALIDATOR_DETAIL_BYTES:
                    raise ValueError("validator_result_details_size")
            results_by_id[requirement_id] = raw
        if set(results_by_id) != {requirement["id"] for requirement in requirements}:
            raise ValueError("validator_result_requirement_set")
        return [
            {
                "id": requirement["id"],
                "requirementDigest": requirement_digest(requirement),
                "passed": results_by_id[requirement["id"]]["passed"],
                **(
                    {"message": results_by_id[requirement["id"]]["message"]}
                    if "message" in results_by_id[requirement["id"]]
                    else {}
                ),
                **(
                    {"details": results_by_id[requirement["id"]]["details"]}
                    if "details" in results_by_id[requirement["id"]]
                    else {}
                ),
            }
            for requirement in requirements
        ]

    @staticmethod
    def _verification_error(
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        required_actions: list[str] | None = None,
        retryable: bool = True,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "rejected",
            "code": code,
            "message": message,
            "details": details or {},
            "requiredActions": (required_actions or ["修复验证错误后重试 verify。"])[:10],
            "retryable": retryable,
        }

    async def _skill_script_verification_error(
        self,
        command: str,
        run_context: RunContext | None,
        scope: CodingTaskScope | None = None,
    ) -> dict[str, Any] | None:
        scope = scope or await self.scope(run_context)
        state = (
            run_context.session_state
            if run_context is not None and isinstance(run_context.session_state, dict)
            else {}
        )
        receipts = state.get(CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY)
        if not isinstance(receipts, dict) or not receipts:
            return None
        try:
            tokens = shlex.split(command)
        except ValueError:
            return None
        receipts_by_name: dict[str, list[dict[str, Any]]] = {}
        for receipt in receipts.values():
            if not isinstance(receipt, dict):
                continue
            script_path = receipt.get("path")
            expected_sha256 = receipt.get("sha256")
            if not isinstance(script_path, str) or not isinstance(expected_sha256, str):
                continue
            script_name = script_path.rsplit("/", 1)[-1]
            receipts_by_name.setdefault(script_name, []).append(receipt)
        for candidate in tokens:
            matching = receipts_by_name.get(candidate.rsplit("/", 1)[-1])
            if not matching:
                continue
            relative = candidate
            if relative.startswith(f"{WORKSPACE_ROOT}/"):
                relative = relative.removeprefix(f"{WORKSPACE_ROOT}/")
            try:
                content, _mime = await asyncio.to_thread(
                    self.service.file_bytes, scope.thread_id, relative
                )
            except (DaytonaNotFoundError, WorkspaceError):
                continue
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if any(receipt["sha256"] == actual_sha256 for receipt in matching):
                continue
            receipt = matching[-1]
            return {
                "ok": False,
                "status": "rejected",
                "code": "verification_skill_script_modified",
                "message": "验证命令引用的 Skill 脚本已被修改，未执行验证。",
                "details": {
                    "skill": receipt.get("skill"),
                    "skillScript": receipt["path"],
                    "workspacePath": relative,
                    "expectedSha256": receipt["sha256"],
                    "actualSha256": actual_sha256,
                },
                "requiredActions": [
                    "从 get_skill_script 返回的原始内容重新创建验证脚本。",
                    "确认脚本 SHA256 未变化后重新执行 verify。",
                ],
                "retryable": True,
            }
        return None

    async def finish_task(
        self,
        summary: str | None,
        artifact_paths: list[str] | None,
        verification_ids: list[str] | None,
        service_sessions: list[dict[str, str]],
        run_context: RunContext | None,
        finish_function: Function,
        *,
        _scope: CodingTaskScope | None = None,
    ) -> dict[str, Any]:
        scope = _scope or await self.scope(run_context)
        if isinstance(scope.task, TaskSnapshot) and scope.task.finish_receipt is not None:
            finish_function.stop_after_tool_call = True
            return {"ok": True, "status": "accepted", **scope.task.finish_receipt}
        state = (
            run_context.session_state
            if run_context and isinstance(run_context.session_state, dict)
            else {}
        )
        plan = state.get(AGENT_PLAN_STATE_KEY)
        steps = plan.get("plan") if isinstance(plan, dict) else []
        task = await self.repository.get_task(scope.external_run_id)
        assert task is not None
        executions = await self.repository.list_executions(scope.external_run_id)
        if verification_ids is None:
            current_verification = next(
                (
                    execution.execution_id
                    for execution in reversed(executions)
                    if execution.is_verification
                    and execution.status == "completed"
                    and execution.exit_code == 0
                    and execution.mutation_sequence == task.mutation_sequence
                ),
                None,
            )
            verification_ids = [current_verification] if current_verification is not None else []
        observation_fingerprint = self._finish_fingerprint(
            scope,
            task.mutation_sequence,
            plan,
            summary,
            artifact_paths,
            verification_ids,
            service_sessions,
            executions,
        )
        previous_failure = state.get(CODING_FINISH_FAILURE_STATE_KEY)
        if (
            isinstance(previous_failure, dict)
            and previous_failure.get("observationFingerprint", previous_failure.get("fingerprint"))
            == observation_fingerprint
        ):
            previous_details = previous_failure.get("details")
            return self._finish_no_progress(
                str(previous_failure.get("code") or "finish_rejected"),
                {
                    **(previous_details if isinstance(previous_details, dict) else {}),
                    "mutationSequence": task.mutation_sequence,
                    "attemptNo": scope.attempt_no,
                },
                list(previous_failure.get("requiredActions") or [])[:10],
            )

        execution_by_id = {execution.execution_id: execution for execution in executions}
        submitted_verification_ids = (
            verification_ids[:MAX_VERIFICATION_IDS] if isinstance(verification_ids, list) else []
        )
        verification_details = [
            {
                "executionId": value,
                "status": getattr(execution_by_id.get(value), "status", "missing")
                if isinstance(value, str)
                else "invalid",
                "exitCode": getattr(execution_by_id.get(value), "exit_code", None)
                if isinstance(value, str)
                else None,
                "mutationSequence": getattr(execution_by_id.get(value), "mutation_sequence", None)
                if isinstance(value, str)
                else None,
                "valid": (
                    (execution_by_id[value].operation_receipt or {}).get("valid", True)
                    if isinstance(value, str) and execution_by_id.get(value)
                    else False
                ),
                "current": bool(
                    isinstance(value, str)
                    and execution_by_id.get(value)
                    and execution_by_id[value].is_verification
                    and execution_by_id[value].status == "completed"
                    and execution_by_id[value].exit_code == 0
                    and (execution_by_id[value].operation_receipt or {}).get("valid", True)
                    is not False
                    and execution_by_id[value].mutation_sequence == task.mutation_sequence
                ),
            }
            for value in submitted_verification_ids
        ]
        active_process_details = [
            {"sessionId": execution.execution_id, "status": execution.status}
            for execution in executions
            if execution.status not in TERMINAL_EXECUTION_STATUSES
        ][:20]

        def reject(
            code: str,
            message: str,
            *,
            details: dict[str, Any] | None = None,
            required_actions: list[str] | None = None,
            progress_state: Any = None,
        ) -> dict[str, Any]:
            result = self._finish_error(
                code,
                message,
                details={
                    "mutationSequence": task.mutation_sequence,
                    "attemptNo": scope.attempt_no,
                    "verification": verification_details,
                    "activeProcesses": active_process_details,
                    **(details or {}),
                },
                required_actions=required_actions,
            )
            gate_fingerprint = self._finish_gate_fingerprint(
                scope,
                code,
                progress_state if progress_state is not None else details,
            )
            failure_state = {
                "fingerprint": observation_fingerprint,
                "observationFingerprint": observation_fingerprint,
                "gateFingerprint": gate_fingerprint,
                "code": code,
                "details": result["details"],
                "requiredActions": result["requiredActions"],
            }
            if (
                isinstance(previous_failure, dict)
                and previous_failure.get("gateFingerprint") == gate_fingerprint
            ):
                state[CODING_FINISH_FAILURE_STATE_KEY] = failure_state
                return self._finish_no_progress(
                    code,
                    result["details"],
                    result["requiredActions"],
                )
            state[CODING_FINISH_FAILURE_STATE_KEY] = failure_state
            return result

        if not isinstance(summary, str) or not summary.strip() or len(summary) > 4000:
            return reject(
                "finish_summary_invalid",
                "summary 必须是 1 至 4000 个字符。",
                required_actions=["提交 1 至 4000 个字符的非空 summary。"],
                progress_state={"summary": summary},
            )
        if (
            not isinstance(artifact_paths, list)
            or len(artifact_paths) > MAX_FINISH_ARTIFACTS
            or any(not isinstance(path, str) or not path for path in artifact_paths)
        ):
            return reject(
                "finish_artifacts_invalid",
                "artifact_paths 无效。",
                required_actions=["提交不超过 50 个非空工作区相对产物路径。"],
                progress_state={"artifactPaths": artifact_paths},
            )
        invalid_paths: list[str] = []
        for path in artifact_paths:
            try:
                WorkspaceService.normalize_path(path, allow_root=False)
            except WorkspaceError:
                invalid_paths.append(path)
        if invalid_paths:
            return reject(
                "finish_artifact_path_invalid",
                "artifact_paths 包含无效工作区路径。",
                details={"invalidPaths": invalid_paths[:MAX_FINISH_ARTIFACTS]},
                required_actions=["把 details.invalidPaths 改为工作区相对路径。"],
                progress_state={"invalidPaths": invalid_paths},
            )
        if not isinstance(service_sessions, list):
            return reject(
                "finish_services_invalid",
                "service_sessions 无效。",
                required_actions=["按声明 schema 提交 service_sessions。"],
                progress_state={"serviceSessions": service_sessions},
            )
        declared_services: dict[str, str] = {}
        for item in service_sessions:
            if (
                not isinstance(item, dict)
                or set(item) != {"session_id", "healthcheck_execution_id"}
                or not isinstance(item.get("session_id"), str)
                or not item["session_id"]
                or not isinstance(item.get("healthcheck_execution_id"), str)
                or not item["healthcheck_execution_id"]
                or item["session_id"] in declared_services
            ):
                return reject(
                    "finish_services_invalid",
                    "service_sessions 无效。",
                    required_actions=[
                        "为每个保留服务提交唯一 session_id 和健康检查 execution_id。"
                    ],
                    progress_state={"serviceSessions": service_sessions},
                )
            declared_services[item["session_id"]] = item["healthcheck_execution_id"]

        if isinstance(steps, list) and any(
            not isinstance(step, dict) or step.get("status") != "completed" for step in steps
        ):
            incomplete_steps = [
                str(step.get("step") or "未命名步骤") if isinstance(step, dict) else "无效步骤"
                for step in steps
                if not isinstance(step, dict) or step.get("status") != "completed"
            ][:20]
            return reject(
                "finish_plan_incomplete",
                "仍有计划步骤未完成。",
                details={"incompleteSteps": incomplete_steps},
                required_actions=[
                    "根据工作区证据更新计划：保留已完成步骤，只将下一真实未完成步骤标为 "
                    "in_progress；完成后再标为 completed，不得为通过验收虚报完成。"
                ],
                progress_state={"incompleteSteps": incomplete_steps},
            )
        artifacts: list[dict[str, Any]] = []
        try:
            async for _sandbox in self._sandbox(scope):
                pass
        except (CodingRepositoryError, WorkspaceError, DaytonaNotFoundError):
            return reject(
                "finish_sandbox_changed",
                "当前 Daytona 工作区与任务绑定不一致。",
                required_actions=["恢复任务绑定的 Daytona 工作区后重新验证。"],
                progress_state={"sandboxId": scope.sandbox_id},
            )
        artifacts = await self.service.abatch_hash_files(scope.thread_id, artifact_paths)
        missing_paths = [item["path"] for item in artifacts if item.get("missing")]
        if missing_paths:
            return reject(
                "finish_artifact_missing",
                "交付产物不存在或已发生变化。",
                details={"missingPaths": missing_paths[:MAX_FINISH_ARTIFACTS]},
                required_actions=[
                    "核对 details.missingPaths：若路径声明错误，下一次 finish_task 使用实际存在的 "
                    "artifact_paths；若确为必需产物，生成后调用 verify，再用实际存在路径重新提交。"
                ],
                progress_state={"missingPaths": missing_paths},
            )
        artifacts = [item for item in artifacts if not item.get("missing")]

        if (
            not isinstance(verification_ids, list)
            or not verification_ids
            or len(verification_ids) > MAX_VERIFICATION_IDS
        ):
            return reject(
                "finish_verification_missing",
                "至少需要一个验证执行回执。",
                required_actions=["在最后一次潜在修改后运行验证并提交 execution_id。"],
                progress_state={"verificationIds": verification_ids},
            )
        for execution_id in verification_ids:
            submitted_execution = (
                execution_by_id.get(execution_id) if isinstance(execution_id, str) else None
            )
            submitted_receipt = (
                submitted_execution.operation_receipt if submitted_execution is not None else None
            )
            if isinstance(submitted_receipt, dict) and submitted_receipt.get("valid") is False:
                return reject(
                    "finish_verification_failed",
                    "验证执行包含确定性的命令或输出错误。",
                    details={
                        "failureCode": submitted_receipt.get("failure_code"),
                        "diagnostics": submitted_receipt.get("diagnostics"),
                    },
                    required_actions=["修复验证错误，并在当前 mutation 上重新运行验证。"],
                    progress_state={
                        "mutationSequence": task.mutation_sequence,
                        "verification": verification_details,
                    },
                )
            if not isinstance(
                execution_id, str
            ) or not await self.repository.successful_verification(
                scope.external_run_id,
                execution_id,
                task.mutation_sequence,
            ):
                return reject(
                    "finish_verification_stale",
                    "验证未成功，或早于最后一次潜在修改。",
                    required_actions=[
                        "在当前 mutation sequence 上完成成功验证并提交其 execution_id。"
                    ],
                    progress_state={
                        "mutationSequence": task.mutation_sequence,
                        "verification": verification_details,
                    },
                )

        active = [
            execution
            for execution in executions
            if execution.status not in TERMINAL_EXECUTION_STATUSES
        ]
        active_ids = {execution.execution_id for execution in active}
        if active_ids != set(declared_services):
            return reject(
                "finish_process_active",
                "存在未声明的活动进程。",
                details={
                    "activeProcesses": [
                        {"sessionId": execution.execution_id, "status": execution.status}
                        for execution in active[:20]
                    ]
                },
                required_actions=["终止活动进程，或声明服务并提交当前 mutation 的健康检查回执。"],
                progress_state={
                    "activeProcesses": active_process_details,
                    "declaredServices": declared_services,
                },
            )
        for execution in active:
            healthcheck_id = declared_services[execution.execution_id]
            if not await self.repository.successful_verification(
                scope.external_run_id,
                healthcheck_id,
                task.mutation_sequence,
            ):
                return reject(
                    "finish_service_unhealthy",
                    "保留服务缺少当前 mutation 的成功健康检查。",
                    details={
                        "activeProcesses": [
                            {"sessionId": execution.execution_id, "status": execution.status}
                            for execution in active[:20]
                        ],
                        "healthcheckExecutionId": healthcheck_id,
                    },
                    required_actions=["为保留服务运行当前 mutation 的成功健康检查。"],
                    progress_state={
                        "activeProcesses": active_process_details,
                        "healthcheckExecutionId": healthcheck_id,
                        "verification": verification_details,
                    },
                )

        acceptance_summary = None
        if task.acceptance_contract is not None:
            acceptance_decision = self.acceptance_policy.evaluate(
                task.acceptance_contract,
                executions,
                task.mutation_sequence,
                artifacts,
                self.validator_registry.script_sha256(),
            )
            if not acceptance_decision.accepted:
                assert acceptance_decision.code is not None
                return reject(
                    acceptance_decision.code,
                    acceptance_decision.message,
                    details=acceptance_decision.details,
                    required_actions=acceptance_decision.required_actions,
                    progress_state=acceptance_decision.details,
                )
            acceptance_summary = acceptance_decision.summary

        extra_evidence = None
        if self.completion_evidence is not None:
            try:
                assert run_context is not None
                extra_evidence = await self.completion_evidence(run_context)
            except (WorkspaceError, DaytonaNotFoundError):
                extra_evidence = None
            if extra_evidence is None:
                return reject(
                    "finish_report_unverified",
                    "报表 PDF 或交付证据未通过验收。",
                    required_actions=["完成报表 PDF 与交付证据验证。"],
                    progress_state={"evidence": None},
                )

        payload: dict[str, Any] = {
            "summary": summary.strip(),
            "artifacts": artifacts,
            "verificationIds": verification_ids,
            "serviceSessions": service_sessions,
            **({"acceptance": acceptance_summary} if acceptance_summary is not None else {}),
            **({"evidence": extra_evidence} if extra_evidence is not None else {}),
        }
        try:
            current_artifacts = await self.service.abatch_hash_files(
                scope.thread_id, artifact_paths
            )
            async for _sandbox in self._sandbox(scope):
                pass
        except (CodingRepositoryError, WorkspaceError, DaytonaNotFoundError):
            return reject(
                "finish_sandbox_changed",
                "当前工作区或交付产物在验收期间发生变化。",
                required_actions=["确认工作区稳定后重新运行验证。"],
                progress_state={"sandboxId": scope.sandbox_id},
            )
        if current_artifacts != artifacts:
            return reject(
                "finish_artifact_changed",
                "交付产物在验收期间发生变化。",
                details={"artifactPaths": artifact_paths[:MAX_FINISH_ARTIFACTS]},
                required_actions=["确认产物稳定后重新运行验证。"],
                progress_state={
                    "artifacts": artifacts,
                    "currentArtifacts": current_artifacts,
                },
            )
        try:
            if isinstance(scope.task, TaskSnapshot):
                receipt = {
                    "taskId": scope.external_run_id,
                    "attemptNo": scope.attempt_no,
                    "internalRunId": scope.internal_run_id,
                    "sandboxId": scope.sandbox_id,
                    "mutationSequence": task.mutation_sequence,
                    **payload,
                    "acceptedAt": utcnow().isoformat(),
                }
                receipt["digest"] = hashlib.sha256(
                    json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                assert scope.lease is not None
                await self.repository.request_finish(
                    scope.external_run_id,
                    scope.lease,
                    scope.task.state_version,
                    receipt,
                    result_text=summary.strip(),
                    retained_execution_ids=list(declared_services),
                )
                payload = receipt
            else:
                await self.repository.complete_task(
                    scope.external_run_id,
                    expected_mutation_sequence=task.mutation_sequence,
                    expected_lease_owner=scope.lease_owner,
                    result_text=summary.strip(),
                    finish_payload=payload,
                    retained_execution_ids=list(declared_services),
                )
        except CodingRepositoryError as error:
            if error.code == "finish_instruction_pending":
                finish_function.stop_after_tool_call = True
                return reject(
                    error.code,
                    str(error),
                    required_actions=["处理待执行的补充指令后再提交验收。"],
                    progress_state={"instructionPending": True},
                )
            if error.code not in {"task_cas_conflict", "attempt_cas_conflict"}:
                raise
            return reject(
                "finish_state_changed",
                "任务状态在验收期间发生变化，请重新验证。",
                required_actions=["基于最新任务状态重新运行验证后提交验收。"],
                progress_state={"stateChanged": True},
            )
        state[CODING_FINISH_STATE_KEY] = payload
        state.pop(CODING_FINISH_FAILURE_STATE_KEY, None)
        finish_function.stop_after_tool_call = True
        return {"ok": True, "status": "accepted", **payload}

    @staticmethod
    def _finish_fingerprint(
        scope: CodingTaskScope,
        mutation_sequence: int,
        plan: Any,
        summary: Any,
        artifact_paths: Any,
        verification_ids: Any,
        service_sessions: Any,
        executions: list[CodingExecution],
    ) -> str:
        payload = {
            "attemptNo": scope.attempt_no,
            "internalRunId": scope.internal_run_id,
            "mutationSequence": mutation_sequence,
            "plan": plan,
            "summary": summary,
            "artifactPaths": artifact_paths,
            "verificationIds": verification_ids,
            "serviceSessions": service_sessions,
            "executions": [
                {
                    "id": execution.execution_id,
                    "status": execution.status,
                    "exitCode": execution.exit_code,
                    "mutationSequence": execution.mutation_sequence,
                    "verification": execution.is_verification,
                    "receiptDigest": (
                        hashlib.sha256(
                            json.dumps(
                                execution.operation_receipt,
                                sort_keys=True,
                                separators=(",", ":"),
                                default=str,
                            ).encode()
                        ).hexdigest()
                        if execution.operation_receipt is not None
                        else None
                    ),
                }
                for execution in executions
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()

    @staticmethod
    def _finish_gate_fingerprint(
        scope: CodingTaskScope,
        code: str,
        progress_state: Any,
    ) -> str:
        payload = {
            "attemptNo": scope.attempt_no,
            "internalRunId": scope.internal_run_id,
            "code": code,
            "progress": progress_state,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()

    @classmethod
    def _finish_no_progress(
        cls,
        failure_code: str,
        details: dict[str, Any],
        required_actions: list[str],
    ) -> dict[str, Any]:
        return cls._finish_error(
            "finish_no_progress",
            "验收门禁与上次失败时相同；请先完成要求的操作再重试。",
            details={**details, "failureCode": failure_code},
            required_actions=required_actions,
        )

    @staticmethod
    def _finish_error(
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        required_actions: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "rejected",
            "code": code,
            "message": message,
            "details": details or {},
            "requiredActions": (required_actions or ["修正验收错误后重试 finish_task。"])[:10],
            "retryable": True,
        }


class WorkspaceCodingToolkit(_ManagedDaytonaTools):
    _FILE_MUTATION_TOOLS = frozenset(
        {"create_file", "create_files", "overwrite_file", "replace_text", "apply_patch", "patch"}
    )
    _PROCESS_OBSERVE_OR_CLEANUP_ACTIONS = frozenset({"list", "poll", "wait", "kill"})
    _FINISH_FILE_REPAIR_CODES = frozenset(
        {
            "finish_artifact_missing",
            "finish_artifact_changed",
            "finish_report_unverified",
            "finish_verification_missing",
            "finish_verification_failed",
            "finish_verification_stale",
            "finish_service_unhealthy",
        }
    )

    def __init__(
        self,
        service: WorkspaceService,
        repository: CodingTaskRepository,
        *,
        completion_evidence: Callable[[RunContext], Awaitable[dict[str, Any] | None]] | None = None,
        validator_registry: SkillValidatorRegistry | None = None,
    ):
        self.kernel = CodingExecutionKernel(
            service,
            repository,
            completion_evidence=completion_evidence,
            validator_registry=validator_registry,
        )
        finish_function = Function(
            name="finish_task",
            description="提交最终任务验收；验收失败时按稳定错误码修复后再次调用。",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "minLength": 1, "maxLength": 4000},
                    "artifact_paths": {
                        "type": "array",
                        "maxItems": MAX_FINISH_ARTIFACTS,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "verification_ids": {
                        "type": "array",
                        "maxItems": MAX_VERIFICATION_IDS,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "service_sessions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["session_id", "healthcheck_execution_id"],
                            "properties": {
                                "session_id": {"type": "string", "minLength": 1},
                                "healthcheck_execution_id": {"type": "string", "minLength": 1},
                            },
                        },
                        "default": [],
                    },
                },
                "required": ["summary", "artifact_paths"],
                "additionalProperties": False,
            },
        )

        async def finish_entrypoint(
            summary: str | None = None,
            artifact_paths: list[str] | None = None,
            verification_ids: list[str] | None = None,
            service_sessions: list[dict[str, str]] | None = None,
            run_context: RunContext | None = None,
        ) -> dict[str, Any]:
            result = await self._invoke(
                "finish_task",
                {
                    "summary": summary,
                    "artifact_paths": artifact_paths,
                    "verification_ids": verification_ids,
                    "service_sessions": service_sessions or [],
                },
                lambda scope: self.kernel.finish_task(
                    summary,
                    artifact_paths,
                    verification_ids,
                    service_sessions or [],
                    run_context,
                    finish_function,
                    _scope=scope,
                ),
                run_context,
            )
            if isinstance(result, dict) and result.get("ok") is True:
                registered = self.async_functions.get("finish_task")
                if registered is not None:
                    registered.stop_after_tool_call = True
            return result

        def finish_post_hook(fc: Any) -> None:
            if isinstance(fc.result, dict) and fc.result.get("status") == "accepted":
                fc.function.stop_after_tool_call = True

        finish_function.entrypoint = finish_entrypoint
        finish_function.post_hook = finish_post_hook
        super().__init__(
            name="workspace_coding",
            tools=[
                Function(
                    name="terminal",
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "minLength": 1},
                            "background": {"type": "boolean", "default": False},
                            "timeout": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_BACKGROUND_EXECUTION_TIMEOUT,
                                "default": DEFAULT_TERMINAL_TIMEOUT,
                            },
                            "workdir": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "pty": {"type": "boolean", "default": False},
                        },
                        "required": ["command"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.terminal,
                ),
                Function(
                    name="process",
                    parameters={
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["list", "poll", "wait", "kill", "write", "submit"],
                            },
                            "session_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "data": {"type": "string", "maxLength": MAX_PROCESS_INPUT_BYTES},
                            "timeout": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_BACKGROUND_EXECUTION_TIMEOUT,
                                "default": 30,
                            },
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.process,
                ),
                Function(
                    name="create_files",
                    description="在一次原子补丁中创建一个或多个不存在的文件。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "files": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": MAX_PATCH_FILES,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "path": {"type": "string", "minLength": 1},
                                        "content": {"type": "string"},
                                    },
                                    "required": ["path", "content"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["files"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.create_files,
                ),
                Function(
                    name="overwrite_file",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "content": {"type": "string"},
                            "expected_sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                        },
                        "required": ["path", "content", "expected_sha256"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.overwrite_file,
                ),
                Function(
                    name="replace_text",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "old_string": {"type": "string", "minLength": 1},
                            "new_string": {"type": "string"},
                            "replace_all": {"type": "boolean", "default": False},
                        },
                        "required": ["path", "old_string", "new_string"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.replace_text,
                ),
                Function(
                    name="apply_patch",
                    parameters={
                        "type": "object",
                        "properties": {"patch": {"type": "string", "minLength": 1}},
                        "required": ["patch"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.apply_patch,
                ),
                Function(
                    name="verify",
                    description=(
                        "在当前工作区执行显式验证，并把回执绑定到当前 mutation。"
                        "command 与 validator_id 必须且只能提供一个；validator 使用服务端固定配置。"
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "minLength": 1},
                            "validator_id": {"type": "string", "minLength": 1},
                            "artifact_paths": {
                                "type": "array",
                                "items": {"type": "string", "minLength": 1},
                                "default": [],
                            },
                            "timeout": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_BACKGROUND_EXECUTION_TIMEOUT,
                                "default": DEFAULT_TERMINAL_TIMEOUT,
                            },
                        },
                        "oneOf": [
                            {"required": ["command"]},
                            {"required": ["validator_id"]},
                        ],
                        "additionalProperties": False,
                    },
                    entrypoint=self.verify,
                ),
                Function(
                    name="list_files",
                    description=(
                        "列出当前工作区的直属文件和目录。路径必须相对工作区根目录；"
                        '列出根目录时 path 传空字符串 ""，禁止传 /workspace 或 '
                        "/home/daytona/workspace。"
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": ('工作区相对目录；根目录必须传空字符串 ""。'),
                                "default": "",
                            }
                        },
                        "additionalProperties": False,
                    },
                    entrypoint=self.coding_list_files,
                ),
                Function(
                    name="read_file",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "offset": {"type": "integer", "minimum": 0, "default": 0},
                            "max_bytes": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_TOOL_OUTPUT_READ_BYTES,
                                "default": MAX_TOOL_OUTPUT_READ_BYTES,
                            },
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.coding_read_file,
                ),
                Function(
                    name="read_lines",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "start_line": {"type": "integer", "minimum": 1, "default": 1},
                            "end_line": {"type": "integer", "minimum": 1},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.read_lines,
                ),
                Function(
                    name="search_text",
                    parameters={
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "minLength": 1},
                            "path": {"type": "string", "default": ""},
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 1000,
                                "default": 100,
                            },
                        },
                        "required": ["pattern"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.search_text,
                ),
                Function(
                    name="tree",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "default": ""},
                            "max_depth": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 20,
                                "default": 4,
                            },
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 1000,
                                "default": 200,
                            },
                        },
                        "additionalProperties": False,
                    },
                    entrypoint=self.tree,
                ),
                Function(
                    name="git_status",
                    parameters={
                        "type": "object",
                        "properties": {"repo_path": {"type": "string", "default": ""}},
                        "additionalProperties": False,
                    },
                    entrypoint=self.git_status,
                ),
                Function(
                    name="git_diff",
                    parameters={
                        "type": "object",
                        "properties": {
                            "repo_path": {"type": "string", "default": ""},
                            "staged": {"type": "boolean", "default": False},
                            "revision": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "file_path": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        },
                        "additionalProperties": False,
                    },
                    entrypoint=self.git_diff,
                ),
                Function(
                    name="read_tool_output",
                    parameters={
                        "type": "object",
                        "properties": {
                            "handle": {"type": "string", "minLength": 1},
                            "offset": {"type": "integer", "minimum": 0, "default": 0},
                            "max_bytes": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_TOOL_OUTPUT_READ_BYTES,
                                "default": MAX_TOOL_OUTPUT_READ_BYTES,
                            },
                        },
                        "required": ["handle"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.read_tool_output,
                ),
                Function(
                    name="view_image",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "detail": {
                                "type": "string",
                                "enum": ["high", "original"],
                                "default": "high",
                            },
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.view_image,
                ),
                Function(
                    name="update_plan",
                    description="更新编码任务计划；最多 20 步且最多一个步骤处于 in_progress。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "plan": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 20,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["step", "status"],
                                    "properties": {
                                        "step": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 300,
                                        },
                                        "status": {
                                            "type": "string",
                                            "enum": ["pending", "in_progress", "completed"],
                                        },
                                    },
                                },
                            },
                            "explanation": {
                                "anyOf": [{"type": "string", "maxLength": 1000}, {"type": "null"}]
                            },
                        },
                        "required": ["plan"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.update_plan,
                ),
                finish_function,
            ],
            instructions=PURE_CODING_TOOLKIT_INSTRUCTIONS,
        )

    async def _invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        call: Callable[[CodingTaskScope], Awaitable[Any]],
        run_context: RunContext | None,
    ) -> Any:
        external_run_id = self.kernel.bound_external_run_id(run_context)
        progress_name = (
            f"process:{arguments.get('action')}" if tool_name == "process" else tool_name
        )
        spec = TOOL_SPECS[tool_name]
        if tool_name == "process" and arguments.get("action") in {"list", "poll", "wait"}:
            spec = ToolSpec("read", True)
        elif tool_name == "terminal" and _is_read_only_terminal_command(
            str(arguments.get("command") or "")
        ):
            spec = ToolSpec("read", True)
        async with (
            self.kernel.task_scheduler(external_run_id) as lock,
            lock.read() if spec.parallel_safe else lock.write(),
        ):
            scope = await self.kernel.scope(run_context)
            state = (
                run_context.session_state
                if run_context is not None and isinstance(run_context.session_state, dict)
                else None
            )
            mutation_before = scope.task.mutation_sequence
            admission_rejection = await self._state_admission_rejection(
                scope,
                tool_name,
                arguments,
                state,
            )
            if admission_rejection is not None:
                return admission_rejection
            args_hash = hashlib.sha256(
                json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str).encode()
            ).hexdigest()
            exempt = progress_name in NO_PROGRESS_EXEMPT_TOOLS or tool_name == "finish_task"
            async with lock.state():
                progress = state.get(CODING_TOOL_PROGRESS_STATE_KEY) if state is not None else None
                entries = (
                    list(progress["entries"])
                    if isinstance(progress, dict)
                    and progress.get("attempt") == scope.attempt_no
                    and progress.get("mutation") == mutation_before
                    and isinstance(progress.get("entries"), list)
                    else []
                )
                failure_state = (
                    state.get(CODING_TOOL_FAILURE_STATE_KEY) if state is not None else None
                )
                failure_entries = (
                    list(failure_state["entries"])
                    if isinstance(failure_state, dict)
                    and failure_state.get("attempt") == scope.attempt_no
                    and isinstance(failure_state.get("entries"), list)
                    else []
                )
                argument_resources = _absolute_paths(arguments)
                blocked_failure = next(
                    (
                        entry
                        for entry in reversed(failure_entries)
                        if isinstance(entry, dict)
                        and isinstance(entry.get("resource"), str)
                        and any(
                            _paths_related(entry["resource"], resource)
                            for resource in argument_resources
                        )
                        and tool_name in {"terminal", "verify"}
                    ),
                    None,
                )
                if isinstance(blocked_failure, dict):
                    return {
                        "ok": False,
                        "code": "tool_no_progress",
                        "message": "当前 Attempt 已确认该绝对路径不可用，本次未执行。",
                        "details": {
                            "failedResource": blocked_failure["resource"],
                            "workspaceRoot": WORKSPACE_ROOT,
                            "failureFingerprint": blocked_failure["fingerprint"],
                        },
                        "requiredActions": [
                            "使用工作区相对路径重新执行。",
                            f"需要绝对路径时使用 {WORKSPACE_ROOT}。",
                        ],
                        "retryable": True,
                    }
                previous = next(
                    (
                        entry
                        for entry in reversed(entries)
                        if isinstance(entry, dict)
                        and entry.get("tool") == progress_name
                        and entry.get("argsHash") == args_hash
                    ),
                    None,
                )
                if not exempt and isinstance(previous, dict) and int(previous.get("count", 0)) >= 2:
                    return {
                        "ok": False,
                        "code": "tool_no_progress",
                        "message": "相同工具和参数已连续两次返回相同结果，本次未执行。",
                        "requiredActions": [
                            "修改参数或使用其他只读工具收集新证据。",
                            "先完成真实工作区修改，再重试该调用。",
                        ],
                        "retryable": True,
                    }
            try:
                result = await call(scope)
            except WorkspacePathConflict as error:
                details: dict[str, Any] = {"tool": tool_name}
                suggested_path = _suggested_workspace_path(arguments)
                if suggested_path is not None:
                    details["suggestedPath"] = suggested_path
                return {
                    "ok": False,
                    "status": "rejected",
                    "code": "workspace_path_conflict",
                    "message": str(error)[:1000],
                    "details": details,
                    "requiredActions": ["重新读取目标路径及最新哈希后再重试。"],
                    "retryable": True,
                }
            except WorkspaceError as error:
                details = {"tool": tool_name}
                suggested_path = _suggested_workspace_path(arguments)
                if suggested_path is not None:
                    details["suggestedPath"] = suggested_path
                return {
                    "ok": False,
                    "status": "rejected",
                    "code": "workspace_error",
                    "message": str(error)[:1000],
                    "details": details,
                    "requiredActions": ["按错误说明修正参数后重试。"],
                    "retryable": True,
                }
            failed_resources = _failed_result_resources(arguments, result)
            if state is not None and failed_resources:
                fingerprint = hashlib.sha256(
                    json.dumps(
                        {
                            "exitCode": result.get("exit_code")
                            if isinstance(result, dict)
                            else None,
                            "output": result.get("output") if isinstance(result, dict) else None,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode()
                ).hexdigest()
                async with lock.state():
                    failure_state = state.get(CODING_TOOL_FAILURE_STATE_KEY)
                    failure_entries = (
                        list(failure_state["entries"])
                        if isinstance(failure_state, dict)
                        and failure_state.get("attempt") == scope.attempt_no
                        and isinstance(failure_state.get("entries"), list)
                        else []
                    )
                    for resource in failed_resources:
                        failure_entries = [
                            entry
                            for entry in failure_entries
                            if not isinstance(entry, dict) or entry.get("resource") != resource
                        ]
                        failure_entries.append({"resource": resource, "fingerprint": fingerprint})
                    state[CODING_TOOL_FAILURE_STATE_KEY] = {
                        "attempt": scope.attempt_no,
                        "entries": failure_entries[-MAX_TOOL_FAILURE_ENTRIES:],
                    }
            result_hash = hashlib.sha256(
                json.dumps(
                    _stable_progress_result(result),
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode()
            ).hexdigest()
            if spec.output_policy == "bounded_text":
                result = await self.kernel.bound_tool_result(scope, result, run_context)
            if (
                tool_name == "verify"
                and isinstance(result, dict)
                and isinstance(result.get("outputHandle"), str)
                and isinstance(result.get("execution_id"), str)
            ):
                execution = await self.kernel.repository.get_execution(result["execution_id"])
                receipt = dict(execution.operation_receipt or {}) if execution is not None else {}
                receipt["output_handle"] = result["outputHandle"]
                await self.kernel.repository.update_execution(
                    result["execution_id"], operation_receipt=receipt
                )
            if not exempt and state is not None:
                if spec.effect == "read":
                    mutation_after = mutation_before
                else:
                    latest_snapshot = await self.kernel.repository.get_task_snapshot(
                        scope.external_run_id
                    )
                    latest_task: TaskSnapshot | CodingTask | None = latest_snapshot
                    if latest_task is None:
                        latest_task = await self.kernel.repository.get_task(scope.external_run_id)
                    mutation_after = (
                        latest_task.mutation_sequence if latest_task is not None else -1
                    )
                async with lock.state():
                    progress = state.get(CODING_TOOL_PROGRESS_STATE_KEY)
                    entries = (
                        list(progress["entries"])
                        if isinstance(progress, dict)
                        and progress.get("attempt") == scope.attempt_no
                        and progress.get("mutation") == mutation_after
                        and isinstance(progress.get("entries"), list)
                        else []
                    )
                    previous = next(
                        (
                            entry
                            for entry in reversed(entries)
                            if isinstance(entry, dict)
                            and entry.get("tool") == progress_name
                            and entry.get("argsHash") == args_hash
                        ),
                        None,
                    )
                    same = bool(
                        isinstance(previous, dict)
                        and previous.get("resultHash") == result_hash
                        and mutation_before == mutation_after
                    )
                    entry = {
                        "attempt": scope.attempt_no,
                        "tool": progress_name,
                        "argsHash": args_hash,
                        "resultHash": result_hash,
                        "mutation": mutation_after,
                        "count": int((previous or {}).get("count", 0)) + 1 if same else 1,
                    }
                    if previous in entries:
                        entries.remove(previous)
                    entries.append(entry)
                    state[CODING_TOOL_PROGRESS_STATE_KEY] = {
                        "attempt": scope.attempt_no,
                        "mutation": mutation_after,
                        "entries": entries[-MAX_TOOL_PROGRESS_ENTRIES:],
                    }
            if tool_name == "finish_task" and isinstance(result, dict) and result.get("ok"):
                await self.kernel.cleanup_tool_outputs(scope, run_context)
            return result

    async def _state_admission_rejection(
        self,
        scope: CodingTaskScope,
        tool_name: str,
        arguments: dict[str, Any],
        state: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        mutation_sequence = scope.task.mutation_sequence
        if tool_name == "process" and arguments.get("action") in (
            self._PROCESS_OBSERVE_OR_CLEANUP_ACTIONS
        ):
            return None

        finish_failure = state.get(CODING_FINISH_FAILURE_STATE_KEY) if state is not None else None
        raw_finish_failure_details = (
            finish_failure.get("details") if isinstance(finish_failure, dict) else None
        )
        finish_failure_details: dict[str, Any] = (
            dict(raw_finish_failure_details) if isinstance(raw_finish_failure_details, dict) else {}
        )
        repairing_finish_failure = bool(
            finish_failure_details.get("mutationSequence") == mutation_sequence
        )
        if mutation_sequence == 0 and not repairing_finish_failure:
            return None

        current_plan = (
            validated_agent_plan(state.get(AGENT_PLAN_STATE_KEY))
            if isinstance(state, dict)
            else None
        )
        if (
            not repairing_finish_failure
            and current_plan is not None
            and any(item["status"] != "completed" for item in current_plan["plan"])
        ):
            return None

        rework = state.get(CODING_REWORK_STATE_KEY) if state is not None else None
        if isinstance(rework, dict) and rework.get("mutationSequence") == mutation_sequence:
            return None

        executions = await self.kernel.repository.list_executions(scope.external_run_id)
        verification = next(
            (
                execution
                for execution in reversed(executions)
                if execution.is_verification
                and execution.mutation_sequence == mutation_sequence
                and execution.status == "completed"
                and execution.exit_code == 0
                and (execution.operation_receipt or {}).get("valid", True) is not False
            ),
            None,
        )
        if verification is None:
            if (
                TOOL_SPECS[tool_name].effect == "read"
                or tool_name in self._FILE_MUTATION_TOOLS
                or tool_name == "verify"
            ):
                return None
            failed_verification = next(
                (
                    execution
                    for execution in reversed(executions)
                    if execution.is_verification
                    and execution.mutation_sequence == mutation_sequence
                    and (
                        execution.status in TERMINAL_EXECUTION_STATUSES
                        or (execution.operation_receipt or {}).get("valid") is False
                    )
                ),
                None,
            )
            return {
                "ok": False,
                "status": "rejected",
                "code": "coding_verification_required",
                "message": "当前工作区修改尚未通过验证，本次工具调用未执行。",
                "details": {
                    "mutationSequence": mutation_sequence,
                    **(
                        {"failedVerificationId": failed_verification.execution_id}
                        if failed_verification is not None
                        else {}
                    ),
                },
                "requiredActions": [
                    "如验证失败，仅修改失败项，然后调用 verify 重新验证。",
                    "如尚未验证，立即调用 verify 执行与本次修改对应的检查。",
                ],
                "retryable": True,
            }

        if tool_name == "finish_task":
            return None
        if repairing_finish_failure and isinstance(finish_failure, dict):
            failure_code = str(finish_failure.get("code") or "finish_rejected")
            repair_with_files = failure_code in self._FINISH_FILE_REPAIR_CODES or (
                failure_code.startswith("finish_acceptance_")
            )
            if failure_code == "finish_plan_incomplete" and tool_name == "update_plan":
                return None
            if repair_with_files and (
                TOOL_SPECS[tool_name].effect == "read"
                or tool_name in self._FILE_MUTATION_TOOLS
                or tool_name in {"verify", "update_plan"}
            ):
                return None
            allowed_tools = (
                ["finish_task", "update_plan"]
                if failure_code == "finish_plan_incomplete"
                else [
                    "finish_task",
                    "update_plan",
                    "verify",
                    "create_files",
                    "overwrite_file",
                    "replace_text",
                    "apply_patch",
                    "view_image",
                    "read_tool_output",
                    "list_files",
                    "read_file",
                    "read_lines",
                    "search_text",
                    "tree",
                    "git_status",
                    "git_diff",
                ]
                if repair_with_files
                else ["finish_task"]
            )
            return {
                "ok": False,
                "status": "rejected",
                "code": "coding_finish_repair_required",
                "message": "上次 finish_task 未通过；本次工具与失败项修复无关，未执行。",
                "details": {
                    **finish_failure_details,
                    "mutationSequence": mutation_sequence,
                    "verificationId": verification.execution_id,
                    "finishFailureCode": failure_code,
                    "allowedTools": allowed_tools,
                },
                "requiredActions": list(finish_failure.get("requiredActions") or [])[:10],
                "retryable": True,
            }
        if tool_name == "update_plan":
            return None
        return {
            "ok": False,
            "status": "rejected",
            "code": "coding_finish_required",
            "message": "当前工作区修改已通过验证，应提交任务验收，本次工具调用未执行。",
            "details": {
                "mutationSequence": mutation_sequence,
                "verificationId": verification.execution_id,
                "allowedTools": ["finish_task", "update_plan"],
                **(
                    {"finishFailureCode": finish_failure.get("code")}
                    if repairing_finish_failure and isinstance(finish_failure, dict)
                    else {}
                ),
            },
            "requiredActions": (
                list(finish_failure.get("requiredActions") or [])[:10]
                if repairing_finish_failure and isinstance(finish_failure, dict)
                else [
                    "若工作已全部完成，更新计划为 completed 后调用 finish_task；"
                    "若仍需工作，先用 update_plan 标记下一真实步骤为 in_progress。"
                ]
            ),
            "retryable": True,
        }

    async def terminal(
        self,
        command: str,
        background: bool = False,
        timeout: int = DEFAULT_TERMINAL_TIMEOUT,
        workdir: str | None = None,
        pty: bool = False,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self._invoke(
            "terminal",
            {
                "command": command,
                "background": background,
                "timeout": timeout,
                "workdir": workdir,
                "pty": pty,
            },
            lambda scope: self.kernel.terminal(
                command,
                background=background,
                timeout=timeout,
                workdir=workdir,
                pty=pty,
                run_context=run_context,
                _scope=scope,
            ),
            run_context,
        )

    async def coding_create_file(
        self,
        path: str,
        content: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self._invoke(
            "create_file",
            {"path": path, "content": content},
            lambda scope: self.kernel.patch(
                "create",
                path,
                None,
                None,
                False,
                None,
                run_context,
                content=content,
                _scope=scope,
            ),
            run_context,
        )

    async def overwrite_file(
        self,
        path: str,
        content: str,
        expected_sha256: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self._invoke(
            "overwrite_file",
            {
                "path": path,
                "content": content,
                "expected_sha256": expected_sha256,
            },
            lambda scope: self.kernel.patch(
                "overwrite",
                path,
                None,
                None,
                False,
                None,
                run_context,
                content=content,
                expected_sha256=expected_sha256,
                _scope=scope,
            ),
            run_context,
        )

    async def replace_text(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self._invoke(
            "replace_text",
            {
                "path": path,
                "old_string": old_string,
                "new_string": new_string,
                "replace_all": replace_all,
            },
            lambda scope: self.kernel.patch(
                "replace",
                path,
                old_string,
                new_string,
                replace_all,
                None,
                run_context,
                _scope=scope,
            ),
            run_context,
        )

    async def apply_patch(
        self,
        patch: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self._invoke(
            "apply_patch",
            {"patch": patch},
            lambda scope: self.kernel.patch(
                "patch",
                None,
                None,
                None,
                False,
                patch,
                run_context,
                _scope=scope,
            ),
            run_context,
        )

    async def create_files(
        self,
        files: list[dict[str, str]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        patch = _create_files_patch(files)
        return await self._invoke(
            "create_files",
            {"files": files},
            lambda scope: self.kernel.patch(
                "patch",
                None,
                None,
                None,
                False,
                patch,
                run_context,
                _scope=scope,
            ),
            run_context,
        )

    async def process(
        self,
        action: str,
        session_id: str | None = None,
        data: str = "",
        timeout: int = 30,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self._invoke(
            "process",
            {"action": action, "session_id": session_id, "data": data, "timeout": timeout},
            lambda scope: self.kernel.process(
                action, session_id, data, timeout, run_context, _scope=scope
            ),
            run_context,
        )

    async def patch(
        self,
        mode: str,
        path: str | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool = False,
        patch: str | None = None,
        content: str | None = None,
        expected_sha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self._invoke(
            "patch",
            {
                "mode": mode,
                "path": path,
                "old_string": old_string,
                "new_string": new_string,
                "replace_all": replace_all,
                "patch": patch,
                "content": content,
                "expected_sha256": expected_sha256,
            },
            lambda scope: self.kernel.patch(
                mode,
                path,
                old_string,
                new_string,
                replace_all,
                patch,
                run_context,
                content=content,
                expected_sha256=expected_sha256,
                _scope=scope,
            ),
            run_context,
        )

    async def verify(
        self,
        command: str | None = None,
        validator_id: str | None = None,
        artifact_paths: list[str] | None = None,
        run_context: RunContext | None = None,
        *,
        timeout: int = DEFAULT_TERMINAL_TIMEOUT,
    ) -> dict[str, Any]:
        return await self._invoke(
            "verify",
            {
                "command": command,
                "validator_id": validator_id,
                "artifact_paths": artifact_paths or [],
                "timeout": timeout,
            },
            lambda scope: self.kernel.verify(
                command,
                artifact_paths or [],
                run_context,
                validator_id=validator_id,
                timeout=timeout,
                _scope=scope,
            ),
            run_context,
        )

    async def coding_list_files(
        self, path: str = "", run_context: RunContext | None = None
    ) -> list[dict[str, Any]]:
        async def call(scope: CodingTaskScope):
            return await self.kernel.service.alist_files(scope.thread_id, path)

        return await self._invoke("list_files", {"path": path}, call, run_context)

    async def coding_read_file(
        self,
        path: str,
        offset: int = 0,
        max_bytes: int = MAX_TOOL_OUTPUT_READ_BYTES,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise WorkspaceError("read_file offset 必须是大于等于 0 的整数。")
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 1 <= max_bytes <= MAX_TOOL_OUTPUT_READ_BYTES
        ):
            raise WorkspaceError("read_file max_bytes 必须是 1 至 65536 之间的整数。")

        async def call(scope: CodingTaskScope):
            content, _mime = await asyncio.to_thread(
                self.kernel.service.file_bytes, scope.thread_id, path
            )
            if offset > len(content):
                raise WorkspaceError("read_file offset 超过文件大小。")
            end = min(len(content), offset + max_bytes)
            while end > offset:
                try:
                    selected = content[offset:end].decode("utf-8")
                    break
                except UnicodeDecodeError:
                    end -= 1
            else:
                selected = ""
            if not selected and offset < len(content):
                raise WorkspaceError("read_file max_bytes 不足以读取下一个 UTF-8 字符。")
            return {
                "path": WorkspaceService.normalize_path(path, allow_root=False)[0],
                "offset": offset,
                "nextOffset": end,
                "totalBytes": len(content),
                "content": selected,
                "hasMore": end < len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }

        return await self._invoke(
            "read_file", {"path": path, "offset": offset, "max_bytes": max_bytes}, call, run_context
        )

    async def read_lines(
        self,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if end_line is not None and end_line < start_line:
            raise WorkspaceError("read_lines end_line 必须大于等于 start_line。")
        line_count = 200 if end_line is None else end_line - start_line + 1

        async def call(scope: CodingTaskScope):
            return await self.kernel.service.aread_lines(
                scope.thread_id, path, start_line, line_count
            )

        return await self._invoke(
            "read_lines",
            {"path": path, "start_line": start_line, "end_line": end_line},
            call,
            run_context,
        )

    async def search_text(
        self,
        pattern: str,
        path: str = "",
        limit: int = 100,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        async def call(scope: CodingTaskScope):
            return await self.kernel.service.asearch_text(
                scope.thread_id, pattern, path=path, limit=limit
            )

        return await self._invoke(
            "search_text",
            {"pattern": pattern, "path": path, "limit": limit},
            call,
            run_context,
        )

    async def tree(
        self,
        path: str = "",
        max_depth: int = 4,
        limit: int = 200,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        async def call(scope: CodingTaskScope):
            return await self.kernel.service.atree(scope.thread_id, path, max_depth, limit)

        return await self._invoke(
            "tree", {"path": path, "max_depth": max_depth, "limit": limit}, call, run_context
        )

    async def git_status(
        self, repo_path: str = "", run_context: RunContext | None = None
    ) -> dict[str, Any]:
        async def call(scope: CodingTaskScope):
            return await self.kernel.service.agit_status(scope.thread_id, repo_path)

        return await self._invoke("git_status", {"repo_path": repo_path}, call, run_context)

    async def git_diff(
        self,
        repo_path: str = "",
        staged: bool = False,
        revision: str | None = None,
        file_path: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        async def call(scope: CodingTaskScope):
            return await self.kernel.service.agit_diff(
                scope.thread_id, repo_path, staged, revision, file_path
            )

        return await self._invoke(
            "git_diff",
            {
                "repo_path": repo_path,
                "staged": staged,
                "revision": revision,
                "file_path": file_path,
            },
            call,
            run_context,
        )

    async def read_tool_output(
        self,
        handle: str,
        offset: int = 0,
        max_bytes: int = MAX_TOOL_OUTPUT_READ_BYTES,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self._invoke(
            "read_tool_output",
            {"handle": handle, "offset": offset, "max_bytes": max_bytes},
            lambda scope: self.kernel.read_tool_output(
                handle, offset, max_bytes, run_context, _scope=scope
            ),
            run_context,
        )

    async def view_image(
        self,
        path: str,
        detail: str = "high",
        run_context: RunContext | None = None,
    ):
        if detail not in {"high", "original"}:
            raise WorkspaceError("图片 detail 必须是 high 或 original。")

        async def call(scope: CodingTaskScope):
            return await asyncio.to_thread(self.kernel.service.view_image, scope.thread_id, path)

        return await self._invoke("view_image", {"path": path, "detail": detail}, call, run_context)

    async def update_plan(
        self,
        plan: list[dict[str, str]] | None = None,
        explanation: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if plan is None:
            return {
                "ok": False,
                "code": "plan_required",
                "message": "plan 必须包含 1 至 20 个步骤。",
            }

        async def call(scope: CodingTaskScope):
            result = self.kernel.plan.agent_update_plan(plan, explanation, run_context)
            state = run_context.session_state if run_context is not None else None
            if isinstance(state, dict) and result.get("ok") is True:
                if any(item.get("status") != "completed" for item in result.get("plan", [])):
                    state[CODING_REWORK_STATE_KEY] = {
                        "mutationSequence": scope.task.mutation_sequence
                    }
                else:
                    state.pop(CODING_REWORK_STATE_KEY, None)
            return result

        return await self._invoke(
            "update_plan", {"plan": plan, "explanation": explanation}, call, run_context
        )
