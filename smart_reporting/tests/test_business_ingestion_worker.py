"""生命周期worker从持久队列恢复；失败任务不能自动重试。"""

import asyncio
from datetime import timedelta
from threading import Event

import pytest

from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_document_ingestion import register
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def wait_status(service, token, scope, job_id, expected):
    async with asyncio.timeout(10):
        while True:
            receipt = await service.get_job(token, scope, job_id)
            if receipt.status == expected:
                return receipt
            await asyncio.sleep(0.05)


async def test_worker_start_stop_and_new_instance_resume_queued_documents(document_context):
    from smart_reporting.management.business_ingestion_worker import BusinessIngestionWorker
    service, token, first, *_ = document_context
    initial = await register(document_context)
    worker = BusinessIngestionWorker(service)
    await worker.start()
    try:
        assert (await wait_status(service, token, first, initial.job_id, "parsed")).attempt == 1
    finally:
        await worker.aclose()
    second = await register(document_context, "upload-2", expected_version=1, body=b"revision two")
    replacement = BusinessIngestionWorker(service)
    await replacement.start()
    replacement.notify()
    try:
        result = await wait_status(service, token, first, second.job_id, "parsed")
        assert result.revision == 2
        assert result.attempt == 1
    finally:
        await replacement.aclose()


async def test_worker_does_not_restart_failed_parse_without_admin_retry(document_context, monkeypatch):
    import smart_reporting.management.business_documents as module
    from smart_reporting.management.business_ingestion_worker import BusinessIngestionWorker
    service, token, first, *_ = document_context
    receipt = await register(document_context)

    def broken(*args, **kwargs):
        raise RuntimeError("parse fault")

    monkeypatch.setattr(module, "parse_document", broken)
    worker = BusinessIngestionWorker(service)
    await worker.start()
    try:
        failed = await wait_status(service, token, first, receipt.job_id, "failed")
        assert failed.attempt == 1
        assert await worker.run_once() is False
        assert (await service.get_job(token, first, receipt.job_id)).attempt == 1
    finally:
        await worker.aclose()


async def test_worker_renews_lease_while_parser_is_running(document_context, auth_context, monkeypatch):
    from sqlalchemy import select

    import smart_reporting.management.business_documents as documents
    import smart_reporting.management.business_ingestion_worker as workers
    from smart_reporting.management.repository import business_ingestion_jobs as jobs

    service, token, scope, *_ = document_context
    receipt = await register(document_context)
    real_parse = documents.parse_document
    entered, release = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()

    def slow_parse(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(10):
            raise TimeoutError("test parser was not released")
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(documents, "parse_document", slow_parse)
    monkeypatch.setattr(workers, "HEARTBEAT_SECONDS", 0.01)
    worker = workers.BusinessIngestionWorker(service)
    running = asyncio.create_task(worker.run_once())
    _, repository, clock = auth_context
    try:
        await asyncio.wait_for(entered.wait(), 10)
        clock[0] += timedelta(seconds=90)
        async with asyncio.timeout(10):
            while True:
                async with repository.transaction() as connection:
                    until = await connection.scalar(select(jobs.c.lease_until).where(jobs.c.job_id == receipt.job_id))
                if until > clock[0] + timedelta(seconds=100):
                    break
                await asyncio.sleep(0.01)
        clock[0] += timedelta(seconds=40)
        assert await service.claim_next() is None
        release.set()
        assert await asyncio.wait_for(running, 10) is True
        assert (await service.get_job(token, scope, receipt.job_id)).status == "parsed"
    finally:
        release.set()
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


async def test_shutdown_leaves_interrupted_job_reclaimable_without_late_result(document_context, auth_context, monkeypatch):
    import smart_reporting.management.business_documents as documents
    from smart_reporting.management.business_ingestion_worker import BusinessIngestionWorker

    service, token, scope, *_ = document_context
    receipt = await register(document_context)
    entered, release = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()
    real_parse = documents.parse_document

    def slow_parse(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(10):
            raise TimeoutError("test parser was not released")
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(documents, "parse_document", slow_parse)
    worker = BusinessIngestionWorker(service)
    await worker.start()
    try:
        await asyncio.wait_for(entered.wait(), 10)
        await worker.aclose()
        assert (await service.get_job(token, scope, receipt.job_id)).status == "running"
        assert await service.claim_next() is None
        _, _, clock = auth_context
        clock[0] += timedelta(seconds=121)
        monkeypatch.setattr(documents, "parse_document", real_parse)
        assert await worker.run_once() is True
        result = await service.get_job(token, scope, receipt.job_id)
        assert result.status == "parsed"
        assert result.attempt == 2
    finally:
        release.set()
        await worker.aclose()


async def test_renewal_cannot_overwrite_owner_claimed_during_transaction(document_context, auth_context, monkeypatch):
    service, *_ = document_context
    await register(document_context)
    lease = await service.claim_next()
    checked, resume = asyncio.Event(), asyncio.Event()
    require_lease = service._require_lease

    async def paused_check(connection, current):
        row = await require_lease(connection, current)
        checked.set()
        await resume.wait()
        return row

    monkeypatch.setattr(service, "_require_lease", paused_check)
    renewal = asyncio.create_task(service.renew_lease(lease))
    try:
        await asyncio.wait_for(checked.wait(), 10)
        auth_context[2][0] += timedelta(seconds=121)
        # 续租事务持有有效身份后，过期重领不能穿过该事务改变owner。
        takeover = asyncio.create_task(service.claim_next())
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(takeover), 0.1)
            resume.set()
            await asyncio.wait_for(renewal, 10)
            assert await asyncio.wait_for(takeover, 10) is None
        finally:
            takeover.cancel()
            await asyncio.gather(takeover, return_exceptions=True)
    finally:
        resume.set()
        await asyncio.gather(renewal, return_exceptions=True)
