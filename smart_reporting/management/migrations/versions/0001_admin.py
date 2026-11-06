"""部署级 admin、服务端会话与账号审计。"""

import sqlalchemy as sa
from alembic import op

revision = "0001_admin"
down_revision = None
branch_labels = None
depends_on = None
SCHEMA = "reporting_management"


def upgrade():
    op.create_table(
        "admin_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id = 1 AND username = 'admin'", name="singleton_admin"),
        schema=SCHEMA,
    )
    op.create_table(
        "admin_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_reporting_management_admin_sessions_expires_at",
        "admin_sessions",
        ["expires_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "login_attempts",
        sa.Column("address", sa.String(128), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_reporting_management_audit_events_occurred_at",
        "audit_events",
        ["occurred_at"],
        schema=SCHEMA,
    )


def downgrade():
    for name in ("audit_events", "login_attempts", "admin_sessions", "admin_account"):
        op.drop_table(name, schema=SCHEMA)
