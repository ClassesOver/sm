from __future__ import annotations

import ast
import hashlib
import subprocess
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from agno.models.message import Message
from agno.tools.function import Function, FunctionCall

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    binding,  # noqa: F401
    workspace,  # noqa: F401
)
from smart_reporting.reporting.workflow.checkpoint import FileIdentity


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def toolkit(binding):  # noqa: F811
    return ReportingCodeModeToolkit(binding, AsyncMock(), ReportingLspProcessManager())


@pytest.mark.anyio
async def test_write_formats_source_and_hashes_saved_content(toolkit):
    source = "# 保留注释\nvalues=[1,2,3]\nprint( values )\n"
    expected = "# 保留注释\nvalues = [1, 2, 3]\nprint(values)\n"

    result = await toolkit.write_script(source)
    saved = await toolkit.read_script()

    assert result["ok"] is True
    assert saved["source"] == expected
    assert result["formatted"] is True
    assert result["savedSource"] == expected
    assert result["sourceSha256"] == result["sha256"]
    assert result["sourceBytes"] == result["size"]
    assert result["changeSummary"]["kind"] == "write"
    assert result["sha256"] == saved["sha256"] == hashlib.sha256(expected.encode()).hexdigest()
    assert result["size"] == len(expected.encode())
    assert ast.dump(ast.parse(saved["source"])) == ast.dump(ast.parse(source))
    second = await toolkit.write_script(saved["source"])
    assert second["formatted"] is False
    assert second["savedSource"] is None
    assert second["sha256"] == result["sha256"]


@pytest.mark.anyio
async def test_write_formats_long_call_without_executing_it(toolkit):
    source = "result = build(" + ", ".join(f"field_{i}=value_{i}" for i in range(500)) + ")\n"
    assert len(source.encode()) > 8192

    result = await toolkit.write_script(source)
    saved = await toolkit.read_script()

    assert result["ok"] is True
    assert max(len(line) for line in saved["source"].splitlines()) <= 100
    assert ast.dump(ast.parse(saved["source"])) == ast.dump(ast.parse(source))


@pytest.mark.anyio
async def test_write_preserves_long_unicode_string_that_formatter_cannot_wrap(toolkit):
    value = "销售额" * 1000
    source = "label = " + repr(value) + "\n"

    result = await toolkit.write_script(source)
    saved = await toolkit.read_script()

    assert result["ok"] is True
    assert ast.literal_eval(ast.parse(saved["source"]).body[0].value) == value


@pytest.mark.anyio
@pytest.mark.parametrize("source", ["if True\n    pass\n", "value = 1  # fmt: skip\n"])
async def test_write_preserves_drafts_and_formatter_directives(toolkit, source):
    result = await toolkit.write_script(source)
    saved = await toolkit.read_script()

    assert result["ok"] is True
    assert result["formatted"] is False
    assert saved["source"] == source
    if source.startswith("if"):
        assert result["warnings"][0]["reason"] == "syntax_error"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(),
        subprocess.TimeoutExpired("ruff", 5),
        subprocess.CalledProcessError(2, "ruff"),
    ],
)
async def test_formatter_failure_preserves_source_with_warning(toolkit, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", fail)
    source = "values=[1,2,3]\n"

    result = await toolkit.write_script(source)
    saved = await toolkit.read_script()

    assert result["ok"] is True
    assert result["formatted"] is False
    assert result["warnings"][0]["code"] == "report_code_formatting_failed"
    assert saved["source"] == source


@pytest.mark.anyio
async def test_format_expansion_over_source_limit_keeps_original(toolkit):
    source = "values=[" + ",".join("1" for _ in range(100)) + "]\n"
    toolkit.binding.context = replace(toolkit.context, max_source_bytes=len(source.encode()))

    result = await toolkit.write_script(source)
    saved = await toolkit.read_script()

    assert result["ok"] is True
    assert result["formatted"] is False
    assert result["warnings"][0]["code"] == "report_code_formatting_failed"
    assert saved["source"] == source


@pytest.mark.anyio
async def test_rejected_source_keeps_existing_script_and_execution_receipt(toolkit):
    await toolkit.write_script("value = 1\n")
    before = await toolkit.read_script()
    receipt = ExecutionReceipt(
        runId="previous-run",
        sourceFile=FileIdentity(path=before["path"], size=before["size"], sha256=before["sha256"]),
        outputFiles=(),
    )
    toolkit.binding.execution_receipt = receipt
    toolkit.submitted_receipt = receipt
    source = "rows = " + repr("x" * 40000) + "\n"

    result = await toolkit.write_script(source)

    assert result["ok"] is False
    assert result["code"] == "report_code_source_invalid"
    assert result["details"] == {
        "reason": "embedded_data",
        "kind": "large_literal",
        "bytes": 40000,
        "line": 1,
        "column": 7,
    }
    assert await toolkit.read_script() == before
    assert toolkit.binding.execution_receipt is receipt
    assert toolkit.submitted_receipt is receipt


@pytest.mark.anyio
async def test_write_rejection_stops_following_batch_call_with_matching_receipts(toolkit):
    source = "rows = " + repr("x" * 40000) + "\n"
    functions = [
        Function(name="write_script", entrypoint=toolkit.write_script),
        Function(name="run_script", entrypoint=toolkit.run_script),
    ]
    for function in functions:
        function.process_entrypoint()
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    results: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(
                    function=functions[0], call_id="write-1", arguments={"source": source}
                ),
                FunctionCall(function=functions[1], call_id="run-2", arguments={}),
            ],
            function_call_results=results,
        )
    ]

    assert [result.tool_call_id for result in results] == ["write-1", "run-2"]
    assert "embedded_data" in results[0].content
    assert "report_code_batch_stopped" in results[1].content
    assert results[1].tool_call_error is True
    assert not toolkit.runtime.execute_script_process.called
