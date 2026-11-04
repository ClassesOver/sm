from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.code_agent.context import ReportingCodingTaskBinding
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.code_mode import ScriptProcessResult
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    ToolkitRuntime,
    _task_context,
    workspace,  # noqa: F401
)


@pytest.mark.anyio
async def test_workbook_submission_rejects_unreadable_output_and_reuses_identity(workspace):  # noqa: F811
    context = replace(
        _task_context(workspace), task_kind='workbook',
        authorized_write_paths=('analysis/a.py', 'reports/report.xlsx'),
        declared_output_paths=('reports/report.xlsx',),
    )

    class Runtime(ToolkitRuntime):
        async def execute_script_process(self, _session, bound_workspace, _path, **_kwargs):
            await bound_workspace.awrite_bytes('task-1', 'reports/report.xlsx', b'not a workbook')
            return ScriptProcessResult(SimpleNamespace(status='ok', stdout='', stderr='', traceback=None), 0)

    binding = ReportingCodingTaskBinding(context, workspace)
    toolkit = ReportingCodeModeToolkit(binding, Runtime(), ReportingLspProcessManager())
    assert (await toolkit.write_script("from pathlib import Path\nPath('reports/report.xlsx').write_bytes(b'not a workbook')\n"))['ok']
    result = await toolkit.run_script()
    assert result['ok'] is False
    assert result['outputValidation']['code'] == 'report_workbook_output_invalid'
    assert binding.execution_receipt is not None
    assert binding.execution_receipt.output_files[0].path == 'reports/report.xlsx'
    assert (await toolkit.submit_script())['code'] == 'report_code_output_validation_pending'


def test_workbook_agent_factory_keeps_native_tools_and_data_drafting_instructions():
    from agno.models.openai import OpenAIChat
    from agno.tools.function import Function

    from smart_reporting.reporting.agent import create_reporting_code_agent_factory

    agent = create_reporting_code_agent_factory(
        model=OpenAIChat(id='test', api_key='test'), name='workbook', task_kind='workbook',
    )([Function(name='write_script'), Function(name='run'), Function(name='submit_script')])
    tools = agent.model._format_tool_params([], agent.tools)
    assert [(item.get('name', item.get('function', {}).get('name')), item['type']) for item in tools] == [
        ('write_script', 'custom'), ('run', 'custom'), ('submit_script', 'function'),
    ]
    instructions = '\n'.join(agent.instructions)
    assert 'build_workbook' in instructions
    assert 'view_image' not in instructions


@pytest.mark.parametrize('code,expected', [
    ('report_code_source_invalid', 'retry'),
    ('report_phase_artifact_changed', 'fatal'),
    ('report_code_generation_no_submission', 'retry_then_degrade'),
])
def test_workbook_repair_policy_uses_existing_coding_budget(code, expected):
    from smart_reporting.reporting.code_agent.failure_policy import recovery_for
    from smart_reporting.reporting.models import ReportingError

    assert recovery_for(ReportingError(code, 'failed'), 'workbook') == expected
