"""Office 引擎子进程调用的并发上限。"""

from __future__ import annotations

import asyncio
import contextvars
import shutil
import threading
import time
from pathlib import Path

import pytest

from smart_reporting.reporting.delivery import office_engine


@pytest.fixture
def fresh_executor(monkeypatch):
    def configure(concurrency: str | None):
        if concurrency is None:
            monkeypatch.delenv("AGENT_REPORTING_OFFICE_ENGINE_CONCURRENCY", raising=False)
        else:
            monkeypatch.setenv("AGENT_REPORTING_OFFICE_ENGINE_CONCURRENCY", concurrency)
        monkeypatch.setattr(office_engine, "_executor", None)
    yield configure
    executor = office_engine._executor
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("3", 3), ("0", None), ("abc", None), (None, None)],
)
def test_concurrency_reads_positive_setting_or_falls_back(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("AGENT_REPORTING_OFFICE_ENGINE_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("AGENT_REPORTING_OFFICE_ENGINE_CONCURRENCY", value)
    concurrency = office_engine.office_engine_concurrency()
    if expected is None:
        assert 1 <= concurrency <= 4
    else:
        assert concurrency == expected


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_engine_calls_never_exceed_configured_concurrency(anyio_backend, fresh_executor):
    fresh_executor("2")
    lock = threading.Lock()
    active = 0
    peak = 0

    def engine_call(index: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return index

    results = await asyncio.gather(*(office_engine.run_office_engine(engine_call, i) for i in range(6)))

    assert results == list(range(6))
    assert peak == 2


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_cancelled_queued_engine_call_never_starts(anyio_backend, fresh_executor):
    fresh_executor("1")
    release = threading.Event()
    started: list[str] = []

    def blocking() -> None:
        started.append("first")
        release.wait(5)

    def queued() -> None:
        started.append("queued")

    first = asyncio.ensure_future(office_engine.run_office_engine(blocking))
    await asyncio.sleep(0.05)
    second = asyncio.ensure_future(office_engine.run_office_engine(queued))
    await asyncio.sleep(0.05)
    second.cancel()
    release.set()
    await first
    with pytest.raises(asyncio.CancelledError):
        await second
    await office_engine.run_office_engine(lambda: None)

    assert started == ["first"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_engine_call_keeps_caller_context(anyio_backend, fresh_executor):
    fresh_executor("1")
    request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id")
    request_id.set("req-1")

    assert await office_engine.run_office_engine(request_id.get) == "req-1"


_PPTX_FIXTURE = Path(__file__).parents[1] / "slides_engine/packages/pptx-engine/tests/fixtures/01_standard_business.pptx"


@pytest.mark.skipif(
    shutil.which("libreoffice") is None and shutil.which("soffice") is None,
    reason="LibreOffice 未安装",
)
def test_concurrent_libreoffice_conversions_use_isolated_profiles():
    """共享默认配置目录时，并发转换会有进程直接退出且不产出 PDF。"""
    from concurrent.futures import ThreadPoolExecutor

    content = _PPTX_FIXTURE.read_bytes()
    with ThreadPoolExecutor(4) as executor:
        results = list(executor.map(
            lambda _index: office_engine.libreoffice_to_pdf(content, suffix=".pptx", timeout=90), range(4),
        ))

    assert all(result.startswith(b"%PDF") for result in results)


def test_libreoffice_conversion_reports_missing_converter(monkeypatch):
    monkeypatch.setattr(office_engine.shutil, "which", lambda _name: None)

    with pytest.raises(office_engine.OfficeConversionError, match="未安装"):
        office_engine.libreoffice_to_pdf(b"x", suffix=".docx", timeout=5)
