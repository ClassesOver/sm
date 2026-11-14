"""偏好验收两类会话的一次性短期交接，不存原会话。"""

import sqlalchemy as sa
from alembic import op

revision = '0013_preference_handoffs'
down_revision = '0012_system_credentials'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('preference_verification_handoffs',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('admin_session_hash', sa.String(64), nullable=False),
        sa.Column('admin_auth_version', sa.Integer(), nullable=False),
        sa.Column('draft_version', sa.Integer(), nullable=False),
        sa.Column('draft_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('editor_session_hash', sa.String(64)),
        sa.Column('context_hash', sa.String(64)),
        sa.Column('report_id', sa.String(256)),
        sa.Column('revision', sa.Integer()),
        sa.Column('consumed_at', sa.DateTime(timezone=True)), schema='reporting_management')
    op.create_index('ix_preference_handoffs_expires_at',
        'preference_verification_handoffs', ['expires_at'], schema='reporting_management')


def downgrade():
    op.drop_table('preference_verification_handoffs', schema='reporting_management')
