"""Persistence for connector invitations and their resulting channel membership."""

import hashlib
from collections.abc import Callable

from sqlalchemy import (
    Column,
    Float,
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
