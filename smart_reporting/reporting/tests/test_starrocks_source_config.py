from __future__ import annotations

import pytest

from smart_reporting.reporting.data_source.starrocks import parse_starrocks_source


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
