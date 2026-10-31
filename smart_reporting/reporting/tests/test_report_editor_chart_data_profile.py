"""编辑器推荐用数据概况：只描述已核验作图数据，失败只省略概况。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.standard_charts import chart_data_profile
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

    thread_id = fixture.context.scope["threadId"]
    plot_path = "reports/revision-1/chart-001.chart-input.json"
    raw = await fixture.editor.workspace.aread_text(thread_id, plot_path)
    await fixture.editor.workspace.awrite_text(thread_id, plot_path, raw + " ", overwrite=True)
    tampered = await service.availability(fixture.context, session, "chart_001")
    assert "dataProfile" not in tampered
    assert tampered["available"] == availability["available"]
