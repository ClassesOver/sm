from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    profile_csv_dataset,
)

REDUNDANT_PROFILE_KEYS = {
    "analysis",
    "duplicates",
    "missing",
    "sample",
    "scatter",
}
REDUNDANT_TABLE_KEYS = {
    "memory_size",
    "n_duplicates",
    "p_duplicates",
    "record_size",
}
REDUNDANT_VARIABLE_KEYS = {
    "block_alias_char_counts",
    "block_alias_counts",
    "block_alias_values",
    "cast_type",
    "category_alias_char_counts",
    "category_alias_counts",
    "category_alias_values",
    "character_counts",
    "first_rows",
    "hashable",
    "histogram_length",
    "length_histogram",
    "max_length",
    "mean_length",
    "median_length",
    "memory_size",
    "min_length",
    "n_block_alias",
    "n_category",
    "n_characters",
    "n_characters_distinct",
    "n_scripts",
    "ordering",
    "script_char_counts",
    "script_counts",
    "value_counts_index_sorted",
    "word_counts",
}


def test_profile_csv从生成源关闭冗余画像计算(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeProfileReport:
        def __init__(self, _dataframe: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

        def to_json(self) -> str:
            return json.dumps(
                {
                    "analysis": {"title": "unused"},
                    "table": {
                        "n": 2,
                        "n_var": 1,
                        "memory_size": 100,
                        "record_size": 50,
                        "n_cells_missing": 0,
                        "p_cells_missing": 0,
                        "n_duplicates": 1,
                        "p_duplicates": 0.5,
                    },
                    "variables": {
                        "amount": {
                            "type": "Numeric",
                            "count": 2,
                            "n_missing": 0,
                            "p_missing": 0,
                            "n_distinct": 2,
                            "p_distinct": 1,
                            "is_unique": True,
                            "value_counts_without_nan": {"1": 1, "2": 1},
                            "value_counts_index_sorted": {"1": 1, "2": 1},
                            "hashable": True,
                            "ordering": True,
                            "cast_type": None,
                            "memory_size": 148,
                        }
                    },
                    "alerts": [],
                    "correlations": {},
                    "missing": {},
                    "scatter": {},
                    "sample": [{"id": "head"}],
                    "duplicates": [{"amount": 1}],
                    "package": {
                        "data_profiling_version": "4.19.1",
                        "data_profiling_config": "large config",
                    },
                }
            )

    monkeypatch.setattr(
        "smart_reporting.reporting.hospital_operation.detailed_analysis.ProfileReport",
        FakeProfileReport,
    )
    content = b"amount\n1\n2\n"

    profiled = profile_csv_dataset(
        content,
        dataset_id="dataset-config",
        path="config.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert captured["samples"] == {"head": 0, "tail": 0, "random": 0}
    assert captured["duplicates"] == {"head": 0}
    assert captured["tsmode"] is False
    assert captured["vars"]["cat"] == {
        "length": False,
        "characters": False,
        "words": False,
    }
    assert captured["vars"]["text"] == {
        "length": False,
        "characters": False,
        "words": False,
    }
    assert REDUNDANT_PROFILE_KEYS.isdisjoint(profiled.profile)
    assert set(profiled.profile["package"]) == {"data_profiling_version"}


def test_profile_csv空数据集生成零行画像而不调用画像引擎(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"period,amount\n"
    monkeypatch.setattr(
        "smart_reporting.reporting.hospital_operation.detailed_analysis.ProfileReport",
        lambda *_args, **_kwargs: pytest.fail("空数据集不得调用 ProfileReport"),
    )

    profiled = profile_csv_dataset(
        content,
        dataset_id="dataset-empty",
        path="empty.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
        period_fields=("period",),
    )

    assert profiled.context.row_count == 0
    assert profiled.context.fields == ("period", "amount")
    assert profiled.profile["table"]["n"] == 0
    assert profiled.profile["variables"]["amount"]["count"] == 0
    assert "数据集为空，无法进行趋势、分布和相关性分析。" in profiled.context.quality_warnings


# 三组数据沿用迁移前 test_detailed_analysis.py 的混合缺失、面板期间和唯一时序
# 样本，固定验证 Profile 收敛不能改变既有业务统计与时序判定。
@pytest.mark.parametrize(
    (
        "content",
        "period_fields",
        "expected_rows",
        "expected_duplicate_rows",
        "time_state",
        "aggregation_required",
    ),
    (
        (
            (
                "period,department,region,amount,cost,note\n"
                + "\n".join(
                    f"2025-{index:02d},{'内科' if index % 2 else '外科'},"
                    f"{'华东' if index % 2 else '华西'},{index},{index * index},"
                    f"{'重点科室' if index % 2 else '普通科'}"
                    for index in range(1, 13)
                )
                + "\n2025-01,内科,华东,1,1,重点科室\n,,,,,\n"
            ).encode(),
            ("period",),
            14,
            1,
            "no_usable_time_index",
            False,
        ),
        (
            (
                "period,department,amount,cost\n"
                + "\n".join(
                    f"2025-{month:02d},{department},{month * multiplier},{month * month}"
                    for month in range(1, 13)
                    for department, multiplier in (("内科", 1), ("外科", 2))
                )
                + "\n"
            ).encode(),
            ("period",),
            24,
            0,
            "duplicate_time_index",
            True,
        ),
        (
            (
                "date,amount\n"
                + "\n".join(f"2025-01-{day:02d},{day + (day % 7) * 3}" for day in range(1, 25))
                + "\n"
            ).encode(),
            ("date",),
            24,
            0,
            "diagnostics_not_requested",
            False,
        ),
    ),
)
def test_profile_csv历史画像去冗余不改变业务统计(
    content: bytes,
    period_fields: tuple[str, ...],
    expected_rows: int,
    expected_duplicate_rows: int,
    time_state: str,
    aggregation_required: bool,
) -> None:
    profiled = profile_csv_dataset(
        content,
        dataset_id="dataset-history",
        path="history.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
        period_fields=period_fields,
    )
    profile = profiled.profile

    assert profiled.context.profile_engine_version == "4.19.1"
    assert profiled.context.row_count == expected_rows
    assert profiled.context.duplicate_row_count == expected_duplicate_rows
    assert REDUNDANT_PROFILE_KEYS.isdisjoint(profile)
    assert REDUNDANT_TABLE_KEYS.isdisjoint(profile["table"])
    assert set(profile["package"]) == {"data_profiling_version"}
    assert all(
        REDUNDANT_VARIABLE_KEYS.isdisjoint(variable) for variable in profile["variables"].values()
    )
    assert profile["variables"]["amount"]["histogram"]["counts"]
    assert profile["correlations"]
    if time_state == "enabled":
        assert profile["time_series_analysis"]["enabled"] is True
        assert profile["time_series_analysis"]["fields"]["amount"]["acf"]
    else:
        assert profile["time_series_analysis"]["reason"] == time_state
        assert profile["time_series_analysis"]["aggregation_required"] is aggregation_required


def test_profile_csv_explicit_time_series_diagnostics_runs_on_bounded_series() -> None:
    content = (
        "date,amount\n"
        + "\n".join(f"2025-01-{day:02d},{day + (day % 7) * 3}" for day in range(1, 25))
        + "\n"
    ).encode()

    profiled = profile_csv_dataset(
        content,
        dataset_id="dataset-diagnostics",
        path="diagnostics.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
        period_fields=("date",),
        enable_time_series_diagnostics=True,
    )

    analysis = profiled.profile["time_series_analysis"]
    assert analysis["enabled"] is True
    assert analysis["fields"]["amount"]["acf"]
    assert analysis["fields"]["amount"]["pacf"]
