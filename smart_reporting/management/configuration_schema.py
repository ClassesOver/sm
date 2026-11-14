"""单实例全局配置表；已发布版本同时由 PostgreSQL 防止改写。"""

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    event,
)

IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION reporting_management.reject_configuration_version_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'published configuration records are immutable' USING ERRCODE = '23514';
END;
$$
"""
IMMUTABLE_TRIGGER = """
CREATE TRIGGER immutable_configuration_versions
BEFORE UPDATE OR DELETE ON reporting_management.configuration_versions
FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_configuration_version_change()
"""


def register_configuration_tables(metadata) -> dict[str, Table]:
    credentials = Table('system_credentials', metadata,
        Column('reference', String(36), primary_key=True),
        Column('key', String(64), nullable=False),
        Column('key_id', String(32), nullable=False),
        Column('ciphertext', String, nullable=False),
        Column('created_at', DateTime(timezone=True), nullable=False))
    drafts = Table("configuration_drafts", metadata,
        Column("kind", String(32), primary_key=True),
        Column("version", Integer, nullable=False),
        Column("document", JSON, nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("initial_document", JSON, nullable=False),
        Column("initial_hash", String(64), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        CheckConstraint("kind IN ('system','preferences') AND version > 0"))
    versions = Table("configuration_versions", metadata,
        Column("kind", String(32), primary_key=True),
        Column("revision", Integer, primary_key=True),
        Column("draft_version", Integer, nullable=False),
        Column("document", JSON, nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("published_at", DateTime(timezone=True), nullable=False),
        Column('preference_approval_id', String(36)),
        ForeignKeyConstraint(['preference_approval_id'], ['reporting_management.preference_approval_receipts.id'],
            name='fk_configuration_preference_approval'),
        UniqueConstraint('preference_approval_id', name='uq_configuration_preference_approval'),
        CheckConstraint("preference_approval_id IS NULL OR kind = 'preferences'",
            name='ck_configuration_preference_approval_kind'),
        CheckConstraint("kind <> 'preferences' OR preference_approval_id IS NOT NULL",
            name='ck_configuration_preferences_require_approval'),
        CheckConstraint("kind IN ('system','preferences') AND revision > 0 AND draft_version > 0"))
    event.listen(versions, "after_create", DDL(IMMUTABLE_FUNCTION).execute_if(dialect="postgresql"))
    event.listen(versions, "after_create", DDL(IMMUTABLE_TRIGGER).execute_if(dialect="postgresql"))
    event.listen(credentials, 'after_create', DDL(IMMUTABLE_FUNCTION).execute_if(dialect='postgresql'))
    event.listen(credentials, 'after_create', DDL('''CREATE TRIGGER immutable_system_credentials
        BEFORE UPDATE OR DELETE ON reporting_management.system_credentials
        FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_configuration_version_change()''').execute_if(dialect='postgresql'))
    snapshots = Table("run_configuration_snapshots", metadata,
        Column("scope_id", String(36), primary_key=True),
        Column("run_id", String(256), primary_key=True),
        Column("document", JSON, nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        ForeignKeyConstraint(["scope_id", "run_id"],
            ["reporting_management.runtime_snapshots.scope_id", "reporting_management.runtime_snapshots.run_id"]))
    event.listen(snapshots, "after_create", DDL(IMMUTABLE_FUNCTION).execute_if(dialect="postgresql"))
    event.listen(snapshots, "after_create", DDL("""CREATE TRIGGER immutable_run_configuration_snapshots
        BEFORE UPDATE OR DELETE ON reporting_management.run_configuration_snapshots
        FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_configuration_version_change()""").execute_if(dialect="postgresql"))
    handoffs = Table('preference_verification_handoffs', metadata,
        Column('token_hash', String(64), primary_key=True),
        Column('admin_session_hash', String(64), nullable=False),
        Column('admin_auth_version', Integer, nullable=False),
        Column('draft_version', Integer, nullable=False),
        Column('draft_hash', String(64), nullable=False),
        Column('expires_at', DateTime(timezone=True), nullable=False),
        Column('editor_session_hash', String(64)),
        Column('context_hash', String(64)),
        Column('report_id', String(256)),
        Column('revision', Integer),
        Column('consumed_at', DateTime(timezone=True)))
    Index('ix_preference_handoffs_expires_at', handoffs.c.expires_at)
    evidence_tables = {}
    for name in ('preference_verification_results', 'preference_approval_receipts'):
        table = Table(name, metadata,
            Column('id', String(36), primary_key=True),
            Column('document', JSON, nullable=False),
            Column('content_hash', String(64), nullable=False),
            Column('created_at', DateTime(timezone=True), nullable=False))
        event.listen(table, 'after_create', DDL(IMMUTABLE_FUNCTION).execute_if(dialect='postgresql'))
        event.listen(table, 'after_create', DDL(f'''CREATE TRIGGER immutable_{name}
            BEFORE UPDATE OR DELETE ON reporting_management.{name}
            FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_configuration_version_change()''').execute_if(dialect='postgresql'))
        evidence_tables[name] = table
    return {"configuration_drafts": drafts, "configuration_versions": versions, 'system_credentials': credentials,
        "run_configuration_snapshots": snapshots, 'preference_verification_handoffs': handoffs, **evidence_tables}
