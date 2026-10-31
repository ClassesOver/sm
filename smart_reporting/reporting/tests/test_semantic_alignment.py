"""Semantic identity is explicit, not an equality join on numbers or labels."""

import hashlib
import json

import pytest

from smart_reporting.reporting.trace.chart_quality import ChartQualityCheck, evaluate_chart_quality
from smart_reporting.reporting.trace.contracts_v1 import ChartSeriesV1, FactRefV1
from smart_reporting.reporting.trace.semantic_alignment import (
    SemanticOperandIdentity,
    _projection_semantics,
    compare_semantic_operands,
    evaluate_semantic_alignment,
)

from .test_chart_quality_bundle import chart_case, encoded


def identity(**changes):
    values = dict(
        sourceSha256="a" * 64,
        profileHash="b" * 64,
        analysisId="analysis_001",
        factId="fact-" + "a" * 16,
        factKind="metric",
        selector="periodValues.0",
        unit="元",
        periods=("2025-09",),
        scope={"院区": "北院"},
    )
    values.update(changes)
    return SemanticOperandIdentity(**values)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({}, None),
        ({"factId": "fact-" + "b" * 16}, "fact_id_mismatch"),
        ({"selector": "periodValues.1"}, "selector_mismatch"),
        ({"periods": ("2024-09",)}, "periods_mismatch"),
        ({"scope": {"院区": "南院"}}, "scope_mismatch"),
        ({"unit": "%"}, "unit_mismatch"),
        ({"profileHash": "c" * 64}, "profile_hash_mismatch"),
        ({"sourceSha256": "d" * 64}, "source_sha256_mismatch"),
    ],
)
def test_explicit_operands_require_the_same_frozen_semantics(changes, reason):
    result = compare_semantic_operands(identity(), identity(**changes))
    assert result.status == ("verified" if reason is None else "conflicting")
    assert result.reasons == (() if reason is None else (reason,))


def test_equal_incomplete_operands_do_not_become_verified():
    operand = identity(unit=None, periods=())
    result = compare_semantic_operands(operand, operand)
    assert result.status == "unknown"
    assert result.reasons == ("operand_semantics_incomplete",)


async def bound_chart(tmp_path, *, monthly=False):
    _, _, _, index, markdown, sources, _ = await chart_case(tmp_path)
    chart = index.chart_traces[0]
    fact_file = index.fact_files[0].file_resource_id
    plot_id = chart.plot_data_file_resource_ids[0]
    document = json.loads(sources[fact_file])
    first = document["metrics"][0]
    first["unit"] = "元"
    first["periodValues"] = [
        {"period": "2025-09", "value": 3600},
        {"period": "2025-10", "value": 3600},
    ]
    other = {**first, "factId": "fact-" + "c" * 16, "fieldRef": "other.metric", "field": "其他指标"}
    document["metrics"].append(other)
    sources[fact_file] = encoded(document)
    plot = json.loads(sources[plot_id])
    plot["source"]["sha256"] = hashlib.sha256(sources[fact_file]).hexdigest()
    plot["columnMeta"] = {"value" if monthly else "total": {"unit": "元"}}
    if monthly:
        plot["source"]["dataPath"] = "metrics[0].periodValues"
        plot["columns"] = ["period", "value"]
        plot["rows"] = [[item["period"], item["value"]] for item in first["periodValues"]]
        plot["rowCount"] = 2
    sources[plot_id] = encoded(plot)
    ref = FactRefV1(
        analysisId=document["analysisId"],
        fileResourceId=fact_file,
        jsonPointer="/metrics/0",
        factKind="metric",
        factKey=first["factId"],
    )
    chart = chart.model_copy(update={"fact_refs": (ref,), "axis_unit": "元"})
    index = index.model_copy(
        update={
            "chart_traces": (chart,),
            "files": tuple(
                file.model_copy(
                    update={
                        "size": len(sources[file.resource_id]),
                        "sha256": hashlib.sha256(sources[file.resource_id]).hexdigest(),
                    }
                )
                for file in index.files
            ),
        }
    )
    return index, markdown, sources


def _verified_arrays(index, markdown, sources, chart_id):
    """静态图自身如实为unknown；语义对齐只消费已核验的图表检查结果。"""
    honest = evaluate_chart_quality(index, markdown, sources)[chart_id]
    assert (honest.status, honest.reason) == ("unknown", "static_image_not_evaluated")
    return {chart_id: ChartQualityCheck(status="verified", reason="standard_render_matches_frozen_inputs")}


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "wrong_metric",
        "unbound",
        "axis",
        "axis_conversion",
        "series_conversion",
        "no_unit",
        "missing",
        "ambiguous_series",
    ],
)
async def test_chart_arrays_do_not_prove_declared_metric_ownership(tmp_path, fault):
    index, markdown, sources = await bound_chart(tmp_path)
    chart = index.chart_traces[0]
    if fault == "wrong_metric":
        ref = chart.fact_refs[0].model_copy(
            update={"json_pointer": "/metrics/1", "fact_key": "fact-" + "c" * 16}
        )
        chart = chart.model_copy(update={"fact_refs": (ref,)})
    elif fault == "unbound":
        chart = chart.model_copy(update={"fact_refs": ()})
    elif fault == "axis":
        chart = chart.model_copy(update={"axis_unit": "%"})
    elif fault == "axis_conversion":
        chart = chart.model_copy(update={"axis_unit": "万元"})
    elif fault == "series_conversion":
        chart = chart.model_copy(update={"series": (ChartSeriesV1(name="收入", unit="万元"),)})
    elif fault == "no_unit":
        chart = chart.model_copy(update={"axis_unit": None})
    elif fault == "ambiguous_series":
        chart = chart.model_copy(
            update={
                "series": (ChartSeriesV1(name="甲", unit="元"), ChartSeriesV1(name="乙", unit="元"))
            }
        )
    index = index.model_copy(update={"chart_traces": (chart,)})
    arrays = _verified_arrays(index, markdown, sources, chart.chart_id)
    if fault == "missing":
        sources.pop(index.fact_files[0].file_resource_id)
    results = evaluate_semantic_alignment(index, sources, chart_checks=arrays)
    check = results[chart.chart_id]
    assert check.status == ("verified" if fault == "none" else "unknown")
    assert check.scope == "registered_fact_projection"
    if fault == "wrong_metric":
        assert check.reasons == ("chart_projection_fact_mismatch",)
    elif fault == "axis_conversion":
        assert check.reasons == ("chart_axis_conversion_unregistered",)
    elif fault == "series_conversion":
        assert check.reasons == ("chart_series_conversion_unregistered",)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("wrong_period", [False, True])
async def test_equal_month_values_cannot_hide_wrong_registered_categories(tmp_path, wrong_period):
    index, markdown, sources = await bound_chart(tmp_path, monthly=True)
    chart = index.chart_traces[0].model_copy(
        update={
            "series": (
                ChartSeriesV1(
                    name="收入",
                    unit="元",
                    categories=("2024-09" if wrong_period else "2025-09", "2025-10"),
                ),
            )
        }
    )
    index = index.model_copy(update={"chart_traces": (chart,)})
    arrays = _verified_arrays(index, markdown, sources, chart.chart_id)
    result = evaluate_semantic_alignment(index, sources, chart_checks=arrays)[chart.chart_id]
    assert result.status == ("unknown" if wrong_period else "verified")
    if wrong_period:
        assert result.reasons == ("chart_series_categories_mismatch",)


@pytest.mark.parametrize(
    "field,unit",
    [("currentTotal", "%"), ("baselineTotal", "%"), ("change", "个百分点"), ("changeRate", "%")],
)
def test_comparison_projection_preserves_level_point_and_relative_rate_roles(field, unit):
    actual, _ = _projection_semantics(
        "comparison", {"unit": "%"}, ("comparisons", 0), ["field", field]
    )
    assert actual == unit


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_unknown_chart_does_not_remove_an_independent_alignment(tmp_path):
    index, markdown, sources = await bound_chart(tmp_path)
    good = index.chart_traces[0]
    bad = good.model_copy(update={"chart_id": "chart_bad", "fact_refs": ()})
    index = index.model_copy(update={"chart_traces": (bad, good)})
    checks = {
        chart.chart_id: ChartQualityCheck(status="verified", reason="registered_arrays_match")
        for chart in index.chart_traces
    }
    results = evaluate_semantic_alignment(index, sources, chart_checks=checks)
    assert results[bad.chart_id].status == "unknown"
    assert results[good.chart_id].status == "verified"


def test_duplicate_frozen_periods_do_not_supply_a_unique_series_identity():
    with pytest.raises(ValueError, match="chart_projection_category_ambiguous"):
        _projection_semantics(
            "metric",
            {
                "unit": "元",
                "periodValues": [
                    {"period": "2025-09", "value": 20},
                    {"period": "2025-09", "value": 20},
                ],
            },
            ("metrics", 0, "periodValues"),
            ["period", "value"],
        )


@pytest.mark.parametrize("columns", [["currentTotal", "baselineTotal"], ["field"], ["customValue"]])
def test_comparison_without_a_unique_registered_value_role_remains_unknown(columns):
    with pytest.raises(ValueError, match="chart_projection_selector_unregistered"):
        _projection_semantics("comparison", {"unit": "%"}, ("comparisons", 0), columns)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_quality_input_hash_binds_chart_metadata_even_if_both_checks_are_unknown(tmp_path):
    from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle

    index, markdown, sources = await bound_chart(tmp_path)
    chart = index.chart_traces[0]
    results = []
    for unit in ("万元", "亿元"):
        current = index.model_copy(
            update={"chart_traces": (chart.model_copy(update={"axis_unit": unit}),)}
        )
        results.append(
            evaluate_quality_bundle(
                current,
                markdown,
                sources,
                authorization_scope_hash="c" * 64,
            )
        )
    assert results[0].semantic_checks[chart.chart_id].status == "unknown"
    assert results[1].semantic_checks[chart.chart_id].status == "unknown"
    assert results[0].input_sha256 != results[1].input_sha256
