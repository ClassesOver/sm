"""独立PG上的版本、组织外键、CAS和审计原子性契约。"""

import asyncio

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def setup_scopes(auth_context):
    from smart_reporting.management.models import ManagementScope
    from smart_reporting.management.scopes import ScopeService
    auth, repository, now = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    scopes = ScopeService(auth)
    first = await scopes.register(login.raw_token, ManagementScope("warehouse", "a"), "组织A")
    second = await scopes.register(login.raw_token, ManagementScope("warehouse", "b"), "组织B")
    return scopes, login, first["id"], second["id"], now[0]


def metric_row(scope_id, now, revision=1):
    from smart_reporting.reporting.tests.test_semantic_models import metric_payload
    return {
        "scope_id": scope_id, "metric_id": "budget", "revision": revision,
        "document": metric_payload(scopeId=scope_id, revision=revision),
        "content_hash": "a" * 64, "published_at": now,
    }


async def test_same_metric_identity_is_isolated_and_cross_scope_dependency_rejected(auth_context):
    from smart_reporting.management.repository import metric_dependencies, metric_versions
    _, repository, _ = auth_context
    _, _, first, second, now = await setup_scopes(auth_context)
    async with repository.engine.begin() as connection:
        await connection.execute(insert(metric_versions), [metric_row(first, now), metric_row(second, now)])
        await connection.execute(insert(metric_versions).values(**metric_row(first, now, 2)))
    async with repository.engine.begin() as connection:
        assert len((await connection.execute(select(metric_versions))).all()) == 3
    with pytest.raises(IntegrityError):
        async with repository.engine.begin() as connection:
            await connection.execute(insert(metric_dependencies).values(
                scope_id=second, metric_id="budget", revision=1,
                dependency_metric_id="budget", dependency_revision=2,
            ))
    with pytest.raises(IntegrityError):
        async with repository.engine.begin() as connection:
            row = metric_row(first, now, 3)
            row["document"]["scopeId"] = second
            await connection.execute(insert(metric_versions).values(**row))


async def test_published_metric_cannot_be_overwritten_or_deleted(auth_context):
    from smart_reporting.management.repository import metric_versions
    _, repository, _ = auth_context
    _, _, first, _, now = await setup_scopes(auth_context)
    async with repository.engine.begin() as connection:
        await connection.execute(insert(metric_versions).values(**metric_row(first, now)))
    for statement in (
        update(metric_versions).values(content_hash="b" * 64),
        metric_versions.delete(),
    ):
        with pytest.raises(DBAPIError):
            async with repository.engine.begin() as connection:
                await connection.execute(statement)
    async with repository.engine.connect() as connection:
        assert await connection.scalar(select(metric_versions.c.content_hash)) == "a" * 64


async def test_metric_draft_cas_and_audit_failure_do_not_silently_overwrite(auth_context, monkeypatch):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.models import ManagementError, ManagementScope
    from smart_reporting.reporting.tests.test_semantic_models import metric_payload
    scopes, login, _, _, _ = await setup_scopes(auth_context)
    service = MetricService(scopes)
    payload = metric_payload()
    payload.pop("scopeId")
    payload.pop("revision")
    scope = ManagementScope("warehouse", "a")
    draft = await service.save_draft(login.raw_token, scope, payload, 0)
    assert draft["version"] == 1
    attempts = await asyncio.gather(*(
        service.save_draft(login.raw_token, scope, {**payload, "name": name}, 1)
        for name in ("候选一", "候选二")
    ), return_exceptions=True)
    assert sum(isinstance(value, ManagementError) and value.status == 409 for value in attempts) == 1
    readback = await service.get(login.raw_token, scope, "budget")
    assert readback["draft"]["version"] == 2

    async def failed_audit(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(scopes, "audit", failed_audit)
    with pytest.raises(RuntimeError, match="audit failed"):
        await service.save_draft(login.raw_token, scope, {**payload, "name": "不能保存"}, 2)
    unchanged = await service.get(login.raw_token, scope, "budget")
    assert unchanged["draft"] == readback["draft"]


async def test_policy_cannot_reference_other_scope_rule_release(auth_context):
    from smart_reporting.management.repository import (
        business_evidence_releases,
        statistical_policy_versions,
    )
    _, repository, _ = auth_context
    _, _, first, second, now = await setup_scopes(auth_context)
    async with repository.engine.begin() as connection:
        await connection.execute(insert(business_evidence_releases).values(
            scope_id=first, release_id="rules-a", kind="rule_evidence", document={},
            content_hash="a" * 64, published_at=now,
        ))
    with pytest.raises(IntegrityError):
        async with repository.engine.begin() as connection:
            await connection.execute(insert(statistical_policy_versions).values(
                scope_id=second, policy_id="monthly", revision=1,
                evidence_release_id="rules-a", document={}, content_hash="b" * 64, published_at=now,
            ))


async def test_metric_read_and_write_reject_foreign_scope_and_server_owned_fields(auth_context):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.models import ManagementError, ManagementScope
    from smart_reporting.reporting.tests.test_semantic_models import metric_payload
    scopes, login, first, _, _ = await setup_scopes(auth_context)
    service = MetricService(scopes)
    payload = metric_payload()
    payload.pop("scopeId")
    payload.pop("revision")
    await service.save_draft(login.raw_token, ManagementScope("warehouse", "a"), payload, 0)
    with pytest.raises(ManagementError) as foreign:
        await service.get(login.raw_token, ManagementScope("warehouse", "b"), "budget")
    assert foreign.value.status == 404
    with pytest.raises(ManagementError) as forged:
        await service.save_draft(login.raw_token, ManagementScope("warehouse", "b"), {**payload, "scopeId": first}, 0)
    assert forged.value.status == 422
    with pytest.raises(ManagementError) as retired_field:
        await service.save_draft(login.raw_token, ManagementScope("warehouse", "a"), {**payload, "profileId": "base"}, 1)
    assert retired_field.value.status == 422


async def test_malformed_metric_id_is_validation_error_before_sql_lookup(auth_context):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.models import ManagementError, ManagementScope
    from smart_reporting.reporting.tests.test_semantic_models import metric_payload
    scopes, login, _, _, _ = await setup_scopes(auth_context)
    payload = metric_payload()
    payload.pop("scopeId")
    payload.pop("revision")
    with pytest.raises(ManagementError) as invalid:
        await MetricService(scopes).save_draft(
            login.raw_token, ManagementScope("warehouse", "a"), {**payload, "id": {"unexpected": "object"}}, 0,
        )
    assert invalid.value.status == 422
