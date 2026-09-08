from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from .data_source.starrocks import StarRocksDataSourceAdapter, StarRocksSourceConfig
from .metadata import ReportingMetadataClient
from .models import ReportingError

STARROCKS_CONNECTION_TEST_SQL = "SELECT 1 AS connection_test"
STARROCKS_CHECK_TIMEOUT_SECONDS = 15
STARROCKS_CLEANUP_TIMEOUT_SECONDS = 5
STARROCKS_CHECK_CONCURRENCY = 4
SANDBOX_CHECK_TIMEOUT_SECONDS = 10
StarRocksAdapterFactory = Callable[[StarRocksSourceConfig], StarRocksDataSourceAdapter]
SandboxCheck = Callable[[], Awaitable[None]]
class DependencyCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    ok: bool
    code: str
    duration_ms: int = Field(alias="durationMs", ge=0)
    http_status: int | None = Field(default=None, alias="httpStatus", ge=100, le=599)


class StarRocksSourceCheckResult(DependencyCheckResult):
    source_id: str = Field(alias="sourceId")


class StarRocksCheckResult(DependencyCheckResult):
    sources: tuple[StarRocksSourceCheckResult, ...] = ()


class ReportingDependencyChecks(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    starrocks: StarRocksCheckResult
    metadata: DependencyCheckResult
    sandbox: DependencyCheckResult


class ReportingDependencyCheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok", "failed"]
    checks: ReportingDependencyChecks


class ReportingDependencyDiagnostics:
    """只探测服务端已批准的 Reporting 依赖，不接受调用方连接参数。"""

    def __init__(
        self,
        *,
        sources: tuple[StarRocksSourceConfig, ...],
        metadata_client: ReportingMetadataClient | None,
        sandbox_check: SandboxCheck | None,
        starrocks_adapter_factory: StarRocksAdapterFactory = StarRocksDataSourceAdapter,
    ):
        self.sources = sources
        self.metadata_client = metadata_client
        self.sandbox_check = sandbox_check
        self.starrocks_adapter_factory = starrocks_adapter_factory

    async def check(self) -> ReportingDependencyCheckResponse:
        started_at = perf_counter()
        starrocks, metadata, sandbox = await asyncio.gather(
            self._check_starrocks(),
            self._check_metadata(),
            self._check_sandbox(),
        )
        checks = ReportingDependencyChecks(
            starrocks=starrocks,
            metadata=metadata,
            sandbox=sandbox,
        )
        response = ReportingDependencyCheckResponse(
            status="ok" if starrocks.ok and metadata.ok and sandbox.ok else "failed",
            checks=checks,
        )
        logger.info(
            "report_dependency_diagnostics_completed status={} duration_ms={} "
            "starrocks_code={} metadata_code={} sandbox_code={}",
            response.status,
            _duration_ms(started_at),
            starrocks.code,
            metadata.code,
            sandbox.code,
        )
        return response

    async def _check_starrocks(self) -> StarRocksCheckResult:
        started_at = perf_counter()
        if not self.sources:
            return StarRocksCheckResult(
                ok=False,
                code="starrocks_not_configured",
                durationMs=_duration_ms(started_at),
            )
        # 诊断路由可被重复调用，数据源数量又由部署配置决定；固定并发和单源时限
        # 共同约束数据库连接占用，不能让一个失联数据源无限阻塞整个 HTTP 请求。
        semaphore = asyncio.Semaphore(STARROCKS_CHECK_CONCURRENCY)
        results = tuple(
            await asyncio.gather(
                *(
                    self._check_starrocks_source_with_limit(source, semaphore)
                    for source in self.sources
                )
            )
        )
        return StarRocksCheckResult(
            ok=all(result.ok for result in results),
            code="ok" if all(result.ok for result in results) else "starrocks_connection_failed",
            durationMs=_duration_ms(started_at),
            sources=results,
        )

    async def _check_starrocks_source_with_limit(
        self,
        source: StarRocksSourceConfig,
        semaphore: asyncio.Semaphore,
    ) -> StarRocksSourceCheckResult:
        started_at = perf_counter()
        try:
            async with asyncio.timeout(STARROCKS_CHECK_TIMEOUT_SECONDS):
                async with semaphore:
                    return await self._check_starrocks_source(source)
        except TimeoutError:
            logger.warning(
                "report_dependency_check_failed dependency=starrocks source_id={} "
                "code=starrocks_timeout duration_ms={}",
                source.id,
                _duration_ms(started_at),
            )
            return StarRocksSourceCheckResult(
                sourceId=source.id,
                ok=False,
                code="starrocks_timeout",
                durationMs=_duration_ms(started_at),
            )

    async def _check_starrocks_source(
        self, source: StarRocksSourceConfig
    ) -> StarRocksSourceCheckResult:
        started_at = perf_counter()
        adapter: StarRocksDataSourceAdapter | None = None
        ok = False
        code = "starrocks_connection_failed"
        try:
            adapter = self.starrocks_adapter_factory(source)
            await adapter.query(STARROCKS_CONNECTION_TEST_SQL)
            ok = True
            code = "ok"
        except ReportingError as error:
            code = error.code
            _log_dependency_failure(
                dependency="starrocks",
                operation="select_1",
                code=code,
                started_at=started_at,
                error=error,
                source_id=source.id,
            )
        except Exception as error:
            _log_dependency_failure(
                dependency="starrocks",
                operation="select_1",
                code=code,
                started_at=started_at,
                error=error,
                source_id=source.id,
            )
        finally:
            if adapter is not None:
                try:
                    await asyncio.wait_for(
                        adapter.aclose(),
                        timeout=STARROCKS_CLEANUP_TIMEOUT_SECONDS,
                    )
                except Exception as error:
                    if ok:
                        ok = False
                        code = "starrocks_cleanup_failed"
                        _log_dependency_failure(
                            dependency="starrocks",
                            operation="close_adapter",
                            code=code,
                            started_at=started_at,
                            error=error,
                            source_id=source.id,
                        )
        if ok:
            logger.debug(
                "report_dependency_check_completed dependency=starrocks source_id={} "
                "code=ok duration_ms={}",
                source.id,
                _duration_ms(started_at),
            )
        return StarRocksSourceCheckResult(
            sourceId=source.id,
            ok=ok,
            code=code,
            durationMs=_duration_ms(started_at),
        )

    async def _check_metadata(self) -> DependencyCheckResult:
        started_at = perf_counter()
        if self.metadata_client is None:
            return DependencyCheckResult(
                ok=False,
                code="report_metadata_not_configured",
                durationMs=_duration_ms(started_at),
            )
        try:
            await self.metadata_client.query_agent()
        except ReportingError as error:
            details = error.details if isinstance(error.details, Mapping) else {}
            http_status = details.get("httpStatus")
            safe_http_status = (
                http_status
                if isinstance(http_status, int) and not isinstance(http_status, bool)
                else None
            )
            _log_dependency_failure(
                dependency="metadata",
                operation="get_agent_json",
                code=error.code,
                started_at=started_at,
                error=error,
                http_status=safe_http_status,
            )
            return DependencyCheckResult(
                ok=False,
                code=error.code,
                durationMs=_duration_ms(started_at),
                httpStatus=safe_http_status,
            )
        except Exception as error:
            _log_dependency_failure(
                dependency="metadata",
                operation="get_agent_json",
                code="report_metadata_check_failed",
                started_at=started_at,
                error=error,
            )
            return DependencyCheckResult(
                ok=False,
                code="report_metadata_check_failed",
                durationMs=_duration_ms(started_at),
            )
        logger.debug(
            "report_dependency_check_completed dependency=metadata code=ok duration_ms={}",
            _duration_ms(started_at),
        )
        return DependencyCheckResult(ok=True, code="ok", durationMs=_duration_ms(started_at))

    async def _check_sandbox(self) -> DependencyCheckResult:
        started_at = perf_counter()
        if self.sandbox_check is None:
            return DependencyCheckResult(
                ok=False,
                code="sandbox_not_configured",
                durationMs=_duration_ms(started_at),
            )
        try:
            await asyncio.wait_for(
                self.sandbox_check(),
                timeout=SANDBOX_CHECK_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "report_dependency_check_failed dependency=sandbox code=sandbox_timeout "
                "duration_ms={}",
                _duration_ms(started_at),
            )
            return DependencyCheckResult(
                ok=False,
                code="sandbox_timeout",
                durationMs=_duration_ms(started_at),
            )
        except Exception as error:
            _log_dependency_failure(
                dependency="sandbox",
                operation="list_sandboxes",
                code="sandbox_unavailable",
                started_at=started_at,
                error=error,
            )
            return DependencyCheckResult(
                ok=False,
                code="sandbox_unavailable",
                durationMs=_duration_ms(started_at),
            )
        logger.debug(
            "report_dependency_check_completed dependency=sandbox code=ok duration_ms={}",
            _duration_ms(started_at),
        )
        return DependencyCheckResult(ok=True, code="ok", durationMs=_duration_ms(started_at))


def create_reporting_dependency_diagnostics_router(
    diagnostics: ReportingDependencyDiagnostics,
) -> APIRouter:
    router = APIRouter()

    @router.post("/diagnostics/reporting-dependencies", include_in_schema=False)
    async def reporting_dependency_diagnostics() -> JSONResponse:
        result = await diagnostics.check()
        return JSONResponse(
            result.model_dump(mode="json", by_alias=True, exclude_none=True),
            status_code=200 if result.status == "ok" else 503,
            headers={"Cache-Control": "no-store"},
        )

    return router


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def _log_dependency_failure(
    *,
    dependency: str,
    operation: str,
    code: str,
    started_at: float,
    error: BaseException,
    source_id: str | None = None,
    http_status: int | None = None,
) -> None:
    error_types, error_numbers = _safe_error_facts(error)
    logger.warning(
        "report_dependency_check_failed dependency={} operation={} source_id={} "
        "code={} duration_ms={} "
        "http_status={} error_types={} error_numbers={}",
        dependency,
        operation,
        source_id or "-",
        code,
        _duration_ms(started_at),
        http_status if http_status is not None else "-",
        ",".join(error_types) or "-",
        ",".join(str(value) for value in error_numbers) or "-",
    )


def _safe_error_facts(error: BaseException) -> tuple[tuple[str, ...], tuple[int, ...]]:
    """只提取类型名和数字状态，禁止把可能含凭据的异常正文写入日志。"""

    pending: list[BaseException] = [error]
    seen: set[int] = set()
    types: list[str] = []
    numbers: list[int] = []
    while pending and len(seen) < 8:
        current = pending.pop(0)
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        type_name = type(current).__name__
        if type_name not in types:
            types.append(type_name)
        for attribute in ("errno", "status", "status_code", "http_status"):
            value = getattr(current, attribute, None)
            if isinstance(value, int) and not isinstance(value, bool) and value not in numbers:
                numbers.append(value)
        arguments = getattr(current, "args", ())
        if arguments and isinstance(arguments[0], int) and arguments[0] not in numbers:
            numbers.append(arguments[0])
        for nested in (
            current.__cause__,
            current.__context__,
            getattr(current, "orig", None),
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return tuple(types), tuple(numbers)
