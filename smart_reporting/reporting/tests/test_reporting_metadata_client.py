from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from loguru import logger

from smart_reporting.reporting.metadata import ReportingMetadataClient
from smart_reporting.reporting.models import ReportingError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "report_metadata_auth_failed"),
        (404, "report_metadata_rejected"),
        (500, "report_metadata_unavailable"),
    ],
)
async def test_metadata_client_preserves_only_safe_upstream_status(
    status_code: int, expected_code: str
) -> None:
    async def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"detail": "secret-upstream-response"},
            request=request,
        )

    client = httpx.AsyncClient(
        base_url="https://metadata.internal",
        transport=httpx.MockTransport(reject),
    )
    metadata = ReportingMetadataClient(
        "https://metadata.internal",
        token="secret-metadata-token",
        client_factory=lambda: client,
    )

    with pytest.raises(ReportingError) as captured:
        await metadata.query_agent()

    await client.aclose()
    assert captured.value.code == expected_code
    assert captured.value.details == {"httpStatus": status_code}
    assert "secret-upstream-response" not in str(captured.value)
    assert "secret-metadata-token" not in str(captured.value)


@pytest.mark.anyio
async def test_metadata_client_logs_safe_http_and_multiple_ddl_diagnostics() -> None:
    private_ddl = (
        "CREATE TABLE dwd.private_first (id BIGINT); CREATE TABLE dwd.private_second (id BIGINT)"
    )

    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ddl": [
                    {
                        "id": 7,
                        "modelName": "private-model-name",
                        "modelDesc": "",
                        "ddl": private_ddl,
                    }
                ],
                "term": [],
                "measureSemantics": [],
            },
            request=request,
        )

    client = httpx.AsyncClient(
        base_url="http://metadata-user:metadata-password@metadata.internal:18083",
        transport=httpx.MockTransport(respond),
    )
    metadata = ReportingMetadataClient(
        "http://metadata-user:metadata-password@metadata.internal:18083",
        token="private-metadata-token",
        client_factory=lambda: client,
    )
    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{message}")

    try:
        with pytest.raises(ReportingError, match="report_ddl_invalid"):
            await metadata.query_model(
                agent_id="1",
                sources=(SimpleNamespace(id="rj", database="dwd"),),
            )
    finally:
        logger.remove(sink_id)

    await client.aclose()
    log_text = "".join(records)
    assert "report_metadata_http_completed" in log_text
    assert "target=metadata.internal:18083" in log_text
    assert "report_metadata_ddl_rejected" in log_text
    assert "model_id=7" in log_text
    assert "statement_count=2" in log_text
    assert "statement_types=Create,Create" in log_text
    assert private_ddl not in log_text
    assert "private-model-name" not in log_text
    assert "metadata-user" not in log_text
    assert "metadata-password" not in log_text
    assert "private-metadata-token" not in log_text
