"""管理端集成测试共用夹具：已发布指标、统计口径、业务证据与合成数据源/目录版本。"""

import pytest

from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_evidence_publication import (
    approved_document,
    evidence_service,
    publish,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context


@pytest.fixture
async def basis_context(document_context, index_context):
    from cryptography.fernet import Fernet
    from sqlalchemy import insert, update

    from smart_reporting.management.catalog import CatalogService
    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.data_sources.service import SourceService
    from smart_reporting.management.repository import (
        catalog_versions,
        tenant_settings,
    )
    from smart_reporting.reporting.contract import (
        ModelColumn,
        ModelTable,
        ModelTermsResponse,
        RawDdlModel,
        SourceRef,
        schema_hash,
    )

    documents, token, scope, other_scope, _, _ = document_context
    scopes = documents.scopes
    repository = scopes.repository
    evidence_docs = document_context
    await approved_document(evidence_docs)
    evidence = evidence_service(evidence_docs, index_context)
    rules = await publish(evidence, evidence_docs)

    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.statistical_policies import StatisticalPolicyService
    from smart_reporting.reporting.tests.test_semantic_models import metric_payload, policy_payload

    metrics = MetricService(scopes)
    body = metric_payload()
    body.pop("scopeId")
    body.pop("revision")
    await metrics.save_draft(token, scope, body, 0)
    await metrics.publish(token, scope, "budget", expected_version=1)
    policy_service = StatisticalPolicyService(scopes, evidence)
    policy = policy_payload(evidenceReleaseId=rules.release_id)
    policy.pop("scopeId")
    policy.pop("revision")
    await policy_service.save_draft(token, scope, policy, expected_version=0)
    await policy_service.publish(token, scope, "monthly-budget", expected_version=1)
    await policy_service.set_default(
        token,
        scope,
        "budget_execution",
        policy_version={"policyId": "monthly-budget", "revision": 1},
        expected_version=0,
    )

    vault = CredentialVault(f"key-a:{Fernet.generate_key().decode()}")
    # 通过新连接服务发布，合成目录不依赖旧Profile。
    table = ModelTable(sourceId="warehouse", database="test", name="budget", columns=(
        ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=False),
        ModelColumn(name="period", dataType="DATE", nullable=False),
        ModelColumn(name="project_id", dataType="VARCHAR(20)", nullable=False),
    ))
    model = ModelTermsResponse(revision="catalog-1", schemaHash=schema_hash((table,)),
        sourceRefs=(SourceRef(sourceId="warehouse"),), tables=(table,),
        ddlModels=(RawDdlModel(id=1, modelName="预算", ddl="CREATE TABLE test.budget (amount DECIMAL(18,2) NOT NULL, period DATE NOT NULL, project_id VARCHAR(20) NOT NULL)"),))
    catalog_body = {"metadata": model.model_dump(mode="json", by_alias=True),
        "tables": [table.model_dump(mode="json", by_alias=True)]}
    from smart_reporting.management.data_sources.models import SourceDraftInput
    source_service = SourceService(scopes, vault)
    await source_service.create_draft(token, scope, "warehouse", SourceDraftInput(
        name="合成数据源", database="test", metadataVersionId="warehouse:1",
        dsn="starrocks://reporter:synthetic-only@localhost:9030/test"))
    async with repository.transaction() as connection:
        registered_scope = await scopes.require_registered(connection, scope)
        now = scopes.auth.clock()
        sid = registered_scope["id"]
        await connection.execute(insert(catalog_versions).values(scope_id=sid, source_id="warehouse",
            revision=1, status="published", catalog=catalog_body,
            content_hash=CatalogService._hash(catalog_body), synced_at=now))
        await connection.execute(update(tenant_settings).where(tenant_settings.c.id == sid)
            .values(default_source_ids=["warehouse"]))
    await source_service.publish(token, scope, "warehouse", 1)
    return {
        "scopes": scopes,
        "repository": repository,
        "policy_service": policy_service,
        "token": token,
        "scope": scope,
        "other_scope": other_scope,
        "scope_id": registered_scope["id"],
        "release_id": rules.release_id,
        "vault": vault,
    }
