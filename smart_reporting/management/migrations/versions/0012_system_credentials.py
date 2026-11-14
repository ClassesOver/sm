"""系统凭据独立加密存储，配置历史仅保存不可变引用。"""
import sqlalchemy as sa
from alembic import op

revision = '0012_system_credentials'
down_revision = '0011_run_configuration'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('system_credentials',
        sa.Column('reference', sa.String(36), primary_key=True),
        sa.Column('key', sa.String(64), nullable=False),
        sa.Column('key_id', sa.String(32), nullable=False),
        sa.Column('ciphertext', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), schema='reporting_management')
    op.execute('''CREATE TRIGGER immutable_system_credentials
        BEFORE UPDATE OR DELETE ON reporting_management.system_credentials
        FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_configuration_version_change()''')


def downgrade():
    op.drop_table('system_credentials', schema='reporting_management')
