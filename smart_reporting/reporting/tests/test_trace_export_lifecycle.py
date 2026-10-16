"""派生 CSV 的真实生成线程在取消后仍须受并发、来源锁和清理约束。"""
from __future__ import annotations

import asyncio
import hashlib
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor import trace_exports
from smart_reporting.report_editor.trace_exports import TraceDerivedExportService
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.dataset_service import TraceDatasetFile


@pytest.mark.anyio
@pytest.mark.parametrize("stop", ["expiry", "timeout", "cancel", "shutdown"])
async def test_cancelled_export_keeps_guard_and_capacity_until_writer_finishes(
    tmp_path: Path, monkeypatch, stop: str,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    guard_released = asyncio.Event()
    deleted = asyncio.Event()

    class Paths:
        def normalize(self, path, **kwargs):
            return path

        def to_host_path(self, path, **kwargs):
            return tmp_path / path

    class Workspace:
        def workspace(self, thread):
            return SimpleNamespace(paths=Paths())

        async def adelete_file(self, thread, path):
            assert finished.is_set(), "清理不能早于实际写线程结束"
            (tmp_path / path).unlink(missing_ok=True)
            deleted.set()

    @asynccontextmanager
    async def guard(context):
        try:
            yield
        finally:
            guard_released.set()

    generate = TraceDerivedExportService._generate

    def blocked_generate(source, target, columns, mask):
        entered.set()
        try:
            assert release.wait(5), "测试没有释放写线程"
            generate(source, target, columns, mask)
        finally:
            finished.set()

    monkeypatch.setattr(trace_exports, "_MAX_DERIVED_EXPORT_JOBS", 1)
    if stop == "timeout":
        monkeypatch.setattr(trace_exports, "_DERIVED_EXPORT_TIMEOUT_SECONDS", 0.1)
    source = tmp_path / "source.csv"
    content = b"name,secret\nAlice,123\n"
    source.write_bytes(content)
    file = TraceDatasetFile(
        dataset_id="dataset-cancel01", local_path=source, size=len(content),
        sha256=hashlib.sha256(content).hexdigest(), row_count=1,
    )
    context = SimpleNamespace(
        report_id="report-1", revision=1, scope={"threadId": "thread-1"},
        markdown_path="report/report.md",
    )
    service = TraceDerivedExportService(Workspace())
    service.source_guard = guard
    monkeypatch.setattr(service, "_generate", blocked_generate)
    started = await service.create(
        context=context, file=file, policy="masked_columns", params={"columns": ["secret"]},
    )
    job = service._jobs[started["exportId"]]
    closing = None
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if stop == "expiry":
            job.created_at = 0
            await service.status(context, job.export_id)
        elif stop == "cancel":
            job.task.cancel()
        elif stop == "shutdown":
            closing = asyncio.create_task(service.aclose())
        await asyncio.wait_for(asyncio.gather(job.task, return_exceptions=True), timeout=2)
        service._cleanup_expired()
        await asyncio.sleep(0)
        assert not guard_released.is_set(), "取消外层任务不得释放仍在使用的来源锁"
        assert not deleted.is_set()
        assert job.export_id in service._jobs
        assert job.status == "failed"
        expected_error = "超时" if stop == "timeout" else "取消"
        assert expected_error in job.error
        if closing is not None:
            assert not closing.done()
        with pytest.raises(ReportingError) as busy:
            await service.create(
                context=context, file=file, policy="masked_columns", params={"columns": ["secret"]},
            )
        assert busy.value.code == "report_editor_export_busy"
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 3)
        await asyncio.wait_for(guard_released.wait(), timeout=3)
    await asyncio.wait_for(deleted.wait(), timeout=3)
    if closing is not None:
        await asyncio.wait_for(closing, timeout=3)
    assert not (tmp_path / job.workspace_path).exists()
    assert job.status != "completed"
    if stop == "expiry":
        service._cleanup_expired()
        assert job.export_id not in service._jobs
