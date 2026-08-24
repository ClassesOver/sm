from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .data_source.starrocks import StarRocksDataSourceAdapter, StarRocksSourceConfig
from .metadata import ReportingMetadataClient
from .models import ReportingError

STARROCKS_CONNECTION_TEST_SQL = "SELECT 1 AS connection_test"
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
        return ReportingDependencyCheckResponse(
            status="ok" if starrocks.ok and metadata.ok and sandbox.ok else "failed",
            checks=checks,
        )

    async def _check_starrocks(self) -> StarRocksCheckResult:
        started_at = perf_counter()
        if not self.sources:
            return StarRocksCheckResult(
                ok=False,
                code="starrocks_not_configured",
                durationMs=_duration_ms(started_at),
            )
        results = tuple([await self._check_starrocks_source(source) for source in self.sources])
        return StarRocksCheckResult(
            ok=all(result.ok for result in results),
            code="ok" if all(result.ok for result in results) else "starrocks_connection_failed",
            durationMs=_duration_ms(started_at),
            sources=results,
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
        except Exception:
            pass
        finally:
            if adapter is not None:
                try:
                    await adapter.aclose()
                except Exception:
                    if ok:
                        ok = False
                        code = "starrocks_cleanup_failed"
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
            return DependencyCheckResult(
                ok=False,
                code=error.code,
                durationMs=_duration_ms(started_at),
                httpStatus=(
                    http_status
                    if isinstance(http_status, int) and not isinstance(http_status, bool)
                    else None
                ),
            )
        except Exception:
            return DependencyCheckResult(
                ok=False,
                code="report_metadata_check_failed",
                durationMs=_duration_ms(started_at),
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
            return DependencyCheckResult(
                ok=False,
                code="sandbox_timeout",
                durationMs=_duration_ms(started_at),
            )
        except Exception:
            return DependencyCheckResult(
                ok=False,
                code="sandbox_unavailable",
                durationMs=_duration_ms(started_at),
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
