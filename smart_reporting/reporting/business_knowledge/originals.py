"""业务原件复用现有宿主机工作区的原子写入、有界读取与路径保护。"""

import hmac
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import anyio

from ..host_workspace import (
    _delete_workspace_path,
    _read_regular_file,
    _write_regular_file,
    validate_host_workspace_root,
)
from .ingestion import MAX_DOCUMENT_BYTES


class BusinessOriginalStore:
    def __init__(self, root: Path):
        self.root = validate_host_workspace_root(root)

    def _path(self, scope_id: str, resource_id: str) -> Path:
        # 两个标识均由服务器生成；不把原始文件名或浏览器路径用于磁盘寻址。
        return self.root / str(UUID(scope_id)) / f"{UUID(resource_id)}.bin"

    async def put(self, scope_id: str, resource_id: str, content: bytes) -> None:
        if not content or len(content) > MAX_DOCUMENT_BYTES:
            raise ValueError("document_size_invalid")
        path = self._path(scope_id, resource_id)
        await anyio.to_thread.run_sync(lambda: _write_regular_file(
            path, self.root, content, overwrite=False, expected_sha256=None,
        ))

    async def read(self, scope_id: str, resource_id: str, *, expected_hash: str, expected_size: int) -> bytes:
        path = self._path(scope_id, resource_id)
        content = await anyio.to_thread.run_sync(lambda: _read_regular_file(path, self.root, MAX_DOCUMENT_BYTES))
        if len(content) != expected_size or not hmac.compare_digest(sha256(content).hexdigest(), expected_hash):
            raise ValueError("document_original_identity_changed")
        return content

    async def discard(self, scope_id: str, resource_id: str) -> None:
        path = self._path(scope_id, resource_id)
        await anyio.to_thread.run_sync(lambda: _delete_workspace_path(path, self.root, recursive=False))
