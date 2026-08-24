from __future__ import annotations

import httpx
import pytest

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
