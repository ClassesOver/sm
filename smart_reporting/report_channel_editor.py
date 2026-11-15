"""Bind channel management to the host's authenticated Word editor session."""

from collections.abc import Awaitable, Callable

from fastapi import Request

from .report_editor.native import NativeEditorService
from .report_editor.native_api import NATIVE_SESSION_COOKIE, _csrf
from .report_editor.native_models import NativeEditorContext
from .reporting.models import ReportingError


def report_channel_editor_authorizer(
    editor: NativeEditorService,
    resolve_channel: Callable[[NativeEditorContext], Awaitable[str | None]],
    *,
    allowed_origin: str,
) -> Callable[[Request], Awaitable[str | None]]:
    async def authorize(request: Request) -> str | None:
        token = request.cookies.get(NATIVE_SESSION_COOKIE)
        if not token:
            return None
        try:
            session = await editor.grants.lookup_session(token)
            context = await editor.context_for_session(session)
        except ReportingError:
            return None
        params = request.path_params
        if params and "document_id" in params and (
            params["document_id"] != context.document_id or params["revision"] != str(context.revision)
        ):
            return None
        if context.format != "docx" or not editor.is_enabled(context.format):
            return None
        if request.method != "GET":
            _csrf(request, editor.grants, NATIVE_SESSION_COOKIE, allowed_origin)
        return await resolve_channel(context)

    return authorize
