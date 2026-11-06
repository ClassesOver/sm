"""服务端可信运行身份与不可变配置引用；不存连接明文。"""

import sqlalchemy as sa
from alembic import op

revision = "0006_runtime_snapshots"
down_revision = "0005_catalog"
branch_labels = None
depends_on = None
SCHEMA = "reporting_management"


def upgrade():
    op.create_table(
        "runtime_snapshots",
        sa.Column("scope_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(256), primary_key=True),
        sa.Column("user_id", sa.String(256), nullable=False),
        sa.Column("thread_id", sa.String(256), nullable=False),
        sa.Column("entrypoint", sa.String(32), nullable=False),
        sa.Column("references", sa.JSON()),
        sa.Column("reference_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )


def downgrade():
    op.drop_table("runtime_snapshots", schema=SCHEMA)
