from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import select, update

from smart_reporting.management.data_sources.models import SourceDraftInput
from smart_reporting.management.models import ManagementError
from smart_reporting.management.repository import sources, tenant_settings
from smart_reporting.management.runtime import ManagedConfigurationProvider
from smart_reporting.tests.management_fixtures import publish_dependencies
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_management_release_dependencies import (
    release_context as release_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
async def pinned_context(release_context):
    service, scopes, repo, token, scope = release_context
    await publish_dependencies(scopes, token, scope)
    await service.publish(token, scope, "operations", 1)
    async with repo.transaction() as connection:
        await connection.execute(update(tenant_settings).values(default_source_ids=["operations"]))
    provider = ManagedConfigurationProvider(scopes, service.vault)
    # 这个主机内部入口只能由已核验 HTTP/MCP 或受控 CLI 生命周期调用。
    await provider.register_run("run-1", scope, user_id="7", thread_id="thread-1", entrypoint="cli")
    return provider, service, scopes, repo, token, scope


async def test_runtime_snapshot_survives_provider_restart_and_source_republication(pinned_context):
    provider, service, scopes, repo, token, scope = pinned_context
    first = await provider.freeze("run-1", scope)
    old_dsn = first.sources["operations"].connection_dsn()
    payload = SourceDraftInput.model_validate(
        {
            "name": "第二版",
            "database": "warehouse",
            "dsn": "starrocks://reporter:second-secret@localhost:9030/warehouse",
            "reportingProfileVersionId": "base:1",
            "metadataVersionId": "operations:1",
        }
    )
    await service.save_draft(token, scope, "operations", payload, 1)
    await service.publish(token, scope, "operations", 2)
    restarted = ManagedConfigurationProvider(scopes, service.vault)
    restored = await restarted.load_pinned(scope, first.references)
    assert restored.source_versions == {"operations": 1}
    assert restored.sources["operations"].connection_dsn() == old_dsn
    assert restored.references == first.references
    assert restored.metadata["operations"].terms[0].name == "收入"
    assert (await restarted.freeze("run-1", scope)).references == first.references
    await restarted.register_run(
        "run-2", scope, user_id="7", thread_id="thread-2", entrypoint="cli"
    )
    second = await restarted.freeze("run-2", scope)
    assert second.source_versions == {"operations": 2}
    assert "second-secret" in second.sources["operations"].connection_dsn()
    from smart_reporting.management.repository import runtime_snapshots

    async with repo.engine.connect() as connection:
        rows = (await connection.execute(select(runtime_snapshots))).mappings().all()
    assert len(rows) == 2
    assert all("test-secret" not in str(row) and "second-secret" not in str(row) for row in rows)
    assert all(row["reference_hash"] for row in rows)


async def test_unregistered_run_forged_references_and_changed_identity_are_rejected(pinned_context):
    provider, _, _, _, _, scope = pinned_context
    with pytest.raises(ManagementError, match="management_run_identity_missing"):
        await provider.freeze("untrusted-run", scope)
    pinned = await provider.freeze("run-1", scope)
    forged = deepcopy(pinned.references)
    forged["sources"][0]["revision"] = 999
    with pytest.raises(ManagementError, match="management_runtime_reference_mismatch"):
        await provider.load_pinned(scope, forged)
    with pytest.raises(ManagementError, match="management_run_identity_conflict"):
        await provider.register_run(
            "run-1", scope, user_id="other", thread_id="thread-1", entrypoint="cli"
        )
    with pytest.raises(ManagementError, match="management_source_selection_conflict"):
        await provider.freeze("run-1", scope, ("different",))


async def test_disabled_source_blocks_new_reads_but_does_not_rewrite_pinned_reference(
    pinned_context,
):
    provider, _, _, repo, _, scope = pinned_context
    pinned = await provider.freeze("run-1", scope)
    async with repo.transaction() as connection:
        await connection.execute(update(sources).values(enabled=0))
    with pytest.raises(ManagementError, match="management_source_disabled"):
        await provider.load_pinned(scope, pinned.references)
    from smart_reporting.management.repository import runtime_snapshots

    async with repo.engine.connect() as connection:
        stored = await connection.scalar(select(runtime_snapshots.c.references))
    assert stored == pinned.references


async def test_concurrent_instances_freeze_once_and_foreign_scope_cannot_restore(pinned_context):
    import asyncio

    from smart_reporting.management.models import ManagementScope
    from smart_reporting.management.repository import runtime_snapshots

    provider, service, scopes, repo, token, scope = pinned_context
    another = ManagedConfigurationProvider(scopes, service.vault)
    first, second = await asyncio.gather(
        provider.freeze("run-1", scope), another.freeze("run-1", scope)
    )
    assert first.references == second.references
    async with repo.engine.connect() as connection:
        assert len((await connection.execute(select(runtime_snapshots))).all()) == 1
    foreign = ManagementScope("warehouse", "other-company")
    await scopes.register(token, foreign, "另一公司")
    with pytest.raises(ManagementError, match="management_run_identity_missing"):
        await another.load_pinned(foreign, first.references)


async def test_tampered_catalog_is_not_used_to_restore_frozen_configuration(pinned_context):
    from smart_reporting.management.repository import catalog_versions

    provider, _, _, repo, _, scope = pinned_context
    pinned = await provider.freeze("run-1", scope)
    async with repo.transaction() as connection:
        catalog = await connection.scalar(select(catalog_versions.c.catalog))
        catalog["metadata"]["terms"][0]["description"] = "changed after publication"
        await connection.execute(update(catalog_versions).values(catalog=catalog))
    with pytest.raises(ManagementError, match="management_runtime_reference_mismatch"):
        await provider.load_pinned(scope, pinned.references)


@pytest.mark.parametrize("write", ["create", "save"])
async def test_normalized_source_input_remains_readable_after_publication(release_context, write):
    service, scopes, _, token, scope = release_context
    source_id = "normalized" if write == "create" else "operations"
    payload = SourceDraftInput.model_validate(
        {
            "name": " 数仓 ",
            "database": "WAREHOUSE",
            "dsn": "starrocks://reporter:test-secret@localhost:9030/warehouse",
            "reportingProfileVersionId": "base:1",
            "metadataVersionId": f"{source_id}:1",
        }
    )
    if write == "create":
        draft = await service.create_draft(token, scope, source_id, payload)
    else:
        draft = await service.save_draft(token, scope, source_id, payload, 1)
    await publish_dependencies(scopes, token, scope, source_id, draft["version"])
    published = await service.publish(token, scope, source_id, draft["version"])
    provider = ManagedConfigurationProvider(scopes, service.vault)
    await provider.register_run(
        "normalized-run", scope, user_id="7", thread_id="t", entrypoint="cli"
    )
    frozen = await provider.freeze("normalized-run", scope, (source_id,))
    restored = await ManagedConfigurationProvider(scopes, service.vault).load_pinned(
        scope, frozen.references
    )
    assert restored.sources[source_id].name == "数仓"
    assert restored.sources[source_id].database == "warehouse"
    assert restored.source_hashes[source_id] == published["contentHash"]


@pytest.mark.parametrize(
    "parameters,code",
    [
        (None, "management_source_reimport_required"),
        ({"maxRows": 1}, "management_runtime_reference_mismatch"),
    ],
)
async def test_missing_or_tampered_execution_parameters_never_fall_back_to_defaults(
    pinned_context, parameters, code
):
    from smart_reporting.management.repository import source_versions

    provider, _, _, repo, _, scope = pinned_context
    pinned = await provider.freeze("run-1", scope)
    async with repo.transaction() as connection:
        await connection.execute(update(source_versions).values(execution_parameters=parameters))
    with pytest.raises(ManagementError, match=code):
        await provider.load_pinned(scope, pinned.references)
