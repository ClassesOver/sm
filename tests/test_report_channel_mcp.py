from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastmcp.exceptions import ToolError
from fastmcp.utilities.tests import asgi_server

from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router
from smart_reporting.report_channel_invitation import ChannelMember
from smart_reporting.report_channel_mcp import create_report_channel_mcp


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_configured_mcp_client_can_join_and_delegate_with_scoped_identity(mode):
    origin = "https://reports.test"
    identity = ConnectorIdentity("dsh", "subscriber", "synthetic-session")
    async def exchange(reference, *, validate_channel, **kwargs):
        validate_channel("a")
        return ChannelMember("a", identity.connector, identity.subject, identity.session)

    repository = SimpleNamespace(
        exchange=AsyncMock(side_effect=exchange),
        conversation=AsyncMock(),
        has_member=AsyncMock(side_effect=lambda channel, actor: channel == "a" and actor == identity),
    )

    async def authenticate(request):
        if request.headers.get("authorization") == "Bearer synthetic-connector":
            return identity
        return None

    delegate = AsyncMock(return_value={"taskId": "word-task", "status": "running", "accepted": False})
    app = FastAPI()
    app.include_router(create_report_channel_router(repository, authenticate,
        editor_path=lambda channel: f"/reports/native/{channel}", delegate_word=delegate))
    server = create_report_channel_mcp(app, origin=origin)
    async with asgi_server(server) as endpoint:
        async with endpoint.client(auth="wrong-synthetic-connector", mode=mode) as client:
            with pytest.raises(ToolError, match="401"):
                await client.call_tool("join_report_channel", {"share_link": f"{origin}/reports/join#" + "A" * 43})
            repository.exchange.assert_not_awaited()
        async with endpoint.client(auth="synthetic-connector", mode=mode) as client:
            instructions = client.instructions or ""
            if mode == "legacy":
                assert (await client.initialize()).instructions == instructions
            for term in ("join_report_channel", "editorUrl", "report editor session",
                         "report_word_task_status", "reviewUrl"):
                assert term in instructions
            tools = {tool.name for tool in await client.list_tools()}
            assert tools == {"join_report_channel", "delegate_report_word_task", "report_word_task_status",
                             "read_report_channel", "post_report_channel_message"}
            join = {"share_link": f"{origin}/reports/join#" + "A" * 43}
            with pytest.raises(ToolError, match="invalid_report_channel_invitation"):
                await client.call_tool("join_report_channel", {"share_link": join["share_link"].replace("reports.test", "other.test")})
            repository.exchange.assert_not_awaited()
            receipt = await client.call_tool("join_report_channel", join)
            joined = receipt.data
            assert joined == {"channel": "a", "editorUrl": f"{origin}/reports/native/a"}
            assert receipt.content[0].type == "resource_link"
            assert str(receipt.content[0].uri) == joined["editorUrl"]
            payload = {"channel": "other", "request_id": "one", "instruction": "Update synthetic text"}
            with pytest.raises(ToolError, match="403"):
                await client.call_tool("delegate_report_word_task", payload)
            delegate.assert_not_awaited()
            receipt = await client.call_tool("delegate_report_word_task", {**payload, "channel": "a"})
            delegated = receipt.data
            assert delegated["reviewUrl"] == f"{origin}/reports/native/a#word-task=word-task"
            assert receipt.content[0].type == "resource_link"
            assert str(receipt.content[0].uri) == delegated["reviewUrl"]
            repository.conversation.assert_awaited_once_with("a", message=("word-task", "word-task"),
                                                            editor_sender="word-task")
