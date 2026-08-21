from __future__ import annotations

from io import BytesIO
from typing import Any

import polars as pl

from ..models import ReportingError
from .models import MaterializedQueryResult


class CsvMaterializer:
    """把数据库结果分块编码为确定性 UTF-8 CSV。"""

    def __init__(self, columns: tuple[str, ...], *, max_bytes: int):
        if not columns or max_bytes <= 0:
            raise ValueError("CSV 物化参数无效")
        self._columns = _deduplicate_columns(columns)
        self._max_bytes = max_bytes
        self._buffer = BytesIO()
        self._row_count = 0
        self._header_written = False

    @property
    def row_count(self) -> int:
        return self._row_count

    def append(self, rows: tuple[tuple[Any, ...], ...]) -> None:
        if not rows:
            return
        normalized = tuple(tuple(_csv_value(value) for value in row) for row in rows)
        try:
            frame = pl.DataFrame(
                normalized,
                schema=self._columns,
                orient="row",
                strict=False,
            )
            frame.write_csv(
                self._buffer,
                include_header=not self._header_written,
                line_terminator="\r\n",
            )
        except (TypeError, ValueError, pl.exceptions.PolarsError) as error:
            raise ReportingError("source_query_failed", "查询结果无法物化为 CSV。") from error
        self._header_written = True
        self._row_count += frame.height
        self._validate_size()

    def finish(self) -> MaterializedQueryResult:
        if not self._header_written:
            try:
                empty = pl.DataFrame(schema={column: pl.String for column in self._columns})
                empty.write_csv(self._buffer, line_terminator="\r\n")
            except (TypeError, ValueError, pl.exceptions.PolarsError) as error:
                raise ReportingError("source_query_failed", "查询结果无法物化为 CSV。") from error
            self._header_written = True
            self._validate_size()
        return MaterializedQueryResult(
            content=self._buffer.getvalue(),
            row_count=self._row_count,
        )

    def _validate_size(self) -> None:
        if self._buffer.tell() > self._max_bytes:
            raise ReportingError("query_result_too_large", "查询结果超过允许的数据量。")


def _deduplicate_columns(columns: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for value in columns:
        name = str(value or "column")
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return tuple(result)


def _csv_value(value: Any) -> Any:
    # Python csv.writer 对数据库标量统一使用 str()，NULL 则写为空字段。先固定
    # 这一历史字节语义，再交给 Polars 的 Rust writer 批量完成转义和写出，避免
    # bool 大小写或 datetime 分隔符变化导致不可变 Dataset 的 SHA-256 漂移。
    return None if value is None else str(value)
