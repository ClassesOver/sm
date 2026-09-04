import hashlib
import json

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting_mcp.adapter import ReportingMcpAdapter
from smart_reporting.reporting_mcp.contracts import ReportingStartInput
from smart_reporting.reporting_mcp.identity import McpRequestIdentity


def _request() -> ReportingStartInput:
    return ReportingStartInput.model_validate(
        {
            "clientRequestId": "request-1",
            "threadId": "thread-1",
            "reportRequest": {
                "reportGoal": "分析月度运营",
                "period": {"start": "2026-01-01", "end": "2026-01-31"},
            },
            "attachments": [{"url": "https://example.com/input.csv"}],
        }
    )


def _identity() -> McpRequestIdentity:
    return McpRequestIdentity(
        database="odoo",
        user_id="7",
        company_id="11",
        thread_id="thread-1",
    )


@pytest.mark.anyio
async def test_adapter_returns_operation_id_and_passes_tenant_scope() -> None:
    calls = []

    class Controller:
        async def start_external_background(self, _payload, **kwargs):
            prepare = kwargs.pop("prepare")
            prepared = await prepare()
            assert prepared.file_inputs[0]["filename"] == "input.csv"
            calls.append(kwargs)
            return {"ok": True, "status": "running"}

    class Materializer:
        async def materialize_all(self, **_kwargs):
            return (
                {
                    "path": "reporting-inputs/op/input.csv",
                    "filename": "input.csv",
                    "size": 8,
                    "sha256": "a" * 64,
                    "mediaType": "text/csv",
                },
            )

    adapter = ReportingMcpAdapter(Controller(), object())  # type: ignore[arg-type]
    adapter.materializer = Materializer()  # type: ignore[assignment]

    result = await adapter.start(_request(), identity=_identity())

    expected_scope = hashlib.sha256(
        json.dumps(
            ["odoo", "11", "7", "thread-1"],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert result["operationId"].startswith(expected_scope)
    assert len(result["operationId"]) == 128
    assert result["status"] == "running"
    assert calls[0]["database"] == "odoo"
    assert calls[0]["company_id"] == "11"
    assert "thread_preclaimed" not in calls[0]


@pytest.mark.anyio
async def test_adapter_rejects_idempotency_conflict_before_download() -> None:
    class Controller:
        async def start_external_background(self, _payload, **_kwargs):
            raise ReportingError(
                "report_mcp_idempotency_conflict",
                "同一 clientRequestId 不得提交不同的报表请求。",
            )

    class Materializer:
        async def materialize_all(self, **_kwargs):
            raise AssertionError("幂等冲突不得访问附件 URL")

        async def cleanup_operation(self, *_args):
            raise AssertionError("幂等冲突不得删除既有请求的附件")

    adapter = ReportingMcpAdapter(Controller(), object())  # type: ignore[arg-type]
    adapter.materializer = Materializer()  # type: ignore[assignment]

    with pytest.raises(ReportingError) as error:
        await adapter.start(_request(), identity=_identity())

    assert error.value.code == "report_mcp_idempotency_conflict"


@pytest.mark.anyio
async def test_adapter_cleans_url_inputs_after_cancel() -> None:
    class Controller:
        async def cancel_external(self, **_kwargs):
            return {"ok": True, "status": "cancelled"}

    class Materializer:
        def __init__(self) -> None:
            self.cleanup_calls: list[tuple[str, str]] = []

        async def cleanup_operation(self, thread_id: str, operation_id: str) -> None:
            self.cleanup_calls.append((thread_id, operation_id))

    materializer = Materializer()
    adapter = ReportingMcpAdapter(Controller(), object())  # type: ignore[arg-type]
    adapter.materializer = materializer  # type: ignore[assignment]

    result = await adapter.cancel(
        operation_id="operation-1",
        thread_id="thread-1",
        identity=_identity(),
    )

    assert result == {"ok": True, "status": "cancelled", "operationId": "operation-1"}
    assert materializer.cleanup_calls == [("thread-1", "operation-1")]


@pytest.mark.anyio
async def test_adapter_cleans_inputs_when_background_start_fails() -> None:
    calls: list[str] = []

    class Controller:
        async def start_external_background(self, _payload, **kwargs):
            await kwargs["prepare"]()
            raise RuntimeError("queue failed")

    class Materializer:
        async def materialize_all(self, **_kwargs):
            return (
                {
                    "path": "reporting-inputs/op/input.csv",
                    "filename": "input.csv",
                    "size": 8,
                    "sha256": "a" * 64,
                    "mediaType": "text/csv",
                },
            )

        async def cleanup_operation(self, _thread_id: str, _operation_id: str) -> None:
            calls.append("cleanup")

    adapter = ReportingMcpAdapter(Controller(), object())  # type: ignore[arg-type]
    adapter.materializer = Materializer()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="queue failed"):
        await adapter.start(_request(), identity=_identity())

    assert calls == ["cleanup"]
