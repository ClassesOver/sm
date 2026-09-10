from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import probe_reporting_patch_agent as probe


class _OfflineCodeAgent:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.tools: list[object] = []

    async def arun(self, prompt: str, **_kwargs: object) -> object:
        payload = json.loads(prompt)
        tool = self.tools[0]
        if tool.name == "read_file":
            return await tool.entrypoint(path=payload["scriptPath"])
        if self.fail_first:
            self.fail_first = False
            return await tool.entrypoint(source="value = (")
        if "visualizationWorkspace" in payload["facts"] or "chart" in payload["scriptPath"]:
            workspace = payload["facts"].get("visualizationWorkspace", {})
            chart_path = workspace.get("chartPath", "analysis/charts/probe_visualization.png")
            source = (
                "import matplotlib\n"
                'matplotlib.use("Agg")\n'
                "import matplotlib.pyplot as plt\n"
                "fig, ax = plt.subplots()\n"
                'ax.plot([1, 2], marker="o")\n'
                f'fig.savefig("{chart_path}")\n'
                "plt.close(fig)\n"
            )
        else:
            source = "value = 2\nprint(value)\n"
        return await tool.entrypoint(source=source)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(report_phase_thinking_budget=4096)


def test_patch_probe_covers_analysis_and_visualization_create_and_repair() -> None:
    scenarios = probe._scenarios()

    assert [(item.name, item.operation) for item in scenarios] == [
        ("analysis_create", "create"),
        ("analysis_repair", "update"),
        ("visualization_create", "create"),
        ("visualization_repair", "update"),
    ]


@pytest.mark.anyio
async def test_patch_probe_uses_current_complete_source_protocol(monkeypatch) -> None:
    monkeypatch.setattr(probe, "_model", lambda *_args, **_kwargs: SimpleNamespace(id="test"))
    monkeypatch.setattr(
        probe,
        "create_reporting_code_agent",
        lambda **_kwargs: _OfflineCodeAgent(),
    )

    results = [
        await probe._probe_once(_settings(), scenario, thinking=False, task_timeout=5)
        for scenario in probe._scenarios()
    ]

    assert all(result["valid"] for result in results)
    assert all(result["maxLineLength"] < 8 * 1024 for result in results)


@pytest.mark.anyio
async def test_patch_probe_retries_shape_failure_with_fresh_code_agent(monkeypatch) -> None:
    created = 0

    def create_agent(**_kwargs: object) -> _OfflineCodeAgent:
        nonlocal created
        created += 1
        return _OfflineCodeAgent(fail_first=created == 1)

    monkeypatch.setattr(probe, "_model", lambda *_args, **_kwargs: SimpleNamespace(id="test"))
    monkeypatch.setattr(probe, "create_reporting_code_agent", create_agent)

    result = await probe._probe_once(
        _settings(), probe._scenarios()[0], thinking=False, task_timeout=5
    )

    assert result["valid"] is True
    assert result["attempts"] == 2
    assert result["firstAttemptValid"] is False
    assert created == 2
