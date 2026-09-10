from types import SimpleNamespace

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow import scope as scope_module
from smart_reporting.reporting.workflow.scope import (
    reporting_scope_keys,
    resolve_reporting_workflow_scope,
)


def test_scope_keys_isolate_tenants_users_threads_and_runs() -> None:
    first = reporting_scope_keys(
        database="db-a",
        company_id="company-a",
        user_id="user-a",
        thread_id="thread-1",
        run_id="run-1",
    )

    assert first.thread_lease_key != reporting_scope_keys(
        database="db-b",
        company_id="company-a",
        user_id="user-a",
        thread_id="thread-1",
        run_id="run-1",
    ).thread_lease_key
    assert first.thread_lease_key != reporting_scope_keys(
        database="db-a",
        company_id="company-b",
        user_id="user-a",
        thread_id="thread-1",
        run_id="run-1",
    ).thread_lease_key
    assert first.thread_lease_key != reporting_scope_keys(
        database="db-a",
        company_id="company-a",
        user_id="user-b",
        thread_id="thread-1",
        run_id="run-1",
    ).thread_lease_key
    second_run = reporting_scope_keys(
        database="db-a",
        company_id="company-a",
        user_id="user-a",
        thread_id="thread-1",
        run_id="run-2",
    )
    assert first.thread_lease_key == second_run.thread_lease_key
    assert first.workspace_key != second_run.workspace_key


def test_mcp_capability_binds_workflow_session_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scope_module,
        "get_access_token",
        lambda: SimpleNamespace(
            claims={
                "database": "db-a",
                "company": "company-a",
                "user": "user-a",
                "thread": "thread-a",
            }
        ),
    )

    with pytest.raises(ReportingError) as raised:
        resolve_reporting_workflow_scope(
            run_id="run-a",
            session_id="thread-b",
            user_id="user-a",
        )

    assert raised.value.code == "report_mcp_thread_mismatch"
