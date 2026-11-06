from __future__ import annotations

import asyncio

import pytest

from smart_reporting.reporting.models import ReportingError


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_verified_identity_is_task_local_and_resets_after_error():
    from smart_reporting.reporting.workflow.identity import (
        VerifiedReportingIdentity,
        bind_verified_reporting_identity,
        require_verified_reporting_identity,
    )

    async def request(company):
        identity = VerifiedReportingIdentity("warehouse", company, "7", "t", "http-capability")
        with bind_verified_reporting_identity(identity):
            await asyncio.sleep(0)
            assert require_verified_reporting_identity() == identity
            return require_verified_reporting_identity().company_id

    assert await asyncio.gather(request("100"), request("200")) == ["100", "200"]
    with pytest.raises(RuntimeError, match="request failed"):
        with bind_verified_reporting_identity(
            VerifiedReportingIdentity("warehouse", "100", "7", "t", "cli")
        ):
            raise RuntimeError("request failed")
    with pytest.raises(ReportingError, match="report_verified_identity_required"):
        require_verified_reporting_identity()


@pytest.mark.anyio
async def test_mcp_identity_comes_from_verified_token_and_checks_scope(monkeypatch):
    from smart_reporting.reporting.workflow import identity as module
    from smart_reporting.reporting_mcp.identity import CapabilityTokenVerifier
    from smart_reporting.tests.test_reporting_request_identity import SECRET, _capability

    token = await CapabilityTokenVerifier(SECRET).verify_token(_capability())
    assert token is not None
    monkeypatch.setattr(module, "get_access_token", lambda: token)
    identity = module.require_verified_reporting_identity()
    assert (identity.database, identity.company_id, identity.user_id, identity.thread_id) == (
        "odoo",
        "3",
        "7",
        "thread-1",
    )
    assert identity.entrypoint == "mcp"
    identity.require_scope("odoo", "3", "7", "thread-1")
    with pytest.raises(ReportingError, match="report_workflow_scope_mismatch"):
        identity.require_scope("odoo", "100", "7", "thread-1")


@pytest.mark.anyio
async def test_database_cli_requires_explicit_scope_before_reading_input():
    from smart_reporting.reporting.cli import run_cli
    from smart_reporting.runtime.settings import AgentSettings

    settings = AgentSettings.from_environment(
        {"AGENT_REPORT_CONFIGURATION_MODE": "database"}, load_env_file=False
    )

    def forbidden_read(_):
        raise AssertionError("缺少显式组织时不能开始报告")

    with pytest.raises(ReportingError, match="report_verified_identity_required"):
        await run_cli(settings=settings, read=forbidden_read)
