"""发布与运行共用的同组织不可变依赖读取。"""

from sqlalchemy import select

from ..catalog import CatalogService
from ..models import ManagementError
from ..repository import catalog_versions, profile_versions, source_credentials


def split_version(reference: str | None) -> tuple[str, int]:
    if reference is None:
        raise ManagementError(
            "management_source_dependencies_invalid",
            "数据源须绑定已发布的 Profile 和目录版本。",
            422,
        )
    try:
        resource_id, revision = reference.rsplit(":", 1)
        if not resource_id or int(revision) < 1 or str(int(revision)) != revision:
            raise ValueError
        return resource_id, int(revision)
    except (AttributeError, TypeError, ValueError) as error:
        raise ManagementError(
            "management_source_dependencies_invalid",
            "数据源须绑定已发布的 Profile 和目录版本。",
            422,
        ) from error


async def require_release_dependencies(connection, scope_id: str, source_id: str, version):
    if version.get("requires_table_discovery"):
        raise ManagementError(
            "management_table_access_confirmation_required",
            "连接已更换，须重新发现数据库目录并保存表范围。",
            422,
        )
    profile_id, profile_revision = split_version(version["profile_version_id"])
    catalog_source, catalog_revision = split_version(version["metadata_version_id"])
    if catalog_source != source_id:
        raise ManagementError(
            "management_source_dependencies_invalid", "目录不属于当前数据源。", 422
        )
    profile = (
        (
            await connection.execute(
                select(profile_versions).where(
                    profile_versions.c.scope_id == scope_id,
                    profile_versions.c.profile_id == profile_id,
                    profile_versions.c.revision == profile_revision,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    catalog = (
        (
            await connection.execute(
                select(catalog_versions).where(
                    catalog_versions.c.scope_id == scope_id,
                    catalog_versions.c.source_id == source_id,
                    catalog_versions.c.revision == catalog_revision,
                    catalog_versions.c.status == "published",
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    credential = (
        (
            await connection.execute(
                select(source_credentials).where(
                    source_credentials.c.scope_id == scope_id,
                    source_credentials.c.source_id == source_id,
                    source_credentials.c.credential_ref == version["credential_ref"],
                    source_credentials.c.revision == version["credential_revision"],
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if profile is None or catalog is None or credential is None:
        raise ManagementError(
            "management_source_dependencies_invalid",
            "数据源依赖不存在、尚未发布或不属于当前组织。",
            422,
        )
    identity = (
        catalog["catalog"].get("connectionIdentity")
        if isinstance(catalog["catalog"], dict)
        else None
    )
    if identity and identity != {
        "database": version["database"],
        "credentialRef": version["credential_ref"],
        "credentialRevision": version["credential_revision"],
    }:
        raise ManagementError(
            "management_catalog_connection_mismatch",
            "目录不属于当前连接，请重新发现并保存表范围。",
            422,
        )
    CatalogService.validate_snapshot(catalog["catalog"], source_id, version["database"])
    return profile, catalog, credential
