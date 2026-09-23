"""离线状态机探针：visualization 修复轮"仅 run_script"交付状态的可达路径。

回放背景：visualization candidate（revision-3）修复轮第 4 次模型请求只声明了
run_script。本文件用真实 toolkit/delivery 生产代码加脚本化工具结果验证：
该状态在 write -> run(失败) -> edit -> run(成功、预检 pending) 的 4 请求预算内，
只有"第 3 次响应为 edit_script + run_script 同批多调用"这一条路径可达。
"""

from types import SimpleNamespace

import pytest
from agno.tools.function import FunctionCall

from smart_reporting.reporting.code_agent.context import (
    ExecutionReceipt,
    OutputValidationState,
    ReportingCodingTaskBinding,
)
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.code_mode import ScriptProcessResult
from smart_reporting.reporting.tests.test_reporting_code_edit import edit_patch
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    VISUAL_SOURCE,
    ToolkitRuntime,
    _code_responses_model,
    _failed_cell,
    _visualization_task_context,
    workspace,  # noqa: F401
)

REPAIR_NEXT_TOOLS = ["read_script", "edit_script", "run_script"]


async def _offline_preflight(_receipt: ExecutionReceipt):
    raise RuntimeError("offline preflight")


def _visual_runtime(runtime: ToolkitRuntime) -> None:
    async def execute_script_process(_session_id, runtime_workspace, _path, **_kwargs):
        if runtime.next_cell is not None:
            cell, runtime.next_cell = runtime.next_cell, None
            return ScriptProcessResult(cell, 1)
        await runtime_workspace.awrite_text(
            "task-1", "charts/chart.png", "image-v2", overwrite=True
        )
        return ScriptProcessResult(
            SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0
        )

    runtime.execute_script_process = execute_script_process


async def _fresh_visualization_toolkit(
    workspace,  # noqa: F811
    runtime: ToolkitRuntime,
) -> tuple[ReportingCodingTaskBinding, ReportingCodeModeToolkit]:
    context = _visualization_task_context(workspace)
    binding = ReportingCodingTaskBinding(context, workspace)
    toolkit = ReportingCodeModeToolkit(
        binding,
        runtime,
        ReportingLspProcessManager(),
        output_preflight=_offline_preflight,
    )
    await toolkit.refresh_delivery_state()
    return binding, toolkit


async def _write_then_failed_run(
    toolkit: ReportingCodeModeToolkit, runtime: ToolkitRuntime
) -> tuple[dict[str, object], str]:
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    write = FunctionCall(
        function=functions["write_script"],
        call_id="call-write",
        arguments={"source": VISUAL_SOURCE},
    )
    assert await write.aexecute()
    assert write.result["ok"] is True
    runtime.next_cell = _failed_cell("FileNotFoundError: charts/chart.png")
    failed_run = FunctionCall(
        function=functions["run_script"], call_id="call-run-failed", arguments={}
    )
    assert await failed_run.aexecute()
    assert failed_run.result["ok"] is False
    return functions, write.result["savedSource"] or VISUAL_SOURCE


async def _apply_edit(functions, saved_source: str, old: str, new: str, call_id: str):
    edit = FunctionCall(
        function=functions["edit_script"],
        call_id=call_id,
        arguments={"patch": edit_patch(saved_source, old, new)},
    )
    assert await edit.aexecute()
    assert edit.result["ok"] is True
    return edit


async def _run(functions, call_id: str):
    rerun = FunctionCall(function=functions["run_script"], call_id=call_id, arguments={})
    assert await rerun.aexecute()
    return rerun


@pytest.mark.anyio
async def test_batched_edit_and_run_reaches_run_script_only_state(workspace):  # noqa: F811
    """命题 1：write 成功 -> run 失败 -> 同批 edit 成功 + run 成功（预检 pending）后，
    delivery_state()["nextTools"] 恰好为 ["run_script"]。"""
    runtime = ToolkitRuntime()
    _visual_runtime(runtime)
    binding, toolkit = await _fresh_visualization_toolkit(workspace, runtime)
    assert toolkit.delivery_state()["nextTools"] == ["write_script"]

    functions, saved_source = await _write_then_failed_run(toolkit, runtime)
    assert toolkit.delivery_state()["nextTools"] == REPAIR_NEXT_TOOLS

    # 第 3 次模型响应为 edit_script + run_script 同批多调用：
    # 宿主整体校验后按 provider 返回顺序执行。
    await _apply_edit(functions, saved_source, "image", "image-v2", "call-edit")
    rerun = await _run(functions, "call-run-repaired")

    # 脚本本体执行成功并签发执行回执；预检未获得可用结论（unavailable 形态）。
    assert binding.execution_receipt is not None
    assert rerun.result["ok"] is False
    state = toolkit.delivery_state()
    assert state["execution"]["valid"] is True
    assert state["outputValidation"] == "unavailable"
    assert state["nextTools"] == ["run_script"]

    # checking 中间态走同一 pending 分支，结论相同。
    binding.output_validation = OutputValidationState.for_run(
        "checking", binding.execution_receipt.run_id
    )
    await toolkit.refresh_delivery_state()
    assert toolkit.delivery_state()["outputValidation"] == "checking"
    assert toolkit.delivery_state()["nextTools"] == ["run_script"]


@pytest.mark.anyio
async def test_unbatched_edit_cannot_reach_run_script_only_state(workspace):  # noqa: F811
    """命题 2：edit 独占第 3 次响应（未同批 run）时，第 4 请求前 nextTools
    必为三件套；仅 run_script 状态在 4 请求预算内只有多调用批次一条路径可达。"""
    runtime = ToolkitRuntime()
    _visual_runtime(runtime)
    _, toolkit = await _fresh_visualization_toolkit(workspace, runtime)
    trajectory = [toolkit.delivery_state()["nextTools"]]

    functions, saved_source = await _write_then_failed_run(toolkit, runtime)
    trajectory.append(toolkit.delivery_state()["nextTools"])
    await _apply_edit(functions, saved_source, "image", "image-v2", "call-edit")
    state = toolkit.delivery_state()
    trajectory.append(state["nextTools"])

    # edit_script 成功清除执行回执；第 4 次模型请求前只能声明三件套。
    assert state["execution"] is None
    assert state["nextTools"] == REPAIR_NEXT_TOOLS
    assert trajectory == [["write_script"], REPAIR_NEXT_TOOLS, REPAIR_NEXT_TOOLS]
    assert ["run_script"] not in trajectory

    # 要进入仅 run_script 状态必须再执行一次 run_script（第 5 次工具执行），
    # 其状态只能在第 4 次响应内产生，无法在第 4 次请求前被声明。
    await _run(functions, "call-run-repaired")
    assert toolkit.delivery_state()["nextTools"] == ["run_script"]


@pytest.mark.anyio
async def test_run_script_only_state_declares_only_run_script(workspace):  # noqa: F811
    """命题 3：仅 run_script 状态下 get_request_params 的工具声明只含 run_script，
    且为 function 类型；对照三件套状态的声明。"""
    runtime = ToolkitRuntime()
    _visual_runtime(runtime)
    _, toolkit = await _fresh_visualization_toolkit(workspace, runtime)
    functions, saved_source = await _write_then_failed_run(toolkit, runtime)
    await _apply_edit(functions, saved_source, "image", "image-v2", "call-edit")
    await _run(functions, "call-run-repaired")
    assert toolkit.delivery_state()["nextTools"] == ["run_script"]

    model = _code_responses_model()
    model.configure_code_run(
        toolkit.tool_functions,
        max_model_requests=4,
        delivery_state_reader=toolkit.delivery_state,
    )
    params = model.get_request_params(messages=[], tools=toolkit.tool_functions)
    assert [tool["name"] for tool in params["tools"]] == ["run_script"]
    assert params["tools"][0]["type"] == "function"
    assert model._code_declared_tools == {"run_script": "function"}

    # 对照：再次 edit 后未同批 run，声明退化为三件套（write_script 因脚本已存在被隐藏）。
    saved_source = await toolkit.workspace.read_limited_regular_file(
        toolkit.context.task_id,
        toolkit.context.script_path,
        max_bytes=toolkit.context.max_source_bytes,
    )
    await _apply_edit(
        functions, saved_source.decode("utf-8"), "image-v2", "image-v3", "call-edit-2"
    )
    assert toolkit.delivery_state()["nextTools"] == REPAIR_NEXT_TOOLS
    params = model.get_request_params(messages=[], tools=toolkit.tool_functions)
    assert {tool["name"] for tool in params["tools"]} == set(REPAIR_NEXT_TOOLS)
