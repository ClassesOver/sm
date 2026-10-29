"""标准图成功的业务软告警必须随最终生产计划保留，不触发模型重绘。"""

from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    VisualizationSectionWorkflow,
)

from .test_reporting_fixed_phase_workflows import (
    _context,
    _execution_receipt,
    _inspection,
    _visualization_payload,
    _visualization_plan,
)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("persist_fails", [False, True])
async def test_successful_family_soft_warning_survives_workflow_without_replanning(persist_fails):
    plan = _visualization_plan().model_copy(update={"warnings": ("已有来源限制",)})
    code_result = CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64),
        execution_receipt=_execution_receipt("charts/charts.py", 1, "b" * 64, ("charts/chart.png",)),
        visual_inspection_receipts=(_inspection(),),
        standard_chart_routes=({"chartId": "chart_001", "route": "standard", "warnings": [
            {"code": "standard_funnel_nonmonotonic", "message": "阶段原值非单调，不据此断言转化损耗。"},
        ]},),
    )
    submitted = []

    async def submit(actual, _inspections, _context):
        submitted.append(actual)
        return {"status": "accepted"}

    generate = AsyncMock(return_value=plan)
    persist = AsyncMock(side_effect=RuntimeError("告警存储不可用") if persist_fails else None)
    workflow = VisualizationSectionWorkflow(
        generate_plan=generate, run_code=AsyncMock(return_value=code_result), submit=submit,
        record_warnings=persist,
    )
    result = await workflow.run(_visualization_payload(), _context())
    assert result.status == "accepted"
    assert result.plan.warnings == ("已有来源限制", "chart_001：阶段原值非单调，不据此断言转化损耗。")
    # 不能在提交前改动计划缓存身份，丢失完整plotDataFiles冻结来源。
    assert submitted[0] == plan
    assert generate.await_count == 1
    persist.assert_awaited_once_with(({
        "code": "standard_funnel_nonmonotonic",
        "message": "阶段原值非单调，不据此断言转化损耗。",
        "chartId": "chart_001",
    },), _context())
