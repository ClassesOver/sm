"""不可变的偏好验收记录和汇总；不改历史已发布版本。"""

import sqlalchemy as sa
from alembic import op

revision = '0014_preference_evidence'
down_revision = '0013_preference_handoffs'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('preference_verification_results', 'preference_approval_receipts'):
        op.create_table(name,
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('document', sa.JSON(), nullable=False),
            sa.Column('content_hash', sa.String(64), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            schema='reporting_management')
        op.execute(f'''CREATE TRIGGER immutable_{name}
            BEFORE UPDATE OR DELETE ON reporting_management.{name}
            FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_configuration_version_change()''')


def downgrade():
    op.drop_table('preference_approval_receipts', schema='reporting_management')
    op.drop_table('preference_verification_results', schema='reporting_management')
