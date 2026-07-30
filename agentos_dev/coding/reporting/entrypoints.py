from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from ag_ui.core import RunAgentInput

from .contract import ReportRequestEnvelope
from .models import ReportingError

REPORT_ENVELOPE_CONTEXT = "AgentOS ReportRequestEnvelope v1"
REPORT_SCHEMA_CONTEXT = "AgentOS Report DDL v1"
_SERVER_ENVELOPE: ContextVar[ReportRequestEnvelope | None] = ContextVar(
    "report_request_envelope_v1", default=None
)
_DDL_BLOCK = re.compile(
    r"(?:```(?:sql)?\s*)?(CREATE\s+TABLE\b.*?;)(?:\s*```)?", re.IGNORECASE | re.DOTALL
)
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class PreparedReportInput:
    envelope: ReportRequestEnvelope
    run_input: RunAgentInput


@dataclass(frozen=True)
class ReportServerIdentity:
    database: str
    user_id: str
    company_id: str
    session_id: str
    thread_id: str


def prepare_agui_envelope(run_input: RunAgentInput) -> PreparedReportInput:
    candidates: list[tuple[str, str]] = []
    for item in run_input.context or []:
        if item.description in {REPORT_ENVELOPE_CONTEXT, REPORT_SCHEMA_CONTEXT}:
            candidates.append((item.description, item.value))
    messages = list(run_input.messages or [])
    if messages and messages[-1].role == "user" and isinstance(messages[-1].content, str):
        candidates.append(("message", messages[-1].content))

    envelope_payload: dict[str, Any] | None = None
    ddl_values: list[str] = []
    for description, value in candidates:
        if description == REPORT_SCHEMA_CONTEXT:
            ddl_values.extend(_extract_ddl(value))
            continue
        parsed = _extract_json(value)
        if parsed is not None and "reportGoal" in parsed:
            if envelope_payload is not None:
                raise ReportingError("report_request_ambiguous", "检测到多个报表 Envelope。")
            envelope_payload = parsed
        ddl_values.extend(_extract_ddl(value))
    if envelope_payload is None:
        raise ReportingError("report_request_invalid", "未找到 ReportRequestEnvelope v1。")
    existing_schema = envelope_payload.get("schemaInput")
    if ddl_values:
        ddl = "\n".join(dict.fromkeys(ddl_values))
        if isinstance(existing_schema, dict) and existing_schema.get("ddl") not in {None, ddl}:
            raise ReportingError("report_schema_conflict", "Envelope 与上下文包含不同 DDL。")
        envelope_payload["schemaInput"] = {**(existing_schema or {}), "ddl": ddl}
    envelope = ReportRequestEnvelope.from_untrusted(envelope_payload)

    sanitized_context = [
        item
        for item in run_input.context or []
        if item.description not in {REPORT_ENVELOPE_CONTEXT, REPORT_SCHEMA_CONTEXT}
    ]
    sanitized_messages = list(messages)
    if sanitized_messages and sanitized_messages[-1].role == "user":
        content = sanitized_messages[-1].content
        if isinstance(content, str):
            sanitized = _DDL_BLOCK.sub("", content)
            sanitized = _JSON_BLOCK.sub("", sanitized).strip() or envelope.report_goal
            parsed_message = _extract_json(sanitized)
            if parsed_message is not None and "reportGoal" in parsed_message:
                sanitized = envelope.report_goal
            sanitized_messages[-1] = sanitized_messages[-1].model_copy(
                update={"content": sanitized}
            )
    prepared = run_input.model_copy(
        update={"context": sanitized_context, "messages": sanitized_messages}
    )
    serialized = repr(prepared)
    if (
        envelope.schema_input
        and envelope.schema_input.ddl
        and envelope.schema_input.ddl in serialized
    ):
        raise ReportingError("report_schema_sanitization_failed", "DDL 未能从模型上下文移除。")
    return PreparedReportInput(envelope=envelope, run_input=prepared)


_SERVER_IDENTITY: ContextVar[ReportServerIdentity | None] = ContextVar(
    "report_server_identity_v1", default=None
)


@contextmanager
def bind_server_request(
    envelope: ReportRequestEnvelope | None,
    identity: ReportServerIdentity | None = None,
) -> Iterator[None]:
    envelope_token = _SERVER_ENVELOPE.set(envelope)
    identity_token = _SERVER_IDENTITY.set(identity)
    try:
        yield
    finally:
        _SERVER_IDENTITY.reset(identity_token)
        _SERVER_ENVELOPE.reset(envelope_token)


@contextmanager
def bind_server_envelope(envelope: ReportRequestEnvelope) -> Iterator[None]:
    with bind_server_request(envelope):
        yield


def current_server_envelope() -> ReportRequestEnvelope | None:
    return _SERVER_ENVELOPE.get()


def current_server_identity() -> ReportServerIdentity | None:
    return _SERVER_IDENTITY.get()


def parse_cli_envelope(value: str) -> ReportRequestEnvelope:
    try:
        payload = json.loads(value)
    except (TypeError, ValueError) as error:
        raise ReportingError("report_request_invalid", "CLI 输入必须是 Envelope JSON。") from error
    return ReportRequestEnvelope.from_untrusted(payload)


def _extract_json(value: str) -> dict[str, Any] | None:
    candidates = [value]
    candidates.extend(match.group(1) for match in _JSON_BLOCK.finditer(value))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_ddl(value: str) -> list[str]:
    return [match.group(1).strip() for match in _DDL_BLOCK.finditer(value)]
