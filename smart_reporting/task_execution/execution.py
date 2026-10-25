from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

from agno.run import RunContext
from agno.tools import Function
from loguru import logger

from ..agent_control import AGENT_PLAN_STATE_KEY, is_scheduler_parallel_safe_tool
from ..skills import TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY
from ..workspace import (
    WorkspaceError,
    _thread,
    normalize_workspace_path,
    validate_patch_hash,
)
from .models import Lease, TaskExecutionScope, TaskSnapshot
from .repository_impl import (
    TERMINAL_EXECUTION_STATUSES,
    TaskExecution,
    TaskExecutionRepository,
    TaskExecutionRepositoryError,
    TaskExecutionTask,
    utcnow,
)
from .tools import abuild_workspace_changes, assert_task_workspace_path

TASK_EXECUTION_DEPENDENCY = "AgentOS 任务执行"
TASK_EXECUTION_FINISH_FAILURE_STATE_KEY = "agentos_task_execution_finish_failure"
TASK_EXECUTION_FINISH_STATE_KEY = "agentos_task_execution_finish"
TASK_EXECUTION_MIGRATION_STATE_KEY = "agentos_task_execution_migrated"
DEFAULT_TERMINAL_TIMEOUT = 900
MAX_FINISH_ARTIFACTS = 50
MAX_TOOL_PREVIEW_BYTES = 48 * 1024
MAX_REPORT_TOOL_PREVIEW_BYTES = 16 * 1024
MAX_TOOL_OUTPUT_RESOURCE_BYTES = 16 * 1024 * 1024
MAX_TASK_TOOL_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_TOOL_OUTPUT_READ_BYTES = 64 * 1024
# read_file 支持分析 evidence 的单次 128 KiB 受控读取；工具输出分页仍使用上面的 64 KiB 窗口。
MAX_READ_FILE_BYTES = 128 * 1024
MAX_PARALLEL_READ_TOOLS = 10
TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY = "agentos_task_execution_tool_outputs"
TASK_EXECUTION_TOOL_PROGRESS_STATE_KEY = "agentos_task_execution_tool_progress"
TASK_EXECUTION_TOOL_FAILURE_STATE_KEY = "agentos_task_execution_tool_failures"
TASK_EXECUTION_TOOL_ARGUMENT_AUTOFIX_STATE_KEY = "agentos_task_execution_tool_argument_autofixes"
TASK_EXECUTION_REWORK_STATE_KEY = "agentos_task_execution_rework"
_LEGACY_TASK_EXECUTION_STATE_KEYS = {
    "agentos_coding_finish_failure": TASK_EXECUTION_FINISH_FAILURE_STATE_KEY,
    "agentos_coding_finish": TASK_EXECUTION_FINISH_STATE_KEY,
    "agentos_coding_execution_migrated": TASK_EXECUTION_MIGRATION_STATE_KEY,
    "agentos_coding_tool_outputs": TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY,
    "agentos_coding_tool_progress": TASK_EXECUTION_TOOL_PROGRESS_STATE_KEY,
    "agentos_coding_tool_failures": TASK_EXECUTION_TOOL_FAILURE_STATE_KEY,
    "agentos_coding_tool_argument_autofixes": TASK_EXECUTION_TOOL_ARGUMENT_AUTOFIX_STATE_KEY,
    "agentos_coding_rework": TASK_EXECUTION_REWORK_STATE_KEY,
    "agentos_coding_skill_script_receipts": TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY,
}
# 工具输出保存在任务工作区内的隐藏目录（工作区相对路径）。
TOOL_OUTPUT_ROOT = ".agentos/tool-output"
# 旧版本记录在会话状态中的工具输出路径带有沙箱 home 前缀，读取时去掉该前缀再访问工作区。
_LEGACY_TOOL_OUTPUT_PREFIX = "/home/daytona/"


def normalize_task_function_call_arguments(
    fc: Any,
    run_context: RunContext | None = None,
) -> None:
    """在 Agno 建立工具执行链前规范化 JSON 等价参数。"""
    if run_context is not None and isinstance(run_context.session_state, dict):
        _migrate_legacy_task_execution_state(run_context.session_state)
    _normalize_function_call_arguments(
        fc,
        run_context,
        state_key=TASK_EXECUTION_TOOL_ARGUMENT_AUTOFIX_STATE_KEY,
        autofix_code="coding_tool_arguments_unwrapped",
    )


def _migrate_legacy_task_execution_state(state: dict[str, Any]) -> None:
    """一次性吸收旧运行状态键；兼容标识不再向新上下文传播。"""

    for legacy_key, current_key in _LEGACY_TASK_EXECUTION_STATE_KEYS.items():
        if current_key not in state and legacy_key in state:
            state[current_key] = state[legacy_key]
        state.pop(legacy_key, None)


def _normalize_function_call_arguments(
    fc: Any,
    run_context: RunContext | None,
    *,
    state_key: str,
    autofix_code: str,
) -> None:
    arguments = getattr(fc, "arguments", None)
    if not isinstance(arguments, dict):
        return

    function = getattr(fc, "function", None)
    parameters = getattr(function, "parameters", None)
    properties = parameters.get("properties") if isinstance(parameters, dict) else None
    schema_properties = properties if isinstance(properties, dict) else {}
    corrected = dict(arguments)
    changed = False

    # `arguments` 不是目标 Function 的真实字段时，允许展开唯一一层传输包装；
    # 同级字段只在无键冲突时确定性合并，展开后仍由原始 strict schema 最终校验。
    if "arguments" not in schema_properties and "arguments" in corrected:
        wrapped = corrected["arguments"]
        if isinstance(wrapped, str):
            try:
                wrapped = json.loads(wrapped)
            except json.JSONDecodeError:
                wrapped = None
        siblings = {key: value for key, value in corrected.items() if key != "arguments"}
        if isinstance(wrapped, dict) and not wrapped.keys() & siblings.keys():
            corrected = {**wrapped, **siblings}
            changed = True

    # 部分 OpenAI-compatible provider 会把 object/array 属性再次 JSON 编码为字符串。
    # 这里只按声明 schema 解码一层且要求容器类型完全一致；不递归、不补括号、
    # 不接受 Python literal，也不改字段名或默认值。
    for key, value in tuple(corrected.items()):
        property_schema = schema_properties.get(key)
        expected_type = property_schema.get("type") if isinstance(property_schema, dict) else None
        if not isinstance(value, str) or expected_type not in {"object", "array"}:
            continue
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            continue
        if (expected_type == "object" and isinstance(decoded, dict)) or (
            expected_type == "array" and isinstance(decoded, list)
        ):
            corrected[key] = decoded
            changed = True

    if not changed:
        return
    fc.arguments = corrected
    state = run_context.session_state if run_context is not None else None
    if not isinstance(state, dict):
        return
    progress = state.get(TASK_EXECUTION_TOOL_PROGRESS_STATE_KEY)
    mutation_sequence = int(progress.get("mutation", 0)) if isinstance(progress, dict) else 0
    entry = {
        "code": autofix_code,
        "toolName": str(getattr(getattr(fc, "function", None), "name", "") or ""),
        "mutationSequence": mutation_sequence,
    }
    stored = state.get(state_key)
    items = list(stored) if isinstance(stored, list) else []
    if not items or items[-1] != entry:
        items.append(entry)
    state[state_key] = items[-50:]


def _tool_output_path(path: str) -> str:
    """工具输出的工作区相对路径；兼容旧版本记录的沙箱绝对路径。"""

    if path.startswith(_LEGACY_TOOL_OUTPUT_PREFIX):
        path = path[len(_LEGACY_TOOL_OUTPUT_PREFIX) :]
    return normalize_workspace_path(path, allow_root=False)


@dataclass(frozen=True)
class ToolSpec:
    effect: str
    parallel_safe: bool
    output_policy: str = "bounded_text"


TOOL_SPECS = {
    "finish_task": ToolSpec("finish", False),
    "view_image": ToolSpec("read", True, "media"),
    "read_tool_output": ToolSpec("read", True, "paged_text"),
    "read_file": ToolSpec("read", True),
}

NO_PROGRESS_EXEMPT_TOOLS = frozenset(
    {"read_tool_output", "view_image"}
)
MAX_TOOL_PROGRESS_ENTRIES = 16
MAX_TOOL_FAILURE_ENTRIES = 16
# 模型偶尔以绝对路径引用工作区；以该根目录开头的路径可改写为工作区相对路径。
ABSOLUTE_WORKSPACE_ROOT = "/workspace"
ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.-])/(?:[\w.-]+/)*[\w.-]+")
VOLATILE_PROGRESS_RESULT_KEYS = frozenset(
    {"commandId", "command_id", "execution_id", "sessionId", "session_id"}
)


def stable_progress_result(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: stable_progress_result(item)
            for key, item in value.items()
            if key not in VOLATILE_PROGRESS_RESULT_KEYS
        }
    if isinstance(value, list):
        return [stable_progress_result(item) for item in value]
    return value


def absolute_paths(value: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            paths.update(absolute_paths(item))
        return paths
    if isinstance(value, list):
        for item in value:
            paths.update(absolute_paths(item))
        return paths
    return set(ABSOLUTE_PATH_RE.findall(value)) if isinstance(value, str) else set()


def paths_related(first: str, second: str) -> bool:
    first_parts = tuple(part for part in first.split("/") if part)
    second_parts = tuple(part for part in second.split("/") if part)
    shorter = min(len(first_parts), len(second_parts))
    return first_parts[:shorter] == second_parts[:shorter]


def suggested_workspace_path(arguments: dict[str, Any]) -> str | None:
    for path in sorted(absolute_paths(arguments), key=len, reverse=True):
        for root in (ABSOLUTE_WORKSPACE_ROOT,):
            if path == root:
                return ""
            if path.startswith(f"{root}/"):
                return path[len(root) + 1 :]
    return None


def failed_result_resources(arguments: dict[str, Any], result: Any) -> list[str]:
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
    argument_paths = absolute_paths(arguments)
    output_paths = absolute_paths(output)
    resources = {
        output_path
        for argument_path in argument_paths
        for output_path in output_paths
        if paths_related(argument_path, output_path)
        and output_path != ABSOLUTE_WORKSPACE_ROOT
        and not output_path.startswith(f"{ABSOLUTE_WORKSPACE_ROOT}/")
    }
    return sorted(resources)[:4]


_TASK_TOOL_SCHEDULER_MARKER = "_agentos_task_execution_tool_scheduler"




class _AsyncRWLock:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._state_lock = asyncio.Lock()
        self._readers = 0
        self._writer = False
        self._writer_owner: asyncio.Task[Any] | None = None
        self._writer_depth = 0
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
        owner = asyncio.current_task()
        if owner is not None and self._writer_owner is owner:
            # Reporting 专用工具可能在外层 Agno hook 持锁后委托通用 Workspace
            # 工具。两层调用属于同一个 Task，应复用已有写锁；其他 Task 仍必须
            # 等待最外层退出，不能借嵌套调用绕过任务级串行边界。
            self._writer_depth += 1
            try:
                yield
            finally:
                self._writer_depth -= 1
            return
        async with self._condition:
            self._waiting_writers += 1
            try:
                await self._condition.wait_for(lambda: not self._writer and self._readers == 0)
                self._writer = True
                self._writer_owner = owner
                self._writer_depth = 1
            finally:
                self._waiting_writers -= 1
                self._condition.notify_all()
        try:
            yield
        finally:
            async with self._condition:
                self._writer_depth -= 1
                self._writer_owner = None
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
    binding = dependencies.get(TASK_EXECUTION_DEPENDENCY)
    external_run_id = binding.get("externalRunId") if isinstance(binding, dict) else None
    return external_run_id if isinstance(external_run_id, str) and external_run_id else None


def create_task_tool_scheduler_hook(
    repository: TaskExecutionRepository,
) -> Callable[
    [RunContext, str, Callable[..., Any], dict[str, Any]],
    Coroutine[Any, Any, Any],
]:
    async def task_tool_scheduler_hook(
        run_context: RunContext,
        function_name: str,
        function_call: Callable[..., Any],
        arguments: dict[str, Any],
    ) -> Any:
        async def invoke() -> Any:
            result = function_call(**arguments)
            return await result if isawaitable(result) else result

        # Reporting runtime applies the same scheduler after it resolves the Task scope.
        if function_name in TOOL_SPECS:
            return await invoke()
        external_run_id = _bound_external_run_id(run_context)
        if external_run_id is None:
            return await invoke()
        async with _task_tool_scheduler(repository, external_run_id) as scheduler:
            lock = (
                scheduler.read()
                if is_scheduler_parallel_safe_tool(function_name, arguments)
                else scheduler.write()
            )
            async with lock:
                return await invoke()

    setattr(task_tool_scheduler_hook, _TASK_TOOL_SCHEDULER_MARKER, True)
    return task_tool_scheduler_hook


def is_task_tool_scheduler_hook(hook: Callable[..., Any]) -> bool:
    return getattr(hook, _TASK_TOOL_SCHEDULER_MARKER, False) is True


@dataclass(frozen=True)
class TaskExecutionRuntime:
    task: TaskExecutionTask | TaskSnapshot
    external_run_id: str
    internal_run_id: str
    owner_user_id: str
    thread_id: str
    sandbox_id: str
    lease_owner: str
    lease_epoch: int
    attempt_no: int
    lease: Lease | None = None


class TaskExecutionKernel:
    def __init__(self, service: Any, repository: TaskExecutionRepository):
        # service 是任务的本地工作区（Reporting 宿主机工作区路由），按 thread_id 定位工作区。
        self.service = service
        self.repository = repository

    def task_scheduler(self, external_run_id: str):
        return _task_tool_scheduler(self.repository, external_run_id)

    @staticmethod
    def bound_external_run_id(run_context: RunContext | None) -> str:
        if run_context is None or not run_context.run_id or not run_context.user_id:
            raise TaskExecutionRepositoryError("task_context_missing", "缺少执行任务运行上下文。")
        dependencies = (
            run_context.dependencies
            if run_context is not None and isinstance(run_context.dependencies, dict)
            else {}
        )
        binding = dependencies.get(TASK_EXECUTION_DEPENDENCY)
        external_run_id = binding.get("externalRunId") if isinstance(binding, dict) else None
        if not isinstance(external_run_id, str) or not external_run_id:
            raise TaskExecutionRepositoryError("task_binding_missing", "当前运行没有绑定执行任务。")
        return external_run_id

    @staticmethod
    def _preview_text(raw: bytes, max_bytes: int = MAX_TOOL_PREVIEW_BYTES) -> str:
        if len(raw) <= max_bytes:
            return raw.decode("utf-8", errors="replace")
        marker = (f"\n[TOOL_OUTPUT_TRUNCATED omitted_bytes={len(raw) - max_bytes}]\n").encode()
        available = max_bytes - len(marker)
        head_size = available // 2
        tail_size = available - head_size
        head = raw[:head_size].decode("utf-8", errors="ignore")
        tail = raw[-tail_size:].decode("utf-8", errors="ignore")
        return head + marker.decode() + tail

    async def bound_tool_result(
        self,
        scope: TaskExecutionRuntime,
        result: Any,
        run_context: RunContext | None,
        *,
        retain: bool = False,
        preview_bytes: int | None = None,
    ) -> dict[str, Any]:
        if preview_bytes is None:
            preview_bytes = (
                MAX_REPORT_TOOL_PREVIEW_BYTES
                if scope.external_run_id.startswith("report-coding-")
                else MAX_TOOL_PREVIEW_BYTES
            )
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
        key: str | None = None
        if candidates:
            key, value = max(candidates, key=lambda item: len(item[1].encode("utf-8")))
            if (
                len(value.encode("utf-8")) <= preview_bytes
                and len(serialized.encode("utf-8")) > preview_bytes
            ):
                result = {"output": serialized, "outputFormat": "json"}
                key, value = "output", serialized
            raw = value.encode("utf-8")
        else:
            raw = serialized.encode("utf-8")
            if len(raw) <= preview_bytes:
                if retain:
                    result = (
                        dict(result)
                        if isinstance(result, dict)
                        else {"output": serialized, "outputFormat": "json"}
                    )
                else:
                    return result
            else:
                result = {"output": serialized, "outputFormat": "json"}
                key = "output"
        if len(raw) <= preview_bytes and not retain:
            return result
        truncated = len(raw) > preview_bytes
        state = (
            run_context.session_state
            if run_context is not None and isinstance(run_context.session_state, dict)
            else None
        )
        if state is None:
            if not truncated:
                return result
            assert key is not None
            return {
                **result,
                key: self._preview_text(raw, preview_bytes),
                "outputBytes": len(raw),
                "outputSha256": hashlib.sha256(raw).hexdigest(),
                "outputTruncated": True,
                "outputStored": False,
            }
        async with self.task_scheduler(scope.external_run_id) as scheduler:
            handle = uuid.uuid4().hex
            path = f"{TOOL_OUTPUT_ROOT}/{hashlib.sha256(scope.external_run_id.encode()).hexdigest()[:24]}/{handle}"
            async with scheduler.state():
                root = state.setdefault(
                    TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY, {"handles": {}, "tasks": {}}
                )
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
                    "storedSha256": hashlib.sha256(raw[:stored_bytes]).hexdigest(),
                }
                handles[handle] = metadata
                task_state["bytes"] = int(task_state.get("bytes", 0)) + stored_bytes
                task_state.setdefault("handles", []).append(handle)
            try:
                if stored_bytes:
                    await self.service.aensure_directory(scope.thread_id, path.rsplit("/", 1)[0])
                    await self.service.awrite_bytes(
                        scope.thread_id, path, raw[:stored_bytes], overwrite=True
                    )
            except Exception:
                async with scheduler.state():
                    current_root = state.get(TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY, {})
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
            **(
                {key: self._preview_text(raw, preview_bytes)}
                if truncated and key is not None
                else {}
            ),
            "outputHandle": handle,
            "outputBytes": len(raw),
            "outputStoredBytes": stored_bytes,
            "outputSha256": metadata["sha256"],
            "outputTruncated": truncated,
            "outputDiscarded": stored_bytes < len(raw),
        }

    async def read_tool_output(
        self,
        handle: str,
        offset: int,
        max_bytes: int,
        run_context: RunContext | None,
        *,
        _scope: TaskExecutionRuntime | None = None,
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
        raw, metadata = await self.read_tool_output_resource(
            handle,
            run_context,
            _scope=scope,
        )
        stored_bytes = int(metadata["storedBytes"])
        if offset > stored_bytes:
            raise WorkspaceError("output offset 超过已保存内容大小。")
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

    async def read_tool_output_resource(
        self,
        handle: str,
        run_context: RunContext | None,
        *,
        _scope: TaskExecutionRuntime | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        """读取当前 Task/Attempt 的完整工具资源，并复核受信存储身份。"""

        if not isinstance(handle, str) or not handle:
            raise WorkspaceError("output handle 无效。")
        scope = _scope or await self.scope(run_context)
        state = run_context.session_state if run_context is not None else None
        root = (
            state.get(TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY, {}) if isinstance(state, dict) else {}
        )
        metadata = root.get("handles", {}).get(handle) if isinstance(root, dict) else None
        if (
            not isinstance(metadata, dict)
            or metadata.get("task") != scope.external_run_id
            or metadata.get("attempt") != scope.attempt_no
        ):
            raise WorkspaceError("output handle 不属于当前 Task/Attempt。")
        stored_bytes = int(metadata.get("storedBytes", 0))
        if stored_bytes:
            raw, _mime = await self.service.afile_bytes(
                scope.thread_id, _tool_output_path(str(metadata["path"]))
            )
        else:
            raw = b""
        if len(raw) != stored_bytes:
            raise WorkspaceError("output handle 已保存内容长度与受信元数据不一致。")
        output_bytes = int(metadata.get("bytes", -1))
        output_sha256 = metadata.get("sha256")
        stored_sha256 = metadata.get("storedSha256")
        # Full legacy resources can still be checked against the original
        # digest.  A truncated handle written before storedSha256 existed has
        # no prefix digest: keep it readable for in-flight tasks (length is
        # still checked above) but mark it unverified instead of failing.
        if not isinstance(stored_sha256, str) and stored_bytes == output_bytes:
            stored_sha256 = output_sha256
        if not isinstance(stored_sha256, str):
            logger.warning(
                "task_tool_output_legacy_unverified stored_bytes={} bytes={}", stored_bytes, output_bytes
            )
            return raw, {**metadata, "integrity": "legacy_unverified"}
        if hashlib.sha256(raw).hexdigest() != stored_sha256:
            raise WorkspaceError("output handle 已保存内容哈希与受信元数据不一致。")
        return raw, dict(metadata)

    async def cleanup_tool_outputs(
        self, scope: TaskExecutionRuntime, run_context: RunContext | None
    ) -> None:
        state = run_context.session_state if run_context is not None else None
        root = state.get(TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY) if isinstance(state, dict) else None
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
            await self.service.adelete_file(scope.thread_id, task_dir, recursive=True)
        except Exception as error:
            # 尽力清理：不阻断任务收尾，但残留输出目录需可排查。
            logger.warning(
                "task_tool_output_cleanup_failed task_dir={} error_type={}",
                task_dir,
                type(error).__name__,
            )

    async def cleanup_old_epoch(self, scope: TaskExecutionScope, current_epoch: int) -> None:
        await self._cleanup_executions(scope, current_epoch, old_only=True)

    async def cleanup_disconnect(self, scope: TaskExecutionScope, current_epoch: int) -> None:
        await self._cleanup_executions(scope, current_epoch, old_only=False)

    async def _cleanup_executions(
        self, scope: TaskExecutionScope, current_epoch: int, *, old_only: bool
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
            # 本地工作区不运行后台命令；仍未结束的非补丁执行只可能来自旧版本，进程已不存在。
            await self.repository.update_execution(execution.execution_id, status="lost")

    async def _settle_applied_patch(self, execution_id: str, receipt: dict[str, Any]) -> bool:
        try:
            execution = await self.repository.get_execution(execution_id)
            if execution is None:
                return False
            coordinated = await self._coordinate_patch(execution)
            if coordinated == "applied":
                await self.repository.update_execution(
                    execution_id,
                    status="completed",
                    exit_code=0,
                    operation_receipt=receipt,
                )
                return True
            if coordinated == "not_applied":
                await self.repository.update_execution(
                    execution_id,
                    status="failed",
                    exit_code=1,
                    operation_receipt=receipt,
                )
                return True
        except Exception as error:
            logger.warning(
                "task_patch_settle_deferred execution_id={} error_type={}",
                execution_id,
                type(error).__name__,
            )
        return False

    async def _coordinate_patch(self, execution: TaskExecution) -> str:
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
            except WorkspaceError:
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

    async def scope(self, run_context: RunContext | None) -> TaskExecutionRuntime:
        if run_context is None or not run_context.run_id or not run_context.user_id:
            raise TaskExecutionRepositoryError("task_context_missing", "缺少执行任务运行上下文。")
        if isinstance(run_context.session_state, dict):
            _migrate_legacy_task_execution_state(run_context.session_state)
        dependencies = (
            run_context.dependencies if isinstance(run_context.dependencies, dict) else {}
        )
        binding = dependencies.get(TASK_EXECUTION_DEPENDENCY)
        if not isinstance(binding, dict):
            raise TaskExecutionRepositoryError("task_binding_missing", "当前运行没有绑定执行任务。")
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
            raise TaskExecutionRepositoryError("task_binding_invalid", "当前执行任务绑定无效。")
        snapshot = await self.repository.get_task_snapshot(external_run_id)
        task: TaskExecutionTask | TaskSnapshot | None = snapshot
        if task is None:
            task = await self.repository.get_task(external_run_id)
        if task is None:
            raise TaskExecutionRepositoryError("task_not_found", "执行任务必须由 协调器 创建。")
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
                raise TaskExecutionRepositoryError("task_scope_mismatch", "执行任务范围不匹配。")
        else:
            self.repository._assert_scope(task, str(run_context.user_id), thread_id, sandbox_id)
        internal_run_id = str(run_context.run_id)
        if not isinstance(task, TaskSnapshot) and task.current_internal_run_id is None:
            task = await self.repository.bind_initial_run(external_run_id, internal_run_id)
        elif internal_run_id != task.current_internal_run_id:
            raise TaskExecutionRepositoryError(
                "task_run_mismatch", "当前内部运行不是执行任务的活动 checkpoint。"
            )
        if isinstance(task, TaskSnapshot):
            if (
                lease_epoch is None
                or task.lease_owner != lease_owner
                or task.lease_epoch != lease_epoch
                or task.lease_expires_at is None
                or task.lease_expires_at <= utcnow()
            ):
                logger.bind(
                    task_id=external_run_id,
                    bound_lease_epoch=lease_epoch,
                    current_lease_epoch=task.lease_epoch,
                    owner_matches=task.lease_owner == lease_owner,
                    lease_expires_at=(task.lease_expires_at.isoformat() if task.lease_expires_at else None),
                    task_state=task.state.value,
                ).warning("task_execution_lease_binding_invalid")
                raise TaskExecutionRepositoryError(
                    "task_lease_binding_invalid", "执行任务租约绑定无效。"
                )
            active_lease = Lease(lease_owner, lease_epoch, task.lease_expires_at)
        else:
            claimed = await self.repository.claim_lease(external_run_id, lease_owner)
            if not claimed:
                raise TaskExecutionRepositoryError(
                    "task_lease_conflict", "执行任务正在由另一连接处理。"
                )
            active_lease = claimed if isinstance(claimed, Lease) else None
        scope = TaskExecutionRuntime(
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
        return scope

    async def _check_fence(self, scope: TaskExecutionRuntime, execution_id: str) -> None:
        if scope.lease is not None:
            await self.repository.validate_execution_fence(execution_id, scope.lease)

    @staticmethod
    def _reject_writable_skill_script_copy(
        changes: list[dict[str, Any]], run_context: RunContext | None
    ) -> None:
        state = (
            run_context.session_state
            if run_context is not None and isinstance(run_context.session_state, dict)
            else {}
        )
        _migrate_legacy_task_execution_state(state)
        receipts = state.get(TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY)
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
                    "Skill 脚本只能通过 get_skill_script 读取或执行，不能在项目目录创建可写副本。"
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
        _changes: list[dict[str, Any]] | None = None,
        _scope: TaskExecutionRuntime | None = None,
    ) -> dict[str, Any]:
        scope = _scope or await self.scope(run_context)
        if path is not None:
            path = assert_task_workspace_path(
                normalize_workspace_path(path, allow_root=False)
            )
        if mode == "patch":
            if not isinstance(patch, str) or not patch.strip():
                raise WorkspaceError("patch 模式必须提供完整补丁。")
            changes = (
                _changes
                if _changes is not None
                else await abuild_workspace_changes(self.service, scope.thread_id, patch)
            )
        elif mode == "replace":
            if not isinstance(path, str) or not isinstance(old_string, str) or not old_string:
                raise WorkspaceError("replace 模式必须提供 path 和非空 old_string。")
            if not isinstance(new_string, str) or not isinstance(replace_all, bool):
                raise WorkspaceError("replace 模式参数无效。")

            file_content, _mime = await self.service.afile_bytes(scope.thread_id, path)
            try:
                original = file_content.decode("utf-8")
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
            changes = (
                []
                if updated == original
                else [
                    {
                        "operation": "update",
                        "path": path,
                        "content": updated,
                        "expected_sha256": hashlib.sha256(file_content).hexdigest(),
                    }
                ]
            )
            replacements = count if replace_all else 1
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
                    "expected_sha256": validate_patch_hash(expected_sha256),
                }
            ]
        else:
            raise WorkspaceError("patch mode 只支持 create、overwrite、replace 或 patch。")
        for change in changes:
            change_path = change.get("path")
            if not isinstance(change_path, str):
                raise WorkspaceError("补丁变更缺少工作区路径。")
            assert_task_workspace_path(
                normalize_workspace_path(change_path, allow_root=False)
            )
        if not changes:
            return {
                "ok": False,
                "status": "rejected",
                "code": "tool_no_progress",
                "message": "替换后的文件内容没有变化，本次未记录 mutation。",
                "details": {"mutationSequence": scope.task.mutation_sequence},
                "requiredActions": ["不要重写该文件；继续执行下一项未完成工作或正式验证。"],
                "retryable": True,
            }
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
            result = await self.service.aapply_changes(scope.thread_id, changes)
            applied = True
            await self._check_fence(scope, execution_id)
            await self.repository.update_execution(
                execution_id,
                status="completed",
                exit_code=0,
                operation_receipt=receipt,
            )
        except Exception as error:
            if not applied:
                await self.repository.update_execution(
                    execution_id,
                    status="failed",
                    exit_code=1,
                    operation_receipt=receipt,
                )
                raise
            # 文件已经写入。能按回执确认结果时立刻落到终态，避免 reserved 挡住收尾；
            # 确认不了则保持非终态，交给周期清理。
            if not await self._settle_applied_patch(execution_id, receipt):
                raise
            logger.warning(
                "task_patch_settled_after_bookkeeping_error execution_id={} error_type={}",
                execution_id,
                type(error).__name__,
            )
        return {
            **result,
            "ok": True,
            "execution_id": execution_id,
            "mutation_sequence": mutation_sequence,
            **({"replacements": replacements} if mode == "replace" else {}),
        }

    async def finish_task(
        self,
        summary: str | None,
        artifact_paths: list[str] | None,
        verification_ids: list[str] | None,
        service_sessions: list[dict[str, str]],
        run_context: RunContext | None,
        finish_function: Function,
        *,
        _scope: TaskExecutionRuntime | None = None,
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
        # 本地工作区不运行验证命令，验收以产物身份与任务状态为准。
        verification_ids = []
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
        previous_failure = state.get(TASK_EXECUTION_FINISH_FAILURE_STATE_KEY)
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

        verification_details: list[dict[str, Any]] = []
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
                state[TASK_EXECUTION_FINISH_FAILURE_STATE_KEY] = failure_state
                return self._finish_no_progress(
                    code,
                    result["details"],
                    result["requiredActions"],
                )
            state[TASK_EXECUTION_FINISH_FAILURE_STATE_KEY] = failure_state
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
                normalize_workspace_path(path, allow_root=False)
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
        artifacts = await self.service.abatch_hash_files(scope.thread_id, artifact_paths)
        missing_paths = [item["path"] for item in artifacts if item.get("missing")]
        if missing_paths:
            return reject(
                "finish_artifact_missing",
                "交付产物不存在或已发生变化。",
                details={"missingPaths": missing_paths[:MAX_FINISH_ARTIFACTS]},
                required_actions=[
                    "核对 details.missingPaths：若路径声明错误，下一次 finish_task 使用实际存在的 "
                    "artifact_paths；若确为必需产物，先生成再用实际存在路径重新提交。"
                ],
                progress_state={"missingPaths": missing_paths},
            )
        artifacts = [item for item in artifacts if not item.get("missing")]

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

        payload: dict[str, Any] = {
            "summary": summary.strip(),
            "artifacts": artifacts,
            "verificationIds": verification_ids,
            "serviceSessions": service_sessions,
        }
        try:
            current_artifacts = await self.service.abatch_hash_files(
                scope.thread_id, artifact_paths
            )
        except WorkspaceError:
            return reject(
                "finish_workspace_changed",
                "当前工作区或交付产物在验收期间发生变化。",
                required_actions=["确认工作区稳定后重新提交。"],
                progress_state={"artifactPaths": artifact_paths},
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
        except TaskExecutionRepositoryError as error:
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
        state[TASK_EXECUTION_FINISH_STATE_KEY] = payload
        state.pop(TASK_EXECUTION_FINISH_FAILURE_STATE_KEY, None)
        finish_function.stop_after_tool_call = True
        return {"ok": True, "status": "accepted", **payload}

    @staticmethod
    def _finish_fingerprint(
        scope: TaskExecutionRuntime,
        mutation_sequence: int,
        plan: Any,
        summary: Any,
        artifact_paths: Any,
        verification_ids: Any,
        service_sessions: Any,
        executions: list[TaskExecution],
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
        scope: TaskExecutionRuntime,
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
