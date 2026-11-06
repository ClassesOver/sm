"""Profile 草稿和不可变发布版本。"""
import sqlalchemy as sa
from alembic import op

revision = "0004_profiles"
down_revision = "0003_sources"
branch_labels = None
depends_on = None
SCHEMA = "reporting_management"


def upgrade():
    op.create_table(
        "profile_drafts",
        sa.Column("scope_id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(128), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "profile_versions",
        sa.Column("scope_id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("effective_profile", sa.JSON(), nullable=False),
        sa.Column("effective_profile_hash", sa.String(64), nullable=False),
        sa.Column("parent_versions", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_table("profile_versions", schema=SCHEMA)
    op.drop_table("profile_drafts", schema=SCHEMA)
