"""工具监控通过 Agno 原生执行链输出 INFO。"""

import pytest
from agno.tools.function import FunctionCall
from loguru import logger

from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    ToolkitRuntime,
    binding,  # noqa: F401
    workspace,  # noqa: F401
)


@pytest.mark.anyio
async def test_tool_calls_log_start_result_and_exception(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    records = []
    sink = logger.add(lambda message: records.append(message.record))
    try:
        await FunctionCall(function=functions['read_script'], call_id='read-1', arguments={}).aexecute()
        await FunctionCall(function=functions['write_script'], call_id='write-1',
                           arguments={'source': ''}).aexecute()
    finally:
        logger.remove(sink)
    events = [r for r in records if 'code_monitor_tool' in r['message']]
    assert len(events) == 4
    assert all(r['level'].name == 'INFO' for r in events)
    assert 'status=started' in events[0]['message']
    assert 'call_id=read-1' in events[0]['message']
    assert 'status=completed' in events[1]['message']
    assert 'status=failed' in events[3]['message']
    assert all(tool.pre_hook is not None and tool.post_hook is not None
               for tool in toolkit.tool_functions)
