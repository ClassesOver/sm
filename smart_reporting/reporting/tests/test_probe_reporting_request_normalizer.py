from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from scripts import probe_reporting_request_normalizer as probe


class _OfflineRuntime:
    def __init__(self, outputs: dict[str, dict[str, Any]]) -> None:
        self.outputs = outputs

    async def normalize_report_request(self, step_input: Any, _run_context: Any) -> Any:
        return type("Output", (), {"content": self.outputs[step_input.input]})()


def test_request_normalizer_probe_covers_semantic_report_types_and_domains() -> None:
    assert [
        (scenario.prompt, scenario.report_type, scenario.domains)
        for scenario in probe.probe_scenarios()
    ] == [
        (
            "分析下2025年医院整体运营情况",
            "comprehensive",
            ("income", "workload", "budget", "full_cost", "cost_control", "funds"),
        ),
        ("分析2025年医院成本", "topic", ("full_cost",)),
        ("分析2025年收入和工作量关系", "topic", ("income", "workload")),
        (
            "综合分析2025年收入、预算和成本",
            "comprehensive",
            ("income", "budget", "full_cost"),
        ),
    ]


@pytest.mark.anyio
async def test_request_normalizer_probe_rejects_semantic_mismatch(capsys: Any) -> None:
    scenarios = probe.probe_scenarios()
    outputs = {
        scenario.prompt: {
            "reportType": scenario.report_type,
            "domains": list(scenario.domains),
        }
        for scenario in scenarios
    }
    outputs[scenarios[1].prompt] = {
        "reportType": "topic",
        "domains": ["cost_control"],
    }
    runtime = _OfflineRuntime(outputs)

    exit_code = await probe._run(
        argparse.Namespace(task_timeout=5, progress_file=None),
        runtime=runtime,
        model_id="offline-model",
    )

    assert exit_code == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["valid_count"] == 3
    mismatch = summary["runs"][1]
    assert mismatch["expectedDomains"] == ["full_cost"]
    assert mismatch["actualDomains"] == ["cost_control"]


@pytest.mark.anyio
async def test_request_normalizer_probe_accepts_all_semantic_matches(capsys: Any) -> None:
    scenarios = probe.probe_scenarios()
    runtime = _OfflineRuntime(
        {
            scenario.prompt: {
                "reportType": scenario.report_type,
                "domains": list(scenario.domains),
            }
            for scenario in scenarios
        }
    )

    exit_code = await probe._run(
        argparse.Namespace(task_timeout=5, progress_file=None),
        runtime=runtime,
        model_id="offline-model",
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["valid_count"] == 4
