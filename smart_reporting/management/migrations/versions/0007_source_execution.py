"""保留已有执行参数；旧记录留空表示需从原文件重新导入，不猜测默认值。"""

import sqlalchemy as sa
from alembic import op

revision = "0007_source_execution"
down_revision = "0006_runtime_snapshots"
branch_labels = None
depends_on = None
SCHEMA = "reporting_management"


def upgrade():
    for table in ("source_drafts", "source_versions"):
        op.add_column(
            table, sa.Column("execution_parameters", sa.JSON(none_as_null=True)), schema=SCHEMA
        )


def downgrade():
    for table in ("source_versions", "source_drafts"):
        op.drop_column(table, "execution_parameters", schema=SCHEMA)
