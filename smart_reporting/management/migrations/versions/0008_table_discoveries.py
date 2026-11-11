"""管理员发现快照与连接更换后的范围确认标记，不改写历史目录。"""

import sqlalchemy as sa
from alembic import op

revision = "0008_table_discoveries"
down_revision = "0007_source_execution"
branch_labels = None
depends_on = None
SCHEMA = "reporting_management"


def upgrade():
    op.add_column(
        "source_drafts",
        sa.Column("requires_table_discovery", sa.Integer(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.create_table(
        "table_discoveries",
        sa.Column("scope_id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("discovery_id", sa.String(36), primary_key=True),
        sa.Column("database", sa.String(128), nullable=False),
        sa.Column("credential_ref", sa.String(36), nullable=False),
        sa.Column("credential_revision", sa.Integer(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tables", sa.JSON(), nullable=False),
        sa.Column("business_metadata", sa.JSON()),
        sa.Column("warnings", sa.JSON(), nullable=False),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_table("table_discoveries", schema=SCHEMA)
    op.drop_column("source_drafts", "requires_table_discovery", schema=SCHEMA)
