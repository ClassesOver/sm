from __future__ import annotations

import ast
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.models.message import Message
from agno.tools.function import FunctionCall
from lark import Lark, UnexpectedInput

from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.workflow.runtime.code_generation import (
    ReportingCodeGenerationRunner,
)
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    _assistant_and_result_messages,
    _code_responses_model,
    _custom_response,
    _receipt,
    binding,  # noqa: F401
    workspace,  # noqa: F401
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def toolkit(binding):  # noqa: F811
    runtime = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(status="ok", result="2")),
        execute_script_process=AsyncMock(),
    )
    return ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())


WRAPPED_INPUTS = [
    json.dumps({key: "import pandas as pd\nprint(pd.__version__)\n"})
    for key in ("data", "code", "source")
] + [
    json.dumps({"data": "import pandas as pd\nprint("}),
    json.dumps({"code": "1 + 1"}),
    json.dumps({"data": json.dumps({"data": "print('must not run')\n"})}),
    "{'source': {'code': 'print(1)'}}",
    "# provider wrapper\n({'data': 'print(1)'})\n",
]


def test_run_is_exposed_as_native_custom_tool(toolkit):
    model = _code_responses_model()
    specs = model._format_tool_params([], toolkit.tool_functions)
    names = {spec["name"] for spec in specs}
    assert "run" in names
    assert "run_snippet" not in names
    run_spec = next(spec for spec in specs if spec["name"] == "run")
    assert run_spec["type"] == "custom"
    assert run_spec["format"]["syntax"] == "lark"
    assert "parameters" not in run_spec
    assert "原始代码" in run_spec["description"]


def test_edit_script_is_exposed_as_native_custom_tool(toolkit):
    specs = _code_responses_model()._format_tool_params([], toolkit.tool_functions)
    edit_spec = next(spec for spec in specs if spec["name"] == "edit_script")

    assert edit_spec["type"] == "custom"
    assert "parameters" not in edit_spec
    assert edit_spec["format"]["syntax"] == "lark"


@pytest.mark.parametrize("name", ["run", "write_script"])
def test_custom_grammar_rejects_wrappers_and_accepts_raw_multiline_source(toolkit, name):
    specs = _code_responses_model()._format_tool_params([], toolkit.tool_functions)
    spec = next(item for item in specs if item["name"] == name)
    parser = Lark(spec["format"]["definition"])
    for source in ('# Python\nprint(1)\n', '# Python\nvalue = {"code": 1}\n',
                   '# Python\nimport matplotlib\nmatplotlib.use("Agg")\n'):
        parser.parse(source)
    for wrapped in ('{"code": "print(1)"}', '"print(1)"', '```python\nprint(1)\n```'):
        with pytest.raises(UnexpectedInput):
            parser.parse(wrapped)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_request_custom_grammars_allow_shell_only_for_run(toolkit, newline):
    params = _code_responses_model().get_request_params(
        messages=[], tools=toolkit.tool_functions,
    )
    assert params["tool_choice"] == "auto"
    for name in ("write_script", "run"):
        spec = next(item for item in params["tools"] if item["name"] == name)
        assert spec["type"] == "custom"
        assert "parameters" not in spec
        assert "strict" not in spec
        parser = Lark(spec["format"]["definition"])
        source = f"# Python{newline}print('收入')"
        parser.parse(source)
        shell = f"%%bash{newline}printf ok"
        if name == "run":
            parser.parse(shell)
        else:
            with pytest.raises(UnexpectedInput):
                parser.parse(shell)
        for wrapped in (json.dumps({"data": source}), json.dumps(source),
                        f"```python{newline}{source}{newline}```"):
            with pytest.raises(UnexpectedInput):
                parser.parse(wrapped)


def test_write_script_explicitly_requires_complete_python_source(toolkit):
    model = _code_responses_model()
    specs = model._format_tool_params([], toolkit.tool_functions)
    write_spec = next(spec for spec in specs if spec["name"] == "write_script")

    assert write_spec["type"] == "custom"
    assert "完整 Python 源码" in write_spec["description"]
    assert "首次创建工具" in write_spec["description"]
    assert "已有脚本的修复必须使用 edit_script" in write_spec["description"]
    assert "JSON 对象" in write_spec["description"]


def test_repair_facts_drop_repeated_visual_plan_but_keep_patch_contract():
    facts = {
        "visualizationFacts": {"rows": ["x"] * 1000},
        "visualizationPlan": {"charts": [{"chartId": "chart-1"}] * 1000},
        "visualizationWorkspace": {"root": "/tmp/workspace"},
        "scriptPath": "charts/charts.py",
        "existingFacts": {"analysisId": "analysis-1", "total": 10},
        "codingRequirements": [{"datasetId": "dataset-1", "fields": ["income"]}],
        "datasets": [
            {
                "datasetId": "dataset-1",
                "path": "data/income.csv",
                "columns": ["income", "period"],
                "rows": [{"period": "2025", "income": 10}] * 1000,
            }
        ],
        "outputContract": {"schema": "evidence"},
    }

    projected = ReportingCodeGenerationRunner._repair_task_facts(facts)

    assert "visualizationFacts" not in projected
    assert "visualizationPlan" not in projected
    assert "visualizationWorkspace" not in projected
    assert projected["scriptPath"] == "charts/charts.py"
    assert projected["existingFacts"] == facts["existingFacts"]
    assert projected["codingRequirements"] == facts["codingRequirements"]
    assert projected["datasets"] == [
        {
            "datasetId": "dataset-1",
            "path": "data/income.csv",
            "columns": ["income", "period"],
        }
    ]
    assert len(json.dumps(projected, ensure_ascii=False).encode()) < len(
        json.dumps(facts, ensure_ascii=False).encode()
    )


@pytest.mark.parametrize("name", ["write_script", "run"])
def test_custom_tool_source_example_matches_wire_grammar(toolkit, name):
    specs = _code_responses_model()._format_tool_params([], toolkit.tool_functions)
    spec = next(item for item in specs if item["name"] == name)
    example = spec["description"].split("输入示例：\n", 1)[1].split("\n示例结束。", 1)[0]
    Lark(spec["format"]["definition"]).parse(example)
    compile(example, "<tool-example>", "exec")


def test_visualization_request_exposes_only_current_delivery_tools(toolkit):
    from dataclasses import replace

    toolkit.binding.context = replace(toolkit.context, task_kind="visualization")
    state = {"taskKind": "visualization", "nextTools": ["write_script"]}
    model = _code_responses_model()
    model.configure_code_run(toolkit.tool_functions, max_model_requests=10,
                             delivery_state_reader=lambda: state)
    params = model.get_request_params(messages=[], tools=toolkit.tool_functions)
    assert {tool["name"] for tool in params["tools"]} == {
        "write_script", "run_script", "submit_script",
    }
    assert params["tools"][0]["type"] == "custom"
    state["nextTools"] = ["run_script"]
    params = model.get_request_params(messages=[], tools=toolkit.tool_functions)
    assert [tool["name"] for tool in params["tools"]] == ["run_script"]


def test_analysis_request_exposes_initial_ordered_delivery_chain(toolkit):
    state = {"taskKind": "analysis_item", "nextTools": ["write_script"]}
    model = _code_responses_model()
    model.configure_code_run(
        toolkit.tool_functions,
        max_model_requests=10,
        delivery_state_reader=lambda: state,
    )

    params = model.get_request_params(messages=[], tools=toolkit.tool_functions)

    assert {tool["name"] for tool in params["tools"]} == {
        "write_script", "run_script", "submit_script",
    }
    assert params["tools"][0]["type"] == "custom"
    assert params["tool_choice"] == "auto"
    assert params["parallel_tool_calls"] is True


def test_visualization_request_exposes_initial_ordered_delivery_chain(toolkit):
    from dataclasses import replace

    toolkit.binding.context = replace(toolkit.context, task_kind="visualization")
    state = {"taskKind": "visualization", "nextTools": ["write_script"]}
    model = _code_responses_model()
    model.configure_code_run(
        toolkit.tool_functions,
        max_model_requests=10,
        delivery_state_reader=lambda: state,
    )

    params = model.get_request_params(messages=[], tools=toolkit.tool_functions)

    assert {tool["name"] for tool in params["tools"]} == {
        "write_script", "run_script", "submit_script",
    }
    assert "run" not in {tool["name"] for tool in params["tools"]}
    assert params["parallel_tool_calls"] is True


def test_analysis_request_exposes_exact_repair_delivery_tools(toolkit):
    state = {
        "taskKind": "analysis_item",
        "script": {"path": toolkit.context.script_path, "sha256": "a" * 64},
        "nextTools": ["read_script", "edit_script", "run_script"],
    }
    model = _code_responses_model()
    model.configure_code_run(
        toolkit.tool_functions,
        max_model_requests=10,
        delivery_state_reader=lambda: state,
    )

    params = model.get_request_params(messages=[], tools=toolkit.tool_functions)

    assert {tool["name"] for tool in params["tools"]} == {
        "read_script",
        "edit_script",
        "run_script",
    }
    assert params["parallel_tool_calls"] is True


@pytest.mark.parametrize("task_kind", ["analysis_item", "visualization"])
def test_delivery_state_with_no_next_tools_fails_closed(toolkit, task_kind):
    state = {"taskKind": task_kind, "nextTools": []}
    model = _code_responses_model()
    model.configure_code_run(
        toolkit.tool_functions,
        max_model_requests=10,
        delivery_state_reader=lambda: state,
    )

    params = model.get_request_params(messages=[], tools=toolkit.tool_functions)

    assert params["tools"] == []
    assert params["parallel_tool_calls"] is True
    assert "tool_choice" not in params


def test_existing_script_hides_full_rewrite_tool_from_model(toolkit):
    state = {
        "taskKind": "analysis_item",
        "script": {"path": toolkit.context.script_path, "sha256": "a" * 64},
        "nextTools": ["read_script", "edit_script", "run_script"],
    }
    model = _code_responses_model()
    model.configure_code_run(
        toolkit.tool_functions,
        max_model_requests=10,
        delivery_state_reader=lambda: state,
    )

    params = model.get_request_params(messages=[], tools=toolkit.tool_functions)
    names = {tool["name"] for tool in params["tools"]}

    assert "write_script" not in names
    assert "edit_script" in names


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["run", "write_script"])
async def test_custom_raw_input_survives_agno_binding_and_replay(toolkit, name):
    model = _code_responses_model()
    source = "# 中文和引号必须原样传递\nprint('ok')\n"
    call = model._parse_provider_response(_custom_response(name, source)).tool_calls[0]
    function = next(f for f in toolkit.tool_functions if f.name == name)
    function.process_entrypoint()
    fc = FunctionCall(function=function, call_id=call["call_id"],
                      arguments=json.loads(call["function"]["arguments"]))
    assert await fc.aexecute()
    assert fc.result["ok"] is True
    if name == "run":
        assert toolkit.runtime.execute.await_args.args[2] == source
    else:
        assert ast.dump(ast.parse((await toolkit.read_script())["source"])) == ast.dump(ast.parse(source))
    replay = model._format_messages(_assistant_and_result_messages(call, fc.result))
    assert replay[-2]["type"] == "custom_tool_call"
    assert replay[-2]["input"] == source
    assert replay[-1]["type"] == "custom_tool_call_output"


@pytest.mark.anyio
async def test_read_script_rejects_model_supplied_path_as_structured_failure(toolkit):
    function = next(f for f in toolkit.tool_functions if f.name == "read_script")
    function.process_entrypoint()

    fc = FunctionCall(function=function, arguments={"path": "other.py"})
    assert await fc.aexecute()

    assert fc.result["ok"] is False
    assert fc.result["code"] == "report_code_script_path_forbidden"


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["run", "write_script"])
async def test_wrapped_input_has_recovery_and_stops_after_two_failures(toolkit, name):
    function = next(f for f in toolkit.tool_functions if f.name == name)
    function.process_entrypoint()
    argument = "code" if name == "run" else "source"
    for index in range(2):
        fc = FunctionCall(function=function, call_id=f"wrapped-{index}",
                          arguments={argument: WRAPPED_INPUTS[0]})
        assert await fc.aexecute()
        assert fc.result["details"]["nextTools"] == [name]
        spec = next(item for item in _code_responses_model()._format_tool_params(
            [], toolkit.tool_functions
        ) if item["name"] == name)
        Lark(spec["format"]["definition"]).parse(fc.result["rawInputExample"])
        assert function.stop_after_tool_call is (index == 1)
    assert toolkit.terminal_failure.code == "report_code_input_wrapped"
    assert toolkit.terminal_failure.details["recovery"] == "retry_then_degrade"
    assert toolkit.terminal_failure.details["stopReason"] == "repeated_identical_input"
    toolkit.runtime.execute.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["run", "write_script"])
async def test_changed_wrapped_input_does_not_trigger_identical_input_stop(toolkit, name):
    function = next(f for f in toolkit.tool_functions if f.name == name)
    function.process_entrypoint()
    argument = "code" if name == "run" else "source"
    for source in ['{"code": "print(1)"}', '{"code": "print(2)"}']:
        fc = FunctionCall(function=function, arguments={argument: source})
        assert await fc.aexecute()
        assert fc.result["ok"] is False
        assert fc.result["code"] == "report_code_input_wrapped"
        assert function.stop_after_tool_call is False
        assert toolkit.terminal_failure is None


@pytest.mark.anyio
async def test_wrapped_retry_recovery_resets_counter(toolkit):
    function = next(f for f in toolkit.tool_functions if f.name == "run")
    function.process_entrypoint()
    for source in [WRAPPED_INPUTS[0], WRAPPED_INPUTS[0], "print(1)", WRAPPED_INPUTS[0]]:
        fc = FunctionCall(function=function, arguments={"code": source})
        assert await fc.aexecute()
    assert toolkit.terminal_failure is None
    assert function.stop_after_tool_call is False
    assert "repeatedFailureCount" not in fc.result


@pytest.mark.anyio
async def test_wrapped_terminal_preserves_batch_receipts(toolkit):
    model = _code_responses_model()
    function = next(f for f in toolkit.tool_functions if f.name == "run")
    function.process_entrypoint()
    for index in range(2):
        fc = FunctionCall(function=function, call_id=f"prior-{index}",
                          arguments={"code": WRAPPED_INPUTS[0]})
        assert await fc.aexecute()
    results = []
    calls = [FunctionCall(function=function, call_id=identity, arguments={"code": source})
             for identity, source in [("terminal", WRAPPED_INPUTS[0]), ("skipped", "print(1)")]]
    _ = [event async for event in model.arun_function_calls(
        function_calls=calls, function_call_results=results)]
    assert [r.tool_call_id for r in results] == ["terminal", "skipped"]
    assert results[0].stop_after_tool_call is True
    assert "report_code_batch_stopped" in results[1].content
    toolkit.runtime.execute.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("source", WRAPPED_INPUTS)
async def test_run_rejects_code_envelope_without_executing(toolkit, source):
    result = await toolkit.run(source)

    assert result["ok"] is False
    assert result["code"] == "report_code_input_wrapped"
    assert result["details"]["reason"] == "code_envelope"
    assert "原始" in result["message"]
    toolkit.runtime.execute.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("source", WRAPPED_INPUTS)
async def test_write_rejects_code_envelope_without_overwriting(toolkit, monkeypatch, source):
    await toolkit.write_script("value = 1\n")
    before = await toolkit.read_script()
    receipt = _receipt()
    toolkit.binding.execution_receipt = receipt
    toolkit.submitted_receipt = receipt
    formatter = AsyncMock()
    monkeypatch.setattr(
        "smart_reporting.reporting.code_agent.toolkit.format_python_source", formatter
    )

    result = await toolkit.write_script(source)

    assert result["ok"] is False
    assert result["code"] == "report_code_input_wrapped"
    assert await toolkit.read_script() == before
    assert toolkit.binding.execution_receipt is receipt
    assert toolkit.submitted_receipt is receipt
    formatter.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "source",
    [
        "1 + 1",
        "print('ok')",
        '{"first": 1, "second": 2}',
        '{"data": "销售额"}',
        '{"data": "hello"}',
        '{"data": "42"}',
        '{"data": {"value": 1}}',
        '{"data": "print(1)", "label": "example"}',
        "payload = {'data': 'print(1)'}",
        "%%bash\nprintf 'ok\\n'",
        "%time 1 + 1",
        "if True print('syntax error')",
    ],
)
async def test_run_forwards_real_cells_and_ordinary_dicts_unchanged(toolkit, source):
    result = await toolkit.run(source)

    assert result["ok"] is True
    assert toolkit.runtime.execute.await_args.args[2] == source


@pytest.mark.anyio
@pytest.mark.parametrize("source", ['{"data": "销售额"}', "payload = {'data': 'print(1)'}"])
async def test_write_preserves_ordinary_dictionary_semantics(toolkit, source):
    assert (await toolkit.write_script(source))["ok"] is True
    saved = await toolkit.read_script()
    assert ast.dump(ast.parse(saved["source"])) == ast.dump(ast.parse(source))


@pytest.mark.anyio
async def test_write_rejects_forbidden_path_operations_before_saving(toolkit):
    await toolkit.write_script("value = 1\n")
    before = await toolkit.read_script()
    receipt = _receipt()
    toolkit.binding.execution_receipt = receipt
    toolkit.submitted_receipt = receipt

    result = await toolkit.write_script(
        'import os\nout_dir = os.path.dirname("analysis/out.json")\nprint(out_dir)\n'
    )

    assert result["ok"] is False
    assert result["code"] == "report_python_source_path_invalid"
    assert result["details"]["forbiddenPathOperations"] == ["os.path.dirname"]
    assert await toolkit.read_script() == before
    assert toolkit.binding.execution_receipt is receipt
    assert toolkit.submitted_receipt is receipt


@pytest.mark.anyio
async def test_write_rejects_unsigned_literal_paths_before_saving(toolkit):
    result = await toolkit.write_script(
        'with open("unauthorized.txt", "w") as handle:\n    handle.write("x")\n'
    )

    assert result["ok"] is False
    assert result["code"] == "report_python_source_path_invalid"
    assert result["details"]["unsignedPaths"] == ["unauthorized.txt"]
    assert (await toolkit.read_script())["exists"] is False


@pytest.mark.anyio
async def test_write_syntax_error_reports_not_ready(toolkit, monkeypatch):
    monkeypatch.setattr(toolkit.workspace, "apath_exists", AsyncMock(return_value=False))
    monkeypatch.setattr(toolkit.workspace, "awrite_text", AsyncMock())
    monkeypatch.setattr(
        toolkit.workspace,
        "ahash_file",
        AsyncMock(return_value={"path": toolkit.context.script_path, "size": 28, "sha256": "a" * 64}),
    )

    result = await toolkit.write_script("if True print('syntax error')\n")

    assert result["ok"] is True
    assert result["readyForExecution"] is False
    assert result["warnings"][0]["reason"] == "syntax_error"


@pytest.mark.anyio
async def test_write_valid_source_reports_ready(toolkit, monkeypatch):
    monkeypatch.setattr(
        "smart_reporting.reporting.code_agent.toolkit.format_python_source",
        AsyncMock(return_value="print('ok')\n"),
    )
    monkeypatch.setattr(toolkit.workspace, "apath_exists", AsyncMock(return_value=False))
    monkeypatch.setattr(toolkit.workspace, "awrite_text", AsyncMock())
    monkeypatch.setattr(
        toolkit.workspace,
        "ahash_file",
        AsyncMock(return_value={"path": toolkit.context.script_path, "size": 12, "sha256": "a" * 64}),
    )

    result = await toolkit.write_script("print('ok')\n")

    assert result["ok"] is True
    assert result["readyForExecution"] is True


@pytest.mark.anyio
async def test_wrapped_run_stops_batch_and_replays_original_custom_input(toolkit):
    model = _code_responses_model()
    functions = {function.name: function for function in toolkit.tool_functions}
    for function in functions.values():
        function.process_entrypoint()
    source = WRAPPED_INPUTS[0]
    original_call = model._parse_provider_response(
        _custom_response("run", source)
    ).tool_calls[0]
    results: list[Message] = []

    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(
                    function=functions["run"],
                    call_id="call-1",
                    arguments={"code": source},
                ),
                FunctionCall(
                    function=functions["write_script"],
                    call_id="call-2",
                    arguments={"source": "print('must not write')"},
                ),
            ],
            function_call_results=results,
        )
    ]

    assert [result.tool_call_id for result in results] == ["call-1", "call-2"]
    rejection = ast.literal_eval(results[0].content)
    assert rejection["code"] == "report_code_input_wrapped"
    assert "report_code_batch_stopped" in results[1].content
    toolkit.runtime.execute.assert_not_awaited()
    assert (await toolkit.read_script())["exists"] is False
    replay = model._format_messages(_assistant_and_result_messages(original_call, rejection))
    assert replay[-2]["type"] == "custom_tool_call"
    assert replay[-2]["input"] == source
    assert replay[-1]["type"] == "custom_tool_call_output"
    assert json.loads(replay[-1]["output"])["ok"] is False
    assert (await toolkit.run("print('fixed')"))["ok"] is True
    assert toolkit.runtime.execute.await_args.args[2] == "print('fixed')"
