from __future__ import annotations

import pytest

from smart_reporting.tests.test_management_persistence import OLD_PASSWORD, auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_profiles_preview_inheritance_and_freeze_parent_revision(auth_context):
    from smart_reporting.management.models import ManagementError, ManagementScope
    from smart_reporting.management.scopes import ScopeService
    from smart_reporting.management.profiles import ProfileService

    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    scopes = ScopeService(auth)
    scope = ManagementScope("warehouse", "100")
    await scopes.register(login.raw_token, scope, "华东公司")
    profiles = ProfileService(scopes)

    parent = {
        "profileId": "base",
        "revision": "input-parent",
        "dimensions": [{"code": "region", "kind": "category", "fieldRefs": ["sales.warehouse.orders.region"]}],
    }
    parent_draft = await profiles.save_draft(login.raw_token, scope, parent, expected_version=0)
    published_parent = await profiles.publish(login.raw_token, scope, "base", parent_draft["version"])

    child = {
        "profileId": "operations",
        "revision": "input-child",
        "extends": ["base"],
        "metrics": [],
    }
    preview = await profiles.preview(login.raw_token, scope, child)
    assert preview["profileId"] == "operations"
    assert [item["profileId"] for item in preview["layers"]] == ["base", "operations"]

    child_draft = await profiles.save_draft(login.raw_token, scope, child, expected_version=0)
    published_child = await profiles.publish(login.raw_token, scope, "operations", child_draft["version"])
    assert published_child["parentVersions"] == [{"profileId": "base", "revision": 1}]
    assert published_child["effectiveProfileHash"] == preview["effectiveProfileHash"]

    parent["dimensions"][0]["description"] = "更新"
    updated_parent = await profiles.save_draft(login.raw_token, scope, parent, expected_version=1)
    await profiles.publish(login.raw_token, scope, "base", updated_parent["version"])
    frozen_child = await profiles.get_version(login.raw_token, scope, "operations", 1)
    assert frozen_child["parentVersions"] == [{"profileId": "base", "revision": 1}]

    with pytest.raises(ManagementError, match="management_version_conflict"):
        await profiles.save_draft(login.raw_token, scope, child, expected_version=0)

