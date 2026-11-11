"""指标与统计口径的独立退役记录，不修改已发布定义。"""

from pydantic import ValidationError
from sqlalchemy import insert, select

from ..reporting.semantics.models import MetricVersionRef, PolicyVersionRef
from .models import ManagementError
from .repository import metric_versions, semantic_asset_retirements, statistical_policy_versions


async def read_retirement(connection, scope_id, asset_type, asset_id, revision):
    row = (await connection.execute(select(semantic_asset_retirements).where(
        semantic_asset_retirements.c.scope_id == scope_id, semantic_asset_retirements.c.asset_type == asset_type,
        semantic_asset_retirements.c.asset_id == asset_id, semantic_asset_retirements.c.revision == revision))).mappings().one_or_none()
    return {"assetType": asset_type, "assetId": asset_id, "revision": revision,
        "reason": row["reason"], "replacement": row["replacement"]} if row else None


async def require_active(connection, scope_id, asset_type, asset_id, revision):
    retired = await connection.scalar(select(semantic_asset_retirements.c.revision).where(
        semantic_asset_retirements.c.scope_id == scope_id, semantic_asset_retirements.c.asset_type == asset_type,
        semantic_asset_retirements.c.asset_id == asset_id, semantic_asset_retirements.c.revision == revision))
    if retired is not None:
        raise ManagementError("management_semantic_asset_retired", "所选精确版本已退役，请明确选择替代版本。", 409)


async def retire_version(scopes, token, scope, asset_type, asset_id, revision, *, reason, replacement=None):
    if type(revision) is not int or revision < 1 or not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
        raise ManagementError("management_retirement_invalid", "退役须提供有效版本与原因。", 422)
    table, id_column = (metric_versions, metric_versions.c.metric_id) if asset_type == "metric" else (statistical_policy_versions, statistical_policy_versions.c.policy_id)
    replacement_body = None
    if replacement is not None:
        try:
            ref = (MetricVersionRef if asset_type == "metric" else PolicyVersionRef).model_validate(replacement)
        except ValidationError:
            raise ManagementError("management_retirement_invalid", "替代版本引用无效。", 422) from None
        replacement_body = ref.model_dump(mode="json", by_alias=True)
    actor = await scopes.actor(token, scope)
    async with scopes.write_transaction(actor) as connection:
        scope_id = (await scopes.require_registered(connection, scope))["id"]
        exists = await connection.scalar(select(table.c.revision).where(table.c.scope_id == scope_id, id_column == asset_id, table.c.revision == revision))
        if exists is None:
            raise ManagementError("management_semantic_version_not_found", "该组织不存在所选发布版本。", 404)
        if replacement_body is not None:
            replacement_id = ref.metric_id if asset_type == "metric" else ref.policy_id
            if (replacement_id, ref.revision) == (asset_id, revision):
                raise ManagementError("management_retirement_invalid", "替代版本不能指向自身。", 422)
            exists = await connection.scalar(select(table.c.revision).where(table.c.scope_id == scope_id, id_column == replacement_id, table.c.revision == ref.revision))
            if exists is None:
                raise ManagementError("management_semantic_version_not_found", "替代版本须已在该组织发布。", 404)
            await require_active(connection, scope_id, asset_type, replacement_id, ref.revision)
        query = select(semantic_asset_retirements).where(semantic_asset_retirements.c.scope_id == scope_id,
            semantic_asset_retirements.c.asset_type == asset_type, semantic_asset_retirements.c.asset_id == asset_id, semantic_asset_retirements.c.revision == revision)
        current = (await connection.execute(query)).mappings().one_or_none()
        if current is not None and (current["reason"] != reason or current["replacement"] != replacement_body):
            raise ManagementError("management_version_conflict", "此版本已有退役记录，请读回核对。", 409)
        if current is None:
            await connection.execute(insert(semantic_asset_retirements).values(scope_id=scope_id, asset_type=asset_type,
                asset_id=asset_id, revision=revision, reason=reason, replacement=replacement_body, retired_at=scopes.auth.clock()))
            await scopes.audit(connection, actor, "semantic_asset_retired", {"assetType": asset_type, "assetId": asset_id, "revision": revision})
        return {"assetType": asset_type, "assetId": asset_id, "revision": revision, "reason": reason, "replacement": replacement_body}
