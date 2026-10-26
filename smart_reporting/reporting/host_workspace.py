"""Reporting 会话专属的宿主机 Agno Workspace。"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import errno
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import stat
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
    normalize_workspace_path,
    validate_patch_hash,
    validate_workspace_content,
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
        return normalize_workspace_path(path, allow_root=allow_root)

    def to_host_path(self, path: str, *, allow_root: bool = False) -> Path:
        relative = self.normalize(path, allow_root=allow_root)
        candidate = self.root.joinpath(*relative.split("/")) if relative else self.root
        current = self.root
        for part in relative.split("/") if relative else ():
            current = current / part
            if current.is_symlink():
                raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
        return candidate


_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)
_RENAME_NOREPLACE = 1
try:
    _RENAMEAT2 = ctypes.CDLL(None, use_errno=True).renameat2
except AttributeError:
    _RENAMEAT2 = None
else:
    _RENAMEAT2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    _RENAMEAT2.restype = ctypes.c_int


def _workspace_relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    """返回已经过业务路径规范化的相对分量，并拒绝根目录本身。"""

    try:
        parts = path.relative_to(root).parts
    except ValueError as error:
        raise WorkspaceError("工作区路径超出当前运行目录。") from error
    if not parts:
        raise WorkspaceError("没有提供工作区路径，请指定文件或目录后重试。")
    return parts


def _open_directory_parts(
    root: Path,
    parts: tuple[str, ...],
    *,
    create: bool,
    root_descriptor: int | None = None,
) -> int:
    """逐级以 ``dir_fd`` 和 ``O_NOFOLLOW`` 打开目录，返回末级描述符。"""

    try:
        current = (
            os.dup(root_descriptor)
            if root_descriptor is not None
            else os.open(root, _DIRECTORY_OPEN_FLAGS)
        )
    except OSError as error:
        raise WorkspaceError("工作区根目录已变化或无法访问。") from error
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
                except OSError as error:
                    raise WorkspaceError("工作区父路径无法安全创建，请更换路径后重试。") from error
            try:
                child = os.open(part, _DIRECTORY_OPEN_FLAGS, dir_fd=current)
            except FileNotFoundError:
                raise
            except OSError as error:
                raise WorkspaceError("工作区父路径不是安全目录，请更换路径后重试。") from error
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _open_parent_directory(
    path: Path,
    root: Path,
    *,
    create: bool,
    root_descriptor: int | None = None,
) -> tuple[int, str]:
    parts = _workspace_relative_parts(path, root)
    descriptor = _open_directory_parts(
        root,
        parts[:-1],
        create=create,
        root_descriptor=root_descriptor,
    )
    return descriptor, parts[-1]


def _open_regular_file_at(parent: int, name: str, max_bytes: int) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
    except FileNotFoundError as error:
        raise WorkspaceError("工作区路径不存在，请检查名称后重试。") from error
    except OSError as error:
        raise WorkspaceError("工作区文件已变化或无法读取，请重试。") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise WorkspaceError("工作区路径不是普通文件。")
        if opened.st_size > max_bytes:
            raise WorkspaceError("工作区文件超过读取大小上限。")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_regular_file(path: Path, root: Path, max_bytes: int) -> int:
    """沿固定目录描述符打开普通文件，父目录竞态不能把读取重定向到工作区外。"""

    try:
        parent, name = _open_parent_directory(path, root, create=False)
    except FileNotFoundError as error:
        raise WorkspaceError("工作区路径不存在，请检查名称后重试。") from error
    try:
        return _open_regular_file_at(parent, name, max_bytes)
    finally:
        os.close(parent)


def _read_regular_file_at(parent: int, name: str, max_bytes: int) -> bytes:
    descriptor = _open_regular_file_at(parent, name, max_bytes)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read(max_bytes + 1)
    except OSError as error:
        raise WorkspaceError("工作区文件已变化或无法读取，请重试。") from error
    finally:
        os.close(descriptor)
    if len(content) > max_bytes:
        raise WorkspaceError("工作区文件超过读取大小上限。")
    return content


def _read_regular_file(path: Path, root: Path, max_bytes: int) -> bytes:
    descriptor = _open_regular_file(path, root, max_bytes)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read(max_bytes + 1)
    except OSError as error:
        raise WorkspaceError("工作区文件已变化或无法读取，请重试。") from error
    finally:
        os.close(descriptor)
    if len(content) > max_bytes:
        raise WorkspaceError("工作区文件超过读取大小上限。")
    return content


def _hash_regular_file(path: Path, root: Path, max_bytes: int) -> tuple[int, str]:
    """分块计算普通文件的大小与 sha256，不把整个文件读入内存。"""

    descriptor = _open_regular_file(path, root, max_bytes)
    digest = hashlib.sha256()
    size = 0
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise WorkspaceError("工作区文件超过读取大小上限。")
            digest.update(chunk)
    except OSError as error:
        raise WorkspaceError("工作区文件已变化或无法读取，请重试。") from error
    finally:
        os.close(descriptor)
    return size, digest.hexdigest()


def _ensure_directory(path: Path, root: Path) -> None:
    parts = path.relative_to(root).parts
    descriptor = _open_directory_parts(root, parts, create=True)
    os.close(descriptor)


def _path_exists(path: Path, root: Path) -> bool:
    try:
        parent, name = _open_parent_directory(path, root, create=False)
    except FileNotFoundError:
        return False
    try:
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return not stat.S_ISLNK(info.st_mode)
    finally:
        os.close(parent)


def _rename_noreplace_at(
    source_parent: int,
    source_name: str,
    destination_parent: int,
    destination_name: str,
    *,
    source_is_directory: bool,
) -> None:
    """Atomically move a directory entry without replacing a concurrent target."""

    if _RENAMEAT2 is not None:
        result = _RENAMEAT2(
            source_parent,
            os.fsencode(source_name),
            destination_parent,
            os.fsencode(destination_name),
            _RENAME_NOREPLACE,
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(error_number, os.strerror(error_number))
        raise OSError(error_number, os.strerror(error_number))

    if source_is_directory:
        raise WorkspaceError("当前平台不支持安全的原子目录移动。")
    try:
        os.link(
            source_name,
            destination_name,
            src_dir_fd=source_parent,
            dst_dir_fd=destination_parent,
            follow_symlinks=False,
        )
    except FileExistsError:
        raise
    try:
        os.unlink(source_name, dir_fd=source_parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(destination_name, dir_fd=destination_parent)
        raise


def _move_workspace_path(source: Path, destination: Path, root: Path) -> None:
    try:
        source_parent, source_name = _open_parent_directory(
            source, root, create=False
        )
    except FileNotFoundError as error:
        raise WorkspaceError("待移动的工作区路径不存在。") from error
    destination_parent: int | None = None
    try:
        try:
            source_info = os.stat(
                source_name, dir_fd=source_parent, follow_symlinks=False
            )
        except FileNotFoundError as error:
            raise WorkspaceError("待移动的工作区路径不存在。") from error
        if stat.S_ISLNK(source_info.st_mode) or not (
            stat.S_ISREG(source_info.st_mode) or stat.S_ISDIR(source_info.st_mode)
        ):
            raise WorkspaceError("工作区路径不是普通文件或目录。")
        destination_parent, destination_name = _open_parent_directory(
            destination, root, create=True
        )
        try:
            os.stat(
                destination_name,
                dir_fd=destination_parent,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise WorkspacePathConflict("移动目标已经存在，请更换路径。")
        try:
            _rename_noreplace_at(
                source_parent,
                source_name,
                destination_parent,
                destination_name,
                source_is_directory=stat.S_ISDIR(source_info.st_mode),
            )
        except FileExistsError as error:
            raise WorkspacePathConflict("移动目标已经存在，请更换路径。") from error
        except OSError as error:
            raise WorkspaceError("工作区路径移动失败，请重新检查源和目标。") from error
    finally:
        if destination_parent is not None:
            os.close(destination_parent)
        os.close(source_parent)


def _delete_workspace_path(path: Path, root: Path, *, recursive: bool) -> None:
    try:
        parent, name = _open_parent_directory(path, root, create=False)
    except FileNotFoundError:
        return
    try:
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
        if stat.S_ISDIR(info.st_mode):
            if recursive:
                if not shutil.rmtree.avoids_symlink_attacks:
                    raise WorkspaceError("当前平台不支持安全递归删除工作区目录。")
                shutil.rmtree(name, dir_fd=parent)
            else:
                os.rmdir(name, dir_fd=parent)
            return
        if not stat.S_ISREG(info.st_mode):
            raise WorkspaceError("工作区路径不是普通文件或目录。")
        os.unlink(name, dir_fd=parent)
    except FileNotFoundError:
        return
    except WorkspaceError:
        raise
    except OSError as error:
        raise WorkspaceError("工作区路径删除失败，请重新检查目标。") from error
    finally:
        os.close(parent)


def _write_regular_file(
    path: Path,
    root: Path,
    content: bytes,
    *,
    overwrite: bool,
    expected_sha256: str | None,
) -> None:
    validate_workspace_content(content)
    parent, name = _open_parent_directory(path, root, create=True)
    temporary: str | None = None
    try:
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        except OSError as error:
            raise WorkspaceError("目标路径已变化或无法访问，请重试。") from error
        if info is not None:
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise WorkspaceError("目标路径不是普通文件，请更换文件路径后重试。")
            if not overwrite:
                raise WorkspacePathConflict("目标文件已经存在，请重新读取后再覆盖。")
            if expected_sha256 is not None:
                current = hashlib.sha256(
                    _read_regular_file_at(parent, name, MAX_DOWNLOAD_BYTES)
                ).hexdigest()
                if not hmac.compare_digest(current, expected_sha256):
                    raise WorkspacePathConflict("目标文件哈希已变化，请重新读取后重试。")
        elif overwrite and expected_sha256 is not None:
            raise WorkspacePathConflict("覆盖目标不存在，请重新读取后重试。")

        for _attempt in range(10):
            candidate = f".reporting-{secrets.token_hex(12)}"
            try:
                descriptor = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=parent,
                )
                temporary = candidate
                break
            except FileExistsError:
                continue
        else:
            raise WorkspaceError("无法创建工作区临时文件，请稍后重试。")
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        else:
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                raise WorkspacePathConflict(
                    "目标文件已经存在，请重新读取后再覆盖。"
                ) from error
            os.unlink(temporary, dir_fd=parent)
        temporary = None
    finally:
        if temporary is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=parent)
        os.close(parent)


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

    normalize_path = staticmethod(normalize_workspace_path)

    @staticmethod
    def validate_content(content: bytes) -> None:
        validate_workspace_content(content)

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
            lambda: _read_regular_file(
                target, self.identity.root, MAX_DOWNLOAD_BYTES
            )
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
        return await anyio.to_thread.run_sync(
            lambda: _path_exists(target, self.identity.root)
        )

    async def amove_files(self, _thread_id: str, source: str, destination: str) -> None:
        source_path = self.paths.to_host_path(source)
        destination_path = self.paths.to_host_path(destination)
        await anyio.to_thread.run_sync(
            lambda: _move_workspace_path(
                source_path, destination_path, self.identity.root
            )
        )

    async def adelete_file(self, _thread_id: str, path: str, recursive: bool = False) -> None:
        target = self.paths.to_host_path(path)
        await anyio.to_thread.run_sync(
            lambda: _delete_workspace_path(
                target, self.identity.root, recursive=recursive
            )
        )

    async def adelete_registered_file(
        self, _thread_id: str, path: str, *, size: int, sha256: str
    ) -> bool:
        """仅删除身份相符的普通文件；逐级 O_NOFOLLOW，不递归删除目录。"""
        relative = self.paths.normalize(path)

        def delete() -> bool:
            parts = Path(relative).parts
            directory = os.open(self.identity.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for part in parts[:-1]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    os.close(directory)
                    directory = child
                try:
                    descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                except FileNotFoundError:
                    return False
                try:
                    info = os.fstat(descriptor)
                    if not stat.S_ISREG(info.st_mode) or info.st_size != size:
                        raise WorkspaceError("待回收来源文件身份已变化。")
                    digest = hashlib.sha256()
                    while chunk := os.read(descriptor, 1024 * 1024):
                        digest.update(chunk)
                    current = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
                    if digest.hexdigest() != sha256 or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                        raise WorkspaceError("待回收来源文件身份已变化。")
                    os.unlink(parts[-1], dir_fd=directory)
                    return True
                finally:
                    os.close(descriptor)
            except FileNotFoundError:
                return False
            finally:
                os.close(directory)

        async with self._path_write_lock(relative):
            return await anyio.to_thread.run_sync(delete)

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
        return await anyio.to_thread.run_sync(
            lambda: _read_regular_file(target, self.identity.root, max_bytes)
        )

    async def aiter_regular_file_chunks(
        self,
        _thread_id: str,
        path: str,
        *,
        max_bytes: int,
        chunk_size: int,
    ) -> AsyncIterator[bytes]:
        """按块读取普通文件，不把整个文件读入内存；打开校验与 read_limited_regular_file 相同。"""

        target = self.paths.to_host_path(path)
        descriptor = await anyio.to_thread.run_sync(
            lambda: _open_regular_file(target, self.identity.root, max_bytes)
        )
        total = 0
        try:
            while True:
                try:
                    chunk = await anyio.to_thread.run_sync(os.read, descriptor, chunk_size)
                except OSError as error:
                    raise WorkspaceError("工作区文件已变化或无法读取，请重试。") from error
                if not chunk:
                    return
                total += len(chunk)
                if total > max_bytes:
                    raise WorkspaceError("工作区文件超过读取大小上限。")
                yield chunk
        finally:
            os.close(descriptor)

    async def ahash_file(self, _thread_id: str, path: str) -> dict[str, Any]:
        relative = self.paths.normalize(path)
        target = self.paths.to_host_path(relative)
        size, sha256 = await anyio.to_thread.run_sync(
            lambda: _hash_regular_file(
                target, self.identity.root, MAX_DOWNLOAD_BYTES
            )
        )
        return {"path": relative, "size": size, "sha256": sha256}

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
                expected_sha256 = validate_patch_hash(change["expected_sha256"])
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
            except BaseException as error:
                async def rollback() -> bool:
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
                                await self.amove_files(
                                    thread_id, item["destination"], item["path"]
                                )
                        except Exception:
                            rollback_failed = True
                    return rollback_failed

                rollback_failed = await complete_cleanup(rollback())
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

    normalize_path = staticmethod(normalize_workspace_path)

    def __init__(self, registry: ReportingWorkspaceRegistry) -> None:
        self.registry = registry
        self._workspaces: dict[str, HostReportingWorkspace] = {}

    @staticmethod
    def validate_content(content: bytes) -> None:
        validate_workspace_content(content)

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

    async def adelete_registered_file(self, thread_id: str, path: str, *, size: int, sha256: str) -> bool:
        return await self.workspace(thread_id).adelete_registered_file(thread_id, path, size=size, sha256=sha256)

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

    def aiter_regular_file_chunks(
        self, thread_id: str, path: str, *, max_bytes: int, chunk_size: int
    ) -> AsyncIterator[bytes]:
        return self.workspace(thread_id).aiter_regular_file_chunks(
            thread_id, path, max_bytes=max_bytes, chunk_size=chunk_size
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
