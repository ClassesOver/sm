"""同机工作区来源生命周期锁，覆盖读取、导出和回收的完整操作。"""

from __future__ import annotations

import asyncio
import fcntl
import os
import stat
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path

from fastapi.concurrency import contextmanager_in_threadpool
from starlette.responses import FileResponse, JSONResponse

from ..reporting.models import ReportingError
from ..reporting.trace.contracts_v1 import TRACE_ERROR_HTTP_STATUS
from ..reporting.trace.dataset_service import TraceDatasetFile, verified_dataset_snapshot


class SourceFileResponse(FileResponse):
    """持有来源锁，从同一份已核验快照发送全部下载字节。"""

    def __init__(self, path, *, service, context, validate, **kwargs):
        super().__init__(path, **kwargs)
        self.service = service
        self.context = context
        self.validate = validate

    async def __call__(self, scope, receive, send):
        started = False

        async def send_download(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            async with source_lifecycle_lock(self.service, self.context):
                path, filename, size, sha256 = await self.validate()
                if str(path) != str(self.path):
                    raise ReportingError("source_missing", "下载来源已变化，请重新下载。")
                # 不委托服务器延后按路径打开文件，否则锁会早于实际发送释放。
                extensions = {key: value for key, value in scope.get("extensions", {}).items()
                    if key != "http.response.pathsend"}
                file = TraceDatasetFile(
                    dataset_id="download", local_path=Path(path), size=size,
                    sha256=sha256, row_count=0,
                )
                async with contextmanager_in_threadpool(verified_dataset_snapshot(file)) as snapshot:
                    headers = dict(self.headers)
                    # 临时文件的时间戳每次不同；Range 的 If-Range 应绑定内容身份。
                    headers["etag"] = f'"{sha256}"'
                    response = FileResponse(
                        snapshot.local_path, status_code=self.status_code,
                        media_type=self.media_type, filename=filename,
                        headers=headers, background=self.background,
                    )
                    response.chunk_size = self.chunk_size
                    await response({**scope, "extensions": extensions}, receive, send_download)
        except ReportingError as error:
            if started:
                raise
            response = JSONResponse({"detail": {"code": error.code, "message": error.message}},
                status_code=TRACE_ERROR_HTTP_STATUS.get(error.code, 404))
            await response(scope, receive, send)


def source_lifecycle(method):
    @wraps(method)
    async def guarded(self, expected, *args, **kwargs):
        async with source_lifecycle_lock(self, expected):
            return await method(self, expected, *args, **kwargs)

    return guarded


@asynccontextmanager
async def source_lifecycle_lock(service, expected, *, exclusive=False):
    context = await service._restore(expected)
    identity = service.workspace_registry.get(context.scope["threadId"])
    key = (asyncio.current_task(), identity.root)
    held = service._source_lifecycle_locks
    if key in held:
        if exclusive and not held[key]:
            raise ReportingError("report_editor_conflict", "不能在来源读取中升级为清理锁。")
        yield
        return
    descriptor = os.open(identity.root / ".editor-sources.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReportingError("snapshot_integrity_failed", "来源生命周期锁不是普通文件。")
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        while True:
            try:
                fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.05)
        held[key] = exclusive
        try:
            yield
        finally:
            held.pop(key, None)
    finally:
        os.close(descriptor)
