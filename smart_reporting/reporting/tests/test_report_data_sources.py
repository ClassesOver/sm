from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import anyio
import pytest
from agno.run import RunContext

from smart_reporting.reporting.contract import ReportFileInput
from smart_reporting.reporting.data_source import MaterializedQueryResult, QueryResult
from smart_reporting.reporting.data_sources import ReportDatasetStore
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.query_pipeline import ApprovedQuery, normalized_sql_hash
from smart_reporting.workspace import WorkspaceError, WorkspaceHashResultError, WorkspaceService


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeFs:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.active_uploads = 0
        self.max_active_uploads = 0
        self.completed_uploads = 0
        self.moves: list[tuple[str, str]] = []
        self.deletes: list[str] = []

    async def upload_file(self, content: bytes, path: str) -> None:
        self.active_uploads += 1
        self.max_active_uploads = max(self.max_active_uploads, self.active_uploads)
        try:
            await anyio.sleep(0)
            self.files[path] = bytes(content)
            self.completed_uploads += 1
        finally:
            self.active_uploads -= 1

    async def move_files(self, source: str, destination: str) -> None:
        self.moves.append((source, destination))

    async def delete_file(self, path: str, *, recursive: bool = False) -> None:
        del recursive
        self.deletes.append(path)


class _FakeDatasetService:
    def __init__(self, hash_results: list[object] | None = None) -> None:
        self.fs = _FakeFs()
        self.sandbox = SimpleNamespace(fs=self.fs)
        self.hash_results = list(hash_results or ())
        self.hash_paths: list[str] = []
        self.active_hashes = 0
        self.max_active_hashes = 0
        self.reads: list[tuple[str, str]] = []

    def file_bytes(self, *_args: object) -> tuple[bytes, str]:
        raise AssertionError("异步数据集登记不得调用同步工作区接口")

    async def afile_bytes(self, thread: str, path: str) -> tuple[bytes, str]:
        self.reads.append((thread, path))
        _relative, remote = self.normalize_path(path)
        return self.fs.files[remote], "text/csv"

    @asynccontextmanager
    async def _async_client(self):
        yield object()

    async def _asandbox_for(self, _client: object, _thread: str):
        return self.sandbox

    async def _aensure_directory(self, _sandbox: object, _remote: str) -> None:
        return None

    @staticmethod
    def normalize_path(path: str, *, allow_root: bool = True) -> tuple[str, str]:
        del allow_root
        relative = path.strip("/")
        return relative, f"/home/daytona/workspace/{relative}"

    async def ahash_file(self, _thread: str, path: str) -> dict[str, Any]:
        # 身份读取特意让出事件循环；若生产实现重新并发调用，本测试会观察到并发数大于 1。
        self.active_hashes += 1
        self.max_active_hashes = max(self.max_active_hashes, self.active_hashes)
        self.hash_paths.append(path)
        try:
            await anyio.sleep(0)
            if self.hash_results:
                result = self.hash_results.pop(0)
                if isinstance(result, Exception):
                    raise result
                assert isinstance(result, dict)
                return result
            _relative, remote = self.normalize_path(path)
            content = self.fs.files[remote]
            return {
                "path": path,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        finally:
            self.active_hashes -= 1


class _FakeAdapter:
    def __init__(self, source_id: str) -> None:
        self.config = SimpleNamespace(
            id=source_id,
            limits=SimpleNamespace(query_concurrency=3, max_bytes=256 * 1024 * 1024),
        )

    async def query(self, sql: str) -> QueryResult:
        raise AssertionError(f"DatasetStore 不应通过行结果物化 CSV: {sql}")

    async def materialize(
        self, sql: str, *, max_bytes: int | None = None
    ) -> MaterializedQueryResult:
        await anyio.sleep(0)
        content = f"sql\r\n{sql}\r\n".encode()
        assert max_bytes == 200 * 1024 * 1024
        return MaterializedQueryResult(content=content, row_count=1)


def _approved_queries(count: int = 3) -> tuple[ApprovedQuery, ...]:
    result = []
    for index in range(count):
        sql = f"SELECT {index}"
        result.append(
            ApprovedQuery(
                requirementId=f"requirement-{index}",
                sourceId="source-1",
                sql=sql,
                sqlHash=normalized_sql_hash(sql),
            )
        )
    return tuple(result)


def _context() -> RunContext:
    return RunContext(run_id="run-1", session_id="thread-1", session_state={})


@pytest.mark.anyio
async def test_外部_csv登记通过异步工作区接口读取() -> None:
    service = _FakeDatasetService()
    content = b"month,revenue\n2026-01,100\n"
    path = "inputs/revenue.csv"
    _relative, remote = service.normalize_path(path)
    service.fs.files[remote] = content
    file = ReportFileInput(
        path=path,
        filename="revenue.csv",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        mediaType="text/csv",
    )

    handles, lineage = await ReportDatasetStore(service).register_external_csv(  # type: ignore[arg-type]
        (file,), run_context=_context()
    )

    assert len(handles) == len(lineage) == 1
    assert handles[0].row_count == 1
    assert service.reads == [("thread-1", path)]


@pytest.mark.anyio
async def test_数据集并发上传后按稳定顺序串行校验身份() -> None:
    service = _FakeDatasetService()
    approved = _approved_queries()

    handles, lineage = await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
        approved,
        {"source-1": _FakeAdapter("source-1")},  # type: ignore[dict-item]
        run_context=_context(),
    )

    assert service.fs.max_active_uploads > 1
    assert service.max_active_hashes == 1
    assert service.fs.completed_uploads == len(approved)
    assert [item.requirement_id for item in handles] == [item.requirement_id for item in approved]
    assert [item.requirement_id for item in lineage] == [item.requirement_id for item in approved]
    assert len(service.hash_paths) == len(approved)
    assert len(service.fs.moves) == 1


@pytest.mark.anyio
async def test_数据集哈希回执瞬时无效时仅重试当前身份读取(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "smart_reporting.reporting.data_sources._DATASET_HASH_RETRY_DELAY_SECONDS", 0
    )
    service = _FakeDatasetService(
        [WorkspaceHashResultError("工作区文件哈希结果无效，请稍后重试。")]
    )

    handles, _lineage = await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
        _approved_queries(1),
        {"source-1": _FakeAdapter("source-1")},  # type: ignore[dict-item]
        run_context=_context(),
    )

    assert len(handles) == 1
    assert len(service.hash_paths) == 2
    assert service.fs.completed_uploads == 1


@pytest.mark.anyio
async def test_数据集哈希回执持续无效时回滚且不发布(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "smart_reporting.reporting.data_sources._DATASET_HASH_RETRY_DELAY_SECONDS", 0
    )
    service = _FakeDatasetService(
        [
            WorkspaceHashResultError("工作区文件哈希结果无效，请稍后重试。"),
            WorkspaceHashResultError("工作区文件哈希结果无效，请稍后重试。"),
            WorkspaceHashResultError("工作区文件哈希结果无效，请稍后重试。"),
        ]
    )

    with pytest.raises(ReportingError) as captured:
        await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
            _approved_queries(1),
            {"source-1": _FakeAdapter("source-1")},  # type: ignore[dict-item]
            run_context=_context(),
        )

    assert captured.value.code == "report_dataset_commit_failed"
    assert len(service.hash_paths) == 3
    assert service.fs.moves == []
    assert len(service.fs.deletes) >= 2


@pytest.mark.anyio
async def test_数据集真实身份冲突立即拒绝且不重试() -> None:
    service = _FakeDatasetService([{"path": "staged.csv", "size": 1, "sha256": "0" * 64}])

    with pytest.raises(ReportingError) as captured:
        await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
            _approved_queries(1),
            {"source-1": _FakeAdapter("source-1")},  # type: ignore[dict-item]
            run_context=_context(),
        )

    assert captured.value.code == "report_dataset_commit_failed"
    assert len(service.hash_paths) == 1
    assert service.fs.moves == []


@pytest.mark.anyio
async def test_数据集存储对适配器结果再次执行字节上限校验() -> None:
    service = _FakeDatasetService()
    adapter = _FakeAdapter("source-1")
    adapter.config.limits.max_bytes = 1

    with pytest.raises(ReportingError) as captured:
        await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
            _approved_queries(1),
            {"source-1": adapter},  # type: ignore[dict-item]
            run_context=_context(),
        )

    assert captured.value.code == "query_result_too_large"
    assert service.fs.completed_uploads == 0
    assert service.fs.moves == []


@pytest.mark.anyio
async def test_数据集哈希命令失败立即拒绝且不重试() -> None:
    service = _FakeDatasetService([WorkspaceError("工作区文件哈希计算失败")])

    with pytest.raises(ReportingError) as captured:
        await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
            _approved_queries(1),
            {"source-1": _FakeAdapter("source-1")},  # type: ignore[dict-item]
            run_context=_context(),
        )

    assert captured.value.code == "report_dataset_commit_failed"
    assert len(service.hash_paths) == 1
    assert service.fs.moves == []


@pytest.mark.anyio
async def test_数据集物化取消时清理暂存和目标目录() -> None:
    entered = asyncio.Event()
    service = _FakeDatasetService()

    class BlockingAdapter(_FakeAdapter):
        async def materialize(
            self, sql: str, *, max_bytes: int | None = None
        ) -> MaterializedQueryResult:
            del sql, max_bytes
            entered.set()
            await asyncio.Future()

    task = asyncio.create_task(
        ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
            _approved_queries(1),
            {"source-1": BlockingAdapter("source-1")},  # type: ignore[dict-item]
            run_context=_context(),
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(service.fs.deletes) == 2
    assert any("/.staging-" in path for path in service.fs.deletes)
    assert any("/batch-" in path for path in service.fs.deletes)


@pytest.mark.anyio
@pytest.mark.parametrize("output", ["invalid\x001\x00", "abc", f"{'0' * 64}\x00x\x00"])
async def test_工作区哈希协议异常使用可重试专用错误(output: str) -> None:
    service = WorkspaceService("0123456789abcdef0123456789abcdef")

    async def run_command(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return output, False

    service._arun_workspace_command = run_command  # type: ignore[method-assign]

    with pytest.raises(WorkspaceHashResultError):
        await service.ahash_file("thread-1", "dataset.csv")
