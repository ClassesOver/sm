"""可信运行配置的数据库快照；不承接已退役业务 Profile 协议。"""

from datetime import date
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import insert, select

from ..preferences.models import FORMATS, FormatPreferences, resolve_format_preferences
from .configuration_catalog import configuration_inventory
from .configuration_store import configuration_hash
from .format_preferences import FormatPreferenceService
from .models import ManagementError
from .repository import run_configuration_snapshots


async def read_run_preferences(connection, scope_id, run_id):
    row = (await connection.execute(select(run_configuration_snapshots).where(
        run_configuration_snapshots.c.scope_id == scope_id, run_configuration_snapshots.c.run_id == run_id,
    ))).mappings().one_or_none()
    if row is None:
        return None
    document = row["document"]
    try:
        valid = isinstance(document, dict) and configuration_hash(document) == row["content_hash"]
        valid = valid and document["runId"] == run_id and document["scopeId"] == scope_id
        parsed = FormatPreferences.model_validate(document["preferences"])
        valid = valid and document['preferenceHash'] == configuration_hash(document['preferences'])
        valid = valid and document["resolvedFormats"] == {format: resolve_format_preferences(parsed, format) for format in FORMATS}
        valid = valid and date.fromisoformat(document["generatedDate"]).isoformat() == document["generatedDate"]
    except (TypeError, ValueError, KeyError, ValidationError):
        valid = False
    if not valid:
        raise ManagementError("management_configuration_snapshot_invalid", "报告配置快照校验失败。", 409)
    return {**document, "contentHash": row["content_hash"]}


async def freeze_run_preferences(connection, *, auth, startup, scope_id, run_id):
    service = FormatPreferenceService(auth, FormatPreferences.from_delivery(startup.report_delivery_settings))
    published = await service._latest(connection)
    if published:
        service._verified(published["document"], published["content_hash"])
        preferences, revision = published["document"], published["revision"]
    else:
        initial = await service._draft(connection)
        preferences, revision = initial["initial_document"], None
    parsed = FormatPreferences.model_validate(preferences)
    now = auth.clock()
    document = {"schemaVersion": 1, "scopeId": scope_id, "runId": run_id,
        "preferenceRevision": revision, "preferenceHash": configuration_hash(preferences),
        "preferences": preferences, "resolvedFormats": {format: resolve_format_preferences(parsed, format) for format in FORMATS},
        "systemRevision": startup.managed_system_revision, "systemHash": startup.managed_system_hash,
        "systemValues": {item["key"]: item["value"] for item in configuration_inventory(startup)
            if item["activation"] == "restart" and not item["redacted"]},
        "generatedDate": now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()}
    digest = configuration_hash(document)
    await connection.execute(insert(run_configuration_snapshots).values(scope_id=scope_id, run_id=run_id,
        document=document, content_hash=digest, created_at=now))
    return {**document, "contentHash": digest}
