import asyncio

import pytest
from fastmcp import FastMCP
from fastmcp.utilities.tests import ASGIServer

from smart_reporting.external_word_transport import ExternalWordTransport


class Server:
    def __init__(self):
        self.ready = asyncio.Event()

    def http_app(self, **options):
        self.ready.set()
        return options


def test_expired_invitation_cannot_exchange_or_reserve_task_forever():
    now = 0
    transport = ExternalWordTransport(clock=lambda: now)
    expired = transport.invite(task_id="synthetic-a", subject="client-a")
    now = 60
    replacement = transport.invite(task_id="synthetic-a", subject="client-a")
    assert replacement != expired
    with pytest.raises(ValueError):
        transport.redeem(expired, subject="client-a")


@pytest.mark.anyio
async def test_invitation_is_bound_and_redeemed_once():
    transport = ExternalWordTransport()
    invite = transport.invite(task_id="synthetic-a", subject="client-a")
    server = Server()
    run = asyncio.create_task(transport.run(
        server=server, ticket="synthetic-ticket", task_id="synthetic-a",
        instruction="Edit the synthetic report", registered_proposal=lambda: {"synthetic": True},
    ))
    try:
        await asyncio.wait_for(server.ready.wait(), 1)
        with pytest.raises(ValueError):
            transport.redeem(invite, subject="client-b")
        assert transport.redeem(invite, subject="client-a").ticket == "synthetic-ticket"
        transport.assert_authorized("synthetic-a", ticket="synthetic-ticket")
        with pytest.raises(ValueError):
            transport.assert_authorized("synthetic-a", ticket="previous-attempt-ticket")
        with pytest.raises(ValueError):
            transport.redeem(invite, subject="client-a")
        transport.complete("synthetic-a", subject="client-a")
        assert await asyncio.wait_for(run, 1) == {"synthetic": True}
    finally:
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)


@pytest.mark.anyio
async def test_revoking_invitation_closes_waiting_run_and_denies_exchange():
    transport = ExternalWordTransport()
    invite = transport.invite(task_id="synthetic-a", subject="client-a")
    server = Server()
    run = asyncio.create_task(transport.run(
        server=server, ticket="synthetic-ticket", task_id="synthetic-a",
        instruction="Edit the synthetic report", registered_proposal=lambda: None,
    ))
    await asyncio.wait_for(server.ready.wait(), 1)
    access = transport.redeem(invite, subject="client-a")
    assert transport.is_pending_candidate("synthetic-a", ticket=access.ticket)
    transport.revoke("synthetic-a", ticket=access.ticket)
    with pytest.raises(ValueError):
        await asyncio.wait_for(run, 1)
    with pytest.raises(ValueError):
        transport.redeem(invite, subject="client-a")
    with pytest.raises(ValueError):
        transport.assert_authorized("synthetic-a", ticket=access.ticket)


@pytest.mark.anyio
async def test_private_streamable_http_routes_only_to_redeemed_task():
    transport = ExternalWordTransport()
    invite = transport.invite(task_id="synthetic-a", subject="client-a")
    transport.invite(task_id="synthetic-b", subject="client-b")
    ready = asyncio.Event()
    server = FastMCP("synthetic-report-a")
    proposal = {}

    @server.tool
    def propose_operations() -> dict:
        transport.assert_authorized("synthetic-a", ticket="synthetic-ticket")
        proposal.update(summary="Synthetic report A candidate")
        return proposal

    class ReadyServer:
        def http_app(self, **options):
            app = server.http_app(**options)
            ready.set()
            return app

    run = asyncio.create_task(transport.run(
        server=ReadyServer(), ticket="synthetic-ticket", task_id="synthetic-a",
        instruction="Edit A", registered_proposal=lambda: proposal or None,
    ))
    try:
        await asyncio.wait_for(ready.wait(), 2)
        transport.redeem(invite, subject="client-a")
        with pytest.raises(ValueError):
            transport.app_for_task("synthetic-a", subject="client-b")
        with pytest.raises(ValueError):
            transport.app_for_task("synthetic-b", subject="client-a")
        with pytest.raises(ValueError):
            transport.complete("synthetic-a", subject="client-a")
        app = transport.app_for_task("synthetic-a", subject="client-a")
        endpoint = ASGIServer(url="http://synthetic.test/mcp", app=app, transport_type="http")
        async with app.router.lifespan_context(app):
            async with endpoint.client() as client:
                await client.call_tool("propose_operations", {})
        transport.complete("synthetic-a", subject="client-a")
        assert await asyncio.wait_for(run, 2) == {"summary": "Synthetic report A candidate"}
    finally:
        transport.revoke("synthetic-a")
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)
