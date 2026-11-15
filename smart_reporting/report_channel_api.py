"""Opt-in channel invitation exchange for a host with connector authentication."""

import secrets
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .report_channel_invitation import Invitation
from .report_channel_repository import ReportChannelRepository


@dataclass(frozen=True)
class ConnectorIdentity:
    connector: str
    subject: str
    session: str


class ExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class IssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=256)


class ChannelMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=8000)


class DelegateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    instruction: str = Field(min_length=1, max_length=2000)


def create_report_channel_router(
    repository: ReportChannelRepository,
    authenticate: Callable[[Request], Awaitable[ConnectorIdentity | None]],
    *,
    authorize_editor: Callable[[Request], Awaitable[str | None]] | None = None,
    public_origin: str | None = None,
    editor_path: Callable[[str], str] | None = None,
    delegate_word: Callable[[str, ConnectorIdentity, DelegateRequest], Awaitable[dict]] | None = None,
    word_status: Callable[[str, ConnectorIdentity, str], Awaitable[dict]] | None = None,
) -> APIRouter:
    router = APIRouter()

    def report_editor_path(channel: str) -> str:
        path = editor_path(channel)
        parsed = urlsplit(path)
        segments = [unquote(segment) for segment in path.split("/")[2:]]
        if (not path.startswith("/reports/") or parsed.path != path or not segments
                or any(not segment or segment in {".", ".."} or re.search(r"[\x00-\x20\x7f/%\\\\?#]", segment)
                       for segment in segments)
                or (segments[:2] == ["v1", "native"] and len(segments) >= 4
                    and segments[2] in {"open", "download", "artifacts"})):
            raise HTTPException(500, "invalid_report_editor_path")
        return path

    async def require_member(request: Request, channel: str) -> ConnectorIdentity:
        identity = await authenticate(request)
        if identity is None:
            raise HTTPException(401, "connector_authentication_required")
        if not await repository.has_member(channel, identity):
            raise HTTPException(403, "report_channel_membership_required")
        return identity

    if delegate_word is not None:
        @router.post("/reports/v1/channels/{channel}/word-tasks", status_code=202)
        async def delegate(request: Request, channel: str, payload: DelegateRequest):
            identity = await require_member(request, channel)
            path = report_editor_path(channel) if editor_path is not None else None
            result = await delegate_word(channel, identity, payload)
            if path is not None:
                task_id = result["taskId"]
                await repository.conversation(channel, message=(task_id, task_id), editor_sender="word-task")
                return {**result, "reviewPath": f"{path}#word-task={quote(result['taskId'], safe='')}"}
            return result

    if word_status is not None:
        @router.get("/reports/v1/channels/{channel}/word-tasks/{task_id}")
        async def task_status(request: Request, channel: str, task_id: str):
            identity = await require_member(request, channel)
            return await word_status(channel, identity, task_id)

    @router.get("/reports/join")
    async def invitation_instructions():
        return {
            "version": 1,
            "action": "join-report-channel",
            "mcpTool": "join_report_channel",
            "referenceLocation": "fragment",
            "exchange": {"method": "POST", "path": "/reports/v1/channels/invitations/exchange"},
            "instructions": "通过连接器认证兑换邀请。加入后打开 editorPath，使用 messagesPath 在频道协作。",
        }

    async def conversation(request: Request, channel: str, after: int, message=None):
        if authorize_editor is not None and await authorize_editor(request) == channel:
            return await repository.conversation(channel, after=after, message=message)
        identity = await authenticate(request)
        if identity is None:
            raise HTTPException(401, "connector_authentication_required")
        try:
            return await repository.conversation(channel, member=identity, after=after, message=message)
        except ValueError:
            raise HTTPException(403, "report_channel_membership_required") from None

    @router.get("/reports/v1/channels/{channel}/messages")
    async def read_messages(request: Request, channel: str, after: int = 0):
        return await conversation(request, channel, after)

    @router.post("/reports/v1/channels/{channel}/messages")
    async def append_message(request: Request, channel: str, payload: ChannelMessage):
        return await conversation(request, channel, 0, (payload.message_id, payload.text))

    if authorize_editor is not None:
        @router.get("/reports/v1/native/{document_id}/{revision}/api/channels/editor-messages")
        @router.get("/reports/v1/channels/editor-messages")
        async def read_editor_messages(request: Request, after: int = 0):
            channel = await authorize_editor(request)
            if channel is None:
                raise HTTPException(403, "report_channel_editor_required")
            return await repository.conversation(channel, after=after)

        @router.post("/reports/v1/native/{document_id}/{revision}/api/channels/editor-messages", status_code=204)
        @router.post("/reports/v1/channels/editor-messages", status_code=204)
        async def post_editor_message(request: Request, payload: ChannelMessage):
            channel = await authorize_editor(request)
            if channel is None:
                raise HTTPException(403, "report_channel_editor_required")
            await repository.conversation(channel, message=(payload.message_id, payload.text))
            return Response(status_code=204)

    if authorize_editor is not None and public_origin is not None:
        @router.post("/reports/v1/native/{document_id}/{revision}/api/channels/invitations", status_code=201)
        @router.post("/reports/v1/channels/invitations", status_code=201)
        async def issue(request: Request, payload: IssueRequest):
            channel = await authorize_editor(request)
            if channel is None:
                raise HTTPException(403, "report_channel_editor_required")
            reference = secrets.token_urlsafe(32)
            expires_at = time.time() + 300
            await repository.issue(
                reference, Invitation(channel, payload.connector, payload.subject, expires_at),
            )
            return {"url": f"{public_origin.rstrip('/')}/reports/join#{reference}", "expiresAt": expires_at}

        @router.post("/reports/v1/native/{document_id}/{revision}/api/channels/revoke", status_code=204)
        @router.post("/reports/v1/channels/revoke", status_code=204)
        async def revoke(request: Request, payload: IssueRequest):
            channel = await authorize_editor(request)
            if channel is None:
                raise HTTPException(403, "report_channel_editor_required")
            await repository.revoke(channel, connector=payload.connector, subject=payload.subject)
            return Response(status_code=204)

    @router.post("/reports/v1/channels/invitations/exchange")
    async def exchange(request: Request, payload: ExchangeRequest):
        identity = await authenticate(request)
        if identity is None:
            raise HTTPException(401, "connector_authentication_required")
        paths = {}

        def validate_channel(channel: str) -> None:
            paths[channel] = report_editor_path(channel)

        try:
            member = await repository.exchange(
                payload.reference,
                connector=identity.connector,
                subject=identity.subject,
                session=identity.session,
                now=time.time(),
                **({"validate_channel": validate_channel} if editor_path is not None else {}),
            )
        except ValueError:
            raise HTTPException(403, "invalid_report_channel_invitation") from None
        if editor_path is None:
            return member
        return {
            "channel": member.channel,
            "editorPath": paths[member.channel],
            "messagesPath": f"/reports/v1/channels/{quote(member.channel, safe='')}/messages",
            **({"wordTasksPath": f"/reports/v1/channels/{quote(member.channel, safe='')}/word-tasks"}
               if delegate_word is not None else {}),
        }

    return router
