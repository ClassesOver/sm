"""Adapt a host's connector token verifier to report-channel identity."""

import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastmcp.server.auth import TokenVerifier

from .report_channel_api import ConnectorIdentity

REPORT_CHANNEL_SCOPE = "reports:channel:join"


def channel_token_authenticator(
    verifier: TokenVerifier, *, connector: str, clock: Callable[[], float] = time.time,
) -> Callable[[Request], Awaitable[ConnectorIdentity | None]]:
    async def authenticate(request: Request) -> ConnectorIdentity | None:
        scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not bearer or any(char.isspace() for char in bearer):
            return None
        token = await verifier.verify_token(bearer)
        if token is None or REPORT_CHANNEL_SCOPE not in token.scopes:
            return None
        if token.expires_at is not None and token.expires_at <= clock():
            return None
        subject = token.subject
        session = token.claims.get("session")
        if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
            return None
        if not isinstance(session, str) or not 1 <= len(session) <= 256:
            return None
        return ConnectorIdentity(connector, subject, session)

    return authenticate
