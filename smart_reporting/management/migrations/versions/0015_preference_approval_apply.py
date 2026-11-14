"""已批准偏好发布引用；旧历史保持可读且不改写。"""

import sqlalchemy as sa
from alembic import op

revision = '0015_preference_approval_apply'
down_revision = '0014_preference_evidence'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('configuration_versions', sa.Column('preference_approval_id', sa.String(36)),
        schema='reporting_management')
    op.create_foreign_key('fk_configuration_preference_approval', 'configuration_versions',
        'preference_approval_receipts', ['preference_approval_id'], ['id'],
        source_schema='reporting_management', referent_schema='reporting_management')
    op.create_unique_constraint('uq_configuration_preference_approval', 'configuration_versions',
        ['preference_approval_id'], schema='reporting_management')
    op.create_check_constraint('ck_configuration_preference_approval_kind', 'configuration_versions',
        "preference_approval_id IS NULL OR kind = 'preferences'", schema='reporting_management')
    # NOT VALID保留不可变旧行；PostgreSQL仍逐条检查迁移后的新增行。
    op.execute('''ALTER TABLE reporting_management.configuration_versions
        ADD CONSTRAINT ck_configuration_preferences_require_approval
        CHECK (kind <> 'preferences' OR preference_approval_id IS NOT NULL) NOT VALID''')


def downgrade():
    for name in ('ck_configuration_preferences_require_approval', 'ck_configuration_preference_approval_kind',
        'uq_configuration_preference_approval', 'fk_configuration_preference_approval'):
        op.drop_constraint(name, 'configuration_versions', schema='reporting_management')
    op.drop_column('configuration_versions', 'preference_approval_id', schema='reporting_management')
