"""发布与运行共用的同组织不可变依赖读取。"""

from sqlalchemy import select

from ...reporting.semantics.models import SourceVersionRef
from ..catalog import CatalogService
from ..models import ManagementError
from ..repository import catalog_versions, source_credentials, source_versions, sources


def split_version(reference: str | None) -> tuple[str, int]:
    if reference is None:
        raise ManagementError(
            "management_source_dependencies_invalid",
            "数据源须绑定已发布的目录版本。",
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
            "数据源须绑定已发布的目录版本。",
            422,
        ) from error


async def require_release_dependencies(connection, scope_id: str, source_id: str, version):
    if version.get("requires_table_discovery"):
        raise ManagementError(
            "management_table_access_confirmation_required",
            "连接已更换，须重新发现数据库目录并保存表范围。",
            422,
        )
    if version["profile_version_id"] is not None:
        raise ManagementError(
            "management_source_contract_retired",
            "该连接仍绑定已停用的业务Profile，请按新契约重新登记连接与表范围。",
            409,
        )
    catalog_source, catalog_revision = split_version(version["metadata_version_id"])
    if catalog_source != source_id:
        raise ManagementError(
            "management_source_dependencies_invalid", "目录不属于当前数据源。", 422
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
    if catalog is None or credential is None:
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
    return catalog, credential


async def resolve_published_source(connection, scope_id, source_id, revision):
    """解析已发布数据源版本及其目录、凭据，并核验内容身份；返回 (数据源引用, 目录引用)。"""

    from .service import SourceService

    enabled = await connection.scalar(select(sources.c.enabled).where(
        sources.c.scope_id == scope_id, sources.c.source_id == source_id,
    ))
    if enabled != 1:
        raise ManagementError("management_source_disabled", "数据源已停用或不属于当前组织。", 403)
    row = (await connection.execute(select(source_versions).where(
        source_versions.c.scope_id == scope_id, source_versions.c.source_id == source_id,
        source_versions.c.revision == revision,
    ))).mappings().one_or_none()
    if row is None or row["execution_parameters"] is None:
        raise ManagementError("management_source_version_not_found", "已发布数据源或执行参数不存在。", 409)
    if row["profile_version_id"] is not None:
        raise ManagementError("management_source_contract_retired", "旧数据源业务契约已停用，请重新登记连接与目录。", 409)
    public = {"name": row["name"], "type": row["source_type"], "database": row["database"],
        "metadataVersionId": row["metadata_version_id"]}
    if SourceService._config_hash(public, row["credential_revision"], row["execution_parameters"]) != row["content_hash"]:
        raise ManagementError("management_basis_identity_invalid", "数据源内容身份不一致。", 409)
    catalog_source, catalog_revision = split_version(row["metadata_version_id"])
    catalog = (await connection.execute(select(catalog_versions).where(
        catalog_versions.c.scope_id == scope_id, catalog_versions.c.source_id == source_id,
        catalog_versions.c.revision == catalog_revision, catalog_versions.c.status == "published",
    ))).mappings().one_or_none()
    credential = (await connection.execute(select(source_credentials.c.revision).where(
        source_credentials.c.scope_id == scope_id, source_credentials.c.source_id == source_id,
        source_credentials.c.credential_ref == row["credential_ref"],
        source_credentials.c.revision == row["credential_revision"],
    ))).first()
    if catalog_source != source_id or catalog is None or credential is None:
        raise ManagementError("management_basis_dependency_missing", "数据源的目录或凭据版本不可用。", 409)
    if CatalogService._hash(catalog["catalog"]) != catalog["content_hash"]:
        raise ManagementError("management_basis_identity_invalid", "目录内容身份不一致。", 409)
    CatalogService.validate_snapshot(catalog["catalog"], source_id, row["database"])
    identity = catalog["catalog"].get("connectionIdentity")
    if identity is not None and identity != {"database": row["database"],
        "credentialRef": row["credential_ref"], "credentialRevision": row["credential_revision"]}:
        raise ManagementError("management_catalog_connection_mismatch", "目录不属于所选连接版本。", 409)
    return (SourceVersionRef(source_id=source_id, revision=revision, content_hash=row["content_hash"]),
        SourceVersionRef(source_id=source_id, revision=catalog_revision, content_hash=catalog["content_hash"]))
