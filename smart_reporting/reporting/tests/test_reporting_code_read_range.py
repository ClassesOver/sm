"""局部读取保留原始字节、整份源码身份和补丁兼容性。"""

import hashlib
import json

import pytest
from agno.tools.function import FunctionCall

from smart_reporting.reporting.tests.test_reporting_code_input import (
    anyio_backend,  # noqa: F401
    binding,  # noqa: F401
    toolkit,  # noqa: F401
    workspace,  # noqa: F401
)
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    _code_responses_model,
)


@pytest.mark.anyio
@pytest.mark.parametrize("arguments,expected,start,end", [
    ({}, "# 中文\r\nvalue = 1\nprint(value)", 1, 3),
    ({"start_line": 2, "end_line": 2}, "value = 1\n", 2, 2),
    ({"start_line": 2}, "value = 1\nprint(value)", 2, 3),
    ({"end_line": 2}, "# 中文\r\nvalue = 1\n", 1, 2),
    ({"start_line": 3, "end_line": 99}, "print(value)", 3, 3),
])
async def test_read_range_keeps_full_file_identity(toolkit, arguments, expected, start, end):  # noqa: F811
    source = "# 中文\r\nvalue = 1\nprint(value)"
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, source)
    result = await toolkit.read_script(**arguments)
    assert result["source"] == expected
    assert result["startLine"] == start
    assert result["endLine"] == end
    assert result["totalLines"] == 3
    assert result["size"] == len(source.encode())
    assert result["sha256"] == hashlib.sha256(source.encode()).hexdigest()


@pytest.mark.anyio
@pytest.mark.parametrize("arguments", [
    {"start_line": 0}, {"end_line": -1}, {"start_line": 3, "end_line": 2},
    {"start_line": True}, {"end_line": 1.5}, {"start_line": "2"},
])
async def test_invalid_read_range_is_rejected(toolkit, arguments):  # noqa: F811
    result = await toolkit.read_script(**arguments)
    assert result["code"] == "report_code_script_range_invalid"


@pytest.mark.anyio
async def test_range_past_eof_and_empty_file(toolkit):  # noqa: F811
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, "")
    empty = await toolkit.read_script()
    assert (empty["source"], empty["totalLines"], empty["startLine"], empty["endLine"]) == ("", 0, None, None)
    result = await toolkit.read_script(start_line=2)
    assert result["code"] == "report_code_script_range_invalid"


@pytest.mark.anyio
async def test_partial_read_through_agno_can_feed_precise_patch(toolkit):  # noqa: F811
    source = "# keep\nvalue = 1\nprint(value)\n"
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, source)
    spec = next(t for t in _code_responses_model().get_request_params(
        messages=[], tools=toolkit.tool_functions,
    )["tools"] if t["name"] == "read_script")
    assert spec["type"] == "function"
    assert {"start_line", "end_line"} <= spec["parameters"]["properties"].keys()
    fn = next(f for f in toolkit.tool_functions if f.name == "read_script")
    fn.process_entrypoint()
    call = FunctionCall(function=fn, arguments=json.loads('{"start_line":2,"end_line":2}'))
    assert await call.aexecute()
    result = call.result
    patch = (f"*** Begin Edit\n*** SHA256: {result['sha256']}\n<<<<<<< SEARCH\n"
             f"{result['source']}\n=======\nvalue = 2\n\n>>>>>>> REPLACE\n*** End Edit")
    assert (await toolkit.edit_script(patch))["ok"]
    assert (await toolkit.read_script())["source"] == "# keep\nvalue = 2\nprint(value)\n"
