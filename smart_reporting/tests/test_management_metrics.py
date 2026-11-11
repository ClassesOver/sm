"""指标发布的精确依赖、CAS与事务原子性。"""

import asyncio

import pytest
from sqlalchemy import func, select

from smart_reporting.reporting.tests.test_semantic_models import metric_payload, ratio_payload
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_semantic_assets_persistence import setup_scopes

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def draft(payload):
    return {key: value for key, value in payload.items() if key not in ("scopeId", "revision")}


async def context(auth_context):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.models import ManagementScope
    scopes, login, *_ = await setup_scopes(auth_context)
    return MetricService(scopes), login.raw_token, ManagementScope("warehouse", "a"), ManagementScope("warehouse", "b")


async def test_publish_uses_exact_dependencies_and_keeps_saved_draft_readable(auth_context):
    service, token, scope, _ = await context(auth_context)
    for identity in ("budget", "actual"):
        saved = await service.save_draft(token, scope, draft(metric_payload(identity)), 0)
        published = await service.publish(token, scope, identity, expected_version=saved["version"])
        assert published["revision"] == 1
    await service.save_draft(token, scope, draft(ratio_payload()), 0)
    published = await service.publish(token, scope, "rate", expected_version=1)
    assert published["document"]["denominatorVersion"] == {"metricId": "budget", "revision": 1}
    assert await service.publish(token, scope, "rate", expected_version=1) == published
    await service.save_draft(token, scope, draft(metric_payload("budget", name="新版预算")), 1)
    await service.publish(token, scope, "budget", expected_version=2)
    readback = await service.get(token, scope, "rate")
    assert readback["published"]["document"]["denominatorVersion"]["revision"] == 1


async def test_missing_foreign_or_self_dependency_never_publishes(auth_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import metric_versions
    service, token, first, second = await context(auth_context)
    await service.save_draft(token, first, draft(metric_payload()), 0)
    await service.publish(token, first, "budget", expected_version=1)
    await service.save_draft(token, second, draft(ratio_payload(numerator="budget")), 0)
    with pytest.raises(ManagementError) as foreign:
        await service.publish(token, second, "rate", expected_version=1)
    assert foreign.value.status == 409
    await service.save_draft(token, first, draft(ratio_payload(numerator="rate")), 0)
    with pytest.raises(ManagementError) as cycle:
        await service.publish(token, first, "rate", expected_version=1)
    assert cycle.value.status == 409
    async with auth_context[1].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(metric_versions)) == 1


async def test_publish_competing_save_and_audit_failure_do_not_silently_overwrite(auth_context, monkeypatch):
    from smart_reporting.management.models import ManagementError
    service, token, scope, _ = await context(auth_context)
    await service.save_draft(token, scope, draft(metric_payload()), 0)
    await service.save_draft(token, scope, draft(metric_payload(name="另一次编辑")), 1)
    with pytest.raises(ManagementError) as stale:
        await service.publish(token, scope, "budget", expected_version=1)
    assert stale.value.status == 409
    original_audit = service.scopes.audit

    async def audit_fault(*args, **kwargs):
        raise RuntimeError("synthetic publish audit fault")

    monkeypatch.setattr(service.scopes, "audit", audit_fault)
    with pytest.raises(RuntimeError, match="synthetic publish audit fault"):
        await service.publish(token, scope, "budget", expected_version=2)
    assert (await service.get(token, scope, "budget"))["published"] is None
    monkeypatch.setattr(service.scopes, "audit", original_audit)
    published = await asyncio.gather(*(service.publish(token, scope, "budget", expected_version=2) for _ in range(2)))
    assert published[0] == published[1]


async def test_business_unit_mismatch_is_published_with_unavailable_issue(auth_context):
    service, token, scope, _ = await context(auth_context)
    for identity, unit in (("budget", "CNY"), ("actual", "万元")):
        await service.save_draft(token, scope, draft(metric_payload(identity, unit=unit)), 0)
        await service.publish(token, scope, identity, expected_version=1)
    await service.save_draft(token, scope, draft(ratio_payload()), 0)
    result = await service.publish(token, scope, "rate", expected_version=1)
    assert [(issue["code"], issue["impact"]) for issue in result["issues"]] == [("ratio_unit_mismatch", "unavailable")]
    assert (await service.get(token, scope, "rate"))["published"]["revision"] == 1


async def test_publish_response_loss_can_be_read_back_without_new_version(auth_context, monkeypatch):
    from contextlib import asynccontextmanager

    service, token, scope, _ = await context(auth_context)
    await service.save_draft(token, scope, draft(metric_payload()), 0)
    transaction = service.scopes.write_transaction

    @asynccontextmanager
    async def lost_response(actor):
        async with transaction(actor) as connection:
            yield connection
        raise ConnectionError("synthetic lost response")

    monkeypatch.setattr(service.scopes, "write_transaction", lost_response)
    with pytest.raises(ConnectionError, match="synthetic lost response"):
        await service.publish(token, scope, "budget", expected_version=1)
    readback = await service.get(token, scope, "budget")
    assert readback["published"]["revision"] == 1
    monkeypatch.setattr(service.scopes, "write_transaction", transaction)
    assert (await service.publish(token, scope, "budget", expected_version=1))["revision"] == 1


async def test_retired_transitive_metric_dependency_is_not_newly_published(auth_context):
    from smart_reporting.management.models import ManagementError
    service, token, scope, _ = await context(auth_context)
    for identity in ("budget", "actual"):
        await service.save_draft(token, scope, draft(metric_payload(identity)), 0)
        await service.publish(token, scope, identity, expected_version=1)
    await service.save_draft(token, scope, draft(ratio_payload()), 0)
    await service.publish(token, scope, "rate", expected_version=1)
    await service.retire(token, scope, "budget", 1, reason="合成测试退役")
    await service.save_draft(token, scope, draft(ratio_payload("other-rate", numerator="rate", denominator="rate")), 0)
    with pytest.raises(ManagementError) as retired:
        await service.publish(token, scope, "other-rate", expected_version=1)
    assert retired.value.code == "management_semantic_asset_retired"
    assert (await service.get(token, scope, "other-rate"))["published"] is None
    assert (await service.get(token, scope, "rate"))["published"]["revision"] == 1


async def test_retirement_replacement_must_be_distinct_published_active_version(auth_context):
    from smart_reporting.management.models import ManagementError
    service, token, scope, other = await context(auth_context)
    for version in (1, 2):
        await service.save_draft(token, scope, draft(metric_payload()), version - 1)
        await service.publish(token, scope, "budget", expected_version=version)
    for replacement, status in (({"metricId": "budget", "revision": 1}, 422),
        ({"metricId": "budget", "revision": 3}, 404), ({"metricId": "budget", "revision": True}, 422)):
        with pytest.raises(ManagementError) as invalid:
            await service.retire(token, scope, "budget", 1, reason="使用第二版", replacement=replacement)
        assert invalid.value.status == status
    await service.retire(token, scope, "budget", 1, reason="使用第二版", replacement={"metricId": "budget", "revision": 2})
    assert (await service.get(token, scope, "budget"))["published"]["revision"] == 2
    with pytest.raises(ManagementError) as foreign:
        await service.retire(token, other, "budget", 1, reason="另一组织")
    assert foreign.value.status == 404
