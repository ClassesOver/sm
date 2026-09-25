from __future__ import annotations

import asyncio
import json
from ast import literal_eval

import pytest
from agno.models.message import Message
from agno.tools.function import Function, FunctionCall
from loguru import logger
from openai.types.responses import Response

from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.code_agent.toolkit import _stop_after_success
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    _batch_response,
    _custom_response,
    _function_response,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("outcome", ["success", "rejected", "exception", "submitted", "limit"])
async def test_batch_preserves_order_stopping_and_total_budget(asynchronous, outcome):
    executed = []

    def first():
        executed.append("first")
        if outcome == "exception":
            raise ValueError("invalid draft")
        return {"ok": outcome != "rejected"}

    def second():
        assert executed == ["first"]
        executed.append("second")
        return {"ok": True}

    def third():
        assert executed == ["first", "second"]
        executed.append("third")
        return {"ok": True}

    async def first_async():
        # 让出执行权，证明后续工具会等待第一个完成。
        await asyncio.sleep(0)
        return first()

    async def second_async():
        return second()

    async def third_async():
        return third()

    entrypoints = (first_async, second_async, third_async) if asynchronous else (first, second, third)
    functions = [
        Function(
            name=f"step_{index}", entrypoint=entrypoint,
            post_hook=_stop_after_success if index == 0 and outcome == "submitted" else None,
        )
        for index, entrypoint in enumerate(entrypoints)
    ]
    for function in functions:
        function.process_entrypoint()
    calls = [
        FunctionCall(function=function, call_id=f"call-{index}", arguments={})
        for index, function in enumerate(functions)
    ]
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    results: list[Message] = []
    kwargs = {
        "function_calls": calls,
        "function_call_results": results,
        "current_function_call_count": 1,
        "function_call_limit": 2 if outcome == "limit" else 4,
    }
    if asynchronous:
        events = [event async for event in model.arun_function_calls(**kwargs)]
    else:
        events = list(model.run_function_calls(**kwargs))

    assert events
    assert executed == (["first", "second", "third"] if outcome == "success" else ["first"])
    assert [result.tool_call_id for result in results] == ["call-0", "call-1", "call-2"]
    if outcome == "success":
        assert all(not result.tool_call_error for result in results)
    else:
        for result in results[2 if outcome == "limit" else 1:]:
            assert result.tool_call_error is True
            payload = json.loads(result.content)
            if outcome == "limit":
                # 限额边界由协议层统一换成编码回执（Agno 裸 tool_call_error 无
                # code，模型与指标需要明确的终止原因）；首个超限调用与批内后续
                # 调用同码，都是本轮未执行。
                assert payload["status"] == "rejected"
                assert payload["code"] == "report_code_tool_call_limit"
            else:
                assert payload["status"] == "skipped"
        if outcome == "submitted":
            assert results[0].stop_after_tool_call is True


def test_entire_batch_is_validated_before_tools_can_execute():
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name="write_script"), Function(name="run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    model.get_request_params(messages=[], tools=tools)
    response = _batch_response(
        _custom_response("write_script", SOURCE, 1),
        _function_response(2, "outside", {}),
    )

    with pytest.raises(ReportingError, match="未声明或类型不匹配"):
        model._parse_provider_response(response)


def test_wire_shaped_freedom_call_is_recovered_and_executed():
    """candidate-32：任务集内 FREEFORM 工具以 function 形态返回时还原为
    custom 形态继续既有链路（stage 内正常执行），不计协议违规。"""
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name="write_script"), Function(name="run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    model.get_request_params(messages=[], tools=tools)
    response = _batch_response(
        _function_response(1, "write_script", {"source": "# Python\nprint(1)\n"}),
    )

    parsed = model._parse_provider_response(response)

    assert [call["function"]["name"] for call in parsed.tool_calls] == ["write_script"]
    assert model._code_budget.wire_shape_recoveries == 1
    assert model._code_budget.protocol_violations == 0
    assert model._code_stage_mismatch_names == frozenset()


def test_wire_shape_recovery_keeps_following_function_calls_aligned():
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name="write_script"), Function(name="run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    model.get_request_params(messages=[], tools=tools)
    response = _batch_response(
        _function_response(1, "write_script", {"source": "# Python\nprint(1)\n"}),
        _function_response(2, "run_script", {}),
    )

    parsed = model._parse_provider_response(response)

    # 还原的调用仍占父类 function 序列一个位置；后续 run_script 不得被错位替换。
    assert [(call["function"]["name"], call["call_id"]) for call in parsed.tool_calls] == [
        ("write_script", "call-1"),
        ("run_script", "call-2"),
    ]


def test_wire_shaped_freedom_call_stage_hidden_gets_soft_rejection():
    """还原后的调用仍受交付阶段白名单约束：stage 外走软拒绝回执，不执行。"""
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name="write_script"), Function(name="run_script")]
    model.configure_code_run(
        tools,
        max_model_requests=2,
        delivery_state_reader=lambda: {
            "marker": "REPORTING_CODE_DELIVERY_STATE",
            "taskKind": "visualization",
            "script": {"path": "analysis/a.py", "sha256": "a" * 64},
            "execution": None,
            "nextTools": ["read_script", "edit_script", "run_script"],
        },
    )
    model.get_request_params(messages=[], tools=tools)
    response = _batch_response(
        _function_response(1, "write_script", {"source": "# Python\nprint(1)\n"}),
    )

    parsed = model._parse_provider_response(response)

    assert [call["function"]["name"] for call in parsed.tool_calls] == ["write_script"]
    assert model._code_stage_mismatch_names == frozenset({"write_script"})
    assert model._code_budget.wire_shape_recoveries == 1
    assert model._code_budget.stage_mismatch_rejections == 1
    assert model._code_budget.protocol_violations == 0


def test_wire_shaped_bare_text_arguments_are_recovered():
    """candidate-38：grammar 退化更深时模型把 free-form 原文直接作为 function
    参数（非 JSON 对象）；按输入前缀特征接受原文并还原为 custom 形态。"""
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name="edit_script"), Function(name="run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    model.get_request_params(messages=[], tools=tools)
    raw_patch = "*** Begin Edit\n*** SHA256: " + "a" * 64 + "\nrandom\n*** End Edit\n"
    response = Response.model_validate({
        "id": "resp-1",
        "created_at": 0,
        "model": "test-model",
        "object": "response",
        "status": "completed",
        "tools": [],
        "output": [
            {
                "id": "item-1",
                "call_id": "call-1",
                "name": "edit_script",
                "arguments": raw_patch,
                "type": "function_call",
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
    })

    parsed = model._parse_provider_response(response)

    assert [call["function"]["name"] for call in parsed.tool_calls] == ["edit_script"]
    assert model._code_budget.wire_shape_recoveries == 1
    assert model._code_budget.protocol_violations == 0


def test_wire_shape_recovery_limit_exhausted_stays_fatal():
    """恢复计数超限后保持 fail-closed，仍按协议异常终止。"""
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name="write_script"), Function(name="run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    model.get_request_params(messages=[], tools=tools)
    model._code_budget.wire_shape_recoveries = 3
    response = _batch_response(
        _function_response(1, "write_script", {"source": "# Python\nprint(1)\n"}),
    )

    with pytest.raises(ReportingError, match="未声明或类型不匹配"):
        model._parse_provider_response(response)
    assert model._code_budget.protocol_violations == 1


def test_mixed_custom_function_custom_response_preserves_provider_order():
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name="write_script"), Function(name="run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    model.get_request_params(messages=[], tools=tools)
    response = _batch_response(
        _custom_response("write_script", "# Python\nprint(1)\n", 1),
        _function_response(2, "run_script", {}),
        _custom_response("write_script", "# Python\nprint(2)\n", 3),
    )

    parsed = model._parse_provider_response(response)

    assert [call["function"]["name"] for call in parsed.tool_calls] == [
        "write_script", "run_script", "write_script",
    ]
    assert [call["call_id"] for call in parsed.tool_calls] == [
        "call-1", "call-2", "call-3",
    ]


@pytest.mark.anyio
async def test_mixed_batch_failure_executes_once_and_replays_skipped_ids():
    executed: list[str] = []

    async def write_script(**_kwargs):
        executed.append("write_script")
        return {"ok": False, "code": "rejected"}

    async def run_script(**_kwargs):
        executed.append("run_script")
        return {"ok": True}

    write = Function(name="write_script", entrypoint=write_script)
    run = Function(name="run_script", entrypoint=run_script)
    for function in (write, run):
        function.process_entrypoint()
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    model.configure_code_run((write, run), max_model_requests=2)
    model.get_request_params(messages=[], tools=(write, run))
    parsed = model._parse_provider_response(_batch_response(
        _custom_response("write_script", "# Python\nprint(1)\n", 1),
        _function_response(2, "run_script", {}),
        _custom_response("write_script", "# Python\nprint(2)\n", 3),
    ))
    assert [
        item.get("provider_data", {}).get("reporting_wire_type")
        for item in parsed.tool_calls
    ] == ["custom", None, "custom"]
    calls = []
    for item in parsed.tool_calls:
        name = item["function"]["name"]
        arguments = json.loads(item["function"]["arguments"])
        calls.append(FunctionCall(
            function=write if name == "write_script" else run,
            call_id=item["call_id"],
            arguments=arguments,
        ))
    results: list[Message] = []

    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=calls,
            function_call_results=results,
            current_function_call_count=0,
            function_call_limit=3,
        )
    ]

    assert executed == ["write_script"]
    assert [result.tool_call_id for result in results] == [
        "call-1", "call-2", "call-3",
    ]
    assert all(json.loads(result.content)["status"] == "skipped" for result in results[1:])


@pytest.mark.anyio
async def test_async_tool_execution_emits_safe_progress_and_path() -> None:
    async def write_script() -> dict[str, object]:
        return {
            "ok": True,
            "path": "evidence/analysis_001/supplement.py",
            "content": "不得输出的源码",
        }

    function = Function(name="write_script", entrypoint=write_script)
    function.process_entrypoint()
    call = FunctionCall(function=function, call_id="call-1", arguments={})
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    results: list[Message] = []
    records: list[dict[str, object]] = []
    sink_id = logger.add(
        lambda message: records.append(dict(message.record["extra"])),
        filter=lambda record: record["extra"].get("reporting_progress") == "code_tool",
    )
    try:
        _ = [
            event
            async for event in model.arun_function_calls(
                function_calls=[call],
                function_call_results=results,
                current_function_call_count=0,
                function_call_limit=2,
            )
        ]
    finally:
        logger.remove(sink_id)

    assert [
        {
            "reporting_progress": item["reporting_progress"],
            "tool_name": item["tool_name"],
            "status": item["status"],
            **({"path": item["path"]} if "path" in item else {}),
        }
        for item in records
    ] == [
        {
            "reporting_progress": "code_tool",
            "tool_name": "write_script",
            "status": "started",
        },
        {
            "reporting_progress": "code_tool",
            "tool_name": "write_script",
            "status": "completed",
            "path": "evidence/analysis_001/supplement.py",
        },
    ]
    assert "不得输出" not in json.dumps(records, ensure_ascii=False)


@pytest.mark.anyio
async def test_last_three_tool_slots_are_reserved_for_formal_delivery() -> None:
    executed: list[str] = []

    def tool(name: str) -> Function:
        async def entrypoint(**_kwargs):
            executed.append(name)
            return {"ok": True}

        return Function(
            name=name,
            entrypoint=entrypoint,
        )

    functions = {
        name: tool(name)
        for name in ("run", "write_script", "run_script", "submit_script")
    }
    for function in functions.values():
        function.process_entrypoint()
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    model.configure_code_run(
        tuple(functions.values()), max_model_requests=4, delivery_reserve=3
    )
    rejected_results: list[Message] = []

    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(
                    function=functions["run"],
                    call_id=f"probe-{index}",
                    arguments={"code": "1 + 1"},
                )
                for index in range(4)
            ],
            function_call_results=rejected_results,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]

    assert executed == []
    assert json.loads(rejected_results[0].content)["code"] == (
        "report_code_delivery_budget_reserved"
    )
    assert all(
        json.loads(result.content)["code"] == "report_code_batch_stopped"
        for result in rejected_results[1:]
    )
    assert model._limit_charge_for(rejected_results, None) == 0
    executed_failure = Message(
        role="tool",
        tool_call_error=False,
        content=json.dumps(
            {
                "ok": False,
                "status": "rejected",
                "code": "report_code_delivery_budget_reserved",
            }
        ),
    )
    assert model._limit_charge_for([executed_failure], None) == 1

    delivery_results: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(function=functions[name], call_id=name, arguments={})
                for name in ("write_script", "run_script", "submit_script")
            ],
            function_call_results=delivery_results,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]

    assert executed == ["write_script", "run_script", "submit_script"]


@pytest.mark.anyio
async def test_reserved_budget_allows_and_recommends_required_source_read() -> None:
    executed: list[str] = []

    def tool(name: str) -> Function:
        async def entrypoint(**_kwargs):
            executed.append(name)
            return {"ok": True}

        function = Function(name=name, entrypoint=entrypoint)
        function.process_entrypoint()
        return function

    functions = {
        name: tool(name)
        for name in ("run", "read_script", "edit_script", "run_script")
    }
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    model.configure_code_run(
        tuple(functions.values()),
        max_model_requests=4,
        delivery_reserve=3,
        delivery_state_reader=lambda: {
            "nextTools": ["read_script", "edit_script", "run_script"]
        },
    )
    rejected: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(
                    function=functions["run"],
                    call_id="exploration",
                    arguments={},
                )
            ],
            function_call_results=rejected,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]
    rejected_payload = json.loads(rejected[0].content)
    assert rejected_payload["details"]["requiredNextTools"] == [
        "edit_script",
        "read_script",
        "run_script",
    ]

    results: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(
                    function=functions["read_script"],
                    call_id="required-read",
                    arguments={},
                )
            ],
            function_call_results=results,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]

    assert executed == ["read_script"]
    assert literal_eval(results[0].content)["ok"] is True


@pytest.mark.anyio
async def test_visual_delivery_reserve_includes_each_image_review() -> None:
    executed: list[str] = []

    def tool(name: str) -> Function:
        async def entrypoint(**_kwargs):
            executed.append(name)
            return {"ok": True}

        function = Function(name=name, entrypoint=entrypoint)
        function.process_entrypoint()
        return function

    functions = {
        name: tool(name)
        for name in (
            "run",
            "write_script",
            "run_script",
            "view_image",
            "submit_script",
        )
    }
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    model.configure_code_run(
        tuple(functions.values()), max_model_requests=6, delivery_reserve=5
    )
    results: list[Message] = []

    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(function=functions[name], call_id=name, arguments={})
                for name in (
                    "write_script",
                    "run_script",
                    "view_image",
                    "view_image",
                    "submit_script",
                )
            ],
            function_call_results=results,
            current_function_call_count=15,
            function_call_limit=20,
        )
    ]

    assert executed == [
        "write_script",
        "run_script",
        "view_image",
        "view_image",
        "submit_script",
    ]


@pytest.mark.anyio
async def test_repeated_delivery_reserve_rejection_eventually_consumes_budget() -> None:
    function = Function(name="run", entrypoint=lambda: {"ok": True})
    function.process_entrypoint()
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    model.configure_code_run((function,), max_model_requests=4, delivery_reserve=3)

    first: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[FunctionCall(function=function, call_id="first", arguments={})],
            function_call_results=first,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]
    second: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[FunctionCall(function=function, call_id="second", arguments={})],
            function_call_results=second,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]

    assert model._limit_charge_for(first, None) == 0
    assert model._limit_charge_for(second, None) == 1
    assert json.loads(second[0].content)["details"]["escalated"] is True


@pytest.mark.anyio
async def test_successful_delivery_call_resets_reserve_rejection_escalation() -> None:
    """一次成功的交付类调用之后，升级计数必须归零，不能让此前的拒绝历史
    带到下一次预留区拒绝上。"""
    run = Function(name="run", entrypoint=lambda: {"ok": True})
    run.process_entrypoint()
    write_script = Function(name="write_script", entrypoint=lambda: {"ok": True})
    write_script.process_entrypoint()
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    model.configure_code_run((run, write_script), max_model_requests=6, delivery_reserve=3)

    first: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[FunctionCall(function=run, call_id="first", arguments={})],
            function_call_results=first,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]
    assert json.loads(first[0].content)["details"]["escalated"] is False

    delivered: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[FunctionCall(function=write_script, call_id="delivered", arguments={})],
            function_call_results=delivered,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]
    # 普通 dict 结果经 Agno str(function_call.result) 落地为 Python repr，
    # 不是 JSON（区别于我们自建的 rejected/skipped 控制结果）。
    assert literal_eval(delivered[0].content)["ok"] is True

    second: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[FunctionCall(function=run, call_id="second", arguments={})],
            function_call_results=second,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]
    assert json.loads(second[0].content)["details"]["escalated"] is False


@pytest.mark.anyio
async def test_tool_results_include_budget_and_reserved_view_rejects_current_review() -> None:
    class Owner:
        reviewed = False

        def has_current_visual_review(self, path: str) -> bool:
            return self.reviewed and path == "charts/chart.png"

        async def view_image(self, path: str) -> dict[str, object]:
            return {"ok": True, "path": path}

    owner = Owner()
    function = Function(name="view_image", entrypoint=owner.view_image)
    function.process_entrypoint()
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    model.configure_code_run((function,), max_model_requests=4, delivery_reserve=3,
                             redundant_call_check=owner.has_current_visual_review)

    allowed: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(
                    function=function,
                    call_id="unreviewed",
                    arguments={"path": "charts/chart.png"},
                )
            ],
            function_call_results=allowed,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]
    # 普通 dict 结果经 Agno str(function_call.result) 落地为 Python repr，
    # 不是 JSON（区别于我们自建的 rejected/skipped 控制结果）。
    allowed_payload = literal_eval(allowed[0].content)
    assert allowed_payload["ok"] is True
    assert allowed_payload["budget"] == {"used": 18, "limit": 20, "remaining": 2}

    owner.reviewed = True
    rejected: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(
                    function=function,
                    call_id="reviewed",
                    arguments={"path": "charts/chart.png"},
                )
            ],
            function_call_results=rejected,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]
    rejected_payload = json.loads(rejected[0].content)
    # 冗余的 view_image（图片已通过当前内容审查）不是预算耗尽，只是浪费的调用；
    # 必须区别于真正的预留门禁拒绝，并且不计费。
    assert rejected_payload["code"] == "report_code_visual_review_redundant"
    assert rejected_payload["status"] == "skipped"
    assert model._limit_charge_for(rejected, None) == 0


@pytest.mark.anyio
async def test_redundant_view_image_rejection_does_not_stop_batch() -> None:
    class Owner:
        def has_current_visual_review(self, path: str) -> bool:
            return path == "charts/reviewed.png"

        async def view_image(self, path: str) -> dict[str, object]:
            return {"ok": True, "path": path}

    owner = Owner()
    view_image = Function(name="view_image", entrypoint=owner.view_image)
    view_image.process_entrypoint()

    executed: list[str] = []

    async def submit_entrypoint() -> dict[str, object]:
        executed.append("submit_script")
        return {"ok": True}

    submit_script = Function(name="submit_script", entrypoint=submit_entrypoint)
    submit_script.process_entrypoint()

    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    model.configure_code_run(
        (view_image, submit_script), max_model_requests=4, delivery_reserve=2,
        redundant_call_check=owner.has_current_visual_review,
    )

    results: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(
                    function=view_image,
                    call_id="redundant",
                    arguments={"path": "charts/reviewed.png"},
                ),
                FunctionCall(function=submit_script, call_id="submit", arguments={}),
            ],
            function_call_results=results,
            current_function_call_count=18,
            function_call_limit=20,
        )
    ]

    # 冗余拒绝之后，同批次内真正需要执行的 submit_script 必须继续执行，
    # 不能被当作批次终止的失败信号误伤。第一项是我们自建的 JSON 控制结果，
    # 第二项是 submit_script 的普通 dict 结果，经 Agno str() 落地为 Python repr。
    assert executed == ["submit_script"]

    def _payload(content: str) -> dict[str, object]:
        try:
            return json.loads(content)
        except (TypeError, ValueError):
            return literal_eval(content)

    assert [_payload(item.content).get("code") for item in results] == [
        "report_code_visual_review_redundant",
        None,
    ]
