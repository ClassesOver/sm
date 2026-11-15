"""Persistence for connector invitations and their resulting channel membership."""

import hashlib
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from .report_channel_invitation import ChannelMember, Invitation

metadata = MetaData()
invitations = Table(
    "report_channel_invitations_v1",
    metadata,
    Column("digest", String(64), primary_key=True),
    Column("channel", String(256), nullable=False),
    Column("connector", String(64), nullable=False),
    Column("subject", String(256), nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("session", String(256)),
)
messages = Table(
    "report_channel_messages_v1", metadata,
    Column("sequence", Integer, primary_key=True),
    Column("channel", String(256), nullable=False, index=True),
    Column("sender", String(64), nullable=False),
    Column("message_id", String(128), nullable=False),
    Column("text", Text, nullable=False),
)
Index("report_channel_message_identity_v1", messages.c.channel, messages.c.sender, messages.c.message_id, unique=True)

acp_bindings = Table(
    "report_channel_acp_bindings_v1",
    metadata,
    Column("grant_digest", String(64), ForeignKey(invitations.c.digest, ondelete="CASCADE"), primary_key=True),
    Column("session_id", String(256)),
)
acp_receipts = Table(
    "report_channel_acp_receipts_v1",
    metadata,
    Column("grant_digest", String(64),
           ForeignKey(acp_bindings.c.grant_digest, ondelete="CASCADE"), primary_key=True),
    Column("message_id", String(133), primary_key=True),
    Column("request_digest", String(64), nullable=False),
    Column("reply", Text),
)


@dataclass(frozen=True)
class ReportChannelAcpBinding:
    session_id: str | None


@dataclass(frozen=True)
class ReportChannelAcpReceipt:
    request_digest: str
    reply: str | None


class ReportChannelRepository:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    @staticmethod
    def _membership(channel, member):
        return select(invitations.c.digest).where(
            invitations.c.channel == channel,
            invitations.c.connector == member.connector,
            invitations.c.subject == member.subject,
            invitations.c.session == member.session,
        ).order_by(invitations.c.expires_at, invitations.c.digest).limit(1)

    async def has_member(self, channel, member) -> bool:
        return await self.member_grant(channel, member) is not None

    async def member_grant(self, channel, member) -> str | None:
        async with self.engine.connect() as connection:
            return await connection.scalar(self._membership(channel, member))

    async def grant_active(self, digest: str) -> bool:
        async with self.engine.connect() as connection:
            return await connection.scalar(select(invitations.c.digest).where(
                invitations.c.digest == digest, invitations.c.session.is_not(None),
            )) is not None

    async def enable_acp_binding(self, digest: str) -> bool:
        async with self.engine.begin() as connection:
            # Serialize creation with deletion of the invitation that owns this binding.
            grant = await connection.scalar(select(invitations.c.digest).where(
                invitations.c.digest == digest, invitations.c.session.is_not(None),
            ).with_for_update())
            if grant is None:
                return False
            await connection.execute(insert(acp_bindings).values(grant_digest=grant)
                                     .on_conflict_do_nothing(index_elements=["grant_digest"]))
            return True

    async def acp_binding(self, digest: str) -> ReportChannelAcpBinding | None:
        async with self.engine.connect() as connection:
            binding = (await connection.execute(select(acp_bindings.c.session_id).where(
                acp_bindings.c.grant_digest == digest,
            ))).one_or_none()
            return None if binding is None else ReportChannelAcpBinding(binding.session_id)

    async def set_acp_session(self, digest: str, session_id: str) -> bool:
        if not session_id or len(session_id) > 256:
            raise ValueError("Invalid ACP session ID")
        async with self.engine.begin() as connection:
            saved = await connection.scalar(update(acp_bindings).where(
                acp_bindings.c.grant_digest == digest,
                acp_bindings.c.session_id.is_(None) | (acp_bindings.c.session_id == session_id),
            ).values(session_id=session_id).returning(acp_bindings.c.grant_digest))
            return saved is not None

    async def acp_receipt(self, digest: str, message_id: str) -> ReportChannelAcpReceipt | None:
        async with self.engine.connect() as connection:
            row = (await connection.execute(select(
                acp_receipts.c.request_digest, acp_receipts.c.reply,
            ).where(
                acp_receipts.c.grant_digest == digest, acp_receipts.c.message_id == message_id,
            ))).one_or_none()
            return None if row is None else ReportChannelAcpReceipt(row.request_digest, row.reply)

    async def reserve_acp_turn(
        self, digest: str, message_id: str, request_digest: str, *, limit: int,
    ) -> Literal["created", "existing", "full", "unavailable"]:
        async with self.engine.begin() as connection:
            binding = await connection.scalar(select(acp_bindings.c.grant_digest).where(
                acp_bindings.c.grant_digest == digest, acp_bindings.c.session_id.is_not(None),
            ).with_for_update())
            if binding is None:
                return "unavailable"
            scoped = acp_receipts.c.grant_digest == digest
            if await connection.scalar(select(acp_receipts.c.message_id).where(
                scoped, acp_receipts.c.message_id == message_id,
            )) is not None:
                return "existing"
            count = await connection.scalar(select(func.count()).select_from(acp_receipts).where(scoped))
            if count >= limit:
                return "full"
            await connection.execute(insert(acp_receipts).values(
                grant_digest=digest, message_id=message_id, request_digest=request_digest,
            ))
            return "created"

    async def complete_acp_turn(
        self, digest: str, message_id: str, request_digest: str, reply: str,
    ) -> bool:
        async with self.engine.begin() as connection:
            saved = await connection.scalar(update(acp_receipts).where(
                acp_receipts.c.grant_digest == digest, acp_receipts.c.message_id == message_id,
                acp_receipts.c.request_digest == request_digest, acp_receipts.c.reply.is_(None),
            ).values(reply=reply).returning(acp_receipts.c.message_id))
            return saved is not None

    @asynccontextmanager
    async def acp_turn_lock(self, digest: str):
        # This lock is separate from revocation; authorization is checked again after ACP returns.
        async with self.engine.begin() as connection:
            locked = await connection.scalar(select(
                func.pg_try_advisory_xact_lock(func.hashtextextended(digest, 8181)),
            ))
            yield bool(locked)

    async def revoke(self, channel: str, *, connector: str, subject: str) -> None:
        """Invalidate pending invitations and redeemed sessions for this subject."""
        async with self.engine.begin() as connection:
            await connection.execute(select(func.pg_advisory_xact_lock(func.hashtext(channel))))
            await connection.execute(delete(invitations).where(
                invitations.c.channel == channel,
                invitations.c.connector == connector,
                invitations.c.subject == subject,
            ))

    async def conversation(self, channel, *, member=None, after=0, message=None, editor_sender="editor"):
        async with self.engine.begin() as connection:
            # Serialize appends within the channel so a cursor cannot skip a late commit.
            await connection.execute(select(func.pg_advisory_xact_lock(func.hashtext(channel))))
            sender = editor_sender
            if member is not None:
                digest = await connection.scalar(self._membership(channel, member))
                if digest is None:
                    raise ValueError("report_channel_membership_required")
                sender = hashlib.sha256(
                    repr((member.connector, member.subject, member.session)).encode()
                ).hexdigest()
            if message is not None:
                message_id, body = message
                await connection.execute(insert(messages).values(
                    channel=channel, sender=sender, message_id=message_id, text=body,
                ).on_conflict_do_nothing(index_elements=["channel", "sender", "message_id"]))
            rows = await connection.execute(select(messages).where(
                messages.c.channel == channel, messages.c.sequence > after,
            ).order_by(messages.c.sequence).limit(100))
            return [dict(row) for row in rows.mappings()]

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)

    async def issue(self, reference: str, invitation: Invitation) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(select(func.pg_advisory_xact_lock(func.hashtext(invitation.channel))))
            await connection.execute(invitations.insert().values(
                digest=hashlib.sha256(reference.encode()).hexdigest(),
                channel=invitation.channel,
                connector=invitation.connector,
                subject=invitation.subject,
                expires_at=invitation.expires_at,
            ))

    async def exchange(
        self, reference: str, *, connector: str, subject: str, session: str, now: float,
        validate_channel: Callable[[str], None] | None = None,
    ) -> ChannelMember:
        if not session or len(session) > 256:
            raise ValueError("invalid_report_channel_invitation")
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(invitations).where(
                    invitations.c.digest == hashlib.sha256(reference.encode()).hexdigest(),
                    invitations.c.connector == connector,
                    invitations.c.subject == subject,
                    invitations.c.expires_at > now,
                    invitations.c.session.is_(None),
                ).values(session=session).returning(invitations.c.channel)
            )
            channel = result.scalar_one_or_none()
            if channel is None:
                raise ValueError("invalid_report_channel_invitation")
            if validate_channel is not None:
                validate_channel(channel)
        return ChannelMember(channel, connector, subject, session)
