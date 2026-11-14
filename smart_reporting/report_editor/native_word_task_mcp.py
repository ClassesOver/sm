"""Word-only bearer and four business MCP tools; no listener/provider or file tools.

This restricts business MCP authority, not Codex native builtin tools. Only an
independently isolated runtime may consume a ticket. No bearer is logged here.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from ..task_execution.native_word_contracts import NativeWordScope, canonical_bytes
from .native_word_ai import NativeWordAIProposal, NativeWordAITools, word_candidate


def _error():
    return ValueError('native_word_task_unauthorized')


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def _principal(value):
    keys = {'taskId', 'scope', 'inputSha256', 'owner', 'epoch', 'runId', 'attempt', 'stateVersion'}
    if not isinstance(value, dict) or set(value) != keys:
        raise _error()
    result = json.loads(canonical_bytes(value))
    for key in ('taskId', 'owner', 'runId'):
        if not isinstance(result[key], str) or not 1 <= len(result[key]) <= 256:
            raise _error()
    if (not isinstance(result['inputSha256'], str) or len(result['inputSha256']) != 64
            or any(c not in '0123456789abcdef' for c in result['inputSha256'])):
        raise _error()
    for key in ('epoch', 'attempt', 'stateVersion'):
        if type(result[key]) is not int or result[key] < (1 if key == 'epoch' else 0):
            raise _error()
    NativeWordScope.model_validate(result['scope'])
    return result


class WordTaskTicketCodec:
    """Independent Word key required; never reuse Reporting/workflow signing keys."""
    def __init__(self, secret: str, *, clock: Callable[[], float] = time.time):
        if not isinstance(secret, str) or len(secret.encode()) < 32:
            raise _error()
        self._key, self._clock = secret.encode(), clock

    def issue(self, principal: dict[str, Any], *, expires_at: float) -> str:
        now = self._clock()
        if (type(expires_at) not in (int, float) or not math.isfinite(expires_at)
                or not now < expires_at <= now + 60):
            raise _error()
        payload = {'aud': 'native-word-task-mcp-v1', 'iat': now, 'exp': expires_at,
                   'principal': _principal(principal)}
        body = _b64(canonical_bytes(payload))
        signature = hmac.new(self._key, body.encode(), hashlib.sha256).digest()
        return body + '.' + _b64(signature)

    def verify(self, token: str) -> dict[str, Any]:
        try:
            if not isinstance(token, str) or len(token) > 8192:
                raise _error()
            body, signature = token.split('.')
            expected = _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(expected, signature):
                raise _error()
            payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
            now = self._clock()
            if (set(payload) != {'aud', 'iat', 'exp', 'principal'}
                    or payload['aud'] != 'native-word-task-mcp-v1'
                    or type(payload['iat']) not in (int, float) or type(payload['exp']) not in (int, float)
                    or not payload['iat'] <= now < payload['exp'] <= payload['iat'] + 60):
                raise _error()
            return _principal(payload['principal'])
        except Exception:
            raise _error() from None



class WordTaskTokenVerifier(TokenVerifier):
    def __init__(self, codec):
        super().__init__()
        self.codec = codec

    async def verify_token(self, token):
        try:
            principal = self.codec.verify(token)
            return AccessToken(token=token, client_id=principal['taskId'], scopes=['word:candidate'],
                               claims={'wordPrincipal': principal})
        except ValueError:
            return None


def _request_bearer():
    access = get_access_token()
    if access is None:
        raise _error()
    return access.token


class WordTaskMcpBridge:
    """Per-task MCP tools; injected authorizer reads current DB/session authority."""
    def __init__(self, *, selected, principal, authorize: Callable[[], Awaitable[dict]],
                 codec: WordTaskTicketCodec, request_token: Callable[[], str] = _request_bearer, enabled=False):
        if not enabled:
            raise ValueError('native_word_task_disabled')
        self._principal, self._authorize_current = _principal(principal), authorize
        self._codec, self._request_token = codec, request_token
        self._selected = deepcopy(selected)
        self._tools = NativeWordAITools(self._selected)
        self._registered, self._closed = None, False
        self._owner = asyncio.current_task()
        self.server = FastMCP('trusted-word-task', tasks=False, strict_input_validation=True,
                              mask_error_details=True, auth=WordTaskTokenVerifier(codec))

        @self.server.tool
        async def get_document_context(task_id: str) -> dict:
            await self._authorize(task_id)
            return self._tools.get_document_context()

        @self.server.tool
        async def read_blocks(task_id: str, block_ids: list[str], offset: int = 0) -> dict:
            await self._authorize(task_id)
            return self._tools.read_blocks(block_ids, offset)

        @self.server.tool
        async def search_text(task_id: str, text: str) -> dict:
            await self._authorize(task_id)
            return self._tools.search_text(text)

        @self.server.tool
        async def propose_operations(task_id: str, summary: str, operations: list[dict[str, Any]]) -> dict:
            await self._authorize(task_id)
            if self._registered is not None:
                raise _error()
            result = self._tools.propose_operations(summary, operations)
            self._registered = deepcopy(result['proposal'])
            return deepcopy(result)

    def _live(self):
        if self._closed or (self._owner is not None and self._owner.cancelling()):
            self._closed = True
            raise _error()

    async def _authorize(self, task_id, *, ticket=None):
        self._live()
        captured_ticket = ticket if ticket is not None else self._request_token()
        if self._codec.verify(captured_ticket) != self._principal:
            raise _error()
        principal = await self._authorize_current()
        self._live()
        if self._codec.verify(captured_ticket) != self._principal:
            raise _error()
        if principal != self._principal or task_id != self._principal['taskId']:
            raise _error()

    def cancel(self):
        self._closed = True

    async def reconcile(self, final: Mapping[str, Any], *, ticket: str) -> NativeWordAIProposal:
        final = json.loads(canonical_bytes(dict(final)))
        await self._authorize(self._principal['taskId'], ticket=ticket)
        if self._registered is None or final != self._registered:
            raise _error()
        parsed = NativeWordAIProposal.model_validate(final)
        if word_candidate(parsed.engine_operations(), self._selected) != self._tools.operations:
            raise _error()
        self._closed = True
        return parsed

    @property
    def registered_proposal(self):
        return deepcopy(self._registered)
