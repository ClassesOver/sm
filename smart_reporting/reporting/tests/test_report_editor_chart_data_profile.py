"""编辑器推荐用数据概况：只描述已核验作图数据，失败只省略概况。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.standard_charts import chart_data_profile, chart_recommendations
from smart_reporting.reporting.tests.test_report_editor_chart_ai import (
    FakeRunner,
    _make_editor_with_chart,
    _service,
)


def files(*documents):
    return [SimpleNamespace(content=json.dumps(document, ensure_ascii=False).encode()) for document in documents]


def test_profile_counts_categories_measures_units_and_range():
    profile = chart_data_profile(files({
        "columns": ["科室", "收入", "完成率"],
        "rows": [["内科", 320, 0.9], ["外科", -12, 1.1], ["儿科", 150, None]],
        "columnMeta": {"收入": {"unit": "万元"}, "完成率": {"unit": "%", "isPercent": False}},
    }))
    assert profile == {
        "inputCount": 1, "rowCount": 3, "categoryCount": 3, "textFieldCount": 1, "numericFieldCount": 2,
        "unitCount": 2, "hasPeriod": False, "hasNegative": True, "magnitudeRatio": round(320 / 0.9, 2),
    }


@pytest.mark.parametrize("document", [
    {"columns": ["月份", "收入"], "rows": [["2025-01", 1], ["2025-02", 2]], "columnMeta": {}},
    {"columns": ["项目", "收入"], "rows": [["门诊", 1]], "columnMeta": {"收入": {"periods": ["2025-01"]}}},
])
def test_profile_detects_period_labels_or_registered_periods(document):
    assert chart_data_profile(files(document))["hasPeriod"] is True


@pytest.mark.parametrize("raw", [b"not json", b"[]", json.dumps({"columns": "x", "rows": []}).encode()])
def test_malformed_input_yields_no_profile(raw):
    assert chart_data_profile([SimpleNamespace(content=raw)]) is None
    assert chart_data_profile([]) is None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_availability_carries_profile_and_omits_it_when_plot_data_is_tampered(tmp_path: Path):
    fixture = await _make_editor_with_chart(tmp_path)
    service = _service(fixture, FakeRunner(fixture.chart_bytes))
    session = SimpleNamespace(capabilities=None)
    availability = await service.availability(fixture.context, session, "chart_001")
    assert availability["dataProfile"]["inputCount"] == 1
    assert availability["dataProfile"]["numericFieldCount"] >= 1

    # 概况按登记身份缓存；这里清空缓存以覆盖重新读取时核验失败的路径。
    service._profiles.clear()
    thread_id = fixture.context.scope["threadId"]
    plot_path = "reports/revision-1/chart-001.chart-input.json"
    raw = await fixture.editor.workspace.aread_text(thread_id, plot_path)
    await fixture.editor.workspace.awrite_text(thread_id, plot_path, raw + " ", overwrite=True)
    tampered = await service.availability(fixture.context, session, "chart_001")
    assert "dataProfile" not in tampered
    assert tampered["available"] == availability["available"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_profile_is_cached_by_registered_identity_but_failures_are_retried(tmp_path: Path, monkeypatch):
    fixture = await _make_editor_with_chart(tmp_path)
    service = _service(fixture, FakeRunner(fixture.chart_bytes))
    session = SimpleNamespace(capabilities=None)
    reads = []
    original = service._materialize_inputs

    async def counted(*args, **kwargs):
        reads.append(1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "_materialize_inputs", counted)
    first = await service.availability(fixture.context, session, "chart_001")
    second = await service.availability(fixture.context, session, "chart_001")
    assert first["dataProfile"] == second["dataProfile"] and len(reads) == 1

    service._profiles.clear()
    thread_id = fixture.context.scope["threadId"]
    plot_path = "reports/revision-1/chart-001.chart-input.json"
    raw = await fixture.editor.workspace.aread_text(thread_id, plot_path)
    await fixture.editor.workspace.awrite_text(thread_id, plot_path, raw + " ", overwrite=True)
    assert "dataProfile" not in await service.availability(fixture.context, session, "chart_001")
    assert "dataProfile" not in await service.availability(fixture.context, session, "chart_001")
    assert len(reads) == 3 and not service._profiles


def profile(**overrides):
    return {"inputCount": 1, "rowCount": 10, "categoryCount": 10, "textFieldCount": 1, "numericFieldCount": 1,
            "unitCount": 1, "hasPeriod": False, "hasNegative": False, "magnitudeRatio": 2, **overrides}


def test_profile_aggregates_units_and_range_across_all_inputs():
    result = chart_data_profile(files(
        {"columns": ["科室", "收入"], "rows": [["内科", 300], ["外科", 200]], "columnMeta": {"收入": {"unit": "万元"}}},
        {"columns": ["科室", "完成率"], "rows": [["内科", 0.9], ["外科", -0.1]], "columnMeta": {"完成率": {"unit": "%"}}},
    ))
    assert (result["inputCount"], result["categoryCount"], result["unitCount"], result["hasNegative"]) == (2, 2, 2, True)
    assert result["magnitudeRatio"] == 3000.0


def test_recommendations_follow_data_and_hide_unfit_generic_commands():
    rich = chart_recommendations(profile(categoryCount=40, unitCount=2, magnitudeRatio=500, hasPeriod=True))
    assert [item["id"] for item in rich["suggestions"]] == ["paginate", "dual-axis", "break", "mark-extremes"]
    assert rich["suppress"] == [] and "pagination" not in rich["cautions"] and "dual" not in rich["cautions"]
    small = chart_recommendations(profile(categoryCount=4))
    assert small["suggestions"] == [] and small["suppress"] == ["top5"]
    assert chart_recommendations(None) is None


@pytest.mark.parametrize("preset,overrides,text", [
    ("pie", {"hasNegative": True}, "含负值"),
    ("radar", {"numericFieldCount": 2}, "3–8"),
    ("bubble", {"numericFieldCount": 2}, "三个数值字段"),
    ("dual", {"unitCount": 1}, "单位一致"),
    ("vertical-break", {"magnitudeRatio": 3}, "差距不大"),
    ("pagination", {"categoryCount": 8}, "无需分页"),
])
def test_recommendations_explain_unfit_presets(preset, overrides, text):
    assert text in chart_recommendations(profile(**overrides))["cautions"][preset]


def test_fit_presets_carry_no_caution():
    cautions = chart_recommendations(profile(numericFieldCount=3, unitCount=2, textFieldCount=2,
                                             categoryCount=30, magnitudeRatio=100))["cautions"]
    assert not {"pie", "radar", "bubble", "heatmap", "dual", "vertical-break", "pagination"} & cautions.keys()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_availability_returns_server_recommendations(tmp_path: Path):
    fixture = await _make_editor_with_chart(tmp_path)
    service = _service(fixture, FakeRunner(fixture.chart_bytes))
    availability = await service.availability(fixture.context, SimpleNamespace(capabilities=None), "chart_001")
    assert availability["recommendations"] == chart_recommendations(availability["dataProfile"])
