"""数据源 Catalog 元数据版本。"""
import sqlalchemy as sa
from alembic import op

revision = "0005_catalog"
down_revision = "0004_profiles"
branch_labels = None
depends_on = None
SCHEMA = "reporting_management"


def upgrade():
    op.create_table(
        "catalog_versions",
        sa.Column("scope_id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("catalog", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_table("catalog_versions", schema=SCHEMA)
