from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from fastmcp.server.auth import AccessToken

from smart_reporting.report_channel_api import ConnectorIdentity
from smart_reporting.report_channel_identity import REPORT_CHANNEL_SCOPE, channel_token_authenticator


@pytest.mark.anyio
@pytest.mark.parametrize(("scopes", "claims", "expires_at", "expected"), [
    ([REPORT_CHANNEL_SCOPE], {"session": "synthetic-session"}, 101,
     ConnectorIdentity("dsh", "synthetic-subject", "synthetic-session")),
    (["workflows:enterprise-reporting-workflow-v1:run"], {"session": "synthetic-session"}, 101, None),
    ([REPORT_CHANNEL_SCOPE], {"thread": "synthetic-session"}, 101, None),
    ([REPORT_CHANNEL_SCOPE], {"session": "synthetic-session"}, 100, None),
])
async def test_channel_authenticator_requires_channel_scope_and_verified_session(scopes, claims, expires_at, expected):
    token = AccessToken(token="synthetic-token", client_id="synthetic-client", subject="synthetic-subject",
                        scopes=scopes, claims=claims, expires_at=expires_at)
    verifier = AsyncMock()
    verifier.verify_token.return_value = token
    authenticate = channel_token_authenticator(verifier, connector="dsh", clock=lambda: 100)
    request = Request({"type": "http", "headers": [
        (b"authorization", b"Bearer synthetic-token"),
        (b"x-connector-session", b"untrusted-session"),
    ]})
    assert await authenticate(request) == expected
    verifier.verify_token.assert_awaited_once_with("synthetic-token")
