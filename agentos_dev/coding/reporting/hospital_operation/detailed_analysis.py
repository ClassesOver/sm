"""基于不可变 CSV 的详细分析计划。

本模块只做受信数据快照的确定性画像，不生成业务 Fact 或覆盖账本。模型可在
此结果上组织分析，但所有 dataset、字段和期间均来自本轮已批准的输入。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Literal

import pandas as pd
from data_profiling import ProfileReport
from pydantic import BaseModel, ConfigDict, Field, model_validator
from statsmodels.tsa.stattools import acf, adfuller, pacf

MAX_PROFILE_MODEL_VIEW_BYTES = 12 * 1024
MAX_PROFILE_HIGHLIGHTS = 10
MAX_PROFILE_VARIABLE_INDEX = 40


class AnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class FieldStatistic(AnalysisModel):
    name: str = Field(min_length=1, max_length=128)
    inferred_type: Literal["numeric", "temporal", "categorical", "empty"] = Field(
        alias="inferredType"
    )
    non_null_count: int = Field(alias="nonNullCount", ge=0)
    missing_count: int = Field(alias="missingCount", ge=0)
    missing_rate: float = Field(alias="missingRate", ge=0, le=1)
    distinct_count: int = Field(alias="distinctCount", ge=0)
    cardinality_rate: float = Field(alias="cardinalityRate", ge=0, le=1)
    unique: bool
    sample_values: tuple[str, ...] = Field(alias="sampleValues", default=(), max_length=20)
    top_values: tuple["ValueFrequency", ...] = Field(
        alias="topValues", default=(), max_length=20
    )
    minimum: float | None = None
    maximum: float | None = None
    average: float | None = None
    standard_deviation: float | None = Field(default=None, alias="standardDeviation")
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    zero_count: int = Field(default=0, alias="zeroCount", ge=0)
    negative_count: int = Field(default=0, alias="negativeCount", ge=0)
    numeric_parse_failure_count: int = Field(
        default=0, alias="numericParseFailureCount", ge=0
    )


class ValueFrequency(AnalysisModel):
    value: str = Field(max_length=2_000)
    count: int = Field(ge=1)
    ratio: float = Field(ge=0, le=1)


class AnalysisFileIdentity(AnalysisModel):
    path: str = Field(min_length=1, max_length=1024)
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DatasetAnalysisContext(AnalysisModel):
    profile_version: Literal["1"] = Field(default="1", alias="profileVersion")
    profile_engine: Literal["fg-data-profiling"] = Field(
        default="fg-data-profiling", alias="profileEngine"
    )
    profile_engine_version: str = Field(alias="profileEngineVersion", min_length=1)
    profile_file: AnalysisFileIdentity = Field(alias="profileFile")
    profile_model_view: dict[str, Any] = Field(alias="profileModelView")
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    path: str = Field(min_length=1, max_length=1024)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(alias="rowCount", ge=0)
    column_count: int = Field(default=0, alias="columnCount", ge=0)
    missing_cell_count: int = Field(default=0, alias="missingCellCount", ge=0)
    missing_cell_rate: float = Field(default=0.0, alias="missingCellRate", ge=0, le=1)
    duplicate_row_count: int = Field(default=0, alias="duplicateRowCount", ge=0)
    duplicate_row_rate: float = Field(default=0.0, alias="duplicateRowRate", ge=0, le=1)
    empty_row_count: int = Field(default=0, alias="emptyRowCount", ge=0)
    fields: tuple[str, ...] = Field(max_length=500)
    schema_snapshot: dict[str, Any] = Field(alias="schema", default_factory=dict)
    period_coverage: tuple[str, ...] = Field(alias="periodCoverage", default=(), max_length=1200)
    organization_grain: tuple[str, ...] = Field(alias="organizationGrain", default=(), max_length=30)
    metric_semantics: tuple[dict[str, Any], ...] = Field(
        alias="metricSemantics", default=(), max_length=200
    )
    field_stats: tuple[FieldStatistic, ...] = Field(alias="fieldStats", default=(), max_length=500)
    numeric_fields: tuple[str, ...] = Field(alias="numericFields", max_length=500)
    period_values: tuple[str, ...] = Field(alias="periodValues", max_length=1200)
    source_warnings: tuple[str, ...] = Field(alias="sourceWarnings", default=(), max_length=100)
    quality_warnings: tuple[str, ...] = Field(
        alias="qualityWarnings", default=(), max_length=100
    )
    time_series_sort_field: str | None = Field(default=None, alias="timeSeriesSortField")
    time_series_fields: tuple[str, ...] = Field(
        default=(), alias="timeSeriesFields", max_length=100
    )


class DetailedAnalysisItem(AnalysisModel):
    analysis_id: str = Field(alias="analysisId", pattern=r"^analysis_[0-9]{3,6}$")
    domain: str = Field(min_length=1, max_length=64)
    management_question: str = Field(alias="managementQuestion", min_length=1, max_length=2_000)
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=100)
    fields: tuple[str, ...] = Field(max_length=100)
    metrics: tuple[str, ...] = Field(max_length=100)
    periods: tuple[str, ...] = Field(max_length=1200)
    comparison_basis: tuple[str, ...] = Field(alias="comparisonBasis", default=(), max_length=10)
    organization_grain: tuple[str, ...] = Field(alias="organizationGrain", default=(), max_length=30)
    actions: tuple[str, ...] = Field(min_length=1, max_length=30)
    evidence_summary: str = Field(alias="evidenceSummary", min_length=1, max_length=4_000)
    limitations: tuple[str, ...] = Field(default=(), max_length=100)
    recommended_tables: tuple[str, ...] = Field(alias="recommendedTables", default=(), max_length=30)
    recommended_charts: tuple[str, ...] = Field(alias="recommendedCharts", default=(), max_length=30)
    suggested_section: str = Field(alias="suggestedSection", min_length=1, max_length=128)
    completion_conditions: tuple[str, ...] = Field(alias="completionConditions", min_length=1, max_length=30)

    @model_validator(mode="after")
    def validate_ids(self) -> DetailedAnalysisItem:
        if len(self.dataset_ids) != len(set(self.dataset_ids)):
            raise ValueError("analysis datasetIds 不能重复")
        return self


class DetailedAnalysisPlan(AnalysisModel):
    version: Literal["1"] = "1"
    analyses: tuple[DetailedAnalysisItem, ...] = Field(min_length=1, max_length=200)
    dataset_ids: tuple[str, ...] = Field(
        alias="datasetIds", min_length=1, max_length=100
    )
    report_goal: str = Field(alias="reportGoal", default="", max_length=4000)
    analysis_goal: str = Field(alias="analysisGoal", default="", max_length=4000)
    warnings: tuple[str, ...] = Field(default=(), max_length=500)

    @model_validator(mode="after")
    def validate_dataset_refs(self) -> DetailedAnalysisPlan:
        known = set(self.dataset_ids)
        if len(known) != len(self.dataset_ids):
            raise ValueError("datasetIds 不能重复")
        if any(set(item.dataset_ids) - known for item in self.analyses):
            raise ValueError("分析计划引用了未授权数据集")
        ids = [item.analysis_id for item in self.analyses]
        if len(ids) != len(set(ids)):
            raise ValueError("analysisId 不能重复")
        return self


@dataclass(frozen=True)
class ProfiledDataset:
    """完整 Profile 只在写入受信文件前短暂存在于服务端内存。"""

    context: DatasetAnalysisContext
    profile: dict[str, Any]
    profile_content: bytes

    def model_dump(self, *, mode: str = "python", by_alias: bool = False) -> dict[str, Any]:
        """提供与 Pydantic 上下文一致的轻量导出，避免把完整 Profile 混入状态。"""
        return self.context.model_dump(mode=mode, by_alias=by_alias)


def profile_csv_dataset(
    content: bytes,
    *,
    dataset_id: str,
    path: str,
    expected_sha256: str,
    profile_path: str | None = None,
    period_fields: tuple[str, ...] = (),
    schema: dict[str, Any] | None = None,
    organization_grain: tuple[str, ...] = (),
    metric_semantics: tuple[dict[str, Any], ...] = (),
    source_warnings: tuple[str, ...] = (),
) -> ProfiledDataset:
    """校验快照身份，并使用 fg-data-profiling 生成完整 JSON 画像。"""
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValueError("CSV 快照哈希变化")
    try:
        dataframe = pd.read_csv(BytesIO(content))
    except (UnicodeDecodeError, pd.errors.EmptyDataError, pd.errors.ParserError) as error:
        raise ValueError("CSV 解析失败") from error
    profile_dataframe, time_series_sort_field, parsed_time_index = _prepare_profile_dataframe(
        dataframe, period_fields=period_fields
    )
    duplicate_time_index = bool(
        parsed_time_index is not None and parsed_time_index.duplicated().any()
    )

    # Profile 只输出统计 JSON。关闭图形型缺失分析和连续变量散点图，避免把
    # 第三方 SVG 混入受信上下文；文件类变量也必须关闭，防止 CSV 文本触发
    # 工作区路径、图片或 URL 读取。直方图 bins、相关矩阵及文本统计仍完整保留。
    try:
        # fg-data-profiling 为生成直方图统计会短暂调用 matplotlib.savefig；其内置
        # 绘图上下文固定使用 DejaVu Sans，中文分类值会产生无害的 Glyph warning。
        # 这里仅过滤该已知提示，不吞掉 Profile 计算、解析或其他数据质量异常。
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Glyph .* missing from font.*",
                category=UserWarning,
            )
            warnings.filterwarnings(
                "ignore",
                message=r"divide by zero encountered in log10",
                category=RuntimeWarning,
            )
            warnings.filterwarnings(
                "ignore",
                message=r"Discarding nonzero nanoseconds in conversion.*",
                category=UserWarning,
            )
            report = ProfileReport(
                profile_dataframe,
                # 同一期间存在多行时属于面板数据。原始行顺序不代表业务时间序列，
                # 因此关闭上游 tsmode；Coding 必须从不可变 CSV 按月和适当组织粒度
                # 聚合后再执行趋势、ACF、PACF 或季节性分析。
                tsmode=time_series_sort_field is not None and not duplicate_time_index,
                sortby=time_series_sort_field if not duplicate_time_index else None,
                # 本工作流只消费完整 JSON description_set。保持 lazy=True 让
                # to_json() 计算全部统计，但不提前构建 HTML/Widget report，避免
                # 展示层直方图、分类频率图和时序概览无意义地调用 matplotlib。
                lazy=True,
                progress_bar=False,
                correlations={
                    "auto": {"calculate": True},
                    "pearson": {"calculate": True},
                    "spearman": {"calculate": True},
                    "kendall": {"calculate": True},
                    "phi_k": {"calculate": True},
                    "cramers": {"calculate": True},
                },
                missing_diagrams={"bar": False, "matrix": False, "heatmap": False},
                interactions={"continuous": False},
                vars={
                    "file": {"active": False},
                    "image": {"active": False},
                    "path": {"active": False},
                    "url": {"active": False},
                },
            )
            # 上游 JSON 会把缺失的样本值编码为非标准 NaN。受信上下文必须能够
            # 严格 JSON 往返并稳定比较，因此仅把这些非有限占位规范为 null。
            profile = json.loads(report.to_json(), parse_constant=lambda _value: None)
    except Exception as error:
        raise ValueError("CSV Profile 生成失败") from error
    if not isinstance(profile, dict):
        raise ValueError("CSV Profile 结构无效")
    time_series_fields = _append_time_series_statistics(
        profile,
        profile_dataframe,
        parsed_time_index,
        time_series_sort_field,
    )

    table = profile.get("table")
    variables = profile.get("variables")
    package = profile.get("package")
    if not isinstance(table, Mapping) or not isinstance(variables, Mapping):
        raise ValueError("CSV Profile 结构无效")
    fields = tuple(str(field) for field in dataframe.columns)
    row_count = int(table.get("n", len(dataframe)))
    numeric: list[str] = []
    field_stats: list[FieldStatistic] = []
    periods: set[str] = set()
    trusted_period_fields = {field.casefold() for field in period_fields}
    for field in fields:
        variable = variables.get(field)
        if not isinstance(variable, Mapping):
            raise ValueError(f"CSV Profile 缺少字段画像: {field}")
        variable_type = str(variable.get("type", ""))
        non_null_count = int(variable.get("count", 0))
        missing_count = int(variable.get("n_missing", 0))
        is_numeric = variable_type in {"Numeric", "TimeSeries"}
        is_temporal = variable_type == "DateTime"
        inferred_type: Literal["numeric", "temporal", "categorical", "empty"] = (
            "empty"
            if not non_null_count
            else "numeric"
            if is_numeric
            else "temporal"
            if is_temporal
            else "categorical"
        )
        distinct_count = int(variable.get("n_distinct", 0))
        value_counts = variable.get("value_counts_without_nan", {})
        if not isinstance(value_counts, Mapping):
            value_counts = {}
        sample_values = tuple(
            str(value)
            for value in dataframe[field].dropna().astype(str).drop_duplicates().head(20)
        )
        field_stats.append(
            FieldStatistic(
                name=field,
                inferredType=inferred_type,
                nonNullCount=non_null_count,
                missingCount=missing_count,
                missingRate=_finite_float(variable.get("p_missing")),
                distinctCount=distinct_count,
                cardinalityRate=_finite_float(variable.get("p_distinct")),
                unique=bool(variable.get("is_unique", False)),
                sampleValues=sample_values,
                topValues=tuple(
                    ValueFrequency(
                        value=str(value),
                        count=int(count),
                        ratio=_ratio(int(count), non_null_count),
                    )
                    for value, count in list(value_counts.items())[:20]
                ),
                minimum=_optional_finite_float(variable.get("min")) if is_numeric else None,
                maximum=_optional_finite_float(variable.get("max")) if is_numeric else None,
                average=_optional_finite_float(variable.get("mean")) if is_numeric else None,
                standardDeviation=(
                    _optional_finite_float(variable.get("std")) if is_numeric else None
                ),
                p25=_optional_finite_float(variable.get("25%")) if is_numeric else None,
                p50=_optional_finite_float(variable.get("50%")) if is_numeric else None,
                p75=_optional_finite_float(variable.get("75%")) if is_numeric else None,
                zeroCount=int(variable.get("n_zeros", 0)) if is_numeric else 0,
                negativeCount=int(variable.get("n_negative", 0)) if is_numeric else 0,
            )
        )
        if is_numeric:
            numeric.append(field)
        # Workflow 会传入已经过 Schema 与 SQL 审核的 periodColumn。期间覆盖只能
        # 来自这些事实字段，不能因 person_time 等业务量字段包含 "time" 就把高
        # 基数数值误登记为期间。独立调用没有审核上下文时使用保守名称识别。
        if (
            field.casefold() in trusted_period_fields
            if trusted_period_fields
            else is_temporal or _is_period_field_name(field)
        ):
            periods.update(str(value).strip() for value in dataframe[field].dropna())
    # fg-data-profiling 4.19.1 的 n_duplicates 实际是重复组合组数。保留原始
    # Profile 值作为引擎诊断，工作流对外语义改用 keep="first" 的重复行数。
    duplicate_group_count = int(table.get("n_duplicates", 0))
    duplicate_row_count = int(dataframe.duplicated(keep="first").sum())
    duplicate_row_rate = _ratio(duplicate_row_count, row_count)
    profile["duplicate_analysis"] = {
        "duplicate_group_count": duplicate_group_count,
        "duplicate_row_count": duplicate_row_count,
        "duplicate_row_rate": duplicate_row_rate,
    }
    empty_row_count = int(dataframe.isna().all(axis=1).sum())
    missing_cell_count = int(table.get("n_cells_missing", 0))
    quality_warnings: list[str] = []
    if duplicate_time_index:
        quality_warnings.append(
            "期间索引存在重复，行级 ACF/PACF 和季节性统计已禁用；需先按月及组织粒度聚合。"
        )
    if duplicate_row_count:
        quality_warnings.append(f"数据集包含 {duplicate_row_count} 行重复记录。")
    if empty_row_count:
        quality_warnings.append(f"数据集包含 {empty_row_count} 行空记录。")
    quality_warnings.extend(
        str(alert)
        for alert in profile.get("alerts", ())
        if isinstance(alert, str)
        and not (alert.startswith("Dataset has ") and " duplicate rows" in alert)
    )
    engine_version = (
        str(package.get("data_profiling_version", ""))
        if isinstance(package, Mapping)
        else ""
    )
    if not engine_version:
        raise ValueError("CSV Profile 缺少引擎版本")
    profile_content = json.dumps(
        profile,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    resolved_profile_path = profile_path or f"{path}.profile.json"
    context = DatasetAnalysisContext(
        profileEngineVersion=engine_version,
        profileFile=AnalysisFileIdentity(
            path=resolved_profile_path,
            size=len(profile_content),
            sha256=hashlib.sha256(profile_content).hexdigest(),
        ),
        profileModelView=build_profile_model_view(profile),
        datasetId=dataset_id,
        path=path,
        size=len(content),
        sha256=digest,
        rowCount=row_count,
        columnCount=len(fields),
        missingCellCount=missing_cell_count,
        missingCellRate=_finite_float(table.get("p_cells_missing")),
        duplicateRowCount=duplicate_row_count,
        duplicateRowRate=duplicate_row_rate,
        emptyRowCount=empty_row_count,
        fields=fields,
        schema=schema or {},
        organizationGrain=organization_grain,
        metricSemantics=metric_semantics,
        numericFields=tuple(numeric),
        periodValues=tuple(sorted(periods)),
        periodCoverage=tuple(sorted(periods)),
        fieldStats=tuple(field_stats),
        sourceWarnings=source_warnings,
        qualityWarnings=tuple(quality_warnings[:100]),
        timeSeriesSortField=time_series_sort_field,
        timeSeriesFields=tuple(time_series_fields),
    )
    return ProfiledDataset(context=context, profile=profile, profile_content=profile_content)


def _prepare_profile_dataframe(
    dataframe: pd.DataFrame,
    *,
    period_fields: tuple[str, ...] = (),
) -> tuple[pd.DataFrame, str | None, pd.Series | None]:
    """为 ProfileReport 找到可排序的时间列，不改变不可变 CSV 本身。

    fg-data-profiling 只有在 `tsmode=True` 且索引可排序时才会运行专用时序摘要。
    业务 CSV 的期间列经常是混合的字符串格式，因此先在画像副本中解析日期。时序
    专用摘要要求完整且足够长的索引；解析失败、存在空时间值或样本过短时保持普通
    表格画像，避免上游 ADF/时间索引渲染器阻断完整 Profile。
    """
    trusted_period_fields = {field.casefold() for field in period_fields}
    candidates = sorted(
        dataframe.columns,
        key=lambda column: (
            0
            if str(column).casefold() in trusted_period_fields
            else 1
            if str(column).lower() in {"data_date", "date", "datetime", "timestamp"}
            else 2
            if _is_period_field_name(str(column))
            else 3,
            str(column),
        ),
    )
    for raw_column in candidates:
        column = str(raw_column)
        values = dataframe[raw_column]
        name_is_temporal = (
            column.casefold() in trusted_period_fields or _is_period_field_name(column)
        )
        dtype_is_temporal = pd.api.types.is_datetime64_any_dtype(values)
        # 日期文本只有字段名明确表达时间语义时才允许解析。普通文本即使全部形似
        # 日期，也可能只是业务标签；数值列还会被 pandas 当作纳秒时间而误判。
        if not name_is_temporal and not dtype_is_temporal:
            continue
        # fg-data-profiling 的时序变量会执行 ADF 和 FFT；少于 8 个观测值时，
        # statsmodels 的默认滞后阶数无效。此处回退普通画像，不丢弃原始行。
        if len(values) < 8:
            continue
        if dtype_is_temporal:
            parsed = pd.to_datetime(values, errors="coerce")
        else:
            try:
                parsed = pd.to_datetime(values, errors="coerce", format="mixed")
            except (TypeError, ValueError):
                parsed = pd.to_datetime(values, errors="coerce")
        valid_count = int(parsed.notna().sum())
        # 时序模式不能携带 NaT 索引：上游时间索引摘要在排序/格式化时会失败。
        # 普通 Profile 仍会按原始值统计缺失，因此这里仅关闭专用时序分支。
        if valid_count != len(values) or valid_count < 3:
            continue
        if int(parsed.dropna().nunique()) < 3:
            continue
        prepared = dataframe.copy()
        prepared[raw_column] = parsed
        return prepared, column, parsed
    return dataframe, None, None


def _is_period_field_name(field: str) -> bool:
    """保守识别日期或期间字段，避免把业务含义中的 time 当作时间轴。"""
    normalized = field.casefold()
    return normalized in {"time", "datetime", "timestamp"} or any(
        token in normalized for token in ("date", "period", "month", "year")
    )


def _append_time_series_statistics(
    profile: dict[str, Any],
    dataframe: pd.DataFrame,
    parsed_time_index: pd.Series | None,
    sort_field: str | None,
) -> tuple[str, ...]:
    """把 ACF、PACF 和季节性数值写入完整 JSON Profile。

    fg-data-profiling 的默认 ACF/PACF 只在 HTML 渲染器中绘图，`to_json()` 不会
    暴露图上的数值。这里复用同一 statsmodels 算法生成有界数值序列，供 Worker
    定位分析重点；图表仍由 Coding Worker 从 CSV 自行生成，Profile 不产出图片。
    """
    if sort_field is None or parsed_time_index is None:
        profile["time_series_analysis"] = {
            "enabled": False,
            "sort_field": None,
            "reason": "no_usable_time_index",
            "aggregation_required": False,
            "fields": {},
        }
        return ()

    if parsed_time_index.duplicated().any():
        profile["time_series_analysis"] = {
            "enabled": False,
            "sort_field": sort_field,
            "reason": "duplicate_time_index",
            "aggregation_required": True,
            "fields": {},
        }
        return ()

    order = parsed_time_index.sort_values(kind="stable").index
    ordered = dataframe.loc[order]
    series_payload: dict[str, Any] = {}
    raw_variables = profile.get("variables")
    variables: Mapping[str, Any] = (
        raw_variables if isinstance(raw_variables, Mapping) else {}
    )
    numeric_fields: list[str] = []
    numeric_fields = [
        field
        for field, variable in variables.items()
        if isinstance(field, str)
        and isinstance(variable, Mapping)
        and str(variable.get("type")) in {"Numeric", "TimeSeries"}
        and field in ordered.columns
    ]

    for field in numeric_fields:
        values = pd.to_numeric(ordered[field], errors="coerce").dropna().astype(float)
        if len(values) < 8:
            continue
        max_lag = min(100, max(1, len(values) // 2 - 1))
        try:
            acf_values = acf(values.to_numpy(), nlags=max_lag, fft=True)
            pacf_values = pacf(values.to_numpy(), nlags=max_lag, method="ywm")
        except (FloatingPointError, ValueError, ZeroDivisionError):
            continue

        seasonality_presence = False
        seasonalities: list[float] = []
        try:
            # 与 fg-data-profiling 的 TimeSeries summarizer 使用同一 FFT 检测逻辑。
            from data_profiling.model.pandas.describe_timeseries_pandas import seasonality_test

            seasonality = seasonality_test(pd.Series(values.to_numpy()))
            seasonality_presence = bool(seasonality.get("seasonality_presence", False))
            seasonalities = [
                number
                for number in (
                    _optional_finite_float(item) for item in seasonality.get("seasonalities", ())
                )
                if number is not None and number > 0
            ]
        except (ImportError, FloatingPointError, ValueError, ZeroDivisionError):
            pass

        adf_p_value: float | None = None
        stationary: bool | None = None
        try:
            adf_p_value = _optional_finite_float(adfuller(values.to_numpy(), autolag="AIC")[1])
            stationary = adf_p_value is not None and adf_p_value < 0.05 and not seasonality_presence
        except (ValueError, FloatingPointError, ZeroDivisionError):
            pass

        acf_payload = [
            {"lag": index, "value": _optional_finite_float(value)}
            for index, value in enumerate(acf_values)
        ]
        pacf_payload = [
            {"lag": index, "value": _optional_finite_float(value)}
            for index, value in enumerate(pacf_values)
        ]
        series_payload[field] = {
            "acf": acf_payload,
            "pacf": pacf_payload,
            "lag_count": max_lag,
            "seasonality": {
                "presence": seasonality_presence,
                "periods": seasonalities,
            },
            "adf_p_value": adf_p_value,
            "stationary": stationary,
        }
        variable = variables.get(field)
        if isinstance(variable, dict):
            # 保留上游摘要，同时把可复现的时序数值挂在同一变量节点上。
            variable.setdefault("seasonal", seasonality_presence)
            variable.setdefault("addfuller", adf_p_value)
            variable.setdefault("stationary", stationary)

    profile["time_series_analysis"] = {
        "enabled": True,
        "sort_field": sort_field,
        "fields": series_payload,
    }
    return tuple(series_payload)


def build_profile_model_view(profile: Mapping[str, Any]) -> dict[str, Any]:
    """把完整 Profile 转成有界高信号摘要和受信 JSON Pointer 索引。"""
    table = profile.get("table")
    variables = profile.get("variables")
    correlations = profile.get("correlations")
    time_series_analysis = profile.get("time_series_analysis")
    time_index_analysis = profile.get("time_index_analysis")
    if not isinstance(table, Mapping) or not isinstance(variables, Mapping):
        raise ValueError("CSV Profile 结构无效")

    variable_views: list[dict[str, Any]] = []
    time_series_views: list[dict[str, Any]] = []
    variable_types: dict[str, int] = {}
    missing_fields: list[dict[str, Any]] = []
    constant_fields: list[dict[str, Any]] = []
    skewness_fields: list[dict[str, Any]] = []
    kurtosis_fields: list[dict[str, Any]] = []
    zero_fields: list[dict[str, Any]] = []
    negative_fields: list[dict[str, Any]] = []
    structured_detail_count = 0
    legacy_panel_time_series = bool(
        isinstance(time_series_analysis, Mapping)
        and time_series_analysis.get("enabled") is True
        and isinstance(time_index_analysis, Mapping)
        and time_index_analysis.get("n_series") == 0
    )
    usable_time_series_fields = (
        time_series_analysis.get("fields")
        if isinstance(time_series_analysis, Mapping) and not legacy_panel_time_series
        else {}
    )

    for raw_name, raw_variable in variables.items():
        if not isinstance(raw_name, str) or not isinstance(raw_variable, Mapping):
            raise ValueError("CSV Profile 字段画像无效")
        pointer_name = _json_pointer_token(raw_name)
        detail_pointers = {
            key: f"/variables/{pointer_name}/{_json_pointer_token(key)}"
            for key, value in raw_variable.items()
            if isinstance(key, str) and not _is_profile_scalar(value)
        }
        structured_detail_count += len(detail_pointers)
        variable_type = str(raw_variable.get("type") or "Unknown")
        variable_types[variable_type] = variable_types.get(variable_type, 0) + 1
        variable_views.append(
            {
                "name": raw_name,
                "type": variable_type,
                "profilePointer": f"/variables/{pointer_name}",
                "detailPointers": detail_pointers,
            }
        )

        field_pointer = f"/variables/{pointer_name}"
        missing_rate = _optional_finite_float(raw_variable.get("p_missing"))
        missing_count = int(raw_variable.get("n_missing", 0) or 0)
        if missing_count:
            missing_fields.append(
                {
                    "name": raw_name,
                    "count": missing_count,
                    "rate": missing_rate,
                    "profilePointer": field_pointer,
                }
            )
        if int(raw_variable.get("count", 0) or 0) and int(
            raw_variable.get("n_distinct", 0) or 0
        ) <= 1:
            constant_fields.append({"name": raw_name, "profilePointer": field_pointer})
        for target, source_key in (
            (skewness_fields, "skewness"),
            (kurtosis_fields, "kurtosis"),
            (zero_fields, "p_zeros"),
            (negative_fields, "p_negative"),
        ):
            value = _optional_finite_float(raw_variable.get(source_key))
            if value is not None and value != 0:
                target.append(
                    {
                        "name": raw_name,
                        "value": value,
                        "profilePointer": (
                            f"{field_pointer}/{_json_pointer_token(source_key)}"
                        ),
                    }
                )
        if (
            isinstance(usable_time_series_fields, Mapping)
            and raw_name in usable_time_series_fields
        ):
            time_series_views.append(
                {
                    "name": raw_name,
                    "profilePointer": f"/time_series_analysis/fields/{pointer_name}",
                    "acfPointer": (
                        f"/time_series_analysis/fields/{pointer_name}/acf"
                    ),
                    "pacfPointer": (
                        f"/time_series_analysis/fields/{pointer_name}/pacf"
                    ),
                    "seasonalityPointer": (
                        f"/time_series_analysis/fields/{pointer_name}/seasonality"
                    ),
                }
            )

    correlation_views: list[dict[str, Any]] = []
    correlation_pairs: list[dict[str, Any]] = []
    if isinstance(correlations, Mapping):
        for method, raw_matrix in correlations.items():
            if not isinstance(method, str):
                continue
            rows = raw_matrix if isinstance(raw_matrix, list) else []
            first_row = rows[0] if rows and isinstance(rows[0], Mapping) else {}
            columns = [key for key in first_row if isinstance(key, str)]
            matrix_valid = bool(columns) and len(rows) == len(columns) and all(
                isinstance(row, Mapping) and list(row) == columns for row in rows
            )
            if matrix_valid:
                for row_index, row in enumerate(rows):
                    for column_index in range(row_index + 1, len(columns)):
                        column = columns[column_index]
                        value = _optional_finite_float(row[column])
                        if value is not None:
                            correlation_pairs.append(
                                {
                                    "method": method,
                                    "left": columns[row_index],
                                    "right": column,
                                    "value": value,
                                    "profilePointer": (
                                        f"/correlations/{_json_pointer_token(method)}/{row_index}/"
                                        f"{_json_pointer_token(column)}"
                                    ),
                                }
                            )
            correlation_views.append(
                {
                    "method": method,
                    "columns": columns,
                    "matrixValid": matrix_valid,
                    "profilePointer": f"/correlations/{_json_pointer_token(method)}",
                }
            )

    alerts = [item for item in profile.get("alerts", ()) if isinstance(item, str)]
    table_statistics = {
        key: value
        for key, value in table.items()
        if isinstance(key, str) and _is_profile_scalar(value)
    }
    table_detail_pointers = {
        key: f"/table/{_json_pointer_token(key)}"
        for key, value in table.items()
        if isinstance(key, str) and not _is_profile_scalar(value)
    }

    for values in (
        missing_fields,
        skewness_fields,
        kurtosis_fields,
        zero_fields,
        negative_fields,
    ):
        values.sort(key=lambda item: abs(float(item.get("value", item.get("rate", 0)) or 0)), reverse=True)
        del values[MAX_PROFILE_HIGHLIGHTS:]
    constant_fields.sort(key=lambda item: item["name"])
    del constant_fields[MAX_PROFILE_HIGHLIGHTS:]
    correlation_pairs.sort(key=lambda item: abs(item["value"]), reverse=True)
    del correlation_pairs[MAX_PROFILE_HIGHLIGHTS:]

    time_series_enabled = bool(
        isinstance(time_series_analysis, Mapping)
        and time_series_analysis.get("enabled") is True
        and not legacy_panel_time_series
    )
    time_series_reason = (
        "duplicate_time_index"
        if legacy_panel_time_series
        else time_series_analysis.get("reason")
        if isinstance(time_series_analysis, Mapping)
        and isinstance(time_series_analysis.get("reason"), str)
        else None
    )
    aggregation_required = bool(
        legacy_panel_time_series
        or (
            isinstance(time_series_analysis, Mapping)
            and time_series_analysis.get("aggregation_required") is True
        )
    )
    chart_opportunities = _profile_chart_opportunities(
        variable_views=variable_views,
        missing_fields=missing_fields,
        skewness_fields=skewness_fields,
        kurtosis_fields=kurtosis_fields,
        zero_fields=zero_fields,
        correlation_pairs=correlation_pairs,
        time_series_enabled=time_series_enabled,
        aggregation_required=aggregation_required,
    )
    indexed_variables = variable_views[:MAX_PROFILE_VARIABLE_INDEX]
    duplicate_analysis = profile.get("duplicate_analysis")
    duplicate_rows = (
        duplicate_analysis.get("duplicate_row_count")
        if isinstance(duplicate_analysis, Mapping)
        else None
    )
    duplicate_groups = (
        duplicate_analysis.get("duplicate_group_count")
        if isinstance(duplicate_analysis, Mapping)
        else table.get("n_duplicates")
    )
    model_view = {
        "version": "1",
        "table": {
            "profilePointer": "/table",
            "statistics": table_statistics,
            "detailPointers": table_detail_pointers,
        },
        "variables": indexed_variables,
        "alerts": alerts[:MAX_PROFILE_HIGHLIGHTS],
        "alertsPointer": "/alerts",
        "correlations": correlation_views,
        "timeSeries": {
            "enabled": time_series_enabled,
            "sortField": (
                time_series_analysis.get("sort_field")
                if isinstance(time_series_analysis, Mapping)
                and isinstance(time_series_analysis.get("sort_field"), str)
                else None
            ),
            "reason": time_series_reason,
            "aggregationRequired": aggregation_required,
            "fields": time_series_views,
            "profilePointer": "/time_series_analysis",
        },
        "highlights": {
            "missingFields": missing_fields,
            "constantFields": constant_fields,
            "highSkewness": skewness_fields,
            "highKurtosis": kurtosis_fields,
            "highZeroRates": zero_fields,
            "highNegativeRates": negative_fields,
            "topCorrelations": correlation_pairs,
            "duplicateRows": dict(duplicate_analysis)
            if isinstance(duplicate_analysis, Mapping)
            else {"duplicateGroupCount": duplicate_groups},
        },
        "chartOpportunities": chart_opportunities,
        "coverage": {
            "variableCount": len(variables),
            "rowCount": table.get("n"),
            "columnCount": table.get("n_var", len(variables)),
            "missingCellCount": table.get("n_cells_missing", 0),
            "missingCellRate": table.get("p_cells_missing", 0.0),
            "duplicateRowCount": duplicate_rows,
            "duplicateGroupCount": duplicate_groups,
            "indexedVariableCount": len(indexed_variables),
            "variableIndexTruncated": len(indexed_variables) < len(variables),
            "eligibleDetailCount": sum(
                len(item["detailPointers"]) for item in indexed_variables
            ),
            "indexedDetailCount": sum(
                len(item["detailPointers"]) for item in indexed_variables
            ),
            "detailIndexTruncated": False,
            "variableTypes": variable_types,
            "alertCount": len(alerts),
            "indexedAlertCount": min(len(alerts), MAX_PROFILE_HIGHLIGHTS),
            "alertIndexTruncated": len(alerts) > MAX_PROFILE_HIGHLIGHTS,
            "correlationMethods": [item["method"] for item in correlation_views],
            "structuredDetailCount": structured_detail_count,
            "timeSeriesFieldCount": len(time_series_views),
        },
        "modelViewTruncated": len(indexed_variables) < len(variables),
    }
    return _bound_profile_model_view(model_view)


def _profile_chart_opportunities(
    *,
    variable_views: list[dict[str, Any]],
    missing_fields: list[dict[str, Any]],
    skewness_fields: list[dict[str, Any]],
    kurtosis_fields: list[dict[str, Any]],
    zero_fields: list[dict[str, Any]],
    correlation_pairs: list[dict[str, Any]],
    time_series_enabled: bool,
    aggregation_required: bool,
) -> list[dict[str, Any]]:
    """只提供基于 Profile 信号的候选，不形成图表数量或类型闭包。"""
    numeric_fields = [
        item["name"]
        for item in variable_views
        if item["type"] in {"Numeric", "TimeSeries"}
    ]
    categorical_fields = [
        item["name"]
        for item in variable_views
        if item["type"] in {"Categorical", "Text", "Boolean"}
    ]
    opportunities: list[dict[str, Any]] = []

    def add(code: str, label: str, reason: str, fields: list[str]) -> None:
        opportunities.append(
            {
                "code": code,
                "label": label,
                "reason": reason,
                "fields": list(dict.fromkeys(fields))[:8],
            }
        )

    if aggregation_required:
        add(
            "monthly_aggregate_trend",
            "月度聚合趋势带或同比哑铃图",
            "原始期间索引重复，必须先按月及适当组织粒度聚合",
            numeric_fields,
        )
    elif time_series_enabled:
        add(
            "time_trend",
            "趋势带、同比哑铃图或拐点图",
            "存在可用的唯一时间索引",
            numeric_fields,
        )
    if categorical_fields and numeric_fields:
        add(
            "categorical_contribution",
            "组织贡献排名、Pareto 图或结构图",
            "分类维度和数值指标可用于结构与贡献分析",
            [*categorical_fields, *numeric_fields],
        )
    if skewness_fields or kurtosis_fields:
        add(
            "distribution_outliers",
            "对数分布、箱线图或极端值贡献图",
            "数值字段存在偏度、峰度或长尾信号",
            [item["name"] for item in (*skewness_fields, *kurtosis_fields)],
        )
    if zero_fields:
        add(
            "zero_rate_matrix",
            "零值率热力矩阵",
            "多个指标存在零值分布信号",
            [item["name"] for item in zero_fields],
        )
    if missing_fields:
        add(
            "missingness_matrix",
            "缺失结构热力矩阵",
            "字段存在缺失分布信号",
            [item["name"] for item in missing_fields],
        )
    if correlation_pairs:
        add(
            "correlation_matrix",
            "相关矩阵、散点图或气泡象限图",
            "Profile 存在可定点复核的高相关字段对",
            [
                field
                for item in correlation_pairs
                for field in (item["left"], item["right"])
            ],
        )
    lowered = {str(item["name"]).casefold() for item in variable_views}
    if any("budget" in name for name in lowered) and any(
        "actual" in name for name in lowered
    ):
        add(
            "budget_variance",
            "预算与实际子弹图、偏差瀑布图或气泡象限图",
            "字段同时包含预算与实际口径",
            [item["name"] for item in variable_views],
        )
    if all(any(token in name for name in lowered) for token in ("budget", "contract", "pay")):
        add(
            "conversion_funnel",
            "预算、合同与付款转化漏斗图",
            "字段具备连续转化阶段",
            [item["name"] for item in variable_views],
        )
    return opportunities


def _bound_profile_model_view(model_view: dict[str, Any]) -> dict[str, Any]:
    """按低信号优先级裁剪索引，确保单个 Dataset 视图不超过 12 KiB。"""
    eligible_detail_counts = {
        item["name"]: len(item.get("detailPointers", {}))
        for item in model_view["variables"]
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }

    def size() -> int:
        return len(
            json.dumps(
                model_view,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    if size() <= MAX_PROFILE_MODEL_VIEW_BYTES:
        return _update_profile_index_coverage(model_view, eligible_detail_counts)
    model_view["modelViewTruncated"] = True
    for variable in reversed(model_view["variables"]):
        detail_pointers = variable.get("detailPointers")
        while isinstance(detail_pointers, dict) and detail_pointers and size() > MAX_PROFILE_MODEL_VIEW_BYTES:
            detail_pointers.pop(next(reversed(detail_pointers)))
    while len(model_view["variables"]) > 10 and size() > MAX_PROFILE_MODEL_VIEW_BYTES:
        model_view["variables"].pop()
    _update_profile_index_coverage(model_view, eligible_detail_counts)
    for key in (
        "topCorrelations",
        "highKurtosis",
        "highSkewness",
        "highZeroRates",
        "highNegativeRates",
        "missingFields",
        "constantFields",
    ):
        values = model_view["highlights"][key]
        while len(values) > 3 and size() > MAX_PROFILE_MODEL_VIEW_BYTES:
            values.pop()
    while len(model_view["alerts"]) > 3 and size() > MAX_PROFILE_MODEL_VIEW_BYTES:
        model_view["alerts"].pop()
    for correlation in model_view["correlations"]:
        if size() <= MAX_PROFILE_MODEL_VIEW_BYTES:
            break
        correlation["columns"] = []
    for opportunity in model_view["chartOpportunities"]:
        if size() <= MAX_PROFILE_MODEL_VIEW_BYTES:
            break
        opportunity["fields"] = []
    while model_view["chartOpportunities"] and size() > MAX_PROFILE_MODEL_VIEW_BYTES:
        model_view["chartOpportunities"].pop()
    while model_view["variables"] and size() > MAX_PROFILE_MODEL_VIEW_BYTES:
        model_view["variables"].pop()
    _update_profile_index_coverage(model_view, eligible_detail_counts)
    if size() > MAX_PROFILE_MODEL_VIEW_BYTES:
        raise ValueError("CSV Profile 模型视图超过有界上下文限制")
    return model_view


def _update_profile_index_coverage(
    model_view: dict[str, Any], eligible_detail_counts: Mapping[str, int]
) -> dict[str, Any]:
    """分别登记各索引层的覆盖，避免把不同裁剪原因压成单一状态。"""
    variables = model_view["variables"]
    coverage = model_view["coverage"]
    eligible_detail_count = 0
    for item in variables:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        eligible_detail_count += eligible_detail_counts.get(item["name"], 0)
    indexed_detail_count = sum(
        len(item.get("detailPointers", {}))
        for item in variables
        if isinstance(item, dict) and isinstance(item.get("detailPointers"), dict)
    )
    coverage["indexedVariableCount"] = len(variables)
    coverage["variableIndexTruncated"] = len(variables) < coverage["variableCount"]
    coverage["eligibleDetailCount"] = eligible_detail_count
    coverage["indexedDetailCount"] = indexed_detail_count
    coverage["detailIndexTruncated"] = indexed_detail_count < eligible_detail_count
    coverage["indexedAlertCount"] = len(model_view["alerts"])
    coverage["alertIndexTruncated"] = len(model_view["alerts"]) < coverage["alertCount"]
    model_view["modelViewTruncated"] = any(
        coverage[key]
        for key in (
            "variableIndexTruncated",
            "detailIndexTruncated",
            "alertIndexTruncated",
        )
    )
    return model_view


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _optional_finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _finite_float(value: Any) -> float:
    converted = _optional_finite_float(value)
    return converted if converted is not None else 0.0


def _is_profile_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


__all__ = [
    "AnalysisFileIdentity",
    "DatasetAnalysisContext",
    "DetailedAnalysisItem",
    "DetailedAnalysisPlan",
    "FieldStatistic",
    "ValueFrequency",
    "ProfiledDataset",
    "build_profile_model_view",
    "profile_csv_dataset",
]
