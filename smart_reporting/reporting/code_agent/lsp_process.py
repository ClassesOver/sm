"""正式 Workspace 复用的 python-lsp-server stdio JSON-RPC 客户端。"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any

from loguru import logger


class ReportingLspProcessError(RuntimeError):
    """pylsp 生命周期或 JSON-RPC 协议不可用。"""


@dataclass(slots=True)
class _LspState:
    root: Path
    process: asyncio.subprocess.Process
    pending: dict[int, asyncio.Future[Any]] = field(default_factory=dict)
    diagnostics: dict[tuple[str, int], asyncio.Future[list[dict[str, Any]]]] = field(
        default_factory=dict
    )
    document_versions: dict[str, int] = field(default_factory=dict)
    reader_task: asyncio.Task[None] | None = None
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    document_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=monotonic)
    active_requests: int = 0
    closed: bool = False


class ReportingLspProcessManager:
    """按正式 Workspace root 管理 pylsp，并提供最小 JSON-RPC 请求能力。"""

    def __init__(
        self,
        *,
        command: tuple[str, ...] | None = None,
        request_timeout_seconds: float = 10,
        idle_ttl_seconds: float = 10 * 60,
    ) -> None:
        self.command = command or (sys.executable, "-m", "pylsp")
        self.request_timeout_seconds = request_timeout_seconds
        self.idle_ttl_seconds = idle_ttl_seconds
        self._states: dict[Path, _LspState] = {}
        self._states_lock = asyncio.Lock()
        self._start_locks: dict[Path, asyncio.Lock] = {}
        self._next_request_id = 1
        self._closed = False
        self._reaper_task: asyncio.Task[None] | None = None

    async def request(self, root: Path, method: str, params: dict[str, Any]) -> Any:
        state = await self._state(root)
        state.active_requests += 1
        try:
            return await self._request(state, method, params)
        finally:
            state.active_requests = max(state.active_requests - 1, 0)

    async def diagnostics(
        self, root: Path, uri: str, text: str
    ) -> tuple[int, list[dict[str, Any]]]:
        state = await self._state(root)
        state.active_requests += 1
        version = 0
        try:
            loop = asyncio.get_running_loop()
            waiter: asyncio.Future[list[dict[str, Any]]] = loop.create_future()
            async with state.document_lock:
                version = state.document_versions.get(uri, 0) + 1
                state.document_versions[uri] = version
                state.diagnostics[(uri, version)] = waiter
                await self._publish_document(state, uri, text, version)
            try:
                diagnostics = await asyncio.wait_for(waiter, timeout=self.request_timeout_seconds)
            except (TimeoutError, ReportingLspProcessError) as error:
                raise ReportingLspProcessError("pylsp diagnostics 未响应。") from error
        finally:
            state.diagnostics.pop((uri, version), None)
            state.active_requests = max(state.active_requests - 1, 0)
        return version, diagnostics

    async def synchronize_document(self, root: Path, uri: str, text: str) -> int:
        state = await self._state(root)
        state.active_requests += 1
        try:
            async with state.document_lock:
                version = state.document_versions.get(uri, 0) + 1
                state.document_versions[uri] = version
                await self._publish_document(state, uri, text, version)
                return version
        finally:
            state.active_requests = max(state.active_requests - 1, 0)

    async def _publish_document(
        self, state: _LspState, uri: str, text: str, version: int
    ) -> None:
        if version == 1:
            await self._notify(
                state,
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "version": version,
                        "text": text,
                        "languageId": "python",
                    }
                },
            )
            return
        await self._notify(
            state,
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [{"text": text}],
            },
        )

    async def reap_idle(self) -> None:
        now = monotonic()
        async with self._states_lock:
            expired = [
                state
                for state in self._states.values()
                if state.active_requests == 0
                and now - state.last_used >= self.idle_ttl_seconds
            ]
            for state in expired:
                self._states.pop(state.root, None)
        for state in expired:
            await self._close_state(state)

    async def aclose(self) -> None:
        self._closed = True
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
            self._reaper_task = None
        async with self._states_lock:
            start_locks = tuple(self._start_locks.values())
        for start_lock in start_locks:
            async with start_lock:
                pass
        async with self._states_lock:
            states = list(self._states.values())
            self._states.clear()
            self._start_locks.clear()
        for state in states:
            await self._close_state(state)

    async def _state(self, root: Path) -> _LspState:
        canonical_root = Path(root).resolve()
        async with self._states_lock:
            if self._closed:
                raise ReportingLspProcessError("pylsp 管理器已关闭。")
            if self._reaper_task is None:
                self._reaper_task = asyncio.create_task(self._reap_loop())
            state = self._states.get(canonical_root)
            if state is not None and state.process.returncode is None and not state.closed:
                state.last_used = monotonic()
                return state
            start_lock = self._start_locks.setdefault(canonical_root, asyncio.Lock())
        async with start_lock:
            async with self._states_lock:
                if self._closed:
                    raise ReportingLspProcessError("pylsp 管理器已关闭。")
                state = self._states.get(canonical_root)
                if state is not None and state.process.returncode is None and not state.closed:
                    state.last_used = monotonic()
                    return state
                if state is not None:
                    self._states.pop(canonical_root, None)
            if state is not None:
                await self._close_state(state)
            try:
                process = await asyncio.create_subprocess_exec(
                    *self.command,
                    cwd=str(canonical_root),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except (OSError, ValueError) as error:
                raise ReportingLspProcessError("pylsp 启动失败。") from error
            if process.stdin is None or process.stdout is None:
                await process.wait()
                raise ReportingLspProcessError("pylsp stdio 不可用。")
            created = _LspState(root=canonical_root, process=process)
            created.reader_task = asyncio.create_task(self._read_loop(created))
            try:
                await self._request(
                    created, "initialize", {"rootUri": canonical_root.as_uri(), "capabilities": {}}
                )
                await self._notify(created, "initialized", {})
            except ReportingLspProcessError:
                await self._close_state(created)
                raise
            async with self._states_lock:
                if self._closed:
                    await self._close_state(created)
                    raise ReportingLspProcessError("pylsp 管理器已关闭。")
                self._states[canonical_root] = created
            return created

    async def _reap_loop(self) -> None:
        interval = max(0.01, min(self.idle_ttl_seconds, 60.0))
        try:
            while not self._closed:
                await asyncio.sleep(interval)
                await self.reap_idle()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning(
                "report_lsp_idle_reaper_failed error_type={}", type(error).__name__
            )

    async def _request(self, state: _LspState, method: str, params: dict[str, Any]) -> Any:
        loop = asyncio.get_running_loop()
        request_id = self._next_request_id
        self._next_request_id += 1
        waiter: asyncio.Future[Any] = loop.create_future()
        state.pending[request_id] = waiter
        await self._send(
            state,
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )
        try:
            result = await asyncio.wait_for(waiter, timeout=self.request_timeout_seconds)
        except (TimeoutError, ReportingLspProcessError) as error:
            raise ReportingLspProcessError("pylsp 请求未响应。") from error
        finally:
            state.pending.pop(request_id, None)
        state.last_used = monotonic()
        return result

    async def _notify(self, state: _LspState, method: str, params: dict[str, Any]) -> None:
        await self._send(state, {"jsonrpc": "2.0", "method": method, "params": params})
        state.last_used = monotonic()

    async def _send(self, state: _LspState, payload: dict[str, Any]) -> None:
        if state.closed or state.process.returncode is not None or state.process.stdin is None:
            raise ReportingLspProcessError("pylsp 进程已退出。")
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        message = b"Content-Length: " + str(len(raw)).encode("ascii") + b"\r\n\r\n" + raw
        async with state.write_lock:
            try:
                state.process.stdin.write(message)
                await state.process.stdin.drain()
            except (BrokenPipeError, ConnectionError) as error:
                raise ReportingLspProcessError("pylsp 通信失败。") from error

    async def _read_loop(self, state: _LspState) -> None:
        try:
            while message := await self._read_message(state):
                self._handle_message(state, message)
        except (ValueError, KeyError, EOFError, json.JSONDecodeError) as error:
            logger.warning(
                "report_lsp_protocol_failed root={} error_type={}", state.root, type(error).__name__
            )
        finally:
            await self._mark_dead(state)

    async def _read_message(self, state: _LspState) -> dict[str, Any] | None:
        if state.process.stdout is None:
            return None
        headers: dict[str, str] = {}
        while True:
            line = await state.process.stdout.readline()
            if not line:
                return None
            if line == b"\r\n":
                break
            name, value = line.decode("ascii").split(":", 1)
            headers[name.lower()] = value.strip()
        size = int(headers["content-length"])
        return json.loads((await state.process.stdout.readexactly(size)).decode("utf-8"))

    def _handle_message(self, state: _LspState, message: dict[str, Any]) -> None:
        response_id = message.get("id")
        if isinstance(response_id, int):
            waiter = state.pending.get(response_id)
            if waiter is not None and not waiter.done():
                if "error" in message:
                    waiter.set_exception(ReportingLspProcessError("pylsp 返回协议错误。"))
                else:
                    waiter.set_result(message.get("result"))
            return
        if message.get("method") != "textDocument/publishDiagnostics":
            return
        params = message.get("params")
        if not isinstance(params, dict):
            return
        uri, version = params.get("uri"), params.get("version")
        if not isinstance(uri, str) or not isinstance(version, int):
            return
        waiter = state.diagnostics.get((uri, version))
        diagnostics = params.get("diagnostics")
        if waiter is not None and not waiter.done() and isinstance(diagnostics, list):
            waiter.set_result([item for item in diagnostics if isinstance(item, dict)])

    async def _mark_dead(self, state: _LspState) -> None:
        async with self._states_lock:
            if self._states.get(state.root) is state:
                self._states.pop(state.root, None)
        self._fail_waiters(state)

    async def _close_state(self, state: _LspState) -> None:
        if state.closed:
            return
        state.closed = True
        self._fail_waiters(state)
        if state.reader_task is not None and state.reader_task is not asyncio.current_task():
            state.reader_task.cancel()
        if state.process.returncode is None:
            state.process.terminate()
            try:
                await asyncio.wait_for(state.process.wait(), timeout=1)
            except TimeoutError:
                state.process.kill()
                await state.process.wait()

    @staticmethod
    def _fail_waiters(state: _LspState) -> None:
        error = ReportingLspProcessError("pylsp 进程已退出。")
        for waiter in (*state.pending.values(), *state.diagnostics.values()):
            if not waiter.done():
                waiter.set_exception(error)


__all__ = ["ReportingLspProcessError", "ReportingLspProcessManager"]
