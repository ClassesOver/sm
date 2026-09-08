from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from loguru import logger

from smart_reporting.reporting import metadata as metadata_module
from smart_reporting.reporting.contract import (
    ModelColumn,
    ModelTable,
    parse_ddl,
    validate_catalog,
)
from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable
from smart_reporting.reporting.data_source.profiling import _catalog_scope
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
async def test_metadata_client_stops_streaming_when_response_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metadata_module, "MAX_METADATA_RESPONSE_BYTES", 4)

    class CountingStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.yielded = 0

        async def __aiter__(self):
            for chunk in (b"123", b"45", b"unread"):
                self.yielded += len(chunk)
                yield chunk

    stream = CountingStream()

    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    client = httpx.AsyncClient(
        base_url="https://metadata.internal",
        transport=httpx.MockTransport(respond),
    )
    metadata = ReportingMetadataClient(
        "https://metadata.internal",
        client_factory=lambda: client,
    )

    with pytest.raises(ReportingError) as captured:
        await metadata.query_agent()

    await client.aclose()
    assert captured.value.code == "report_metadata_response_too_large"
    assert stream.yielded == 5


@pytest.mark.anyio
async def test_metadata_client_logs_safe_http_and_multiple_ddl_diagnostics() -> None:
    private_ddl = (
        "CREATE TABLE dwd.private_first (id BIGINT); "
        "CREATE VIEW dwd.private_second AS SELECT id FROM dwd.private_first"
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
    debug_records: list[str] = []
    info_records: list[str] = []
    debug_sink_id = logger.add(debug_records.append, level="DEBUG", format="{message}")
    info_sink_id = logger.add(info_records.append, level="INFO", format="{message}")

    try:
        with pytest.raises(ReportingError, match="report_ddl_invalid"):
            await metadata.query_model(
                agent_id="1",
                sources=(SimpleNamespace(id="rj", database="dwd"),),
            )
    finally:
        logger.remove(debug_sink_id)
        logger.remove(info_sink_id)

    await client.aclose()
    log_text = "".join(debug_records)
    info_text = "".join(info_records)
    assert "report_metadata_http_completed" in log_text
    assert "report_metadata_http_completed" not in info_text
    assert "target=metadata.internal:18083" in log_text
    assert "report_metadata_ddl_rejected" in log_text
    assert "model_id=7" in log_text
    assert "statement_count=2" in log_text
    assert "statement_types=Create,Create" in log_text
    assert "report_metadata_ddl_rejected" in info_text
    assert private_ddl not in log_text
    assert "private-model-name" not in log_text
    assert "metadata-user" not in log_text
    assert "metadata-password" not in log_text
    assert "private-metadata-token" not in log_text


def test_ddl_comments_support_inline_and_separate_forms_without_semantic_drift() -> None:
    inline = """
    CREATE TABLE reporting.income (
        data_date DATE COMMENT '数据日期' NOT NULL,
        amount DECIMAL(18, 2) COMMENT '收入金额' NULL
    ) COMMENT='收入表';
    """
    separate = """
    CREATE TABLE reporting.income (
        data_date DATE NOT NULL,
        amount DECIMAL(18, 2) NULL
    );
    COMMENT ON TABLE reporting.income IS '收入表';
    COMMENT ON COLUMN reporting.income.data_date IS '数据日期';
    COMMENT ON COLUMN reporting.income.amount IS '收入金额';
    """

    inline_tables = parse_ddl(inline, source_id="rj", default_database="reporting")
    separate_tables = parse_ddl(separate, source_id="rj", default_database="reporting")

    assert separate_tables == inline_tables


@pytest.mark.anyio
async def test_metadata_client_accepts_separate_ddl_comments() -> None:
    ddl = """
    CREATE TABLE reporting.income (
        data_date DATE NOT NULL,
        amount DECIMAL(18, 2) NULL
    );
    COMMENT ON TABLE reporting.income IS '收入表';
    COMMENT ON COLUMN reporting.income.data_date IS '数据日期';
    COMMENT ON COLUMN reporting.income.amount IS '收入金额';
    """

    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ddl": [
                    {
                        "id": 1,
                        "modelName": "收入分析",
                        "modelDesc": "收入表",
                        "ddl": ddl,
                    }
                ],
                "term": [],
                "measureSemantics": [],
            },
            request=request,
        )

    client = httpx.AsyncClient(
        base_url="https://metadata.internal",
        transport=httpx.MockTransport(respond),
    )
    metadata = ReportingMetadataClient(
        "https://metadata.internal",
        client_factory=lambda: client,
    )

    result = await metadata.query_model(
        agent_id="1",
        sources=(SimpleNamespace(id="rj", database="reporting"),),
    )

    await client.aclose()
    assert result.tables[0].description == "收入表"
    assert [column.description for column in result.tables[0].columns] == [
        "数据日期",
        "收入金额",
    ]


@pytest.mark.parametrize(
    "suffix",
    [
        "COMMENT ON COLUMN reporting.income.unknown IS '未知字段';",
        "COMMENT ON TABLE reporting.other IS '其他表';",
        "ALTER TABLE reporting.income ADD COLUMN secret VARCHAR(10);",
        "COMMENT ON COLUMN reporting.income.amount IS '冲突注释';",
    ],
)
def test_ddl_separate_comments_fail_closed_for_invalid_or_conflicting_targets(
    suffix: str,
) -> None:
    ddl = (
        """
    CREATE TABLE reporting.income (
        amount DECIMAL(18, 2) COMMENT '收入金额' NULL
    ) COMMENT='收入表';
    """
        + suffix
    )

    with pytest.raises(ReportingError, match="report_ddl_invalid"):
        parse_ddl(ddl, source_id="rj", default_database="reporting")


def test_catalog_descriptions_override_metadata_candidates() -> None:
    requested = (
        ModelTable(
            sourceId="rj",
            database="reporting",
            name="income",
            description="接口表注释",
            columns=(
                ModelColumn(
                    name="amount",
                    dataType="DECIMAL",
                    nullable=False,
                    description="接口字段注释",
                ),
            ),
        ),
    )
    catalog = (
        ModelTable(
            sourceId="rj",
            database="reporting",
            name="income",
            description="实际表注释",
            columns=(
                ModelColumn(
                    name="amount",
                    dataType="DECIMAL(18, 2)",
                    nullable=True,
                    description="实际字段注释",
                ),
            ),
        ),
    )

    resolved = validate_catalog(
        requested,
        catalog,
        allowed_tables=("reporting.income",),
    )

    assert resolved[0].description == "实际表注释"
    assert resolved[0].columns[0].description == "实际字段注释"
    assert resolved[0].columns[0].data_type == "DECIMAL(18, 2)"
    assert resolved[0].columns[0].nullable is True


def test_empty_catalog_descriptions_preserve_metadata_candidates() -> None:
    requested = (
        ModelTable(
            sourceId="rj",
            database="reporting",
            name="income",
            description="接口表注释",
            columns=(
                ModelColumn(
                    name="amount",
                    dataType="DECIMAL",
                    nullable=False,
                    description="接口字段注释",
                ),
            ),
        ),
    )
    catalog = (
        ModelTable(
            sourceId="rj",
            database="reporting",
            name="income",
            columns=(
                ModelColumn(
                    name="amount",
                    dataType="DECIMAL(18, 2)",
                    nullable=True,
                ),
            ),
        ),
    )

    resolved = validate_catalog(
        requested,
        catalog,
        allowed_tables=("reporting.income",),
    )

    assert resolved[0].description == "接口表注释"
    assert resolved[0].columns[0].description == "接口字段注释"


@pytest.mark.parametrize(
    ("table_description", "column_description"),
    [("已变更表注释", "实际字段注释"), ("实际表注释", "已变更字段注释")],
)
def test_catalog_comment_drift_fails_closed_during_profile(
    table_description: str,
    column_description: str,
) -> None:
    expected = (
        CatalogTable(
            source_id="rj",
            database="reporting",
            name="income",
            description="实际表注释",
            columns=(
                CatalogColumn(
                    name="amount",
                    data_type="DECIMAL(18, 2)",
                    nullable=True,
                    description="实际字段注释",
                ),
            ),
        ),
    )
    current = (
        CatalogTable(
            source_id="rj",
            database="reporting",
            name="income",
            description=table_description,
            columns=(
                CatalogColumn(
                    name="amount",
                    data_type="DECIMAL(18, 2)",
                    nullable=True,
                    description=column_description,
                ),
            ),
        ),
    )
    adapter = SimpleNamespace(
        config=SimpleNamespace(id="rj", database="reporting"),
        allowed_tables=("reporting.income",),
    )

    with pytest.raises(ReportingError, match="report_catalog_drift"):
        _catalog_scope(adapter, current, expected)
