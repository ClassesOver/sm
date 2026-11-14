"""单实例系统配置与格式偏好版本；不转换旧业务资产。"""

import sqlalchemy as sa
from alembic import op

revision = "0010_global_configuration"
down_revision = "0009_semantic_assets"
branch_labels = None
depends_on = None
SCHEMA = "reporting_management"


def upgrade():
    op.create_table("configuration_drafts",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("initial_document", sa.JSON(), nullable=False),
        sa.Column("initial_hash", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('system','preferences') AND version > 0"), schema=SCHEMA)
    op.create_table("configuration_versions",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('system','preferences') AND revision > 0 AND draft_version > 0"), schema=SCHEMA)
    op.execute("""CREATE FUNCTION reporting_management.reject_configuration_version_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'published configuration records are immutable' USING ERRCODE = '23514';
END;
$$""")
    op.execute("""CREATE TRIGGER immutable_configuration_versions
BEFORE UPDATE OR DELETE ON reporting_management.configuration_versions
FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_configuration_version_change()""")


def downgrade():
    op.drop_table("configuration_versions", schema=SCHEMA)
    op.drop_table("configuration_drafts", schema=SCHEMA)
    op.execute("DROP FUNCTION reporting_management.reject_configuration_version_change()")
