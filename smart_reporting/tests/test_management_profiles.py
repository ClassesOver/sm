from __future__ import annotations

import pytest

from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_profiles_preview_inheritance_and_freeze_parent_revision(auth_context):
    from smart_reporting.management.models import ManagementError, ManagementScope
    from smart_reporting.management.profiles import ProfileService
    from smart_reporting.management.scopes import ScopeService

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
        "dimensions": [
            {"code": "region", "kind": "category", "fieldRefs": ["sales.warehouse.orders.region"]}
        ],
    }
    parent_draft = await profiles.save_draft(login.raw_token, scope, parent, expected_version=0)
    published_parent = await profiles.publish(
        login.raw_token, scope, "base", parent_draft["version"]
    )
    assert published_parent["revision"] == 1

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
    published_child = await profiles.publish(
        login.raw_token, scope, "operations", child_draft["version"]
    )
    assert published_child["parentVersions"] == [{"profileId": "base", "revision": 1}]
    assert published_child["effectiveProfileHash"] == preview["effectiveProfileHash"]

    parent["dimensions"][0]["description"] = "更新"
    updated_parent = await profiles.save_draft(login.raw_token, scope, parent, expected_version=1)
    await profiles.publish(login.raw_token, scope, "base", updated_parent["version"])
    frozen_child = await profiles.get_version(login.raw_token, scope, "operations", 1)
    assert frozen_child["parentVersions"] == [{"profileId": "base", "revision": 1}]

    grandchild = {"profileId": "report", "revision": "r1", "extends": ["operations"]}
    grandchild_draft = await profiles.save_draft(login.raw_token, scope, grandchild, 0)
    published_grandchild = await profiles.publish(
        login.raw_token, scope, "report", grandchild_draft["version"]
    )
    assert published_grandchild["parentVersions"] == [
        {"profileId": "base", "revision": 1},
        {"profileId": "operations", "revision": 1},
    ]
    pinned_grandchild = await profiles.get_version(login.raw_token, scope, "report", 1)
    # 新子版本继承的是已发布父版本的闭包，不随更上层祖先的独立更新漂移。
    assert (
        pinned_grandchild["effectiveProfile"]["dimensions"]
        == frozen_child["effectiveProfile"]["dimensions"]
    )
    with pytest.raises(ManagementError, match="management_profile_parent_conflict"):
        await profiles.preview(
            login.raw_token,
            scope,
            {
                "profileId": "conflict",
                "revision": "r1",
                "extends": ["base", "operations"],
            },
        )

    with pytest.raises(ManagementError, match="management_version_conflict"):
        await profiles.save_draft(login.raw_token, scope, child, expected_version=0)
