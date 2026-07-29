from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import anyio
import pytest
from agno.run import RunContext

from agentos_dev.coding.reporting.data_source import DataSourceAdapter, QueryResult
from agentos_dev.coding.reporting.data_sources import (
    REPORT_DATASET_HANDLES_STATE_KEY,
    ReportDatasetStore,
)
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.workflow_v1 import ApprovedQuery, normalized_sql_hash


class FakeAdapter:
    config: Any = SimpleNamespace(id="operations", limits=SimpleNamespace(query_concurrency=2))

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.active_queries = 0
        self.max_active_queries = 0

    async def query(self, sql: str) -> QueryResult:
        self.queries.append(sql)
        self.active_queries += 1
        self.max_active_queries = max(self.max_active_queries, self.active_queries)
        try:
            await anyio.sleep(0.01)
            value = int(sql.split("SELECT ", 1)[1].split(" ", 1)[0])
            return QueryResult(("month", "amount"), (("2025-01", value),), 20)
        finally:
            self.active_queries -= 1


class FakeFs:
    def __init__(self, *, fail_upload: int | None = None, fail_move: int | None = None):
        self.entries: dict[str, bytes | None] = {}
        self.fail_upload = fail_upload
        self.fail_move = fail_move
        self.upload_count = 0
        self.move_count = 0

    async def upload_file(self, content: bytes, path: str) -> None:
        self.upload_count += 1
        if self.upload_count == self.fail_upload:
            raise RuntimeError("upload failed")
        self.entries[path] = bytes(content)

    async def move_files(self, source: str, destination: str) -> None:
        self.move_count += 1
        if self.move_count == self.fail_move:
            raise RuntimeError("move failed")
        prefix = source.rstrip("/") + "/"
        moved = {
            destination + path[len(source) :]: content
            for path, content in self.entries.items()
            if path == source or path.startswith(prefix)
        }
        for path in tuple(self.entries):
            if path == source or path.startswith(prefix):
                self.entries.pop(path)
        self.entries.update(moved)

    async def delete_file(self, path: str, recursive: bool = False) -> None:
        if recursive:
            prefix = path.rstrip("/") + "/"
            for item in tuple(self.entries):
                if item == path or item.startswith(prefix):
                    self.entries.pop(item, None)
            return
        self.entries.pop(path, None)


class FakeWorkspaceService:
    def __init__(
        self,
        *,
        fail_upload: int | None = None,
        fail_hash: int | None = None,
        fail_move: int | None = None,
    ) -> None:
        self.fs = FakeFs(fail_upload=fail_upload, fail_move=fail_move)
        self.sandbox = SimpleNamespace(fs=self.fs)
        self.fail_hash = fail_hash
        self.hash_count = 0

    @asynccontextmanager
    async def _async_client(self):
        yield object()

    async def _asandbox_for(self, _client: object, _thread: str):
        return self.sandbox

    def normalize_path(self, path: str, *, allow_root: bool):
        assert not allow_root
        return path, f"/workspace/{path}"

    async def _aensure_directory(self, _sandbox: object, remote: str) -> None:
        self.fs.entries[remote] = None

    async def ahash_file(self, _thread: str, path: str) -> dict[str, str | int]:
        self.hash_count += 1
        content = self.fs.entries[f"/workspace/{path}"]
        assert content is not None
        digest = hashlib.sha256(content).hexdigest()
        if self.hash_count == self.fail_hash:
            digest = "0" * 64
        return {"sha256": digest, "size": len(content)}


def approved_queries(indexes: tuple[int, ...] = (1, 2)) -> tuple[ApprovedQuery, ...]:
    return tuple(
        ApprovedQuery(
            requirementId=f"requirement-{index}",
            sourceId="operations",
            sql=f"SELECT {index} AS value FROM reporting.income",
            sqlHash=normalized_sql_hash(f"SELECT {index} AS value FROM reporting.income"),
        )
        for index in indexes
    )


def run_context() -> RunContext:
    return RunContext(
        run_id="run-atomic",
        session_id="thread-1",
        session_state={"existing": "unchanged"},
    )


def adapters(adapter: FakeAdapter) -> dict[str, DataSourceAdapter]:
    return {"operations": cast(DataSourceAdapter, adapter)}


def assert_failed_batch_is_clean(service: FakeWorkspaceService, context: RunContext) -> None:
    assert context.session_state == {"existing": "unchanged"}
    assert REPORT_DATASET_HANDLES_STATE_KEY not in context.session_state
    assert not any(path.endswith(".csv") for path in service.fs.entries)
    assert not any("/.staging-" in path for path in service.fs.entries)


@pytest.mark.anyio
async def test_第二次上传失败不发布状态并清理staging():
    service = FakeWorkspaceService(fail_upload=2)
    context = run_context()
    adapter = FakeAdapter()

    with pytest.raises(ReportingError) as captured:
        await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
            approved_queries(), adapters(adapter), run_context=context
        )

    assert captured.value.code == "report_dataset_commit_failed"
    assert len(adapter.queries) == 2
    assert_failed_batch_is_clean(service, context)


@pytest.mark.anyio
async def test_第二个staging文件校验失败不发布状态并清理文件():
    service = FakeWorkspaceService(fail_hash=2)
    context = run_context()

    with pytest.raises(ReportingError) as captured:
        await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
            approved_queries(), adapters(FakeAdapter()), run_context=context
        )

    assert captured.value.code == "report_dataset_commit_failed"
    assert_failed_batch_is_clean(service, context)


@pytest.mark.anyio
async def test_目录原子移动失败不留下本批次最终文件():
    service = FakeWorkspaceService(fail_move=1)
    context = run_context()

    with pytest.raises(ReportingError) as captured:
        await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
            approved_queries(), adapters(FakeAdapter()), run_context=context
        )

    assert captured.value.code == "report_dataset_commit_failed"
    assert service.fs.move_count == 1
    assert_failed_batch_is_clean(service, context)


@pytest.mark.anyio
async def test_全部移动成功后统一写入句柄和血缘():
    service = FakeWorkspaceService()
    context = run_context()
    adapter = FakeAdapter()

    handles, lineage = await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
        approved_queries(), adapters(adapter), run_context=context
    )

    assert len(adapter.queries) == 2
    assert len(handles) == len(lineage) == 2
    assert all(f"/workspace/{handle.path}" in service.fs.entries for handle in handles)
    assert context.session_state is not None
    stored = context.session_state[REPORT_DATASET_HANDLES_STATE_KEY]
    assert set(stored) == {handle.dataset_id for handle in handles}
    assert not any("/.staging-" in path for path in service.fs.entries)


@pytest.mark.anyio
async def test_审核sql按配置有界并行且句柄顺序稳定():
    service = FakeWorkspaceService()
    context = run_context()
    adapter = FakeAdapter()
    approved = approved_queries((1, 2, 3, 4))

    handles, lineage = await ReportDatasetStore(service).materialize_batch(  # type: ignore[arg-type]
        approved, adapters(adapter), run_context=context
    )

    assert adapter.max_active_queries == 2
    assert [item.requirement_id for item in handles] == [item.requirement_id for item in approved]
    assert [item.requirement_id for item in lineage] == [item.requirement_id for item in approved]
