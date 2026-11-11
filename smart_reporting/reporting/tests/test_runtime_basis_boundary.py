"""实际运行读取必须通过新依据，部署遗漏不得回退文件配置。"""

from types import SimpleNamespace

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["source", "sources", "ensure"])
async def test_missing_basis_configuration_cannot_use_file_registry(operation):
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.registry = SimpleNamespace(sources=(SimpleNamespace(id="legacy"),))
    context = RunContext(run_id="new-run", session_id="session", session_state={})
    with pytest.raises(ReportingError) as caught:
        if operation == "source":
            await runtime._source("legacy", context)
        elif operation == "sources":
            await runtime._sources(context)
        else:
            await runtime._ensure_managed_execution_state(context)
    assert caught.value.code == "report_configuration_missing"
