from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import ReportingError

CONFIG_FILE_NAME = "report-data-sources.json"


@dataclass(frozen=True)
class QueryLimits:
    statement_timeout_seconds: int
    max_rows: int
    max_bytes: int
    exact_distinct_max_rows: int
    statistics_column_batch_size: int
    top_values_max_columns: int
    top_values_limit: int
    profile_concurrency: int
    query_concurrency: int

    def public_dict(self) -> dict[str, int]:
        return {
            "statementTimeoutSeconds": self.statement_timeout_seconds,
            "maxRows": self.max_rows,
            "maxBytes": self.max_bytes,
            "exactDistinctMaxRows": self.exact_distinct_max_rows,
            "statisticsColumnBatchSize": self.statistics_column_batch_size,
            "topValuesMaxColumns": self.top_values_max_columns,
            "topValuesLimit": self.top_values_limit,
            "profileConcurrency": self.profile_concurrency,
            "queryConcurrency": self.query_concurrency,
        }


class DataSourceConfig(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def source_type(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def database(self) -> str: ...

    @property
    def tables(self) -> tuple[str, ...]: ...

    @property
    def period_columns(self) -> dict[str, str]: ...

    @property
    def limits(self) -> QueryLimits: ...

    def public_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CatalogColumn:
    name: str
    data_type: str
    nullable: bool


@dataclass(frozen=True)
class CatalogTable:
    source_id: str
    database: str
    name: str
    columns: tuple[CatalogColumn, ...]

    @property
    def qualified_name(self) -> str:
        return f"{self.database}.{self.name}"


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: Sequence[Sequence[Any]]
    byte_count: int


class DataSourceAdapter(Protocol):
    @property
    def config(self) -> DataSourceConfig: ...

    async def verify_read_only(self) -> None: ...

    async def catalog(self) -> tuple[CatalogTable, ...]: ...

    async def query(self, sql: str) -> QueryResult: ...

    async def aclose(self) -> None: ...


class ShapeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class TopValue(ShapeModel):
    value: str | int | float
    count: int = Field(ge=1)
    ratio: float = Field(ge=0, le=1)


class ColumnShape(ShapeModel):
    name: str = Field(min_length=1, max_length=128)
    data_type: str = Field(alias="dataType", min_length=1, max_length=128)
    nullable: bool
    null_count: int = Field(alias="nullCount", ge=0)
    null_rate: float = Field(alias="nullRate", ge=0, le=1)
    distinct_count: int = Field(alias="distinctCount", ge=0)
    distinct_mode: str = Field(alias="distinctMode", pattern=r"^(exact|approximate)$")
    cardinality_rate: float = Field(alias="cardinalityRate", ge=0)
    unique: bool | None
    minimum: str | int | float | None = None
    maximum: str | int | float | None = None
    zero_count: int | None = Field(default=None, alias="zeroCount", ge=0)
    negative_count: int | None = Field(default=None, alias="negativeCount", ge=0)
    average: str | int | float | None = None
    standard_deviation: str | int | float | None = Field(default=None, alias="standardDeviation")
    p25: str | int | float | None = None
    p50: str | int | float | None = None
    p75: str | int | float | None = None
    top_values: tuple[TopValue, ...] = Field(default=(), alias="topValues", max_length=100)


class TableDataShape(ShapeModel):
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    database: str = Field(min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    total_row_count: int = Field(alias="totalRowCount", ge=0)
    period_row_count: int = Field(alias="periodRowCount", ge=0)
    outside_period_row_count: int = Field(alias="outsidePeriodRowCount", ge=0)
    period_null_count: int = Field(alias="periodNullCount", ge=0)
    first_effective_date: str | None = Field(default=None, alias="firstEffectiveDate")
    last_effective_date: str | None = Field(default=None, alias="lastEffectiveDate")
    column_count: int = Field(alias="columnCount", ge=1)
    month_coverage: tuple[str, ...] = Field(default=(), alias="monthCoverage", max_length=1200)
    missing_months: tuple[str, ...] = Field(default=(), alias="missingMonths", max_length=1200)
    columns: tuple[ColumnShape, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_column_count(self) -> TableDataShape:
        if self.column_count != len(self.columns):
            raise ValueError("columnCount 与 columns 不一致")
        if (
            self.period_row_count + self.outside_period_row_count + self.period_null_count
            != self.total_row_count
        ):
            raise ValueError("全表行数与期间分布不一致")
        if self.period_row_count == 0 and (
            self.first_effective_date is not None
            or self.last_effective_date is not None
            or self.month_coverage
        ):
            raise ValueError("空期间不得包含日期覆盖")
        if self.period_row_count > 0 and (
            self.first_effective_date is None or self.last_effective_date is None
        ):
            raise ValueError("期间首末有效日期缺失")
        return self


class DataShape(ShapeModel):
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    metadata_revision: str = Field(alias="metadataRevision", min_length=1, max_length=128)
    schema_hash: str = Field(alias="schemaHash", pattern=r"^[0-9a-f]{64}$")
    statistics_version: str = Field(alias="statisticsVersion", pattern=r"^1$")
    query_count: int = Field(alias="queryCount", ge=1)
    period_start: str = Field(alias="periodStart", pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_end: str = Field(alias="periodEnd", pattern=r"^\d{4}-\d{2}-\d{2}$")
    tables: tuple[TableDataShape, ...] = Field(min_length=1, max_length=200)


@dataclass(frozen=True)
class ReportSourceRegistryConfig:
    default_source_ids: tuple[str, ...]
    sources: dict[str, DataSourceConfig]
    config_paths: tuple[Path, ...]

    def require_defaults(self) -> tuple[str, ...]:
        if not self.default_source_ids:
            raise ReportingError("report_default_source_missing", "服务端未配置默认报表数据源。")
        return self.default_source_ids
