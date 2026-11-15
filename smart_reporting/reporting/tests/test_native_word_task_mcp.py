"""Word-purpose ticket and actual MCP tool boundary."""
from importlib import import_module, util

import pytest


def adapter():
    name = 'smart_reporting.report_editor.native_word_task_mcp'
    assert util.find_spec(name) is not None, 'trusted Word MCP adapter missing'
    return import_module(name)


def test_word_ticket_is_purpose_bound_short_lived_and_tamper_proof():
    module = adapter()
    codec = module.WordTaskTicketCodec('s' * 32, clock=lambda: 100)
    principal = {'taskId': 'task', 'scope': {'database': 'db', 'companyId': 'co',
        'userId': 'u', 'threadId': 't'}, 'inputSha256': 'a' * 64, 'owner': 'owner',
        'epoch': 1, 'runId': 'run', 'attempt': 0, 'stateVersion': 2}
    token = codec.issue(principal, expires_at=120)
    assert codec.verify(token) == principal
    with pytest.raises(ValueError):
        codec.verify(token + 'x')
    with pytest.raises(ValueError):
        codec.issue(principal, expires_at=161)
    with pytest.raises(ValueError):
        module.WordTaskTicketCodec('other' * 8, clock=lambda: 100).verify(token)
    with pytest.raises(ValueError):
        module.WordTaskTicketCodec('s' * 32, clock=lambda: 120).verify(token)


@pytest.mark.anyio
async def test_real_mcp_tools_require_full_read_and_current_authority():
    from fastmcp import Client

    module = adapter()
    assert hasattr(module, 'WordTaskMcpBridge'), 'trusted Word MCP bridge missing'
    principal = {'taskId': 'task', 'scope': {'database': 'db', 'companyId': 'co',
        'userId': 'u', 'threadId': 't'}, 'inputSha256': 'a' * 64, 'owner': 'owner',
        'epoch': 1, 'runId': 'run', 'attempt': 0, 'stateVersion': 2}
    active = True
    async def authorize():
        if not active:
            raise ValueError('cancelled')
        return principal
    selected = [{'blockId': 'p1', 'type': 'paragraph', 'text': 'Source',
        'expectedObjectSha256': 'b' * 64, 'allowedOperations': ['replaceParagraph'],
        'before': [], 'after': [], 'styleChanges': [], 'draftOperations': []}]
    codec = module.WordTaskTicketCodec('s' * 32, clock=lambda: 100)
    token = codec.issue(principal, expires_at=120)
    bridge = module.WordTaskMcpBridge(selected=selected, principal=principal, authorize=authorize,
        codec=codec, request_token=lambda: token, enabled=True)
    async with Client(bridge.server) as client:
        assert {tool.name for tool in await client.list_tools()} == {
            'get_document_context', 'read_blocks', 'search_text', 'propose_operations'}
        args = {'task_id': 'task', 'summary': 'Edit', 'operations': [
            {'kind': 'replaceParagraph', 'blockId': 'p1', 'text': 'Candidate'}]}
        assert (await client.call_tool('propose_operations', args, raise_on_error=False)).is_error
        assert (await client.call_tool('read_blocks', {'task_id': 'task', 'block_ids': ['p1']})).is_error is False
        result = await client.call_tool('propose_operations', args)
        assert not result.is_error
        active = False
        with pytest.raises(ValueError):
            await bridge.reconcile(bridge.registered_proposal, ticket=token)
        assert (await client.call_tool('read_blocks', {'task_id': 'task', 'block_ids': ['p1']},
                                       raise_on_error=False)).is_error


@pytest.mark.anyio
async def test_mcp_rejects_signed_ticket_for_another_task_before_tool_read():
    from fastmcp import Client

    module = adapter()
    codec = module.WordTaskTicketCodec('s' * 32, clock=lambda: 100)
    principal = {'taskId': 'task', 'scope': {'database': 'db', 'companyId': 'co',
        'userId': 'u', 'threadId': 't'}, 'inputSha256': 'a' * 64, 'owner': 'owner',
        'epoch': 1, 'runId': 'run', 'attempt': 0, 'stateVersion': 2}
    token = codec.issue({**principal, 'taskId': 'foreign'}, expires_at=120)
    calls = 0
    async def authorize():
        nonlocal calls
        calls += 1
        return principal
    selected = [{'blockId': 'p1', 'type': 'paragraph', 'text': 'Source',
        'expectedObjectSha256': 'b' * 64, 'allowedOperations': ['replaceParagraph']}]
    assert 'codec' in __import__('inspect').signature(module.WordTaskMcpBridge).parameters
    bridge = module.WordTaskMcpBridge(selected=selected, principal=principal, authorize=authorize,
        codec=codec, request_token=lambda: token, enabled=True)
    async with Client(bridge.server) as client:
        assert (await client.call_tool('read_blocks', {'task_id': 'task', 'block_ids': ['p1']},
                                      raise_on_error=False)).is_error
    assert calls == 0


@pytest.mark.anyio
async def test_ticket_cannot_expire_during_async_authorization_and_still_read():
    from fastmcp import Client

    module = adapter()
    now = 100
    codec = module.WordTaskTicketCodec('s' * 32, clock=lambda: now)
    principal = {'taskId': 'task', 'scope': {'database': 'db', 'companyId': 'co',
        'userId': 'u', 'threadId': 't'}, 'inputSha256': 'a' * 64, 'owner': 'owner',
        'epoch': 1, 'runId': 'run', 'attempt': 0, 'stateVersion': 2}
    token = codec.issue(principal, expires_at=110)
    async def authorize():
        nonlocal now
        now = 111
        return principal
    selected = [{'blockId': 'p1', 'type': 'paragraph', 'text': 'Source',
        'expectedObjectSha256': 'b' * 64, 'allowedOperations': ['replaceParagraph']}]
    bridge = module.WordTaskMcpBridge(selected=selected, principal=principal, authorize=authorize,
        codec=codec, request_token=lambda: token, enabled=True)
    async with Client(bridge.server) as client:
        assert (await client.call_tool('read_blocks', {'task_id': 'task', 'block_ids': ['p1']},
                                      raise_on_error=False)).is_error


@pytest.mark.anyio
async def test_actual_http_mcp_authentication_uses_request_bearer_not_server_assumption():
    from fastmcp.utilities.tests import asgi_server

    module = adapter()
    codec = module.WordTaskTicketCodec('s' * 32)
    principal = {'taskId': 'task', 'scope': {'database': 'db', 'companyId': 'co',
        'userId': 'u', 'threadId': 't'}, 'inputSha256': 'a' * 64, 'owner': 'owner',
        'epoch': 1, 'runId': 'run', 'attempt': 0, 'stateVersion': 2}
    import time
    ticket = codec.issue(principal, expires_at=time.time() + 30)
    async def authorize():
        return principal
    selected = [{'blockId': 'p1', 'type': 'paragraph', 'text': 'Source',
        'expectedObjectSha256': 'b' * 64, 'allowedOperations': ['replaceParagraph']}]
    bridge = module.WordTaskMcpBridge(selected=selected, principal=principal, authorize=authorize,
                                    codec=codec, enabled=True)
    async with asgi_server(bridge.server) as server:
        async with server.client(auth=ticket) as client:
            assert not (await client.call_tool('read_blocks', {'task_id': 'task', 'block_ids': ['p1']})).is_error
        with pytest.raises(Exception):
            async with server.client(auth=ticket + 'tampered') as client:
                await client.list_tools()
