"""编辑器规划器复用真实结构化执行器的供应商选择与领域校验。"""

import json
import subprocess
import sys
from types import SimpleNamespace
from pydantic import ValidationError

import anyio
import httpx
import pytest
from agno.agent import _response as agno_response
from agno.agent._messages import get_system_message
from agno.run import RunContext
from agno.session import AgentSession

from smart_reporting.report_editor import chart_ai
from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.structured_output.execution import _validate_content


def test_editor_planner_system_message_stays_in_editor_scope():
    service = chart_ai.create_report_editor_chart_ai_service(editor=SimpleNamespace(),
        workspace_registry=SimpleNamespace(), model=ReportingPhaseOpenAIChat(id="offline-fixture",
            api_key="fixture-key", base_url="http://localhost"), runner=SimpleNamespace())
    context = RunContext(run_id="offline-run", session_id="offline-session")
    context.output_schema = chart_ai.ChartEditPlan
    system = get_system_message(service.planner.agent, AgentSession(session_id="offline-session"),
        run_context=context).content
    assert "VisualizationPlanDraft" not in system
    assert "Coding Agent" not in system
    assert "standardChartSchema" not in system


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("model_id,mode", [
    ("deepseek-v4-flash-0731", "json_object"),
    ("qwen3.8-flash", "json_schema"),
])
async def test_editor_planner_wire_uses_one_complete_editor_contract(model_id, mode):
    requests = []
    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "chatcmpl-editor-contract",
            "object": "chat.completion", "created": 1, "model": model_id,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"level": ["L1"],
                    "drawInstruction": "保留冻结数据，调整布局"}, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = chart_ai.create_report_editor_chart_ai_service(editor=SimpleNamespace(),
            workspace_registry=SimpleNamespace(), model=ReportingPhaseOpenAIChat(id=model_id,
                api_key="fixture-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                http_client=client), runner=SimpleNamespace())
        with anyio.fail_after(10):
            plan = await service._plan(SimpleNamespace(scope={"userId": "offline-owner"}),
                "chart_contract", chart_ai.ChartAIEditRequest(instruction="调整布局"), [], [])
    assert plan.level == ("L1",)
    assert len(requests) == 1
    body = requests[0]
    assert body["response_format"]["type"] == mode
    user = next(message["content"] for message in body["messages"] if message["role"] == "user")
    payload = json.loads(user.split("<chart_edit_request>\n", 1)[1].split("\n</chart_edit_request>", 1)[0])
    assert "standardChartSchema" not in payload
    assert payload["chartId"] == "chart_contract"
    assert payload["standardChartCapabilities"]
    capabilities = payload["standardChartCapabilities"]
    assert capabilities["familyAxesOverrides"] == ["leftDisplayUnit"]
    assert capabilities["families"]["sankey"]["encodingFields"] == ["xField", "yField", "valueField"]
    system = "\n".join(message["content"] for message in body["messages"]
        if message["role"] in {"system", "developer"})
    contract = system if mode == "json_object" else json.dumps(body["response_format"]["json_schema"]["schema"])
    for field in ("standardComposition", "standardRadar", "standardFunnel", "standardSankey"):
        assert f'"{field}"' in contract
    assert "ChartEditPlan" in system
    assert "VisualizationPlanDraft" not in system
    assert "Coding Agent" not in system
    assert "standardChartSchema" not in system


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_custom_editor_planner_keeps_full_standard_schema():
    captured = []
    async def planner(request):
        captured.append(request)
        return chart_ai.ChartEditPlan(level=("L1",), drawInstruction="调整布局")
    service = chart_ai.ChartAIEditService(editor=SimpleNamespace(), workspace_registry=SimpleNamespace(),
        planner=planner, runner=SimpleNamespace())
    plan = await service._plan(SimpleNamespace(scope={"userId": "offline-owner"}),
        "chart_custom", chart_ai.ChartAIEditRequest(instruction="调整布局"), [], [])
    assert plan.level == ("L1",)
    assert len(captured) == 1
    assert captured[0]["chartId"] == "chart_custom"
    schema = captured[0]["standardChartSchema"]
    for field in ("standardComposition", "standardRadar", "standardFunnel", "standardSankey"):
        assert field in schema["properties"]
    assert schema["$defs"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_planner_exposes_current_frozen_bindings_separately_from_l2_catalog():
    captured = []
    async def planner(request):
        captured.append(request)
        return chart_ai.ChartEditPlan(level=("L1",), drawInstruction="雷达呈现")
    service = chart_ai.ChartAIEditService(editor=SimpleNamespace(), workspace_registry=SimpleNamespace(),
        planner=planner, runner=SimpleNamespace())
    document = {"schema": "chart-input/v1", "columns": ["period", "a", "b", "c"],
        "rows": [["甲", 2, 4, 6]], "role": "measure",
        "source": {"analysisId": "analysis_001", "path": "facts/current.json",
                   "dataPath": "metrics[0]"}}
    await service._plan(SimpleNamespace(scope={"userId": "owner"}), "chart_001",
        chart_ai.ChartAIEditRequest(instruction="换成雷达图"), [], [],
        plot_files=[SimpleNamespace(content=json.dumps(document).encode())])
    assert captured[0]["currentBindings"] == [{"analysisId": "analysis_001",
        "factPath": "facts/current.json", "dataPath": "metrics[0]",
        "fields": ["period", "a", "b", "c"], "role": "measure"}]
    assert captured[0]["registeredBindings"] == []


def test_reporting_agent_cold_import_does_not_cycle_through_editor_planner():
    imported = subprocess.run([sys.executable, "-c", "import smart_reporting.reporting.agent"],
        capture_output=True, text=True, timeout=60)
    assert imported.returncode == 0, imported.stderr


@pytest.mark.parametrize("raw,expected_instruction", [
    ('{"level":["L1"],"draw_instruction":"调整布局","sourcePath":"foreign.png"}', None),
    ('{"level":["L1"]}\n{"draw_instruction":"保留冻结数据","sourcePath":"foreign.png"}', None),
    ('{"level":["L1"],"draw_instruction":"完整首个对象"}\n'
     '{"level":["L2"],"draw_instruction":"完整第二个对象"}', "完整首个对象"),
], ids=["reject-extra", "reject-merged-fragments", "keep-complete-object"])
def test_editor_planner_parser_preserves_strict_complete_object_boundary(raw, expected_instruction):
    service = chart_ai.create_report_editor_chart_ai_service(editor=SimpleNamespace(),
        workspace_registry=SimpleNamespace(), model=ReportingPhaseOpenAIChat(id="offline-fixture",
            api_key="fixture-key", base_url="http://localhost"), runner=SimpleNamespace())
    output = SimpleNamespace(content=raw)
    context = RunContext(run_id="offline-run", session_id="offline-session")
    context.output_schema = chart_ai.ChartEditPlan
    agno_response.convert_response_to_structured_format(service.planner.agent, output, context)
    if expected_instruction is None:
        # Agno须保留原文本，让公共执行器拒绝；不得先丢extra或拼片段成合法实例。
        assert output.content == raw
        with pytest.raises(ReportingError) as failed:
            _validate_content(output.content, chart_ai.ChartEditPlan)
        assert failed.value.code == "report_phase_output_invalid"
    else:
        plan = _validate_content(output.content, chart_ai.ChartEditPlan)
        assert plan.level == ("L1",)
        assert plan.draw_instruction == expected_instruction


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("model_id,mode,valid", [
    ("deepseek-v4-flash-0731", "json_object", True),
    ("deepseek-v4-flash-0731", "json_object", False),
    ("deepseek-v4-flash-0731", "json_object", "recover"),
    ("qwen3.8-flash", "json_schema", True),
])
async def test_editor_planner_uses_shared_provider_policy_and_bounded_correction(model_id, mode, valid):
    requests = []
    valid_candidate = {"level": ["L1"], "drawInstruction": "保留冻结数据，调整布局",
        "standard": {"standardForm": "bar"}}
    candidate = valid_candidate if valid is True else {**valid_candidate, "standardPlotSummaryNote": "不允许的额外字段"}
    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("response_format", {}).get("type") != mode:
            return httpx.Response(400, json={"error": {"message": "This response_format type is unavailable now",
                "type": "invalid_request_error", "code": "invalid_parameter"}})
        return httpx.Response(200, json={"id": "chatcmpl-editor-fixture", "object": "chat.completion",
            "created": 1, "model": model_id, "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(
                valid_candidate if valid == "recover" and len(requests) == 2 else candidate,
                ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = ReportingPhaseOpenAIChat(id=model_id, api_key="fixture-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", http_client=client)
        service = chart_ai.create_report_editor_chart_ai_service(editor=SimpleNamespace(),
            workspace_registry=SimpleNamespace(), model=model, runner=SimpleNamespace())
        context = SimpleNamespace(scope={"userId": "trusted-owner-only"})
        request = chart_ai.ChartAIEditRequest(instruction="调整布局")
        if valid:
            plan = await service._plan(context, "chart_001", request, [], [])
            assert isinstance(plan, chart_ai.ChartEditPlan)
            assert plan.level == ("L1",)
            assert plan.standard.standard_form == "bar"
        else:
            with pytest.raises(ReportingError) as failed:
                await service._plan(context, "chart_001", request, [], [])
            assert failed.value.code == "report_phase_output_invalid"
            assert failed.value.__cause__ is not failed.value
            assert failed.value.__cause__ is not None
        assert len(requests) == (1 if valid is True else 2)
        if valid == "recover":
            correction = json.dumps(requests[1]["messages"], ensure_ascii=False)
            assert "standardPlotSummaryNote" in correction
            assert "extra_forbidden" in correction
        assert requests[0]["response_format"]["type"] == mode
        assert "trusted-owner-only" not in json.dumps(requests[0]["messages"])
        if mode == "json_schema":
            assert requests[0]["response_format"]["json_schema"]["schema"]["type"] == "object"


@pytest.mark.parametrize("cycle_length", [1, 2])
def test_chart_job_observation_handles_cyclic_error_causes(cycle_length):
    errors = [ReportingError("invalid_plan", "规划无效") for _ in range(cycle_length)]
    for position, error in enumerate(errors):
        error.__cause__ = errors[(position + 1) % cycle_length]
    job = chart_ai._ChartEditJob(report_id="report", revision=1,
        chart_id="chart", user_id="user", task=None, started_at=0)
    job.capture_execution(errors[0])
    assert job.execution_rounds == []


@pytest.mark.parametrize("standard", [
    {"standardForm": "funnel", "standardAxes": {"zeroBaseline": True}},
    {"standardForm": "sankey", "standardEncoding": {
        "xField": "source", "yField": "target", "valueField": "value", "xCaption": "起点"}},
])
def test_editor_planner_checks_family_parameter_policy_before_drawing(standard):
    with pytest.raises(ValidationError):
        chart_ai.ChartEditPlan(level=("L1",), drawInstruction="保留冻结输入", standard=standard)


def test_editor_planner_preserves_omitted_family_groups_for_next_edit():
    from smart_reporting.report_editor.standard_charts import inherit_standard

    previous = {"standardForm": "sankey", "standardEncoding": {
        "xField": "source", "yField": "target", "valueField": "value"}}
    plan = chart_ai.ChartEditPlan(level=("L1",), drawInstruction="调整背景色", standard={
        "standardForm": "sankey", "standardStyle": {"background": "#eeeeee"}})
    effective = inherit_standard(previous, plan.standard)
    assert effective.standard_encoding.x_field == "source"
    assert effective.standard_style.background == "#eeeeee"
