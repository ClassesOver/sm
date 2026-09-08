from __future__ import annotations

import re
import shlex
import uuid
from typing import Any

from daytona import SessionExecuteRequest
from daytona.common.errors import DaytonaNotFoundError

from ..async_utils import complete_cleanup
from ..sandbox import (
    ExecutionStatus,
    SandboxNotFound,
    SessionCommandRequest,
    SessionRef,
)
from ..workspace import (
    MANAGED_PROCESS_PREFIX,
    MAX_TOOL_OUTPUT_BYTES,
    WorkspaceError,
    WorkspaceProcessNotFound,
    WorkspaceService,
)

MAX_MANAGED_PROCESSES = 4
MANAGED_TIMEOUT_ENV = "AGENT_MANAGED_TIMEOUT_MARKER"
MANAGED_TIMEOUT_OUTPUT_PREFIX = "__AGENT_MANAGED_TIMEOUT__"


class ManagedProcessRuntime:
    """TaskExecutionKernel 使用的受管进程原语，不向模型注册工具。"""

    def __init__(self, service: WorkspaceService) -> None:
        self._service = service

    @staticmethod
    def _validate_ids(session_id: str, command_id: str) -> tuple[str, str]:
        suffix = session_id[len(MANAGED_PROCESS_PREFIX) :] if isinstance(session_id, str) else ""
        if (
            not isinstance(session_id, str)
            or not session_id.startswith(MANAGED_PROCESS_PREFIX)
            or len(suffix) != 32
            or any(character not in "0123456789abcdef" for character in suffix)
        ):
            raise WorkspaceError("后台进程会话标识无效。")
        if (
            not isinstance(command_id, str)
            or not 1 <= len(command_id) <= 128
            or not command_id.isascii()
            or any(not (character.isalnum() or character in "-_.") for character in command_id)
        ):
            raise WorkspaceError("后台进程命令标识无效。")
        return session_id, command_id

    @classmethod
    async def get_command(cls, process: Any, session_id: str, command_id: str) -> Any:
        session_id, command_id = cls._validate_ids(session_id, command_id)
        try:
            session = await process.get_session(session_id)
        except (DaytonaNotFoundError, SandboxNotFound) as error:
            raise WorkspaceProcessNotFound("后台进程不属于当前会话或已经结束。") from error
        commands = getattr(session, "commands", None)
        if commands is not None and command_id not in {
            str(getattr(command, "id", "") or "") for command in commands
        }:
            raise WorkspaceProcessNotFound("后台进程不属于当前会话或已经结束。")
        try:
            return await process.get_session_command(session_id, command_id)
        except (DaytonaNotFoundError, SandboxNotFound) as error:
            raise WorkspaceProcessNotFound("后台进程不属于当前会话或已经结束。") from error

    async def start_session(
        self,
        process: Any,
        thread_id: str,
        request: SessionExecuteRequest,
        session_id: str | None = None,
    ) -> tuple[str, str, Any]:
        lock_key = f"agent-managed-processes:{self._service._hash(thread_id)}"
        async with self._service.async_registry.locked(lock_key):
            active = 0
            for session in await process.list_sessions():
                existing_session_id = str(getattr(session, "session_id", "") or "")
                if not existing_session_id.startswith(MANAGED_PROCESS_PREFIX):
                    continue
                commands = getattr(session, "commands", None)
                if commands is None:
                    if getattr(session, "status", None) == ExecutionStatus.RUNNING:
                        active += 1
                    continue
                commands = list(commands)
                if not commands:
                    await process.delete_session(existing_session_id)
                elif any(getattr(command, "exit_code", None) is None for command in commands):
                    active += 1
            if active >= MAX_MANAGED_PROCESSES:
                raise WorkspaceError(
                    f"当前对话已有 {MAX_MANAGED_PROCESSES} 个后台进程，请轮询或终止后再启动。"
                )
            session_id = session_id or f"{MANAGED_PROCESS_PREFIX}{uuid.uuid4().hex}"
            self._validate_ids(session_id, "pending")
            session = await process.create_session(session_id)
            try:
                # provider 返回 SessionRef，并只接受仓库内的稳定命令契约；旧 Daytona SDK
                # create_session 返回 None，且启动调用仍需 5 秒传输超时。这里以返回类型
                # 区分两条仍在使用的边界，避免通过捕获 TypeError 掩盖后端真实参数错误。
                if isinstance(session, SessionRef):
                    value = await process.execute_session_command(
                        session_id,
                        SessionCommandRequest(
                            command=request.command,
                            run_async=bool(request.run_async),
                            suppress_input_echo=bool(request.suppress_input_echo),
                        ),
                    )
                    command_id = str(getattr(value, "command_id", "") or "")
                else:
                    value = await process.execute_session_command(session_id, request, timeout=5)
                    command_id = str(getattr(value, "cmd_id", "") or "")
                self._validate_ids(session_id, command_id)
            except BaseException:
                try:
                    await complete_cleanup(process.delete_session(session_id))
                except Exception:
                    pass
                raise
            return session_id, command_id, value

    @staticmethod
    def format_output(
        value: Any,
        *,
        session_id: str,
        command_id: str,
        status: str,
        exit_code: int | None,
        offset: int = 0,
        max_bytes: int = MAX_TOOL_OUTPUT_BYTES,
        wall_time_seconds: float | None = None,
        timeout_marker: str | None = None,
    ) -> dict[str, Any]:
        stdout = str(getattr(value, "stdout", "") or "")
        stderr = str(getattr(value, "stderr", "") or "")
        output = (
            stdout + (("\n" if stdout and stderr else "") + stderr)
            if stdout or stderr
            else re.sub(
                r"(?m)^(?:\x01{1,3}|\x02{1,3})",
                "",
                str(getattr(value, "output", "") or ""),
            )
        )
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise WorkspaceError("后台日志偏移必须是大于等于 0 的整数。")
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 1 <= max_bytes <= MAX_TOOL_OUTPUT_BYTES
        ):
            raise WorkspaceError(
                f"后台日志单次读取字节数必须是 1 至 {MAX_TOOL_OUTPUT_BYTES} 之间的整数。"
            )
        marker_output = (
            ManagedProcessRuntime.timeout_output_marker(timeout_marker) if timeout_marker else None
        )
        raw_output = str(output or "")
        timed_out = bool(marker_output and marker_output in raw_output)
        if marker_output:
            raw_output = raw_output.replace(marker_output, "")
        encoded = raw_output.encode("utf-8", errors="replace")
        total_bytes = len(encoded)
        if offset > total_bytes:
            raise WorkspaceError("后台日志偏移超过当前日志大小，请使用返回的 nextOffset。")
        try:
            encoded[:offset].decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkspaceError(
                "后台日志偏移不是 UTF-8 字符边界，请使用返回的 nextOffset。"
            ) from error
        end = min(total_bytes, offset + max_bytes)
        while end > offset:
            try:
                selected = encoded[offset:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            selected = ""
        if not selected and offset < total_bytes:
            raise WorkspaceError(
                "后台日志单次读取字节数不足以容纳下一个 UTF-8 字符，请增大 max_bytes。"
            )
        has_more = end < total_bytes
        result: dict[str, Any] = {
            "sessionId": session_id,
            "commandId": command_id,
            "status": status,
            "exitCode": exit_code,
            "output": selected,
            "offset": offset,
            "nextOffset": end,
            "totalBytes": total_bytes,
            "originalBytes": total_bytes,
            "hasMore": has_more,
            "truncated": has_more,
        }
        if wall_time_seconds is not None:
            result["wallTimeSeconds"] = round(max(0.0, wall_time_seconds), 3)
        if timed_out:
            result["timedOut"] = True
        return result

    @staticmethod
    def timeout_output_marker(marker: str) -> str:
        return f"\n{MANAGED_TIMEOUT_OUTPUT_PREFIX}:{marker}\n"

    @staticmethod
    def timeout_marker(command: Any) -> str | None:
        try:
            wrapper = shlex.split(str(getattr(command, "command", "") or ""))
        except ValueError:
            return None
        prefix = f"{MANAGED_TIMEOUT_ENV}="
        for token in wrapper:
            if token.startswith(prefix):
                marker = token.removeprefix(prefix)
                if len(marker) == 32 and all(
                    character in "0123456789abcdef" for character in marker
                ):
                    return marker
        return None
