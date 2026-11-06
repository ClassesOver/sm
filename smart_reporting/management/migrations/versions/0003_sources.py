"""数据源草稿、不可变发布版本和加密凭据。"""
import sqlalchemy as sa
from alembic import op

revision = '0003_sources'
down_revision = '0002_scopes'
branch_labels = None
depends_on = None
SCHEMA = 'reporting_management'


def upgrade():
    op.create_table('sources',
        sa.Column('scope_id', sa.String(36), primary_key=True),
        sa.Column('source_id', sa.String(64), primary_key=True),
        sa.Column('enabled', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('draft_version', sa.Integer(), nullable=False),
        sa.Column('published_revision', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False), schema=SCHEMA)
    op.create_table('source_drafts',
        sa.Column('scope_id', sa.String(36), primary_key=True),
        sa.Column('source_id', sa.String(64), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('source_type', sa.String(32), nullable=False),
        sa.Column('database', sa.String(128), nullable=False),
        sa.Column('credential_ref', sa.String(36), nullable=False),
        sa.Column('credential_revision', sa.Integer(), nullable=False),
        sa.Column('profile_version_id', sa.String(64)),
        sa.Column('metadata_version_id', sa.String(64)),
        sa.Column('content_hash', sa.String(64), nullable=False), schema=SCHEMA)
    op.create_table('source_versions',
        sa.Column('scope_id', sa.String(36), primary_key=True),
        sa.Column('source_id', sa.String(64), primary_key=True),
        sa.Column('revision', sa.Integer(), primary_key=True),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('source_type', sa.String(32), nullable=False),
        sa.Column('database', sa.String(128), nullable=False),
        sa.Column('credential_ref', sa.String(36), nullable=False),
        sa.Column('credential_revision', sa.Integer(), nullable=False),
        sa.Column('profile_version_id', sa.String(64)),
        sa.Column('metadata_version_id', sa.String(64)), schema=SCHEMA)
    op.create_table('source_credentials',
        sa.Column('scope_id', sa.String(36), primary_key=True),
        sa.Column('source_id', sa.String(64), primary_key=True),
        sa.Column('credential_ref', sa.String(36), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('key_id', sa.String(32), nullable=False),
        sa.Column('ciphertext', sa.JSON(), nullable=False),
        sa.Column('secret_hash', sa.String(64), nullable=False), schema=SCHEMA)


def downgrade():
    for table in ('source_credentials', 'source_versions', 'source_drafts', 'sources'):
        op.drop_table(table, schema=SCHEMA)
