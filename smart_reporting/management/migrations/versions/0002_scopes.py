"""显式组织登记与默认资源设置。"""
import sqlalchemy as sa
from alembic import op

revision = '0002_scopes'
down_revision = '0001_admin'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('tenant_settings',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('database', sa.String(128), nullable=False),
        sa.Column('company_id', sa.String(128), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('default_source_ids', sa.JSON(), nullable=False),
        sa.Column('default_knowledge_base_ids', sa.JSON(), nullable=False),
        sa.UniqueConstraint('database', 'company_id', name='uq_management_scope'),
        schema='reporting_management')


def downgrade():
    op.drop_table('tenant_settings', schema='reporting_management')
