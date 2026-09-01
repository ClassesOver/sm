from __future__ import annotations

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.controller import (
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    ReportWorkflowController,
)


def test_controller_scope_defaults_missing_tenant() -> None:
    context = RunContext(
        run_id="external-run",
        session_id="thread-1",
        user_id="user-1",
        dependencies={
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                "externalRunId": "external-run",
                "threadId": "thread-1",
                "userId": "user-1",
            }
        },
    )

    scope = ReportWorkflowController._scope(context)

    assert scope["database"] == "default"
    assert scope["company_id"] == "default"


@pytest.mark.parametrize(
    "tenant",
    [
        {"database": "odoo"},
        {"companyId": "3"},
    ],
)
def test_controller_scope_rejects_partial_tenant(tenant: dict[str, str]) -> None:
    context = RunContext(
        run_id="external-run",
        session_id="thread-1",
        user_id="user-1",
        dependencies={
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                "externalRunId": "external-run",
                "threadId": "thread-1",
                "userId": "user-1",
                **tenant,
            }
        },
    )

    with pytest.raises(ReportingError) as raised:
        ReportWorkflowController._scope(context)

    assert raised.value.code == "report_workflow_context_missing"
