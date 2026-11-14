"""未消费偏好只保留历史兼容，不接受草稿新增修改。"""

from copy import deepcopy

import pytest
from sqlalchemy import select

from smart_reporting.management.models import ManagementError
from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.tests.preference_version_fixtures import seed_preference_version
from smart_reporting.tests.test_format_preferences_persistence import context as context
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def unsupported_paths():
    """独立列出已知65项；不从被测能力函数生成预期。"""
    paths = [f"md.common.{key}" for key in ("generatedByLabel", "font", "accentColor")]
    for format in ("word", "pdf"):
        paths.extend(f"{format}.{key}" for key in ("tables.captionNumbering", "charts.imageDpi"))
    paths.extend(f"pptx.{key}" for key in (
        "common.generatedByLabel", "signature.spaceBefore", "signature.indent",
        "charts.imageDpi", "charts.keepWithCaption", "footerStyle.indent",
        "typography.body.indent", "typography.h1.indent", "typography.caption.indent"))
    paths.extend(f"pptx.typography.{role}.{key}" for role in ("h2", "h3", "table")
        for key in ("font", "size", "color", "bold", "lineHeight", "spaceBefore", "spaceAfter", "indent"))
    paths.extend(f"pptx.tables.{key}" for key in (
        "repeatHeader", "splitRows", "borders", "striped", "captionNumbering"))
    paths.extend(f"xlsx.{role}.{key}" for role in ("body", "header", "signature")
        for key in ("lineHeight", "spaceBefore", "spaceAfter", "indent"))
    paths.extend(f"xlsx.{key}" for key in (
        "signature.dateGap", "header.color", "common.generatedByLabel", "print.headerFooter.divider"))
    paths.extend(f"xlsx.print.headerFooter.style.{key}" for key in (
        "lineHeight", "spaceBefore", "spaceAfter", "indent"))
    return paths


def modify(document, path):
    target = document
    parts = path.split(".")
    for key in parts[:-1]:
        target = target[key]
    key = parts[-1]
    value = target[key]
    target[key] = (not value if type(value) is bool else value + 1
        if isinstance(value, (int, float)) else "serif" if key == "font" else "#123456"
        if key in {"color", "accentColor"} else "all" if key == "borders" else "未消费内容不得写入")


def current_unsupported_paths():
    """原65项保留历史身份，只剔除已有真实原生消费者的字段。"""
    implemented = {f'pptx.tables.{key}' for key in ('repeatHeader', 'borders', 'striped', 'captionNumbering')}
    implemented.update(f'pptx.typography.table.{key}' for key in (
        'font', 'size', 'color', 'bold', 'lineHeight', 'spaceBefore', 'spaceAfter'))
    implemented.add('pptx.signature.spaceBefore')
    implemented.update('pptx.' + local for local in ('signature.indent', 'footerStyle.indent',
        'typography.body.indent', 'typography.h1.indent', 'typography.table.indent', 'typography.caption.indent'))
    implemented.update(f'{format}.tables.captionNumbering' for format in ('word', 'pdf'))
    implemented.update(f'{format}.charts.imageDpi' for format in ('word', 'pdf', 'pptx'))
    return [path for path in unsupported_paths() if path not in implemented]


async def test_current_unconsumed_changes_are_rejected_without_writing_draft_or_save_audit(context):
    from smart_reporting.management.repository import audit_events

    service, token, repository, _ = context
    first = await service.detail(token)
    for path in current_unsupported_paths():
        document = deepcopy(first["draft"]["document"])
        modify(document, path)
        with pytest.raises(ManagementError) as error:
            await service.save_draft(token, document, 1)
        assert error.value.code == "management_preferences_unsupported_change", path
        assert error.value.status == 422
        assert path in error.value.message
        assert "尚未" in error.value.message
        assert (await service.detail(token))["draft"] == first["draft"]
    async with repository.engine.connect() as connection:
        actions = (await connection.execute(select(audit_events.c.action))).scalars().all()
    assert "format_preferences_saved" not in actions


async def test_supported_changes_and_shared_office_defaults_do_not_reject_md_inheritance(context):
    service, token, _, _ = context
    first = await service.detail(token)
    document = deepcopy(first["draft"]["document"])
    document["common"].update(font="serif", accentColor="#123456", generatedByLabel="共享生成说明")
    document["word"]["signature"].update(lineHeight=1.8, spaceBefore=23, dateGap=7)
    document["pdf"]["charts"]["captionNumbering"] = False
    document["xlsx"]["numbers"]["decimalPlaces"] = 4
    saved = await service.save_draft(token, document, 1)
    assert saved["version"] == 2
    assert (await service.detail(token))["draft"]["document"] == document


async def test_authentication_and_current_version_take_precedence_over_capability_reasons(context):
    service, token, _, _ = context
    first = await service.detail(token)
    unsupported = deepcopy(first["draft"]["document"])
    modify(unsupported, "xlsx.print.headerFooter.divider")
    with pytest.raises(ManagementError) as error:
        await service.save_draft("invalid-session", unsupported, 1)
    assert error.value.status == 401
    assert "divider" not in error.value.message
    supported = deepcopy(first["draft"]["document"])
    supported["common"]["signer"] = "新的有效署名"
    await service.save_draft(token, supported, 1)
    with pytest.raises(ManagementError) as error:
        await service.save_draft(token, unsupported, 1)
    assert error.value.code == "management_version_conflict"
    assert "divider" not in error.value.message


async def test_legacy_unsupported_values_survive_read_save_restore_and_reset_without_new_permission(context):
    from smart_reporting.management.format_preferences import FormatPreferenceService

    original, token, _, _ = context
    legacy = deepcopy(original.initial)
    for path in unsupported_paths():
        modify(legacy, path)
    service = FormatPreferenceService(original.auth, FormatPreferences.model_validate(legacy))
    first = await service.detail(token)
    assert first["draft"]["document"] == legacy
    published = await seed_preference_version(service, token, 1)
    changed = deepcopy(legacy)
    changed["common"]["signer"] = "只修改已支持的署名"
    await service.save_draft(token, changed, 1)
    assert (await service.detail(token))["draft"]["document"] == changed
    await service.restore_draft(token, published["revision"], 2)
    restored = (await service.detail(token))["draft"]
    assert restored["document"] == legacy and restored["version"] == 3
    invalid = deepcopy(legacy)
    modify(invalid, "xlsx.print.headerFooter.divider")
    with pytest.raises(ManagementError, match="management_preferences_unsupported_change"):
        await service.save_draft(token, invalid, 3)
    await service.reset_draft(token, 3)
    assert (await service.detail(token))["draft"]["document"] == legacy
    assert (await service.version(token, published["revision"])) == published


def test_public_capability_classification_limits_only_remaining_historical_fields():
    from smart_reporting.preferences.capabilities import unsupported_preference_reason
    from smart_reporting.preferences.models import FORMATS, resolve_format_preferences

    def leaves(document, prefix):
        for key, value in document.items():
            path = prefix + "." + key
            if isinstance(value, dict):
                yield from leaves(value, path)
            else:
                yield path

    preferences = FormatPreferences.model_validate({"common": {"signer": "能力边界"}})
    unsupported = {path for format in FORMATS
        for path in leaves(resolve_format_preferences(preferences, format), format)
        if unsupported_preference_reason(format, path)}
    assert len(unsupported_paths()) == 65
    assert len(unsupported) == 42
    assert unsupported == set(current_unsupported_paths())


async def test_http_reports_specific_unsupported_reason_and_preserves_saved_document(context):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.runtime.settings import AgentSettings

    service, token, _, _ = context
    first = await service.detail(token)
    app = FastAPI()
    app.include_router(create_management_router(service.auth,
        ManagementSettings(public_origin="https://reports.example"),
        startup_settings=AgentSettings.from_environment({}, load_env_file=False)))
    path = "/management/api/v1/configuration/preferences"
    headers = {"origin": "https://reports.example", "x-csrf-token": csrf_token(token)}
    document = deepcopy(first["draft"]["document"])
    document["xlsx"]["common"]["generatedByLabel"] = "不应被响应回显的输入"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
        base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, token)
        response = await client.put(path + "/draft", headers=headers,
            json={"expectedVersion": 1, "document": document})
        assert response.status_code == 422
        assert "management_preferences_unsupported_change" in response.text
        assert "xlsx.common.generatedByLabel" in response.text
        assert "尚未" in response.text
        assert "不应被响应回显的输入" not in response.text
        assert (await client.get(path)).json()["draft"]["document"] == first["draft"]["document"]
        assert (await client.get(path)).json()["application"]["canApply"] is False
