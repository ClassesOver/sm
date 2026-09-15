"""正式 Workspace 的只读 python-lsp-server 适配。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from loguru import logger

from ...workspace import WorkspaceError
from ..models import ReportingError
from .context import ReportingCodingTaskBinding
from .lsp_process import ReportingLspProcessError, ReportingLspProcessManager

MAX_HOVER_BYTES = 2048


class ReportingWorkspaceLsp:
    def __init__(
        self,
        binding: ReportingCodingTaskBinding,
        manager: ReportingLspProcessManager,
    ) -> None:
        # Manager 在构造阶段固定，避免请求期间懒创建和并发竞态。
        self.binding, self.manager = binding, manager

    async def diagnostics(
        self, path: str | None = None, *, expected_source_sha256: str | None = None
    ) -> dict[str, Any]:
        path, source, sha = await self._source(path)
        if failure := self._expected(expected_source_sha256, sha):
            return failure
        try:
            _, diagnostics = await self.manager.diagnostics(
                self.binding.context.workspace_root, self._uri(path), source
            )
        except ReportingLspProcessError:
            return self._unavailable(path, sha)
        return {"ok": True, "path": path, "diagnostics": diagnostics, "sourceSha256": sha}

    async def hover(
        self, path: str, *, line: int, character: int, expected_source_sha256: str | None = None
    ) -> dict[str, Any]:
        path, source, sha = await self._source(path)
        if failure := self._expected(expected_source_sha256, sha):
            return failure
        value = await self._request(path, source, "textDocument/hover", line, character, sha)
        if isinstance(value, dict) and value.get("ok") is False:
            return value
        text = self._contents(value.get("contents") if isinstance(value, dict) else None)
        if not text:
            return {"ok": True, "found": False, "sourceSha256": sha}
        return {"ok": True, "found": True, "contents": text, "sourceSha256": sha}

    async def definition(
        self, path: str, *, line: int, character: int, expected_source_sha256: str | None = None
    ) -> dict[str, Any]:
        return await self._locations(
            path, line, character, expected_source_sha256, "textDocument/definition"
        )

    async def references(
        self, path: str, *, line: int, character: int, expected_source_sha256: str | None = None
    ) -> dict[str, Any]:
        return await self._locations(
            path, line, character, expected_source_sha256, "textDocument/references"
        )

    async def document_symbols(
        self, path: str, *, expected_source_sha256: str | None = None
    ) -> dict[str, Any]:
        path, source, sha = await self._source(path)
        if failure := self._expected(expected_source_sha256, sha):
            return failure
        value = await self._request(path, source, "textDocument/documentSymbol", None, None, sha)
        if isinstance(value, dict) and value.get("ok") is False:
            return value
        symbols = []
        for item in value or []:
            if isinstance(item, dict):
                location = item.get("location") or {}
                position = (
                    item.get("range") or item.get("selectionRange") or location.get("range") or {}
                ).get("start", {})
                line = position.get("line", 0)
                character = position.get("character", 0)
                name = str(item.get("name", ""))
                if isinstance(line, int) and 0 <= line < len(source.splitlines()):
                    source_line = source.splitlines()[line]
                    found = source_line.find(name)
                    if found >= 0:
                        character = found
                symbols.append(
                    {
                        "name": name,
                        "kind": item.get("kind", "symbol"),
                        "line": line,
                        "character": character,
                    }
                )
        return {"ok": True, "path": path, "symbols": symbols, "sourceSha256": sha}

    async def _locations(
        self, path: str, line: int, character: int, expected: str | None, method: str
    ) -> dict[str, Any]:
        path, source, sha = await self._source(path)
        if failure := self._expected(expected, sha):
            return failure
        value = await self._request(path, source, method, line, character, sha)
        if isinstance(value, dict) and value.get("ok") is False:
            return value
        raw = value if isinstance(value, list) else [value] if value else []
        locations = [self._location(item) for item in raw if isinstance(item, dict)]
        return {"ok": True, "locations": locations, "sourceSha256": sha}

    async def _request(
        self, path: str, source: str, method: str, line: int | None, character: int | None, sha: str
    ) -> Any:
        try:
            manager = self.manager
            root = self.binding.context.workspace_root
            uri = self._uri(path)
            await manager.synchronize_document(root, uri, source)
            params: dict[str, Any] = {"textDocument": {"uri": uri}}
            if line is not None:
                params["position"] = {"line": line, "character": character}
            if method == "textDocument/references":
                params["context"] = {"includeDeclaration": True}
            return await manager.request(root, method, params)
        except ReportingLspProcessError:
            return self._unavailable(path, sha)

    async def _source(self, path: str | None) -> tuple[str, str, str]:
        path = self.binding.context.script_path if path is None else self._path(path)
        if not path.endswith(".py"):
            raise ReportingError("report_lsp_invalid_request", "LSP 仅支持 Python 文件。")
        try:
            raw = await self.binding.workspace.read_limited_regular_file(
                self.binding.context.task_id, path, max_bytes=self.binding.context.max_source_bytes
            )
            return path, raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()
        except (WorkspaceError, UnicodeDecodeError) as error:
            raise ReportingError(
                "report_lsp_file_invalid", "LSP 读取工作区 Python 文件失败。"
            ) from error

    def _path(self, path: str) -> str:
        if not isinstance(path, str) or not path:
            raise ReportingError("report_lsp_invalid_request", "LSP 路径无效。")
        try:
            return self.binding.workspace.paths.normalize(path)
        except (WorkspaceError, TypeError) as error:
            raise ReportingError(
                "report_lsp_invalid_request", "LSP 路径必须位于当前工作区。"
            ) from error

    def _uri(self, path: str) -> str:
        return (self.binding.context.workspace_root / path).resolve().as_uri()

    @staticmethod
    def _expected(expected: str | None, actual: str) -> dict[str, Any] | None:
        if expected is not None and (not isinstance(expected, str) or len(expected) != 64):
            return {
                "ok": False,
                "code": "report_lsp_invalid_request",
                "message": "LSP 文件版本无效。",
                "sourceSha256": actual,
            }
        if expected is not None and expected != actual:
            return {
                "ok": False,
                "code": "report_lsp_document_version_mismatch",
                "message": "LSP 请求对应的脚本版本已变化，请重新读取后重试。",
                "sourceSha256": actual,
            }
        return None

    def _unavailable(self, path: str, sha: str) -> dict[str, Any]:
        logger.warning(
            "report_lsp_unavailable workspace_key={} path={}",
            self.binding.context.workspace_key,
            path,
        )
        return {
            "ok": False,
            "code": "report_lsp_unavailable",
            "message": "Python LSP 当前不可用。",
            "sourceSha256": sha,
        }

    def _location(self, item: dict[str, Any]) -> dict[str, Any]:
        nested = item.get("location") or {}
        uri = item.get("targetUri") or item.get("uri") or nested.get("uri")
        position = (
            item.get("targetSelectionRange") or item.get("range") or nested.get("range") or {}
        ).get("start", {})
        try:
            path = (
                Path(str(uri).removeprefix("file://"))
                .resolve()
                .relative_to(self.binding.context.workspace_root.resolve())
                .as_posix()
            )
        except (OSError, ValueError, WorkspaceError):
            return {"outsideWorkspace": True}
        path = self.binding.workspace.paths.normalize(path)
        return {
            "path": path,
            "line": position.get("line", 0),
            "character": position.get("character", 0),
            "kind": "symbol",
        }

    @staticmethod
    def _contents(value: Any) -> str:
        if isinstance(value, str):
            return value.encode()[:MAX_HOVER_BYTES].decode(errors="ignore")
        if isinstance(value, dict):
            return ReportingWorkspaceLsp._contents(value.get("value"))
        if isinstance(value, list):
            return "\n".join(ReportingWorkspaceLsp._contents(item) for item in value)
        return ""


__all__ = ["ReportingWorkspaceLsp"]
