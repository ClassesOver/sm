"""Private stdio client for an explicitly configured DSH ACP process."""

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path


class ReportAcpError(RuntimeError):
    pass


class ReportAcpClient:
    """Own one child process and serialize requests for one report conversation."""

    def __init__(
        self, command: tuple[str, ...], cwd: Path, *,
        env: Mapping[str, str] | None = None, timeout: float = 90,
    ):
        self._command = command
        self._cwd = str(cwd.resolve())
        self._env = env
        self._timeout = timeout
        self._process = None
        self._session_id = None
        self._request_id = 0
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        self._process = await asyncio.create_subprocess_exec(
            *self._command, cwd=self._cwd, env=self._env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=1024 * 1024,
        )
        return self

    async def __aexit__(self, *_):
        await self.aclose()

    async def aclose(self):
        process, self._process = self._process, None
        self._session_id = None
        if process is None:
            return
        # The peer may have exited or closed stdin before cleanup begins.
        try:
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass
        try:
            await asyncio.wait_for(process.communicate(), 3)
        except (BrokenPipeError, ConnectionResetError):
            # Preserve the original protocol error if the child died abruptly.
            await process.wait()
        except TimeoutError:
            if process.returncode is None:
                process.kill()
            try:
                await process.communicate()
            except (BrokenPipeError, ConnectionResetError):
                await process.wait()

    async def open_session(self, resume: str | None = None) -> str:
        async with self._lock:
            if self._session_id is not None:
                raise ReportAcpError("ACP session already open")
            init = await self._call("initialize", {
                "protocolVersion": 1, "clientCapabilities": {},
            })
            if init.get("protocolVersion") != 1:
                raise ReportAcpError("Unsupported ACP protocol version")
            params = {"cwd": self._cwd, "mcpServers": []}
            if resume is not None:
                await self._call("session/resume", {**params, "sessionId": resume})
                session_id = resume
            else:
                session_id = (await self._call("session/new", params)).get("sessionId")
            if not isinstance(session_id, str) or not session_id:
                raise ReportAcpError("ACP peer did not return a session ID")
            self._session_id = session_id
            return session_id

    async def prompt(self, text: str, *, on_chunk: Callable[[str], None] | None = None) -> str:
        async with self._lock:
            if self._session_id is None:
                raise ReportAcpError("No ACP session is open")
            parts: list[str] = []
            size = 0

            def update(params: dict):
                nonlocal size
                if params.get("sessionId") != self._session_id:
                    return
                event = params.get("update", {})
                if not isinstance(event, dict):
                    raise ReportAcpError("Invalid ACP session update")
                content = event.get("content", {})
                if event.get("sessionUpdate") != "agent_message_chunk":
                    return
                if not isinstance(content, dict):
                    raise ReportAcpError("Invalid ACP message chunk")
                if content.get("type") == "text":
                    chunk = content.get("text")
                    if isinstance(chunk, str):
                        size += len(chunk)
                        if size > 262144:
                            raise ReportAcpError("ACP reply is too large")
                        parts.append(chunk)
                        if on_chunk is not None:
                            on_chunk(chunk)

            result = await self._call("session/prompt", {
                "sessionId": self._session_id,
                "prompt": [{"type": "text", "text": text}],
            }, update)
            if result.get("stopReason") != "end_turn":
                raise ReportAcpError("ACP turn did not finish normally")
            return "".join(parts)

    async def _call(self, method: str, params: dict, on_update=None) -> dict:
        process = self._process
        if process is None:
            raise ReportAcpError("ACP process is closed")
        self._request_id += 1
        request_id = self._request_id

        async def send(message):
            process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}).encode() + b"\n")
            await process.stdin.drain()

        try:
            async with asyncio.timeout(self._timeout):
                await send({"id": request_id, "method": method, "params": params})
                while True:
                    try:
                        line = await process.stdout.readline()
                        if not line:
                            raise ReportAcpError("ACP peer disconnected")
                        message = json.loads(line)
                    except (ValueError, UnicodeError):
                        raise ReportAcpError("Invalid ACP frame") from None
                    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                        raise ReportAcpError("Invalid ACP frame")
                    if "method" in message and "id" in message:
                        await send({"id": message["id"], "error": {
                            "code": -32601, "message": "Client operation unavailable",
                        }})
                    elif message.get("method") == "session/update" and on_update is not None:
                        update_params = message.get("params")
                        if not isinstance(update_params, dict):
                            raise ReportAcpError("Invalid ACP session update")
                        on_update(update_params)
                    elif message.get("id") == request_id:
                        result = message.get("result")
                        if isinstance(result, dict) and "error" not in message:
                            return result
                        raise ReportAcpError(f"ACP {method} failed")
        except (Exception, asyncio.CancelledError):
            await self.aclose()
            raise
