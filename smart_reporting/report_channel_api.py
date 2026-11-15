"""Opt-in channel invitation exchange for a host with connector authentication."""

import asyncio
import secrets
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .report_channel_invitation import Invitation
from .report_channel_acp import (
    ReportChannelAcpCapacity,
    ReportChannelAcpConflict,
    ReportChannelAcpDenied,
)
from .report_acp_client import ReportAcpError
from .report_channel_repository import ReportChannelRepository

if TYPE_CHECKING:
    from .report_channel_acp import ReportChannelAcp, ReportAcpConversation


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
    prepare_with_acp: bool = False


class AcpMessage(ChannelMessage):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReportChannelRouter(APIRouter):
    def __init__(self, authenticate: Callable[[Request], Awaitable[ConnectorIdentity | None]]):
        super().__init__()
        self.authenticate = authenticate
        self.acp_enabled = False


def create_report_channel_router(
    repository: ReportChannelRepository,
    authenticate: Callable[[Request], Awaitable[ConnectorIdentity | None]],
    *,
    authorize_editor: Callable[[Request], Awaitable[str | None]] | None = None,
    public_origin: str | None = None,
    editor_path: Callable[[str], str] | None = None,
    delegate_word: Callable[[str, ConnectorIdentity, DelegateRequest], Awaitable[dict]] | None = None,
    word_status: Callable[[str, ConnectorIdentity, str], Awaitable[dict]] | None = None,
    acp: "ReportChannelAcp | None" = None,
) -> ReportChannelRouter:
    router = ReportChannelRouter(authenticate)
    router.acp_enabled = acp is not None
    acp_conversations: dict[tuple[str, ConnectorIdentity], ReportAcpConversation] = {}
    acp_restore_lock = asyncio.Lock()

    async def acp_turn(channel: str, identity: ConnectorIdentity, text: str, message_id: str) -> str:
        bound = acp_conversations.get((channel, identity))
        if bound is None and acp is not None:
            async with acp_restore_lock:
                # Two requests may arrive before the first restore completes.
                # Reuse the same conversation instance within this worker.
                bound = acp_conversations.get((channel, identity))
                if bound is None:
                    bound = await acp.restore(channel, identity)
                    if bound is not None:
                        acp_conversations[(channel, identity)] = bound
        if bound is None:
            raise HTTPException(403, "report_channel_membership_required")
        try:
            return await bound.prompt(identity, text, message_id=message_id)
        except ReportChannelAcpDenied:
            raise HTTPException(403, "report_channel_membership_required") from None
        except ReportChannelAcpConflict as error:
            raise HTTPException(409, str(error)) from None
        except ReportChannelAcpCapacity as error:
            raise HTTPException(429, str(error)) from None
        except (ReportAcpError, TimeoutError, OSError):
            raise HTTPException(502, "report_channel_acp_unavailable") from None

    if acp is not None:
        @router.post("/reports/v1/channels/{channel}/acp/messages")
        async def acp_message(request: Request, channel: str, payload: AcpMessage):
            identity = await authenticate(request)
            if identity is None:
                raise HTTPException(401, "connector_authentication_required")
            return {"reply": await acp_turn(channel, identity, payload.text, "chat:" + payload.message_id)}

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
            if payload.prepare_with_acp:
                if acp is None:
                    raise HTTPException(422, "report_channel_acp_unavailable")
                instruction = await acp_turn(
                    channel, identity,
                    "Rewrite the following request as one concise instruction for a Word "
                    "report assistant. Return only the instruction. Keep the requested scope "
                    "and facts unchanged. Do not use tools.\n\n" + payload.instruction,
                    "word:" + payload.request_id,
                )
                instruction = instruction.strip()
                if not instruction or len(instruction) > 2000:
                    raise HTTPException(502, "report_channel_acp_instruction_invalid")
                payload = DelegateRequest(request_id=payload.request_id, instruction=instruction)
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
    async def invitation_instructions(response: Response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        if router.acp_enabled:
            return {
                "version": 1,
                "action": "join-report-channel",
                "referenceLocation": "fragment",
                "authentication": "host-issued-connector-bearer",
                "exchange": {
                    "method": "POST",
                    "path": "/reports/v1/channels/invitations/exchange",
                    "referenceField": "reference",
                },
                "conversation": {
                    "method": "POST", "pathField": "acpMessagesPath",
                    "messageField": "text", "messageIdField": "message_id", "replyField": "reply",
                    "agentProtocol": "acp",
                },
                **({
                    "wordCandidates": {
                        "method": "POST",
                        "pathField": "wordTasksPath",
                        "requestFields": ["request_id", "instruction"],
                        "prepareWithAcpField": "prepare_with_acp",
                        "status": {"method": "GET", "pathSuffix": "/{taskId}"},
                        "reviewPathField": "reviewPath",
                    },
                } if delegate_word is not None and word_status is not None and editor_path is not None else {}),
                "savePolicy": "human-review-accept-save",
            }
        return {
            "version": 1,
            "action": "join-report-channel",
            "mcpTool": "join_report_channel",
            "referenceLocation": "fragment",
            "exchange": {"method": "POST", "path": "/reports/v1/channels/invitations/exchange"},
            "mcp": {
                "path": "/reports/channel-mcp", "transport": "streamable-http",
                "authentication": "host-issued-connector-bearer", "automaticSetup": False,
            },
            "join": {"tool": "join_report_channel", "argument": "share_link", "value": "complete-original-share-link"},
            "workflow": [
                {"action": "open-editor", "resultField": "editorUrl", "requires": "authorized-browser-editor-session"},
                {"tool": "delegate_report_word_task", "arguments": ["channel", "request_id", "instruction"]},
                {"tool": "report_word_task_status", "arguments": ["channel", "task_id"]},
                {"action": "present-candidate", "resultField": "reviewUrl", "requires": "human-review"},
                {"action": "reopen-and-verify", "requires": "human-save"},
            ],
            "conversation": {"readTool": "read_report_channel", "postTool": "post_report_channel_message"},
            "savePolicy": "human-review-accept-save",
            "instructions": (
                "这是报告频道的接入说明，读取此页面不会兑换邀请，也不代表已经加入。"
                "MCP 地址相对于此链接来源解析；使用客户端受支持的连接器配置和宿主认证流程接入，"
                "不要在聊天中索取密码或令牌。链接不能自动安装连接器，也不能代替身份认证。"
                "接入后把用户提供的完整原始链接（保留 # 后的片段）作为 share_link 传给 join_report_channel；"
                "片段不会随网页请求发送，不能从此页面恢复。"
                "使用返回的 channel 进行聊天与任务委派。通过客户端受支持的浏览器操作打开 editorUrl；"
                "浏览器须具备该报告的编辑会话，必要时走宿主正常登录流程。文本抓取不算打开编辑器。"
                "智能报告助手负责生成 Word 候选；用返回的 taskId 查询进度，向用户展示 reviewUrl。"
                "用户审阅、采纳并保存后重新打开核对；不得自动替用户采纳或宣称未经验证的保存成功。"
            ),
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
            for key in list(acp_conversations):
                bound_channel, identity = key
                if (bound_channel, identity.connector, identity.subject) == (
                    channel, payload.connector, payload.subject,
                ):
                    acp_conversations.pop(key, None)
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
        acp_result = {}
        if acp is not None:
            try:
                bound = await acp.bind(member.channel, identity)
            except ReportChannelAcpDenied:
                raise HTTPException(403, "report_channel_membership_required") from None
            key = (member.channel, identity)
            previous = acp_conversations.get(key)
            if previous is None or not bound.matches_binding(previous):
                acp_conversations[key] = bound
            acp_result["acpMessagesPath"] = (
                f"/reports/v1/channels/{quote(member.channel, safe='')}/acp/messages"
            )
        return {
            "channel": member.channel,
            **acp_result,
            **({"editorPath": paths[member.channel]} if editor_path is not None else {}),
            "messagesPath": f"/reports/v1/channels/{quote(member.channel, safe='')}/messages",
            **({"wordTasksPath": f"/reports/v1/channels/{quote(member.channel, safe='')}/word-tasks"}
               if delegate_word is not None else {}),
        }

    return router
