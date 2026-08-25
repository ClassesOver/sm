from __future__ import annotations

from types import SimpleNamespace

import pytest

from smart_reporting.reporting.data_source.starrocks import (
    StarRocksDataSourceAdapter,
    parse_starrocks_source,
)


def _source(**overrides: object) -> dict[str, object]:
    return {
        "id": "rj",
        "type": "starrocks",
        "name": "瑞金经营分析",
        "dsnEnv": "REPORT_STARROCKS_DSN",
        **overrides,
    }


def test_starrocks数据源从dsn解析数据库() -> None:
    source = parse_starrocks_source(
        _source(),
        {"REPORT_STARROCKS_DSN": "starrocks://root:secret@starrocks:9030/dwd"},
    )

    assert source.database == "dwd"


def test_starrocks数据源未配置数据库时要求dsn包含数据库() -> None:
    with pytest.raises(ValueError, match="DSN 必须包含数据库"):
        parse_starrocks_source(
            _source(),
            {"REPORT_STARROCKS_DSN": "starrocks://root:secret@starrocks:9030"},
        )


def test_starrocks数据源保留显式数据库一致性校验() -> None:
    with pytest.raises(ValueError, match="DSN 数据库与配置不一致"):
        parse_starrocks_source(
            _source(database="rj"),
            {"REPORT_STARROCKS_DSN": "starrocks://root:secret@starrocks:9030/dwd"},
        )


def test_starrocks_catalog保留实际表和字段注释(monkeypatch: pytest.MonkeyPatch) -> None:
    class Inspector:
        def get_columns(self, table: str, *, schema: str) -> list[dict[str, object]]:
            assert (schema, table) == ("reporting", "income")
            return [
                {
                    "name": "amount",
                    "type": "DECIMAL(18, 2)",
                    "nullable": True,
                    "comment": "实际字段注释",
                }
            ]

        def get_table_comment(self, table: str, *, schema: str) -> dict[str, str]:
            assert (schema, table) == ("reporting", "income")
            return {"text": "实际表注释"}

    monkeypatch.setattr(
        "smart_reporting.reporting.data_source.starrocks.inspect",
        lambda _engine: Inspector(),
    )
    adapter = object.__new__(StarRocksDataSourceAdapter)
    adapter.config = SimpleNamespace(id="rj")
    adapter.allowed_tables = ("reporting.income",)
    adapter._engine = object()

    catalog = adapter._catalog()

    assert catalog[0].description == "实际表注释"
    assert catalog[0].columns[0].description == "实际字段注释"
