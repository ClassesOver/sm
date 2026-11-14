"""可信任务持有独立不可变的系统配置与格式偏好快照。"""

import sqlalchemy as sa
from alembic import op

revision = "0011_run_configuration"
down_revision = "0010_global_configuration"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("run_configuration_snapshots",
        sa.Column("scope_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(256), primary_key=True),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scope_id", "run_id"],
            ["reporting_management.runtime_snapshots.scope_id", "reporting_management.runtime_snapshots.run_id"]),
        schema="reporting_management")
    op.execute("""CREATE TRIGGER immutable_run_configuration_snapshots
        BEFORE UPDATE OR DELETE ON reporting_management.run_configuration_snapshots
        FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_configuration_version_change()""")


def downgrade():
    op.drop_table("run_configuration_snapshots", schema="reporting_management")
