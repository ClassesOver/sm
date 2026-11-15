"""Request/task-local Office authority propagated through native editor operations."""
from contextvars import ContextVar

_session = ContextVar("office_native_session", default=None)
_authorize = ContextVar("office_native_authorize", default=None)


def bind(session, authorize):
    _session.set(session if (session.capabilities or {}).get("office") else None)
    _authorize.set(authorize)


def capabilities(document_id: str) -> dict:
    session = _session.get()
    if session is None:
        return {}
    # Never silently turn an Office task into an unrestricted publication,
    # including when a task creates a derived document.
    value = dict(session.capabilities['office'])
    if session.report_id != document_id:
        value['derivedDocument'] = document_id
    return {"office": value}


async def publication_capabilities(context):
    session, authorize = current()
    documents = getattr(authorize, '__self__', None)
    if session is None or documents is None or session.report_id == context.document_id:
        return capabilities(context.document_id)
    return {'office': await documents.register_derived(session, context)}


def current():
    """Trusted task context only; never populated from a client-supplied identity."""
    return _session.get(), _authorize.get()


async def check(document_id: str, *, write=False):
    session = _session.get()
    if session is None:
        return
    if session.report_id != document_id:
        from ..reporting.models import ReportingError
        raise ReportingError("native_permission_denied", "Office 任务与文档不一致。")
    authorize = _authorize.get()
    if authorize is None:
        from ..reporting.models import ReportingError
        raise ReportingError("native_permission_denied", "Office 授权服务不可用。")
    await authorize(session, write=write)
