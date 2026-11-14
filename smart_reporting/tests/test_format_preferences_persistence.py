"""真实 PostgreSQL 验证全局偏好生命周期，不依赖业务库或模型。"""

import asyncio

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from smart_reporting.management.models import ManagementError
from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.reporting.delivery.settings import ReportDeliverySettings
from smart_reporting.tests.preference_version_fixtures import seed_preference_version
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def context(auth_context):
    from smart_reporting.management.format_preferences import FormatPreferenceService

    auth, repository, now = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    initial = FormatPreferences.from_delivery(ReportDeliverySettings.model_validate({
        "branding": {"organizationName": "部署初始署名"}}))
    return FormatPreferenceService(auth, initial), token, repository, now


def changed(detail, signer):
    document = detail["draft"]["document"]
    document["common"]["signer"] = signer
    return document


async def test_initialization_survives_reconstruction_and_reads_do_not_change_version(context):
    from smart_reporting.management.format_preferences import FormatPreferenceService

    service, token, repository, _ = context
    first = await service.detail(token)
    assert first["draft"]["version"] == 1
    assert first["draft"]["document"]["common"]["signer"] == "部署初始署名"
    reloaded = FormatPreferenceService(service.auth, FormatPreferences.model_validate({
        "common": {"signer": "重启后的环境值"}}))
    assert (await reloaded.detail(token))["draft"] == first["draft"]
    assert (await reloaded.detail(token))["initial"]["common"]["signer"] == "部署初始署名"
    async with repository.engine.connect() as connection:
        from smart_reporting.management.repository import audit_events
        actions = (await connection.execute(select(audit_events.c.action))).scalars().all()
    assert actions.count("format_preferences_initialized") == 1


async def test_concurrent_saves_use_cas_and_preserve_exactly_one_document(context):
    service, token, _, _ = context
    first = await service.detail(token)
    payload = changed(first, "保存后署名")
    results = await asyncio.gather(*(
        service.save_draft(token, payload, first["draft"]["version"]) for _ in range(2)
    ), return_exceptions=True)
    assert sum(isinstance(item, dict) for item in results) == 1
    errors = [item for item in results if isinstance(item, ManagementError)]
    assert len(errors) == 1 and errors[0].code == "management_version_conflict"
    actual = await service.detail(token)
    assert actual["draft"]["version"] == 2
    assert actual["draft"]["document"]["common"]["signer"] == "保存后署名"
    assert actual["changes"] == [{"path": "common.signer", "before": "部署初始署名", "after": "保存后署名"}]


async def test_invalid_document_and_expired_session_never_write(context):
    service, token, _, _ = context
    first = await service.detail(token)
    with pytest.raises(ManagementError) as error:
        await service.save_draft(token, {"common": {"signer": ""}}, 1)
    assert error.value.code == "management_preferences_invalid"
    await service.auth.logout(token)
    with pytest.raises(ManagementError) as error:
        await service.save_draft(token, changed(first, "不应保存"), 1)
    assert error.value.status == 401
    valid_token = (await service.auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    assert (await service.detail(valid_token))["draft"]["version"] == 1


async def test_version_seed_is_idempotent_and_history_is_not_overwritten_by_restore(context):
    service, token, _, _ = context
    await service.detail(token)
    first = await seed_preference_version(service, token, 1)
    assert first["revision"] == 1
    assert await seed_preference_version(service, token, 1) == first
    detail = await service.detail(token)
    await service.save_draft(token, changed(detail, "第二个署名"), 1)
    assert (await seed_preference_version(service, token, 2))["revision"] == 2
    restored = await service.restore_draft(token, 1, 2)
    assert restored["version"] == 3
    detail = await service.detail(token)
    assert detail["draft"]["document"]["common"]["signer"] == "部署初始署名"
    assert detail["effective"]["document"]["common"]["signer"] == "第二个署名"
    assert (await seed_preference_version(service, token, 3))["revision"] == 3
    history = await service.history(token)
    assert [item["revision"] for item in history["items"]] == [3, 2, 1]
    assert (await service.version(token, 2))["document"]["common"]["signer"] == "第二个署名"


async def test_reset_uses_stored_initial_values_and_requires_current_version(context):
    service, token, _, _ = context
    first = await service.detail(token)
    await service.save_draft(token, changed(first, "修改署名"), 1)
    with pytest.raises(ManagementError, match="management_version_conflict"):
        await service.reset_draft(token, 1)
    await service.reset_draft(token, 2)
    detail = await service.detail(token)
    assert detail["draft"]["version"] == 3
    assert detail["draft"]["document"]["common"]["signer"] == "部署初始署名"


async def test_missing_history_and_corrupt_draft_fail_without_exposing_document(context):
    from smart_reporting.management.repository import configuration_drafts

    service, token, repository, _ = context
    await service.detail(token)
    with pytest.raises(ManagementError) as error:
        await service.restore_draft(token, 999, 1)
    assert error.value.status == 404
    async with repository.engine.begin() as connection:
        await connection.execute(update(configuration_drafts).where(
            configuration_drafts.c.kind == "preferences").values(content_hash="0" * 64))
    with pytest.raises(ManagementError) as error:
        await service.detail(token)
    assert error.value.code == "management_configuration_corrupt"
    assert "署名" not in error.value.message


async def test_version_seed_and_restore_verify_historical_document_hash(context):
    from smart_reporting.management.repository import configuration_versions

    service, token, repository, _ = context
    await service.detail(token)
    await seed_preference_version(service, token, 1)
    async with repository.engine.begin() as connection:
        # 故障注入刻意绕过数据库不可变保护，验证读取端仍检查身份。
        await connection.execute(text("ALTER TABLE reporting_management.configuration_versions DISABLE TRIGGER USER"))
        await connection.execute(update(configuration_versions).where(
            configuration_versions.c.kind == "preferences").values(content_hash="0" * 64))
        await connection.execute(text("ALTER TABLE reporting_management.configuration_versions ENABLE TRIGGER USER"))
    for operation in (service.version(token, 1), service.restore_draft(token, 1, 1), seed_preference_version(service, token, 1)):
        with pytest.raises(ManagementError, match="management_configuration_corrupt"):
            await operation


async def test_audit_contains_only_version_identity_and_not_preference_contents(context):
    from smart_reporting.management.repository import audit_events

    service, token, repository, _ = context
    first = await service.detail(token)
    await service.save_draft(token, changed(first, "审计中不得出现的署名"), 1)
    await seed_preference_version(service, token, 2)
    async with repository.engine.connect() as connection:
        events = (await connection.execute(select(audit_events))).mappings().all()
    assert "审计中不得出现的署名" not in str(events)
    assert any(item["action"] == "format_preferences_published" for item in events)


async def test_database_rejects_rewriting_published_preferences(context):
    from smart_reporting.management.repository import configuration_versions

    service, token, repository, _ = context
    await service.detail(token)
    await seed_preference_version(service, token, 1)
    with pytest.raises(IntegrityError):
        async with repository.engine.begin() as connection:
            await connection.execute(update(configuration_versions).where(
                configuration_versions.c.kind == "preferences").values(content_hash="0" * 64))
    assert (await service.version(token, 1))["document"]["common"]["signer"] == "部署初始署名"


async def test_verified_history_can_recover_a_corrupt_draft_without_rewriting_history(context):
    from smart_reporting.management.repository import configuration_drafts

    service, token, repository, _ = context
    await service.detail(token)
    await seed_preference_version(service, token, 1)
    async with repository.engine.begin() as connection:
        await connection.execute(update(configuration_drafts).where(
            configuration_drafts.c.kind == "preferences").values(content_hash="0" * 64))
    await service.restore_draft(token, 1, 1)
    assert (await service.detail(token))["draft"]["version"] == 2
    assert (await service.version(token, 1))["document"]["common"]["signer"] == "部署初始署名"


async def test_reset_can_recover_corrupt_draft_using_verified_deployment_initial(context):
    from smart_reporting.management.repository import configuration_drafts

    service, token, repository, _ = context
    await service.detail(token)
    async with repository.engine.begin() as connection:
        await connection.execute(update(configuration_drafts).where(
            configuration_drafts.c.kind == "preferences").values(content_hash="0" * 64))
    await service.reset_draft(token, 1)
    assert (await service.detail(token))["draft"]["document"]["common"]["signer"] == "部署初始署名"
