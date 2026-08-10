from __future__ import annotations

import hashlib
import json
import warnings

import pandas as pd
import pytest

from agentos_dev.coding.reporting.hospital_operation.detailed_analysis import (
    DetailedAnalysisItem,
    DetailedAnalysisPlan,
    _prepare_profile_dataframe,
    build_profile_model_view,
    profile_csv_dataset,
)
from agentos_dev.coding.reporting.workflow.runtime import _coding_detailed_analysis_plan


def test_profile_csv_reads_all_rows_and_validates_snapshot() -> None:
    content = (
        "period,department,amount\n"
        "2025-01,内科,10\n"
        "2025-02,外科,20\n"
        "2025-03,内科,30\n"
        "2025-04,外科,40\n"
        "2025-05,内科,50\n"
        "2025-06,外科,60\n"
    ).encode()
    digest = hashlib.sha256(content).hexdigest()
    profiled = profile_csv_dataset(
        content,
        dataset_id="dataset-1",
        path="报表/数据集/dataset-1.csv",
        expected_sha256=digest,
    )
    context = profiled.context
    assert context.row_count == 6
    assert context.numeric_fields == ("amount",)
    assert context.period_values == (
        "2025-01",
        "2025-02",
        "2025-03",
        "2025-04",
        "2025-05",
        "2025-06",
    )
    assert context.column_count == 3
    assert context.missing_cell_count == 0
    assert context.duplicate_row_count == 0
    with pytest.raises(ValueError, match="哈希"):
        profile_csv_dataset(
            content,
            dataset_id="dataset-1",
            path="x.csv",
            expected_sha256="0" * 64,
        )


def test_profile_csv_produces_ydata_aligned_json_statistics() -> None:
    rows = [
        f"2025-{index:02d},{'内科' if index % 2 else '外科'},"
        f"{'华东' if index % 2 else '华西'},{index},{index * index},"
        f"{'重点科室' if index % 2 else '普通科'}"
        for index in range(1, 13)
    ]
    content = (
        "period,department,region,amount,cost,note\n"
        + "\n".join(rows)
        + "\n2025-01,内科,华东,1,1,重点科室\n,,,,,\n"
    ).encode()
    profiled = profile_csv_dataset(
        content,
        dataset_id="dataset-profile",
        path="profile.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )
    context = profiled.context
    profile = profiled.profile

    assert context.row_count == 14
    assert context.missing_cell_count == 6
    assert context.missing_cell_rate == pytest.approx(6 / 84)
    assert context.duplicate_row_count == 1
    assert context.duplicate_row_rate == pytest.approx(1 / 14)
    assert context.empty_row_count == 1
    assert context.profile_version == "1"
    assert context.profile_engine == "fg-data-profiling"
    assert context.profile_engine_version == "4.19.1"
    assert "数据集包含 1 行重复记录。" in context.quality_warnings
    assert "数据集包含 1 行空记录。" in context.quality_warnings

    fields = {item.name: item for item in context.field_stats}
    amount = fields["amount"]
    assert amount.inferred_type == "numeric"
    assert amount.missing_count == 1
    assert amount.minimum == 1
    assert amount.maximum == 12
    assert amount.average == pytest.approx(profile["variables"]["amount"]["mean"])

    department = fields["department"]
    assert department.inferred_type == "categorical"
    assert department.distinct_count == 2
    assert department.top_values[0].value == "内科"
    assert department.top_values[0].count == 7
    assert department.top_values[0].ratio == pytest.approx(7 / 13)

    assert profile["variables"]["amount"]["skewness"] is not None
    assert profile["variables"]["amount"]["kurtosis"] is not None
    assert profile["variables"]["amount"]["histogram"]["counts"]
    assert profile["variables"]["note"]["length_histogram"]
    assert set(profile["correlations"]) == {
        "auto",
        "pearson",
        "spearman",
        "kendall",
        "phi_k",
        "cramers",
    }
    assert profile["scatter"] == {}
    serialized = json.dumps(profile, ensure_ascii=False)
    assert "<svg" not in serialized.lower()
    assert "data:image" not in serialized.lower()
    assert "<html" not in serialized.lower()

    stored = context.model_dump(mode="json", by_alias=True)
    assert "profile" not in stored
    assert context.profile_file.size == len(profiled.profile_content)
    assert context.profile_file.sha256 == hashlib.sha256(profiled.profile_content).hexdigest()
    assert context.profile_file.path == "profile.csv.profile.json"

    # 完整 Profile 原样保存，模型视图只保留高信号摘要和定点读取索引。
    model_view = build_profile_model_view(profile)
    assert model_view == context.profile_model_view
    assert len(json.dumps(model_view, ensure_ascii=False).encode("utf-8")) <= 12 * 1024
    assert model_view["coverage"]["variableCount"] == len(profile["variables"])
    assert model_view["coverage"]["rowCount"] == profile["table"]["n"]
    assert model_view["coverage"]["missingCellCount"] == profile["table"]["n_cells_missing"]
    assert model_view["coverage"]["variableTypes"]["Numeric"] == 2
    assert model_view["alertsPointer"] == "/alerts"
    assert len(model_view["alerts"]) <= 10
    assert model_view["coverage"]["alertCount"] == len(profile["alerts"])
    assert model_view["coverage"]["indexedAlertCount"] == len(model_view["alerts"])
    assert model_view["coverage"]["alertIndexTruncated"] is (
        len(model_view["alerts"]) < len(profile["alerts"])
    )
    assert model_view["coverage"]["detailIndexTruncated"] is False
    variables = {item["name"]: item for item in model_view["variables"]}
    for name, source in profile["variables"].items():
        expected_details = {
            key: f"/variables/{name}/{key}"
            for key, value in source.items()
            if not (value is None or isinstance(value, (bool, int, float, str)))
        }
        assert variables[name]["type"] == source["type"]
        assert variables[name]["profilePointer"] == f"/variables/{name}"
        assert set(variables[name]["detailPointers"]).issubset(expected_details)

    correlations = {item["method"]: item for item in model_view["correlations"]}
    for method, matrix in profile["correlations"].items():
        columns = list(matrix[0])
        assert correlations[method]["columns"] == columns
        assert correlations[method]["profilePointer"] == f"/correlations/{method}"
    assert len(model_view["highlights"]["topCorrelations"]) <= 10
    assert model_view["highlights"]["highSkewness"]
    assert {item["code"] for item in model_view["chartOpportunities"]} >= {
        "distribution_outliers",
        "correlation_matrix",
    }

    compact = json.dumps(model_view, ensure_ascii=False)
    assert "<svg" not in compact.lower()
    assert "data:image" not in compact.lower()
    assert "<html" not in compact.lower()


def test_profile_model_view分别标记变量明细和告警索引裁剪() -> None:
    variables = {
        f"field_{index:02d}": {
            "type": "Numeric",
            "count": 100,
            "skewness": float(index),
            "kurtosis": float(index + 3),
            "histogram": {
                "counts": list(range(40)),
                "bin_edges": list(range(41)),
            },
            "value_counts_without_nan": {str(item): item for item in range(40)},
        }
        for index in range(45)
    }
    profile = {
        "table": {"n": 100, "n_var": len(variables), "types": {"Numeric": 45}},
        "variables": variables,
        "alerts": [f"alert-{index}" for index in range(25)],
        "correlations": {},
        "time_series_analysis": {"enabled": False, "fields": {}},
    }

    model_view = build_profile_model_view(profile)
    coverage = model_view["coverage"]

    assert coverage["variableIndexTruncated"] is True
    assert coverage["detailIndexTruncated"] is False
    assert coverage["alertIndexTruncated"] is True
    assert coverage["indexedAlertCount"] == len(model_view["alerts"])
    assert model_view["modelViewTruncated"] is True

    detail_heavy_profile = {
        "table": {"n": 100, "n_var": 10, "types": {"Numeric": 10}},
        "variables": {
            f"field_{index}": {
                "type": "Numeric",
                "count": 100,
                **{
                    f"detail_{detail}": {"counts": [detail]}
                    for detail in range(80)
                },
            }
            for index in range(10)
        },
        "alerts": [],
        "correlations": {},
        "time_series_analysis": {"enabled": False, "fields": {}},
    }

    detail_coverage = build_profile_model_view(detail_heavy_profile)["coverage"]

    assert detail_coverage["variableIndexTruncated"] is False
    assert detail_coverage["detailIndexTruncated"] is True
    assert detail_coverage["indexedDetailCount"] < detail_coverage[
        "eligibleDetailCount"
    ]


def test_profile_csv面板时序要求先聚合且不产生duplicate_label警告() -> None:
    content = (
        "period,department,amount,cost\n"
        + "\n".join(
            f"2025-{month:02d},{department},{month * multiplier},{month * month}"
            for month in range(1, 13)
            for department, multiplier in (("内科", 1), ("外科", 2))
        )
        + "\n"
    ).encode()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        profiled = profile_csv_dataset(
            content,
            dataset_id="dataset-panel",
            path="panel.csv",
            expected_sha256=hashlib.sha256(content).hexdigest(),
            period_fields=("period",),
        )

    assert profiled.profile["correlations"]["auto"]
    time_series = profiled.profile["time_series_analysis"]
    assert time_series == {
        "enabled": False,
        "sort_field": "period",
        "reason": "duplicate_time_index",
        "aggregation_required": True,
        "fields": {},
    }
    assert profiled.context.time_series_fields == ()
    assert profiled.context.profile_model_view["timeSeries"]["reason"] == (
        "duplicate_time_index"
    )
    assert profiled.context.profile_model_view["timeSeries"]["aggregationRequired"] is True
    assert any("行级 ACF/PACF" in warning for warning in profiled.context.quality_warnings)
    assert not any(
        "cannot reindex on an axis with duplicate labels" in str(item.message)
        for item in caught
    )


def test_profile_csv_json_does_not_build_visual_report(monkeypatch) -> None:
    def reject_visual_report(*_args, **_kwargs):
        raise AssertionError("JSON Profile 不应构建 HTML/Widget 展示结构")

    monkeypatch.setattr(
        "data_profiling.profile_report.get_report_structure",
        reject_visual_report,
    )
    content = (
        "period,amount\n"
        + "\n".join(f"2025-{index:02d},{index}" for index in range(1, 13))
        + "\n"
    ).encode()

    profiled = profile_csv_dataset(
        content,
        dataset_id="dataset-json-only",
        path="json-only.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert profiled.profile["variables"]["amount"]["histogram"]["counts"]
    assert profiled.context.profile_file.size == len(profiled.profile_content)


def test_profile_csv_exposes_time_series_statistics_by_pointer() -> None:
    content = (
        "date,amount\n"
        + "\n".join(
            f"2025-01-{day:02d},{day + (day % 7) * 3}" for day in range(1, 25)
        )
        + "\n"
    ).encode()

    profiled = profile_csv_dataset(
        content,
        dataset_id="dataset-time-series",
        path="time-series.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )

    context = profiled.context
    profile = profiled.profile
    time_series = profile["time_series_analysis"]
    model_view = context.profile_model_view["timeSeries"]
    amount = next(item for item in context.field_stats if item.name == "amount")

    assert context.time_series_sort_field == "date"
    assert context.time_series_fields == ("amount",)
    assert context.numeric_fields == ("amount",)
    assert amount.inferred_type == "numeric"
    assert amount.minimum is not None
    assert time_series["enabled"] is True
    assert time_series["fields"]["amount"]["acf"]
    assert time_series["fields"]["amount"]["pacf"]
    assert "seasonality" in time_series["fields"]["amount"]
    assert model_view["fields"] == [
        {
            "name": "amount",
            "profilePointer": "/time_series_analysis/fields/amount",
            "acfPointer": "/time_series_analysis/fields/amount/acf",
            "pacfPointer": "/time_series_analysis/fields/amount/pacf",
            "seasonalityPointer": "/time_series_analysis/fields/amount/seasonality",
        }
    ]


def test_profile_csv_duplicate_count_uses_duplicate_rows_not_duplicate_groups() -> None:
    content = (
        "period,amount\n"
        "2025-01,10\n"
        "2025-01,10\n"
        "2025-01,10\n"
        "2025-02,20\n"
    ).encode()

    profiled = profile_csv_dataset(
        content,
        dataset_id="dataset-duplicates",
        path="duplicates.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert profiled.profile["table"]["n_duplicates"] == 1
    assert profiled.context.duplicate_row_count == 2
    assert profiled.context.duplicate_row_rate == pytest.approx(0.5)
    assert "数据集包含 2 行重复记录。" in profiled.context.quality_warnings


def test_profile_csv_does_not_infer_time_axis_from_amount_or_plain_text() -> None:
    content = (
        "amount,label\n"
        + "\n".join(
            f"{20250100 + day},2025-01-{day:02d}" for day in range(1, 13)
        )
        + "\n"
    ).encode()

    context = profile_csv_dataset(
        content,
        dataset_id="dataset-no-time-axis",
        path="no-time-axis.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
    ).context

    assert context.time_series_sort_field is None
    assert context.time_series_fields == ()
    assert context.profile_model_view["timeSeries"]["enabled"] is False


def test_profile_csv_period_coverage_uses_authorized_period_fields() -> None:
    content = (
        "period_code,actual_person_time,amount\n"
        + "\n".join(
            f"2025-{1 + index // 4:02d},{1000 + index},{index + 1}"
            for index in range(8)
        )
        + "\n"
    ).encode()

    context = profile_csv_dataset(
        content,
        dataset_id="dataset-authorized-period",
        path="authorized-period.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
        period_fields=("period_code",),
    ).context

    assert context.period_values == ("2025-01", "2025-02")
    assert context.period_coverage == ("2025-01", "2025-02")
    assert "actual_person_time" in context.numeric_fields


def test_prepare_profile_dataframe_does_not_mutate_datetime_source() -> None:
    dataframe = pd.DataFrame(
        {
            "captured_at": pd.date_range("2025-01-01", periods=8, freq="D"),
            "amount": [10, 20, 30, 40, 50, 60, 70, 80],
        }
    )
    original = dataframe.copy(deep=True)

    prepared, sort_field, parsed = _prepare_profile_dataframe(dataframe)

    pd.testing.assert_frame_equal(dataframe, original)
    assert prepared is not dataframe
    assert sort_field == "captured_at"
    assert parsed is not None


def test_profile_csv_rejects_malformed_csv() -> None:
    content = b'period,amount\n2025-01,"unterminated\n'

    with pytest.raises(ValueError, match="CSV"):
        profile_csv_dataset(
            content,
            dataset_id="dataset-invalid",
            path="invalid.csv",
            expected_sha256=hashlib.sha256(content).hexdigest(),
        )


def test_detailed_plan_rejects_unknown_dataset_and_duplicate_analysis_id() -> None:
    item = DetailedAnalysisItem(
        analysisId="analysis_001",
        domain="income",
        managementQuestion="收入趋势",
        datasetIds=("dataset-1",),
        fields=("amount",),
        metrics=("amount",),
        periods=("2025-01",),
        actions=("trend",),
        evidenceSummary="CSV 包含完整期间记录。",
        suggestedSection="income",
        completionConditions=("覆盖全部授权期间",),
    )
    context = profile_csv_dataset(
        b"period,amount\n2025-01,1\n",
        dataset_id="dataset-1",
        path="x.csv",
        expected_sha256=hashlib.sha256(b"period,amount\n2025-01,1\n").hexdigest(),
    ).context
    plan = DetailedAnalysisPlan(analyses=(item,), datasetIds=(context.dataset_id,))
    assert plan.analyses[0].analysis_id == "analysis_001"
    with pytest.raises(ValueError, match="未授权"):
        DetailedAnalysisPlan(
            analyses=(item.model_copy(update={"dataset_ids": ("missing",)}),),
            datasetIds=(context.dataset_id,),
        )


def test_detailed_plan_allows_question_style_management_text() -> None:
    content = b"period,amount\n2025-01,1\n"
    context = profile_csv_dataset(
        content,
        dataset_id="dataset-question-text",
        path="dataset.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
    ).context

    plan = DetailedAnalysisPlan(
        analyses=(
            DetailedAnalysisItem(
                analysisId="analysis_002",
                domain="income",
                managementQuestion="收入规模是否满足经营目标？",
                datasetIds=("dataset-question-text",),
                fields=("amount",),
                metrics=("amount",),
                periods=("2025-01",),
                actions=("规模分析",),
                evidenceSummary="CSV 已完成全量画像，是否需要补充趋势比较？",
                limitations=("当前期间是否存在截断？",),
                suggestedSection="收入分析",
                completionConditions=("覆盖授权数据集",),
            ),
        ),
        datasetIds=(context.dataset_id,),
    )

    assert "？" in plan.analyses[0].management_question
    assert "？" in plan.analyses[0].evidence_summary
    assert plan.analyses[0].limitations == ("当前期间是否存在截断？",)


def test_coding_detailed_analysis_plan只保留codex风格执行步骤() -> None:
    content = b"period,amount\n2025-01,1\n"
    context = profile_csv_dataset(
        content,
        dataset_id="dataset-1",
        path="dataset.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
    ).context
    plan = DetailedAnalysisPlan(
        analyses=(
            DetailedAnalysisItem(
                analysisId="analysis_001",
                domain="income",
                managementQuestion="收入趋势形成管理判断。",
                datasetIds=("dataset-1",),
                fields=("amount",),
                metrics=("amount",),
                periods=("2025-01",),
                actions=("趋势分析",),
                evidenceSummary="CSV 已完成全量画像。",
                suggestedSection="收入分析",
                completionConditions=("覆盖授权数据集",),
            ),
        ),
        datasetIds=(context.dataset_id,),
        reportGoal="分析经营情况",
        analysisGoal="形成逐章可执行的分析依据",
        warnings=("期间覆盖以 CSV 为准。",),
    )

    payload = _coding_detailed_analysis_plan(plan)

    assert set(payload) == {"version", "analyses"}
    assert payload["analyses"] == [
        {
            "analysisId": "analysis_001",
            "domain": "income",
            "step": "收入趋势形成管理判断。",
            "datasetIds": ["dataset-1"],
        }
    ]
    serialized = json.dumps(payload, ensure_ascii=False)
    for redundant in (
        "fields",
        "metrics",
        "periods",
        "evidenceSummary",
        "limitations",
        "recommendedCharts",
        "warnings",
    ):
        assert redundant not in serialized
