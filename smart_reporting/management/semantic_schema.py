"""语义资产表登记；组织外键和已发布记录不可变由PG同时约束。"""

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Table,
    UniqueConstraint,
    event,
)

SCHEMA = "reporting_management"
IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION reporting_management.reject_semantic_version_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'published semantic records are immutable' USING ERRCODE = '23514';
END;
$$
"""


def register_semantic_tables(metadata) -> dict[str, Table]:
    tables = {}

    def scoped(name, *columns, immutable=False):
        table = Table(
            name, metadata,
            Column("scope_id", String(36), primary_key=True), *columns,
            ForeignKeyConstraint(["scope_id"], [f"{SCHEMA}.tenant_settings.id"]),
        )
        tables[name] = table
        if immutable:
            event.listen(table, "after_create", DDL(IMMUTABLE_FUNCTION).execute_if(dialect="postgresql"))
            trigger = f"""CREATE TRIGGER immutable_{name}
                BEFORE UPDATE OR DELETE ON {SCHEMA}.{name}
                FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_semantic_version_change()"""
            event.listen(table, "after_create", DDL(trigger).execute_if(dialect="postgresql"))
        return table

    def content():
        return (
            Column("document", JSON, nullable=False),
            Column("content_hash", String(64), nullable=False),
        )

    def version_columns(identity):
        return (
            Column(identity, String(128), primary_key=True),
            Column("revision", Integer, primary_key=True), *content(),
            Column("published_at", DateTime(timezone=True), nullable=False),
            CheckConstraint("revision > 0"),
        )

    for kind in ("metric", "statistical_policy"):
        identity = f"{kind.removeprefix('statistical_')}_id"
        scoped(
            f"{kind}_drafts", Column(identity, String(128), primary_key=True),
            Column("version", Integer, nullable=False), *content(),
            CheckConstraint("version > 0"),
        )

    scoped(
        "metric_versions", *version_columns("metric_id"),
        CheckConstraint("COALESCE(document->>'scopeId' = scope_id, false)", name="metric_document_scope"),
        CheckConstraint("COALESCE(document->>'id' = metric_id, false)", name="metric_document_identity"),
        CheckConstraint("COALESCE((document->>'revision')::integer = revision, false)", name="metric_document_revision"),
        immutable=True,
    )
    scoped(
        "metric_dependencies", Column("metric_id", String(128), primary_key=True),
        Column("revision", Integer, primary_key=True),
        Column("dependency_metric_id", String(128), primary_key=True),
        Column("dependency_revision", Integer, primary_key=True),
        ForeignKeyConstraint(
            ["scope_id", "metric_id", "revision"],
            [f"{SCHEMA}.metric_versions.{key}" for key in ("scope_id", "metric_id", "revision")],
        ),
        ForeignKeyConstraint(
            ["scope_id", "dependency_metric_id", "dependency_revision"],
            [f"{SCHEMA}.metric_versions.{key}" for key in ("scope_id", "metric_id", "revision")],
        ), immutable=True,
    )
    scoped(
        "business_documents", Column("document_id", String(128), primary_key=True),
        Column("version", Integer, nullable=False),
        Column("title", String(200), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        CheckConstraint("version > 0"),
    )
    scoped(
        "business_document_revisions", Column("document_id", String(128), primary_key=True),
        Column("revision", Integer, primary_key=True),
        Column("original_resource_id", String(256), nullable=False),
        Column("original_hash", String(64), nullable=False),
        Column("media_type", String(128), nullable=False),
        Column("size_bytes", Integer, nullable=False), *content(),
        Column("registered_at", DateTime(timezone=True), nullable=False),
        ForeignKeyConstraint(
            ["scope_id", "document_id"],
            [f"{SCHEMA}.business_documents.{key}" for key in ("scope_id", "document_id")],
        ),
        CheckConstraint("revision > 0 AND size_bytes > 0 AND size_bytes <= 20971520"),
        immutable=True,
    )
    # 原件修订不改写；解析与审核状态单独保存，避免把ready状态混入不可变原件。
    scoped(
        "business_revision_states", Column("document_id", String(128), primary_key=True),
        Column("revision", Integer, primary_key=True),
        Column("version", Integer, nullable=False),
        Column("ingestion_status", String(32), nullable=False),
        Column("review_status", String(32), nullable=False),
        Column("parse_receipt", JSON), Column("review_receipt", JSON),
        ForeignKeyConstraint(
            ["scope_id", "document_id", "revision"],
            [f"{SCHEMA}.business_document_revisions.{key}" for key in ("scope_id", "document_id", "revision")],
        ),
        CheckConstraint("version > 0"),
        CheckConstraint("ingestion_status IN ('queued','running','parsed','failed','ready','needs_transcription')"),
        CheckConstraint("review_status IN ('pending','approved','rejected','revoked')"),
    )
    scoped(
        "business_ingestion_jobs", Column("job_id", String(128), primary_key=True),
        Column("document_id", String(128), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("request_id", String(128), nullable=False),
        Column("input_hash", String(64), nullable=False),
        Column("status", String(32), nullable=False),
        Column("attempts", Integer, nullable=False, server_default="0"),
        Column("lease_owner", String(128)), Column("lease_until", DateTime(timezone=True)),
        Column("issues", JSON, nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("scope_id", "request_id"),
        ForeignKeyConstraint(
            ["scope_id", "document_id", "revision"],
            [f"{SCHEMA}.business_document_revisions.{key}" for key in ("scope_id", "document_id", "revision")],
        ),
        CheckConstraint("status IN ('queued','running','parsed','failed','ready','needs_transcription') AND attempts >= 0"),
    )
    scoped(
        "business_evidence_releases", Column("release_id", String(128), primary_key=True),
        Column("kind", String(32), nullable=False), *content(),
        Column("published_at", DateTime(timezone=True), nullable=False),
        CheckConstraint("kind IN ('rule_evidence','background')"), immutable=True,
    )
    scoped(
        "business_evidence_release_documents", Column("release_id", String(128), primary_key=True),
        Column("document_id", String(128), primary_key=True),
        Column("revision", Integer, primary_key=True),
        ForeignKeyConstraint(
            ["scope_id", "release_id"],
            [f"{SCHEMA}.business_evidence_releases.{key}" for key in ("scope_id", "release_id")],
        ),
        ForeignKeyConstraint(
            ["scope_id", "document_id", "revision"],
            [f"{SCHEMA}.business_document_revisions.{key}" for key in ("scope_id", "document_id", "revision")],
        ), immutable=True,
    )
    scoped(
        "statistical_policy_versions", *version_columns("policy_id"),
        Column("evidence_release_id", String(128), nullable=False),
        ForeignKeyConstraint(
            ["scope_id", "evidence_release_id"],
            [f"{SCHEMA}.business_evidence_releases.{key}" for key in ("scope_id", "release_id")],
        ), immutable=True,
    )
    scoped(
        "statistical_policy_metrics", Column("policy_id", String(128), primary_key=True),
        Column("policy_revision", Integer, primary_key=True),
        Column("metric_id", String(128), primary_key=True),
        Column("metric_revision", Integer, primary_key=True),
        ForeignKeyConstraint(
            ["scope_id", "policy_id", "policy_revision"],
            [f"{SCHEMA}.statistical_policy_versions.{key}" for key in ("scope_id", "policy_id", "revision")],
        ),
        ForeignKeyConstraint(
            ["scope_id", "metric_id", "metric_revision"],
            [f"{SCHEMA}.metric_versions.{key}" for key in ("scope_id", "metric_id", "revision")],
        ), immutable=True,
    )
    scoped(
        "reporting_policy_defaults", Column("scenario", String(128), primary_key=True),
        Column("version", Integer, nullable=False),
        Column("policy_id", String(128), nullable=False),
        Column("policy_revision", Integer, nullable=False),
        Column("background_release_id", String(128)),
        ForeignKeyConstraint(
            ["scope_id", "policy_id", "policy_revision"],
            [f"{SCHEMA}.statistical_policy_versions.{key}" for key in ("scope_id", "policy_id", "revision")],
        ),
        ForeignKeyConstraint(
            ["scope_id", "background_release_id"],
            [f"{SCHEMA}.business_evidence_releases.{key}" for key in ("scope_id", "release_id")],
        ), CheckConstraint("version > 0"),
    )
    scoped(
        "report_bases", Column("run_id", String(256), primary_key=True),
        Column("basis_id", String(128), nullable=False),
        Column("policy_id", String(128), nullable=False),
        Column("policy_revision", Integer, nullable=False),
        Column("evidence_release_id", String(128), nullable=False),
        Column("background_release_id", String(128)), *content(),
        Column("registered_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("scope_id", "basis_id"),
        ForeignKeyConstraint(
            ["scope_id", "policy_id", "policy_revision"],
            [f"{SCHEMA}.statistical_policy_versions.{key}" for key in ("scope_id", "policy_id", "revision")],
        ),
        ForeignKeyConstraint(
            ["scope_id", "evidence_release_id"],
            [f"{SCHEMA}.business_evidence_releases.{key}" for key in ("scope_id", "release_id")],
        ),
        ForeignKeyConstraint(
            ["scope_id", "background_release_id"],
            [f"{SCHEMA}.business_evidence_releases.{key}" for key in ("scope_id", "release_id")],
        ), immutable=True,
    )
    scoped(
        "report_basis_receipts", Column("basis_id", String(128), primary_key=True),
        Column("receipt_id", String(128), primary_key=True),
        Column("report_revision", String(256), nullable=False), *content(),
        Column("created_at", DateTime(timezone=True), nullable=False),
        ForeignKeyConstraint(
            ["scope_id", "basis_id"],
            [f"{SCHEMA}.report_bases.{key}" for key in ("scope_id", "basis_id")],
        ), immutable=True,
    )
    scoped(
        "semantic_asset_retirements", Column("asset_type", String(32), primary_key=True),
        Column("asset_id", String(128), primary_key=True),
        Column("revision", Integer, primary_key=True),
        Column("reason", String(4000), nullable=False),
        Column("replacement", JSON), Column("retired_at", DateTime(timezone=True), nullable=False),
        CheckConstraint("asset_type IN ('metric','statistical_policy') AND revision > 0"),
        immutable=True,
    )
    scoped(
        "report_issue_reviews", Column("issue_id", String(128), primary_key=True),
        Column("basis_id", String(128), nullable=False),
        Column("report_revision", String(256), nullable=False),
        Column("version", Integer, nullable=False),
        Column("status", String(32), nullable=False), Column("document", JSON, nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        ForeignKeyConstraint(
            ["scope_id", "basis_id"],
            [f"{SCHEMA}.report_bases.{key}" for key in ("scope_id", "basis_id")],
        ),
        CheckConstraint("status IN ('open','needs_evidence','accepted','rejected','resolved') AND version > 0"),
    )
    return tables
