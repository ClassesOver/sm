from __future__ import annotations

import json
from typing import Any

from ag_ui.core import Context, RunAgentInput

from .binding import TemporarySourceBindingService
from .intake import ReportIntakeService
from .models import ReportingError

REPORT_SOURCE_INTAKE_DEPENDENCY = "报表临时数据源绑定"


def prepare_agui_report_intake(
    run_input: RunAgentInput,
    *,
    user_id: str,
    service: ReportIntakeService,
    binding_service: TemporarySourceBindingService,
) -> RunAgentInput:
    messages = list(run_input.messages or [])
    index = next(
        (
            position
            for position in range(len(messages) - 1, -1, -1)
            if messages[position].role == "user"
        ),
        None,
    )
    if index is None:
        return run_input
    content = getattr(messages[index], "content", None)
    if not isinstance(content, str):
        return run_input
    parsed = service.parse(content)
    if parsed.source_request is None:
        return run_input
    if not parsed.ddl_tables:
        raise ReportingError(
            "source_tables_required", "临时数据库连接必须同时提供目标表 DDL 或字段说明。"
        )
    confirmation = binding_service.prepare(
        parsed,
        user_id=user_id,
        thread_id=run_input.thread_id,
        session_id=run_input.thread_id,
    )
    messages[index] = messages[index].model_copy(update={"content": parsed.sanitized_text})
    endpoint = f"{parsed.source_request.host}:{parsed.source_request.port}"
    dependency = Context(
        description=REPORT_SOURCE_INTAKE_DEPENDENCY,
        value=json.dumps(
            {
                "confirmationId": confirmation.confirmation_id,
                "sourceMode": "temporary_database",
                "sourceType": "starrocks",
                "endpoint": endpoint,
                "database": parsed.source_request.database,
                "ddlTables": list(parsed.ddl_tables),
                "metadataFingerprint": parsed.metadata_fingerprint,
                "expiresAt": confirmation.expires_at.isoformat(),
                "requiresConfirmation": True,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ),
    )
    context = [
        item
        for item in (run_input.context or [])
        if item.description != REPORT_SOURCE_INTAKE_DEPENDENCY
    ]
    context.append(dependency)
    return run_input.model_copy(update={"messages": messages, "context": context})


def sanitized_intake_snapshot(run_input: RunAgentInput) -> dict[str, Any] | None:
    for item in run_input.context or []:
        if item.description != REPORT_SOURCE_INTAKE_DEPENDENCY:
            continue
        try:
            value = json.loads(item.value)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None
    return None
