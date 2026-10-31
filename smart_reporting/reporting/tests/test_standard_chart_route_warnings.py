"""路由仅暴露本图及全局软告警，并记录真实编译阶段。"""
import itertools
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_standard_chart_routing import setup
from smart_reporting.reporting.workflow.runtime import standard_chart_routing as routing


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("deterministic", [False, True])
async def test_group_routes_keep_warning_ownership_and_measured_compile_time(tmp_path, monkeypatch, deterministic):
    plan, inputs, context = setup(tmp_path, ["line", "bar"])
    warning0 = {"chartId": "0", "code": "first_only", "message": "只属于第一图"}
    warning1 = {"chartId": "1", "code": "second_only", "message": "只属于第二图"}
    global_warning = {"code": "shared", "message": "全局提示"}
    # 每次读表前进25ms；编译耗时只覆盖预检前后相邻两次读表。
    clock = itertools.count(1.0, 0.025)
    monkeypatch.setattr(routing, "perf_counter", lambda: next(clock), raising=False)
    monkeypatch.setattr(routing, "standard_visualization_preflight", lambda *args: SimpleNamespace(
        source="pass", diagnostic=None, warnings=(warning0, warning1, global_warning)))

    class Runner:
        async def run_standard_visualization(self, *args, **kwargs):
            return SimpleNamespace(stage_timings={"draw": 12, "inspect": 3, "total": 15})
        async def run(self, *args, **kwargs):
            raise AssertionError("标准成功不调用自由绘图")

    result = await routing.run_standard_chart_routes(Runner(), context, None, plan, inputs, {}, None, deterministic=deterministic)
    assert result.standard_chart_routes[0]["warnings"] == [warning0, global_warning]
    assert result.standard_chart_routes[1]["warnings"] == [warning1, global_warning]
    assert result.stage_timings["compile"] == 25
    assert result.stage_timings["draw"] == 12
