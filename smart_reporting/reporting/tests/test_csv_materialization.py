from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from io import StringIO

import pytest

from smart_reporting.reporting.data_source.materialization import CsvMaterializer
from smart_reporting.reporting.models import ReportingError


def _rows(content: bytes) -> list[list[str]]:
    return list(csv.reader(StringIO(content.decode("utf-8"), newline="")))


def test_polars_csv分块物化保持业务值和稳定列名() -> None:
    materializer = CsvMaterializer(
        ("value", "value", "day", "at", "nullable", "text", "department"),
        max_bytes=10_000,
    )
    materializer.append(
        (
            (
                1,
                Decimal("1.2300"),
                date(2025, 1, 2),
                datetime(2025, 1, 2, 3, 4, 5),
                None,
                'a,"b"',
                "内科",
            ),
        )
    )
    materializer.append(
        (
            (
                2,
                Decimal("2.5000"),
                date(2025, 2, 3),
                datetime(2025, 2, 3, 4, 5, 6),
                True,
                "x\ny",
                "外科",
            ),
        )
    )

    result = materializer.finish()

    assert result.row_count == 2
    assert result.size == len(result.content)
    assert result.content.endswith(b"\r\n")
    assert _rows(result.content) == [
        ["value", "value_2", "day", "at", "nullable", "text", "department"],
        ["1", "1.2300", "2025-01-02", "2025-01-02 03:04:05", "", 'a,"b"', "内科"],
        ["2", "2.5000", "2025-02-03", "2025-02-03 04:05:06", "True", "x\ny", "外科"],
    ]


def test_polars_csv相同分块输入产生完全一致字节() -> None:
    def materialize() -> bytes:
        materializer = CsvMaterializer(("period", "amount"), max_bytes=10_000)
        materializer.append((("2025-01", 10.5), ("2025-02", 20.0)))
        return materializer.finish().content

    assert materialize() == materialize()


def test_polars_csv与历史csv_writer保持完全相同字节() -> None:
    columns = ("amount", "day", "at", "enabled", "nullable", "text")
    rows = (
        (
            Decimal("1.2300"),
            date(2025, 1, 2),
            datetime(2025, 1, 2, 3, 4, 5),
            True,
            None,
            '中文,"换行"\n第二行',
        ),
    )
    expected = StringIO(newline="")
    writer = csv.writer(expected)
    writer.writerow(columns)
    writer.writerows(rows)
    materializer = CsvMaterializer(columns, max_bytes=10_000)
    materializer.append(rows)

    assert materializer.finish().content == expected.getvalue().encode("utf-8")


def test_polars_csv空结果仍写入表头() -> None:
    result = CsvMaterializer(("period", "amount"), max_bytes=100).finish()

    assert result.row_count == 0
    assert result.content == b"period,amount\r\n"


def test_polars_csv非常规数据库值保持原字符串语义() -> None:
    materializer = CsvMaterializer(("items", "metadata", "binary"), max_bytes=1_000)
    materializer.append((([1, 2], {"a": 1}, b"abc"),))

    assert _rows(materializer.finish().content) == [
        ["items", "metadata", "binary"],
        ["[1, 2]", "{'a': 1}", "b'abc'"],
    ]


def test_polars_csv超过精确字节上限时失败关闭() -> None:
    materializer = CsvMaterializer(("value",), max_bytes=8)

    with pytest.raises(ReportingError) as captured:
        materializer.append((("123456789",),))

    assert captured.value.code == "query_result_too_large"
