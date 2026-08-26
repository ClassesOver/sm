from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
from smart_reporting.reporting.models import ReportingError


class _FakeResult:
    def __init__(self, rows: tuple[tuple[Any, ...], ...]):
        self._rows = list(rows)
        self.fetch_sizes: list[int] = []

    def keys(self) -> tuple[str, ...]:
        return ("value",)

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        self.fetch_sizes.append(size)
        chunk = self._rows[:size]
        del self._rows[:size]
        return chunk


class _FakeConnection:
    def __init__(self, result: _FakeResult):
        self.result = result
        self.statements: list[str] = []

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execution_options(self, **_kwargs: object) -> _FakeConnection:
        return self

    def execute(self, statement: object) -> _FakeResult | None:
        sql = str(statement)
        self.statements.append(sql)
        return None if sql.startswith("SET query_timeout") else self.result


class _FakeEngine:
    def __init__(self, result: _FakeResult):
        self.connection = _FakeConnection(result)

    def connect(self) -> _FakeConnection:
        return self.connection


def _adapter(
    rows: tuple[tuple[Any, ...], ...],
    *,
    max_rows: int = 1_000_000,
    max_bytes: int = 256 * 1024 * 1024,
) -> tuple[StarRocksDataSourceAdapter, _FakeResult]:
    result = _FakeResult(rows)
    adapter = object.__new__(StarRocksDataSourceAdapter)
    adapter.config = SimpleNamespace(
        statement_timeout_seconds=30,
        max_rows=max_rows,
        max_bytes=max_bytes,
    )
    adapter._engine = _FakeEngine(result)
    return adapter, result


def test_starrocks物化按固定批次增量写入csv() -> None:
    adapter, source = _adapter(tuple((index,) for index in range(15_001)))

    result = adapter._materialize("SELECT value FROM db.table")

    assert result.row_count == 15_001
    assert source.fetch_sizes == [10_000, 10_000, 10_000]
    assert result.content.startswith(b"value\r\n0\r\n1\r\n")
    assert result.content.endswith(b"15000\r\n")


def test_starrocks物化超过行数上限时在超额批次写入前拒绝() -> None:
    adapter, source = _adapter(((1,), (2,), (3,)), max_rows=2)

    with pytest.raises(ReportingError) as captured:
        adapter._materialize("SELECT value FROM db.table")

    assert captured.value.code == "query_result_too_large"
    assert source.fetch_sizes == [3]


def test_starrocks物化按实际csv字节执行上限() -> None:
    adapter, _source = _adapter((("123456789",),), max_bytes=8)

    with pytest.raises(ReportingError) as captured:
        adapter._materialize("SELECT value FROM db.table")

    assert captured.value.code == "query_result_too_large"


def test_starrocks物化使用配置和调用方中的较小字节上限() -> None:
    adapter, _source = _adapter((("123456789",),), max_bytes=1_000)

    with pytest.raises(ReportingError) as captured:
        adapter._materialize("SELECT value FROM db.table", max_bytes=8)

    assert captured.value.code == "query_result_too_large"


def test_starrocks查询增量计算json字节数() -> None:
    rows = (("中文",), (2,))
    adapter, _source = _adapter(rows)

    result = adapter._query("SELECT value FROM db.table")

    assert result.rows == rows
    assert result.byte_count == len(
        json.dumps(rows, ensure_ascii=False, default=str, separators=(",", ":")).encode()
    )


def test_starrocks空查询结果也执行字节上限() -> None:
    adapter, _source = _adapter((), max_bytes=1)

    with pytest.raises(ReportingError) as captured:
        adapter._query("SELECT value FROM db.table")

    assert captured.value.code == "query_result_too_large"


def test_starrocks查询超过字节上限时不再读取后续批次() -> None:
    adapter, source = _adapter(
        (("oversized",),) + tuple((index,) for index in range(10_000)),
        max_bytes=4,
    )

    with pytest.raises(ReportingError) as captured:
        adapter._query("SELECT value FROM db.table")

    assert captured.value.code == "query_result_too_large"
    assert source.fetch_sizes == [10_000]
