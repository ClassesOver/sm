"""新指标、统计口径、业务证据与报告依据；旧Profile数据不转换。"""

from alembic import op

revision = "0009_semantic_assets"
down_revision = "0008_table_discoveries"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE reporting_management.business_documents (
	scope_id VARCHAR(36) NOT NULL,
	document_id VARCHAR(128) NOT NULL,
	version INTEGER NOT NULL,
	title VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (scope_id, document_id),
	CHECK (version > 0),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.business_evidence_releases (
	scope_id VARCHAR(36) NOT NULL,
	release_id VARCHAR(128) NOT NULL,
	kind VARCHAR(32) NOT NULL,
	document JSON NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (scope_id, release_id),
	CHECK (kind IN ('rule_evidence','background')),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.metric_drafts (
	scope_id VARCHAR(36) NOT NULL,
	metric_id VARCHAR(128) NOT NULL,
	version INTEGER NOT NULL,
	document JSON NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	PRIMARY KEY (scope_id, metric_id),
	CHECK (version > 0),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.metric_versions (
	scope_id VARCHAR(36) NOT NULL,
	metric_id VARCHAR(128) NOT NULL,
	revision INTEGER NOT NULL,
	document JSON NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (scope_id, metric_id, revision),
	CHECK (revision > 0),
	CONSTRAINT metric_document_scope CHECK (COALESCE(document->>'scopeId' = scope_id, false)),
	CONSTRAINT metric_document_identity CHECK (COALESCE(document->>'id' = metric_id, false)),
	CONSTRAINT metric_document_revision CHECK (COALESCE((document->>'revision')::integer = revision, false)),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.semantic_asset_retirements (
	scope_id VARCHAR(36) NOT NULL,
	asset_type VARCHAR(32) NOT NULL,
	asset_id VARCHAR(128) NOT NULL,
	revision INTEGER NOT NULL,
	reason VARCHAR(4000) NOT NULL,
	replacement JSON,
	retired_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (scope_id, asset_type, asset_id, revision),
	CHECK (asset_type IN ('metric','statistical_policy') AND revision > 0),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.statistical_policy_drafts (
	scope_id VARCHAR(36) NOT NULL,
	policy_id VARCHAR(128) NOT NULL,
	version INTEGER NOT NULL,
	document JSON NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	PRIMARY KEY (scope_id, policy_id),
	CHECK (version > 0),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.business_document_revisions (
	scope_id VARCHAR(36) NOT NULL,
	document_id VARCHAR(128) NOT NULL,
	revision INTEGER NOT NULL,
	original_resource_id VARCHAR(256) NOT NULL,
	original_hash VARCHAR(64) NOT NULL,
	media_type VARCHAR(128) NOT NULL,
	size_bytes INTEGER NOT NULL,
	document JSON NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	registered_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (scope_id, document_id, revision),
	FOREIGN KEY(scope_id, document_id) REFERENCES reporting_management.business_documents (scope_id, document_id),
	CHECK (revision > 0 AND size_bytes > 0 AND size_bytes <= 20971520),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.metric_dependencies (
	scope_id VARCHAR(36) NOT NULL,
	metric_id VARCHAR(128) NOT NULL,
	revision INTEGER NOT NULL,
	dependency_metric_id VARCHAR(128) NOT NULL,
	dependency_revision INTEGER NOT NULL,
	PRIMARY KEY (scope_id, metric_id, revision, dependency_metric_id, dependency_revision),
	FOREIGN KEY(scope_id, metric_id, revision) REFERENCES reporting_management.metric_versions (scope_id, metric_id, revision),
	FOREIGN KEY(scope_id, dependency_metric_id, dependency_revision) REFERENCES reporting_management.metric_versions (scope_id, metric_id, revision),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.statistical_policy_versions (
	scope_id VARCHAR(36) NOT NULL,
	policy_id VARCHAR(128) NOT NULL,
	revision INTEGER NOT NULL,
	document JSON NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE NOT NULL,
	evidence_release_id VARCHAR(128) NOT NULL,
	PRIMARY KEY (scope_id, policy_id, revision),
	CHECK (revision > 0),
	FOREIGN KEY(scope_id, evidence_release_id) REFERENCES reporting_management.business_evidence_releases (scope_id, release_id),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.business_evidence_release_documents (
	scope_id VARCHAR(36) NOT NULL,
	release_id VARCHAR(128) NOT NULL,
	document_id VARCHAR(128) NOT NULL,
	revision INTEGER NOT NULL,
	PRIMARY KEY (scope_id, release_id, document_id, revision),
	FOREIGN KEY(scope_id, release_id) REFERENCES reporting_management.business_evidence_releases (scope_id, release_id),
	FOREIGN KEY(scope_id, document_id, revision) REFERENCES reporting_management.business_document_revisions (scope_id, document_id, revision),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.business_ingestion_jobs (
	scope_id VARCHAR(36) NOT NULL,
	job_id VARCHAR(128) NOT NULL,
	document_id VARCHAR(128) NOT NULL,
	revision INTEGER NOT NULL,
	request_id VARCHAR(128) NOT NULL,
	input_hash VARCHAR(64) NOT NULL,
	status VARCHAR(32) NOT NULL,
	attempts INTEGER DEFAULT '0' NOT NULL,
	lease_owner VARCHAR(128),
	lease_until TIMESTAMP WITH TIME ZONE,
	issues JSON NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (scope_id, job_id),
	UNIQUE (scope_id, request_id),
	FOREIGN KEY(scope_id, document_id, revision) REFERENCES reporting_management.business_document_revisions (scope_id, document_id, revision),
	CHECK (status IN ('queued','running','parsed','failed','ready','needs_transcription') AND attempts >= 0),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.business_revision_states (
	scope_id VARCHAR(36) NOT NULL,
	document_id VARCHAR(128) NOT NULL,
	revision INTEGER NOT NULL,
	version INTEGER NOT NULL,
	ingestion_status VARCHAR(32) NOT NULL,
	review_status VARCHAR(32) NOT NULL,
	parse_receipt JSON,
	review_receipt JSON,
	PRIMARY KEY (scope_id, document_id, revision),
	FOREIGN KEY(scope_id, document_id, revision) REFERENCES reporting_management.business_document_revisions (scope_id, document_id, revision),
	CHECK (version > 0),
	CHECK (ingestion_status IN ('queued','running','parsed','failed','ready','needs_transcription')),
	CHECK (review_status IN ('pending','approved','rejected','revoked')),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.report_bases (
	scope_id VARCHAR(36) NOT NULL,
	run_id VARCHAR(256) NOT NULL,
	basis_id VARCHAR(128) NOT NULL,
	policy_id VARCHAR(128) NOT NULL,
	policy_revision INTEGER NOT NULL,
	evidence_release_id VARCHAR(128) NOT NULL,
	background_release_id VARCHAR(128),
	document JSON NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	registered_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (scope_id, run_id),
	UNIQUE (scope_id, basis_id),
	FOREIGN KEY(scope_id, policy_id, policy_revision) REFERENCES reporting_management.statistical_policy_versions (scope_id, policy_id, revision),
	FOREIGN KEY(scope_id, evidence_release_id) REFERENCES reporting_management.business_evidence_releases (scope_id, release_id),
	FOREIGN KEY(scope_id, background_release_id) REFERENCES reporting_management.business_evidence_releases (scope_id, release_id),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.reporting_policy_defaults (
	scope_id VARCHAR(36) NOT NULL,
	scenario VARCHAR(128) NOT NULL,
	version INTEGER NOT NULL,
	policy_id VARCHAR(128) NOT NULL,
	policy_revision INTEGER NOT NULL,
	background_release_id VARCHAR(128),
	PRIMARY KEY (scope_id, scenario),
	FOREIGN KEY(scope_id, policy_id, policy_revision) REFERENCES reporting_management.statistical_policy_versions (scope_id, policy_id, revision),
	FOREIGN KEY(scope_id, background_release_id) REFERENCES reporting_management.business_evidence_releases (scope_id, release_id),
	CHECK (version > 0),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.statistical_policy_metrics (
	scope_id VARCHAR(36) NOT NULL,
	policy_id VARCHAR(128) NOT NULL,
	policy_revision INTEGER NOT NULL,
	metric_id VARCHAR(128) NOT NULL,
	metric_revision INTEGER NOT NULL,
	PRIMARY KEY (scope_id, policy_id, policy_revision, metric_id, metric_revision),
	FOREIGN KEY(scope_id, policy_id, policy_revision) REFERENCES reporting_management.statistical_policy_versions (scope_id, policy_id, revision),
	FOREIGN KEY(scope_id, metric_id, metric_revision) REFERENCES reporting_management.metric_versions (scope_id, metric_id, revision),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.report_basis_receipts (
	scope_id VARCHAR(36) NOT NULL,
	basis_id VARCHAR(128) NOT NULL,
	receipt_id VARCHAR(128) NOT NULL,
	report_revision VARCHAR(256) NOT NULL,
	document JSON NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (scope_id, basis_id, receipt_id),
	FOREIGN KEY(scope_id, basis_id) REFERENCES reporting_management.report_bases (scope_id, basis_id),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE TABLE reporting_management.report_issue_reviews (
	scope_id VARCHAR(36) NOT NULL,
	issue_id VARCHAR(128) NOT NULL,
	basis_id VARCHAR(128) NOT NULL,
	report_revision VARCHAR(256) NOT NULL,
	version INTEGER NOT NULL,
	status VARCHAR(32) NOT NULL,
	document JSON NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (scope_id, issue_id),
	FOREIGN KEY(scope_id, basis_id) REFERENCES reporting_management.report_bases (scope_id, basis_id),
	CHECK (status IN ('open','needs_evidence','accepted','rejected','resolved') AND version > 0),
	FOREIGN KEY(scope_id) REFERENCES reporting_management.tenant_settings (id)
)""")
    op.execute("""CREATE OR REPLACE FUNCTION reporting_management.reject_semantic_version_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'published semantic records are immutable' USING ERRCODE = '23514';
END;
$$""")
    op.execute("""CREATE TRIGGER immutable_metric_versions BEFORE UPDATE OR DELETE ON reporting_management.metric_versions FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_semantic_version_change()""")
    op.execute("""CREATE TRIGGER immutable_metric_dependencies BEFORE UPDATE OR DELETE ON reporting_management.metric_dependencies FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_semantic_version_change()""")
    op.execute("""CREATE TRIGGER immutable_business_document_revisions BEFORE UPDATE OR DELETE ON reporting_management.business_document_revisions FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_semantic_version_change()""")
    op.execute("""CREATE TRIGGER immutable_business_evidence_releases BEFORE UPDATE OR DELETE ON reporting_management.business_evidence_releases FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_semantic_version_change()""")
    op.execute("""CREATE TRIGGER immutable_business_evidence_release_documents BEFORE UPDATE OR DELETE ON reporting_management.business_evidence_release_documents FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_semantic_version_change()""")
    op.execute("""CREATE TRIGGER immutable_statistical_policy_versions BEFORE UPDATE OR DELETE ON reporting_management.statistical_policy_versions FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_semantic_version_change()""")
    op.execute("""CREATE TRIGGER immutable_statistical_policy_metrics BEFORE UPDATE OR DELETE ON reporting_management.statistical_policy_metrics FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_semantic_version_change()""")
    op.execute("""CREATE TRIGGER immutable_report_bases BEFORE UPDATE OR DELETE ON reporting_management.report_bases FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_semantic_version_change()""")
    op.execute("""CREATE TRIGGER immutable_report_basis_receipts BEFORE UPDATE OR DELETE ON reporting_management.report_basis_receipts FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_semantic_version_change()""")
    op.execute("""CREATE TRIGGER immutable_semantic_asset_retirements BEFORE UPDATE OR DELETE ON reporting_management.semantic_asset_retirements FOR EACH ROW EXECUTE FUNCTION reporting_management.reject_semantic_version_change()""")


def downgrade():
    op.drop_table("report_issue_reviews", schema="reporting_management")
    op.drop_table("report_basis_receipts", schema="reporting_management")
    op.drop_table("statistical_policy_metrics", schema="reporting_management")
    op.drop_table("reporting_policy_defaults", schema="reporting_management")
    op.drop_table("report_bases", schema="reporting_management")
    op.drop_table("business_revision_states", schema="reporting_management")
    op.drop_table("business_ingestion_jobs", schema="reporting_management")
    op.drop_table("business_evidence_release_documents", schema="reporting_management")
    op.drop_table("statistical_policy_versions", schema="reporting_management")
    op.drop_table("metric_dependencies", schema="reporting_management")
    op.drop_table("business_document_revisions", schema="reporting_management")
    op.drop_table("statistical_policy_drafts", schema="reporting_management")
    op.drop_table("semantic_asset_retirements", schema="reporting_management")
    op.drop_table("metric_versions", schema="reporting_management")
    op.drop_table("metric_drafts", schema="reporting_management")
    op.drop_table("business_evidence_releases", schema="reporting_management")
    op.drop_table("business_documents", schema="reporting_management")
    op.execute("DROP FUNCTION reporting_management.reject_semantic_version_change()")
