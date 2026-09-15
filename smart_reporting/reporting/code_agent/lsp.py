"""正式 Reporting Workspace 的只读 Python 代码理解能力。"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import anyio
from loguru import logger

from ...workspace import WorkspaceError
from ..models import ReportingError
from .context import ReportingCodingTaskBinding

try:
    import jedi
except ImportError:  # pragma: no cover - 覆盖由部署环境决定。
    jedi = None


MAX_HOVER_BYTES = 2 * 1024
MAX_LOCATIONS = 100
MAX_SYMBOLS = 200


def _failure(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "message": message}


def _bounded_text(value: str, maximum: int) -> str:
    return value.encode("utf-8")[:maximum].decode("utf-8", errors="ignore")


class ReportingWorkspaceLsp:
    """以 task binding 限定读取范围的 Jedi 适配器。

    该最小实现不拥有 LSP 子进程，也不会写入或同步 Workspace；每次请求使用
    当前磁盘快照创建 Jedi Script，因而不会返回陈旧草稿的分析结果。
    """

    def __init__(self, binding: ReportingCodingTaskBinding) -> None:
        self.binding = binding

    @property
    def _workspace_root(self) -> Path:
        return self.binding.context.workspace_root

    async def diagnostics(self, path: str | None = None) -> dict[str, Any]:
        relative, source = await self._source(path)
        try:
            ast.parse(source, filename=relative)
        except SyntaxError as error:
            return {
                "ok": True,
                "path": relative,
                "sourceSha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "diagnostics": [
                    {
                        "code": "syntax-error",
                        "severity": "error",
                        "line": max(0, (error.lineno or 1) - 1),
                        "character": max(0, (error.offset or 1) - 1),
                        "message": error.msg,
                    }
                ],
            }
        return {
            "ok": True,
            "path": relative,
            "sourceSha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "diagnostics": [],
        }

    async def hover(self, path: str, *, line: int, character: int) -> dict[str, Any]:
        relative, source = await self._source(path)
        request = self._position(source, line, character)
        result = await self._jedi_call(
            source,
            relative,
            lambda script: script.infer(*request),
        )
        if isinstance(result, dict):
            return result
        definitions = tuple(result)
        if not definitions:
            return {"ok": True, "found": False}
        first = definitions[0]
        location = self._location(first)
        if location.get("outsideWorkspace"):
            return {"ok": True, "found": True, "outsideWorkspace": True}
        parts = [str(getattr(first, "description", "") or "")]
        docstring = str(getattr(first, "docstring", lambda: "")() or "")
        if docstring and docstring not in parts:
            parts.append(docstring)
        contents = _bounded_text("\n\n".join(part for part in parts if part), MAX_HOVER_BYTES)
        return {"ok": True, "found": True, "contents": contents, "location": location}

    async def definition(self, path: str, *, line: int, character: int) -> dict[str, Any]:
        return await self._locations(path, line, character, lambda script, request: script.goto(*request))

    async def references(self, path: str, *, line: int, character: int) -> dict[str, Any]:
        return await self._locations(
            path,
            line,
            character,
            lambda script, request: script.get_references(*request),
        )

    async def document_symbols(self, path: str) -> dict[str, Any]:
        relative, source = await self._source(path)
        result = await self._jedi_call(
            source,
            relative,
            lambda script: script.get_names(all_scopes=True, definitions=True, references=False),
        )
        if isinstance(result, dict):
            return result
        symbols = [
            {
                "name": str(item.name),
                "kind": str(item.type),
                "line": max(0, int(item.line) - 1),
                "character": max(0, int(item.column)),
            }
            for item in result
            if self._location(item).get("path") == relative
        ]
        symbols.sort(key=lambda item: (item["line"], item["character"], item["name"], item["kind"]))
        return {"ok": True, "path": relative, "symbols": symbols[:MAX_SYMBOLS]}

    async def _locations(
        self,
        path: str,
        line: int,
        character: int,
        operation: Callable[[Any, tuple[int, int]], Iterable[Any]],
    ) -> dict[str, Any]:
        relative, source = await self._source(path)
        request = self._position(source, line, character)
        result = await self._jedi_call(source, relative, lambda script: operation(script, request))
        if isinstance(result, dict):
            return result
        locations = self._unique_locations(result)
        return {"ok": True, "locations": locations}

    async def _source(self, path: str | None) -> tuple[str, str]:
        relative = self.binding.context.script_path if path is None else self._path(path)
        if not relative.endswith(".py"):
            raise ReportingError("report_lsp_invalid_request", "LSP 仅支持 Python 文件。")
        try:
            raw = await self.binding.workspace.read_limited_regular_file(
                self.binding.context.task_id,
                relative,
                max_bytes=self.binding.context.max_source_bytes,
            )
        except WorkspaceError as error:
            raise ReportingError("report_lsp_file_invalid", "LSP 读取工作区 Python 文件失败。") from error
        try:
            return relative, raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReportingError("report_lsp_file_invalid", "LSP 文件不是有效的 UTF-8 文本。") from error

    def _path(self, path: str) -> str:
        if not isinstance(path, str) or not path:
            raise ReportingError("report_lsp_invalid_request", "LSP 路径无效。")
        try:
            return self.binding.workspace.paths.normalize(path)
        except WorkspaceError as error:
            raise ReportingError("report_lsp_invalid_request", "LSP 路径必须位于当前工作区。") from error

    @staticmethod
    def _position(source: str, line: int, character: int) -> tuple[int, int]:
        if (
            isinstance(line, bool)
            or isinstance(character, bool)
            or not isinstance(line, int)
            or not isinstance(character, int)
            or line < 0
            or character < 0
        ):
            raise ReportingError("report_lsp_invalid_request", "LSP 位置必须是非负整数。")
        lines = source.splitlines()
        if line >= len(lines) or character > len(lines[line]):
            raise ReportingError("report_lsp_invalid_request", "LSP 位置超出文件范围。")
        return line + 1, character

    async def _jedi_call(
        self,
        source: str,
        relative: str,
        operation: Callable[[Any], Iterable[Any]],
    ) -> tuple[Any, ...] | dict[str, Any]:
        if jedi is None:
            return _failure("report_lsp_unavailable", "Python LSP 当前不可用。")

        def run() -> tuple[Any, ...]:
            script = jedi.Script(
                code=source,
                path=str(self._workspace_root / relative),
                project=jedi.Project(path=str(self._workspace_root)),
            )
            return tuple(operation(script))

        try:
            return await anyio.to_thread.run_sync(run)
        except Exception as error:
            logger.warning(
                "report_lsp_jedi_failed workspace_key={} path={} error_type={}",
                self.binding.context.workspace_key,
                relative,
                type(error).__name__,
            )
            return _failure("report_lsp_unavailable", "Python LSP 当前不可用。")

    def _location(self, item: Any) -> dict[str, Any]:
        module_path = getattr(item, "module_path", None)
        if module_path is None:
            return {"outsideWorkspace": True}
        try:
            relative = Path(module_path).resolve().relative_to(self._workspace_root.resolve())
            path = self.binding.workspace.paths.normalize(relative.as_posix())
        except (OSError, ValueError, WorkspaceError):
            return {"outsideWorkspace": True}
        return {
            "path": path,
            "line": max(0, int(getattr(item, "line", 1)) - 1),
            "character": max(0, int(getattr(item, "column", 0))),
            "kind": str(getattr(item, "type", "unknown")),
        }

    def _unique_locations(self, items: Iterable[Any]) -> list[dict[str, Any]]:
        locations: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
        for item in items:
            location = self._location(item)
            locations[tuple(sorted(location.items()))] = location
        return sorted(
            locations.values(),
            key=lambda item: (
                item.get("outsideWorkspace", False),
                item.get("path", ""),
                item.get("line", -1),
                item.get("character", -1),
                item.get("kind", ""),
            ),
        )[:MAX_LOCATIONS]


__all__ = ["ReportingWorkspaceLsp"]
