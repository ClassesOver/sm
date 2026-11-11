"""应用生命周期内的业务原件解析；任务及恢复身份由数据库租约保存。"""

import asyncio

from loguru import logger

from ..reporting.business_knowledge.models import IngestionLease
from .business_documents import BusinessDocumentService

HEARTBEAT_SECONDS = 30
POLL_SECONDS = 5


class BusinessIngestionWorker:
    def __init__(self, service: BusinessDocumentService):
        self.service = service
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="business-document-ingestion")

    def notify(self) -> None:
        self._wake.set()

    async def aclose(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _heartbeat(self, lease: IngestionLease) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await self.service.renew_lease(lease)

    async def run_once(self) -> bool:
        lease = await self.service.claim_next()
        if lease is None:
            return False
        parsing = asyncio.create_task(self.service.ingest_revision(lease))
        heartbeat = asyncio.create_task(self._heartbeat(lease))
        try:
            done, _ = await asyncio.wait((parsing, heartbeat), return_when=asyncio.FIRST_COMPLETED)
            if parsing in done:
                await parsing
            else:
                # 续租失败即停止本次提交；线程仅解析原件，迟到结果不能覆盖新租约。
                await heartbeat
            return True
        finally:
            for task in (parsing, heartbeat):
                if not task.done():
                    task.cancel()
            await asyncio.gather(parsing, heartbeat, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            self._wake.clear()
            try:
                if await self.run_once():
                    continue
            except Exception as error:
                logger.warning("business_ingestion_worker_failed error_type={}", type(error).__name__)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=POLL_SECONDS)
            except TimeoutError:
                pass
