"""Reporting 会话专属的宿主机 Agno Workspace。"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import mimetypes
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from agno.media import Image
from agno.tools.function import ToolResult
from agno.tools.workspace import Workspace

from ..workspace import (
    MAX_DOWNLOAD_BYTES,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
)
from .models import ReportingError
from .workflow.scope import ReportingWorkflowScope


def validate_host_workspace_root(root: str | Path) -> Path:
    """校验并创建 Reporting 宿主机工作区根目录。"""

    raw = str(root).strip()
    if not raw:
        raise ValueError("REPORTING_HOST_WORKSPACE_ROOT 不能为空")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("REPORTING_HOST_WORKSPACE_ROOT 必须是绝对路径")
    if path.is_symlink():
        raise ValueError("REPORTING_HOST_WORKSPACE_ROOT 不得是符号链接")
    if path.exists() and not path.is_dir():
        raise ValueError("REPORTING_HOST_WORKSPACE_ROOT 必须是目录")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("REPORTING_HOST_WORKSPACE_ROOT 必须是非符号链接目录")
    return path


@dataclass(frozen=True)
class ReportingWorkspaceIdentity:
    """一个报表 run 的宿主机目录和原生 Agno Workspace。"""

    workflow_session_id: str
    workspace_key: str
    scope_fingerprint: str
    root: Path
    workspace: Workspace


class ReportingPathMapper:
    """把既有相对业务路径解析到当前会话根目录。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @staticmethod
    def normalize(path: str, *, allow_root: bool = False) -> str:
        return WorkspaceService.normalize_path(path, allow_root=allow_root)[0]

    def to_host_path(self, path: str, *, allow_root: bool = False) -> Path:
        relative = self.normalize(path, allow_root=allow_root)
        candidate = self.root.joinpath(*relative.split("/")) if relative else self.root
        current = self.root
        for part in relative.split("/") if relative else ():
            current = current / part
            if current.is_symlink():
                raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
        return candidate


def _read_regular_file(path: Path, max_bytes: int) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise WorkspaceError("工作区路径不存在，请检查名称后重试。") from error
    if stat.S_ISLNK(info.st_mode):
        raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
    if not stat.S_ISREG(info.st_mode):
        raise WorkspaceError("工作区路径不是普通文件。")
    if info.st_size > max_bytes:
        raise WorkspaceError("工作区文件超过读取大小上限。")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > max_bytes:
            raise WorkspaceError("工作区路径不是允许大小的普通文件。")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read(max_bytes + 1)
    finally:
        os.close(descriptor)
    if len(content) > max_bytes:
        raise WorkspaceError("工作区文件超过读取大小上限。")
    return content


def _ensure_directory(path: Path, root: Path) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise WorkspaceError("工作区父路径不是安全目录，请更换路径后重试。")


def _write_regular_file(
    path: Path,
    root: Path,
    content: bytes,
    *,
    overwrite: bool,
    expected_sha256: str | None,
) -> None:
    WorkspaceService._validate_content(content)
    _ensure_directory(path.parent, root)
    if path.is_symlink():
        raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
    if path.exists():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise WorkspaceError("目标路径不是普通文件，请更换文件路径后重试。")
        if not overwrite:
            raise WorkspacePathConflict("目标文件已经存在，请重新读取后再覆盖。")
        if expected_sha256 is not None:
            current = hashlib.sha256(_read_regular_file(path, MAX_DOWNLOAD_BYTES)).hexdigest()
            if not hmac.compare_digest(current, expected_sha256):
                raise WorkspacePathConflict("目标文件哈希已变化，请重新读取后重试。")
    elif overwrite and expected_sha256 is not None:
        raise WorkspacePathConflict("覆盖目标不存在，请重新读取后重试。")

    descriptor, temporary = tempfile.mkstemp(prefix=".reporting-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class HostReportingWorkspace:
    """固定 Workflow 使用的宿主机二进制和文件身份适配。"""

    def __init__(self, identity: ReportingWorkspaceIdentity) -> None:
        self.identity = identity
        self.paths = ReportingPathMapper(identity.root)
        self._write_locks: dict[str, asyncio.Lock] = {}

    normalize_path = staticmethod(WorkspaceService.normalize_path)

    async def awrite_bytes(
        self,
        _thread_id: str,
        path: str,
        content: bytes,
        *,
        overwrite: bool = False,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        relative = self.paths.normalize(path)
        target = self.paths.to_host_path(relative)
        lock = self._write_locks.setdefault(relative, asyncio.Lock())
        async with lock:
            await anyio.to_thread.run_sync(
                lambda: _write_regular_file(
                    target,
                    self.identity.root,
                    content,
                    overwrite=overwrite,
                    expected_sha256=expected_sha256,
                )
            )
        return {"path": relative, "size": len(content), "status": "synced"}

    async def awrite_text(
        self,
        thread_id: str,
        path: str,
        content: str,
        *,
        overwrite: bool = False,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        return await self.awrite_bytes(
            thread_id,
            path,
            content.encode("utf-8"),
            overwrite=overwrite,
            expected_sha256=expected_sha256,
        )

    async def afile_bytes(self, _thread_id: str, path: str) -> tuple[bytes, str]:
        relative = self.paths.normalize(path)
        target = self.paths.to_host_path(relative)
        content = await anyio.to_thread.run_sync(
            lambda: _read_regular_file(target, MAX_DOWNLOAD_BYTES)
        )
        return content, mimetypes.guess_type(relative)[0] or "application/octet-stream"

    async def aread_text(self, thread_id: str, path: str) -> str:
        content, _mime_type = await self.afile_bytes(thread_id, path)
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkspaceError("工作区文件不是有效的 UTF-8 文本。") from error

    async def read_limited_regular_file(
        self,
        _thread_id: str,
        path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        target = self.paths.to_host_path(path)
        return await anyio.to_thread.run_sync(lambda: _read_regular_file(target, max_bytes))

    async def ahash_file(self, thread_id: str, path: str) -> dict[str, Any]:
        relative = self.paths.normalize(path)
        content = await self.read_limited_regular_file(
            thread_id,
            relative,
            max_bytes=MAX_DOWNLOAD_BYTES,
        )
        return {
            "path": relative,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    async def abatch_hash_files(
        self, thread_id: str, paths: list[str]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for path in paths:
            relative = self.paths.normalize(path)
            try:
                results.append(await self.ahash_file(thread_id, relative))
            except WorkspaceError:
                results.append({"path": relative, "missing": True})
        return results

    async def inspect_chart_file(self, thread_id: str, path: str) -> dict[str, Any]:
        from .workspace import inspect_report_chart_file

        return await inspect_report_chart_file(self, thread_id=thread_id, path=path)

    async def aview_image(self, thread_id: str, path: str) -> ToolResult:
        inspection = await self.inspect_chart_file(thread_id, path)
        content = await self.read_limited_regular_file(
            thread_id,
            path,
            max_bytes=inspection["size"],
        )
        return ToolResult(
            content="loaded",
            images=[
                Image(
                    content=content,
                    mime_type=inspection["mediaType"],
                    format=inspection["extension"].lstrip("."),
                )
            ],
        )


class ReportingWorkspaceRegistry:
    """按可信 workspace key 复用当前进程内的 Reporting Workspace。"""

    def __init__(self, root: str | Path, *, secret: str) -> None:
        self.root = validate_host_workspace_root(root)
        self._secret = secret.encode("utf-8")
        self._entries: dict[str, ReportingWorkspaceIdentity] = {}

    def _fingerprint(self, scope: ReportingWorkflowScope) -> str:
        payload = json.dumps(
            [
                scope.database,
                scope.company_id,
                scope.user_id,
                scope.caller_thread_id,
                scope.session_id,
                scope.workspace_key,
                scope.run_id,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def resolve(self, scope: ReportingWorkflowScope) -> ReportingWorkspaceIdentity:
        fingerprint = self._fingerprint(scope)
        existing = self._entries.get(scope.workspace_key)
        if existing is not None:
            if (
                existing.workflow_session_id != scope.session_id
                or existing.scope_fingerprint != fingerprint
            ):
                raise ReportingError(
                    "report_host_workspace_scope_mismatch",
                    "Reporting Workspace 作用域不一致。",
                )
            return existing

        session_root = self.root / "sessions" / fingerprint
        session_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        workspace = Workspace(
            root=session_root,
            allowed=Workspace.ALL_TOOLS,
            confirm=[],
        )
        identity = ReportingWorkspaceIdentity(
            workflow_session_id=scope.session_id,
            workspace_key=scope.workspace_key,
            scope_fingerprint=fingerprint,
            root=session_root,
            workspace=workspace,
        )
        self._entries[scope.workspace_key] = identity
        return identity

    def get(self, workspace_key: str) -> ReportingWorkspaceIdentity | None:
        return self._entries.get(workspace_key)

    def release(self, workspace_key: str) -> bool:
        return self._entries.pop(workspace_key, None) is not None

    async def aclose(self) -> None:
        self._entries.clear()


__all__ = [
    "HostReportingWorkspace",
    "ReportingPathMapper",
    "ReportingWorkspaceIdentity",
    "ReportingWorkspaceRegistry",
    "validate_host_workspace_root",
]
