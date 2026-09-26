"""Reporting 会话专属的宿主机 Agno Workspace。"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import mimetypes
import os
import re
import shutil
import signal
import stat
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from agno.media import Image
from agno.tools.function import ToolResult
from agno.tools.workspace import Workspace

from ..async_utils import complete_cleanup
from ..workspace import (
    MAX_DOWNLOAD_BYTES,
    MAX_PATCH_FILES,
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


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    # 回收进程必须完成，即使调用方正在被取消，否则会留下僵尸进程。
    await complete_cleanup(process.wait())


class HostReportingWorkspace:
    """固定 Workflow 使用的宿主机二进制和文件身份适配。"""

    def __init__(self, identity: ReportingWorkspaceIdentity) -> None:
        self.identity = identity
        self.paths = ReportingPathMapper(identity.root)
        # 按路径串行化写入；记录等待者数量，最后一个使用者释放后移除，避免长会话中
        # 每个写过的路径都永久保留一把锁。
        self._write_locks: dict[str, tuple[asyncio.Lock, int]] = {}
        self._changes_lock = asyncio.Lock()

    normalize_path = staticmethod(WorkspaceService.normalize_path)

    @staticmethod
    def validate_content(content: bytes) -> None:
        WorkspaceService._validate_content(content)

    @contextlib.asynccontextmanager
    async def _path_write_lock(self, relative: str) -> AsyncIterator[None]:
        lock, users = self._write_locks.get(relative, (asyncio.Lock(), 0))
        self._write_locks[relative] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._write_locks[relative]
            if users <= 1:
                del self._write_locks[relative]
            else:
                self._write_locks[relative] = (lock, users - 1)

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
        async with self._path_write_lock(relative):
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

    async def aensure_directory(self, _thread_id: str, path: str) -> None:
        target = self.paths.to_host_path(path)
        await anyio.to_thread.run_sync(lambda: _ensure_directory(target, self.identity.root))

    async def apath_exists(self, _thread_id: str, path: str) -> bool:
        target = self.paths.to_host_path(path)
        return await anyio.to_thread.run_sync(lambda: target.exists() and not target.is_symlink())

    async def amove_files(self, _thread_id: str, source: str, destination: str) -> None:
        source_path = self.paths.to_host_path(source)
        destination_path = self.paths.to_host_path(destination)

        def move() -> None:
            try:
                source_info = source_path.lstat()
            except FileNotFoundError as error:
                raise WorkspaceError("待移动的工作区路径不存在。") from error
            if stat.S_ISLNK(source_info.st_mode):
                raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
            if destination_path.exists() or destination_path.is_symlink():
                raise WorkspacePathConflict("移动目标已经存在，请更换路径。")
            _ensure_directory(destination_path.parent, self.identity.root)
            os.replace(source_path, destination_path)

        await anyio.to_thread.run_sync(move)

    async def adelete_file(self, _thread_id: str, path: str, recursive: bool = False) -> None:
        target = self.paths.to_host_path(path)

        def delete() -> None:
            try:
                info = target.lstat()
            except FileNotFoundError:
                return
            if stat.S_ISLNK(info.st_mode):
                raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
            if stat.S_ISDIR(info.st_mode):
                if recursive:
                    shutil.rmtree(target)
                else:
                    target.rmdir()
                return
            if not stat.S_ISREG(info.st_mode):
                raise WorkspaceError("工作区路径不是普通文件或目录。")
            target.unlink()

        await anyio.to_thread.run_sync(delete)

    async def arun_command(
        self,
        _thread_id: str,
        args: list[str],
        *,
        timeout: int,
        tail: int = 100,
    ) -> str:
        """与 Agno ``Workspace.run_command`` 相同的输出协议，但超时与取消会终止整个进程组。

        Agno 的同步实现在线程中阻塞、无法被取消；异步实现在取消时不终止子进程，超时
        也只杀直接子进程。报表运行时还会拉起 LibreOffice、pdftoppm 等孙进程，因此这里
        以独立进程组启动，并在超时或上层取消（如编辑器导出超时）时整组终止。
        """

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.identity.workspace.root),
            start_new_session=True,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except TimeoutError:
            await _terminate_process_group(process)
            return f"Error: command timed out after {timeout} seconds"
        except BaseException:
            await _terminate_process_group(process)
            raise
        if process.returncode != 0:
            stderr = _ANSI_ESCAPE.sub("", stderr_bytes.decode("utf-8", errors="replace"))
            return f"Error (exit {process.returncode}): " + "\n".join(stderr.splitlines()[-tail:])
        stdout = _ANSI_ESCAPE.sub("", stdout_bytes.decode("utf-8", errors="replace"))
        return "\n".join(stdout.splitlines()[-tail:])

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

    async def abatch_hash_files(self, thread_id: str, paths: list[str]) -> list[dict[str, Any]]:
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

    async def inspect_plotly_file(self, thread_id: str, path: str) -> dict[str, Any]:
        from .workspace import inspect_report_plotly_file

        return await inspect_report_plotly_file(self, thread_id=thread_id, path=path)

    async def aapply_changes(self, thread_id: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_PATCH_FILES:
            raise WorkspaceError(f"变更集必须包含 1 至 {MAX_PATCH_FILES} 个文件操作。")
        keys_by_operation = {
            "create": {"operation", "path", "content"},
            "update": {"operation", "path", "content", "expected_sha256"},
            "delete": {"operation", "path", "expected_sha256"},
            "move": {"operation", "path", "destination", "expected_sha256"},
        }
        async with self._changes_lock:
            prepared: list[dict[str, Any]] = []
            used_paths: set[str] = set()
            for change in changes:
                if not isinstance(change, dict):
                    raise WorkspaceError("变更集中的每一项都必须是文件操作对象。")
                raw_operation = change.get("operation")
                if not isinstance(raw_operation, str):
                    raise WorkspaceError("变更集操作必须是 create、update、delete 或 move。")
                required_keys = keys_by_operation.get(raw_operation)
                if required_keys is None or set(change) != required_keys:
                    raise WorkspaceError(
                        "变更集操作字段无效；请按 create、update、delete 或 move 的字段要求重试。"
                    )
                if not isinstance(change.get("path"), str):
                    raise WorkspaceError("变更集路径必须是工作区相对路径字符串。")
                relative = self.paths.normalize(change["path"])
                occupied = [relative]
                destination: str | None = None
                if raw_operation == "move":
                    if not isinstance(change.get("destination"), str):
                        raise WorkspaceError("移动目标必须是工作区相对路径字符串。")
                    destination = self.paths.normalize(change["destination"])
                    if destination == relative:
                        raise WorkspaceError("移动源路径和目标路径不能相同。")
                    occupied.append(destination)
                if any(path in used_paths for path in occupied):
                    raise WorkspaceError("变更集不能重复使用同一个源路径或目标路径。")
                used_paths.update(occupied)

                if raw_operation == "create":
                    content = change["content"]
                    if not isinstance(content, str):
                        raise WorkspaceError("新建文件内容必须是 UTF-8 文本。")
                    updated = content.encode("utf-8")
                    self.validate_content(updated)
                    if await self.apath_exists(thread_id, relative):
                        raise WorkspacePathConflict(
                            f"文件“{relative}”已经存在，请重新读取变更目标后重试。"
                        )
                    prepared.append(
                        {"operation": raw_operation, "path": relative, "updated": updated}
                    )
                    continue

                if not await self.apath_exists(thread_id, relative):
                    raise WorkspaceError("工作区路径不存在，请检查名称后重试。")
                original, _mime = await self.afile_bytes(thread_id, relative)
                expected_sha256 = WorkspaceService._validate_patch_hash(change["expected_sha256"])
                if hashlib.sha256(original).hexdigest() != expected_sha256:
                    raise WorkspacePathConflict(
                        "文件内容已变化，请重新读取全部目标文件和哈希后再应用变更集。"
                    )
                item: dict[str, Any] = {
                    "operation": raw_operation,
                    "path": relative,
                    "original": original,
                    "sha256": expected_sha256,
                }
                if raw_operation == "update":
                    content = change["content"]
                    if not isinstance(content, str):
                        raise WorkspaceError("更新文件内容必须是 UTF-8 文本。")
                    item["updated"] = content.encode("utf-8")
                    self.validate_content(item["updated"])
                elif raw_operation == "move":
                    if destination is None:
                        raise WorkspaceError("移动目标必须是工作区相对路径字符串。")
                    if await self.apath_exists(thread_id, destination):
                        raise WorkspacePathConflict(
                            f"移动目标“{destination}”已经存在，请更换路径后重试。"
                        )
                    item["destination"] = destination
                prepared.append(item)

            completed: list[dict[str, Any]] = []
            try:
                for item in prepared:
                    operation = item["operation"]
                    if operation in {"create", "update"}:
                        await self.awrite_bytes(
                            thread_id,
                            item["path"],
                            item["updated"],
                            overwrite=operation == "update",
                        )
                    elif operation == "delete":
                        await self.adelete_file(thread_id, item["path"])
                    else:
                        await self.amove_files(thread_id, item["path"], item["destination"])
                    completed.append(item)
                    if operation in {"create", "update"}:
                        persisted, _mime = await self.afile_bytes(thread_id, item["path"])
                        if persisted != item["updated"]:
                            raise WorkspaceError("变更集落盘校验失败，请重新检查目标文件。")
                    elif operation == "move":
                        persisted, _mime = await self.afile_bytes(thread_id, item["destination"])
                        if persisted != item["original"]:
                            raise WorkspaceError("变更集移动校验失败，请重新检查目标文件。")
            except Exception as error:
                rollback_failed = False
                for item in reversed(completed):
                    try:
                        operation = item["operation"]
                        if operation == "create":
                            await self.adelete_file(thread_id, item["path"])
                        elif operation == "update":
                            await self.awrite_bytes(
                                thread_id,
                                item["path"],
                                item["original"],
                                overwrite=True,
                            )
                        elif operation == "delete":
                            await self.awrite_bytes(
                                thread_id,
                                item["path"],
                                item["original"],
                                overwrite=False,
                            )
                        else:
                            await self.amove_files(thread_id, item["destination"], item["path"])
                    except Exception:
                        rollback_failed = True
                if rollback_failed:
                    raise WorkspaceError(
                        "变更集执行失败且未能完整回滚，请重新检查所有目标文件。"
                    ) from error
                raise

        results = []
        for item in prepared:
            result: dict[str, Any] = {"operation": item["operation"], "path": item["path"]}
            if item["operation"] in {"create", "update"}:
                result.update(
                    {
                        "size": len(item["updated"]),
                        "sha256": hashlib.sha256(item["updated"]).hexdigest(),
                    }
                )
            elif item["operation"] == "move":
                result["destination"] = item["destination"]
                result["sha256"] = item["sha256"]
            else:
                result["sha256"] = item["sha256"]
            results.append(result)
        return {"files": results, "operations": len(results)}

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


class ReportingWorkspaceRouter:
    """按 Reporting workspace key 路由程序化文件访问。"""

    normalize_path = staticmethod(WorkspaceService.normalize_path)

    def __init__(self, registry: ReportingWorkspaceRegistry) -> None:
        self.registry = registry
        self._workspaces: dict[str, HostReportingWorkspace] = {}

    @staticmethod
    def validate_content(content: bytes) -> None:
        WorkspaceService._validate_content(content)

    def workspace(self, workspace_key: str) -> HostReportingWorkspace:
        identity = self.registry.get(workspace_key)
        if identity is None:
            raise ReportingError(
                "report_host_workspace_missing",
                "Reporting Workspace 尚未绑定当前运行。",
            )
        workspace = self._workspaces.get(workspace_key)
        if workspace is None or workspace.identity is not identity:
            workspace = HostReportingWorkspace(identity)
            self._workspaces[workspace_key] = workspace
        return workspace

    async def awrite_bytes(self, thread_id: str, path: str, content: bytes, **kwargs: Any):
        return await self.workspace(thread_id).awrite_bytes(thread_id, path, content, **kwargs)

    async def awrite_text(self, thread_id: str, path: str, content: str, **kwargs: Any):
        return await self.workspace(thread_id).awrite_text(thread_id, path, content, **kwargs)

    async def afile_bytes(self, thread_id: str, path: str) -> tuple[bytes, str]:
        return await self.workspace(thread_id).afile_bytes(thread_id, path)

    async def aread_text(self, thread_id: str, path: str) -> str:
        return await self.workspace(thread_id).aread_text(thread_id, path)

    async def read_limited_regular_file(
        self, thread_id: str, path: str, *, max_bytes: int
    ) -> bytes:
        return await self.workspace(thread_id).read_limited_regular_file(
            thread_id, path, max_bytes=max_bytes
        )

    async def ahash_file(self, thread_id: str, path: str) -> dict[str, Any]:
        return await self.workspace(thread_id).ahash_file(thread_id, path)

    async def abatch_hash_files(self, thread_id: str, paths: list[str]) -> list[dict[str, Any]]:
        return await self.workspace(thread_id).abatch_hash_files(thread_id, paths)

    async def inspect_chart_file(self, thread_id: str, path: str) -> dict[str, Any]:
        return await self.workspace(thread_id).inspect_chart_file(thread_id, path)

    async def inspect_plotly_file(self, thread_id: str, path: str) -> dict[str, Any]:
        return await self.workspace(thread_id).inspect_plotly_file(thread_id, path)

    async def aview_image(self, thread_id: str, path: str) -> ToolResult:
        return await self.workspace(thread_id).aview_image(thread_id, path)

    async def aensure_directory(self, thread_id: str, path: str) -> None:
        await self.workspace(thread_id).aensure_directory(thread_id, path)

    async def apath_exists(self, thread_id: str, path: str) -> bool:
        return await self.workspace(thread_id).apath_exists(thread_id, path)

    async def amove_files(self, thread_id: str, source: str, destination: str) -> None:
        await self.workspace(thread_id).amove_files(thread_id, source, destination)

    async def adelete_file(self, thread_id: str, path: str, recursive: bool = False) -> None:
        await self.workspace(thread_id).adelete_file(thread_id, path, recursive)

    async def arun_command(
        self,
        thread_id: str,
        args: list[str],
        *,
        timeout: int,
        tail: int = 100,
    ) -> str:
        return await self.workspace(thread_id).arun_command(
            thread_id, args, timeout=timeout, tail=tail
        )

    async def aapply_changes(self, thread_id: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
        return await self.workspace(thread_id).aapply_changes(thread_id, changes)


__all__ = [
    "HostReportingWorkspace",
    "ReportingPathMapper",
    "ReportingWorkspaceIdentity",
    "ReportingWorkspaceRegistry",
    "ReportingWorkspaceRouter",
    "validate_host_workspace_root",
]
