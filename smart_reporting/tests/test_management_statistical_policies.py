"""统计口径发布与默认绑定分离；只引用真实已发布证据和指标版本。"""

import asyncio

import pytest

from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.reporting.tests.test_semantic_models import metric_payload, policy_payload
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_evidence_publication import (
    approved_document,
    evidence_service,
    publish,
)
from smart_reporting.tests.test_management_metrics import draft
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def policy_context(documents, index):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.statistical_policies import StatisticalPolicyService
    await approved_document(documents)
    evidence = evidence_service(documents, index)
    release = await publish(evidence, documents)
    metrics = MetricService(documents[0].scopes)
    await metrics.save_draft(documents[1], documents[2], draft(metric_payload()), 0)
    await metrics.publish(documents[1], documents[2], "budget", expected_version=1)
    return StatisticalPolicyService(documents[0].scopes, evidence), draft(policy_payload(evidenceReleaseId=release.release_id))


async def test_policy_publication_does_not_change_default_and_default_uses_cas(document_context, index_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting.semantics.models import PolicyVersionRef
    service, payload = await policy_context(document_context, index_context)
    token, scope = document_context[1:3]
    await service.save_draft(token, scope, payload, expected_version=0)
    first = await service.publish(token, scope, "monthly-budget", expected_version=1)
    assert first["revision"] == 1
    assert (await service.get_default(token, scope, "budget_execution"))["policyVersion"] is None
    selected = await service.set_default(token, scope, "budget_execution",
        policy_version=PolicyVersionRef(policy_id="monthly-budget", revision=1), expected_version=0)
    assert selected["version"] == 1
    await service.save_draft(token, scope, {**payload, "name": "第二版口径"}, expected_version=1)
    await service.publish(token, scope, "monthly-budget", expected_version=2)
    assert (await service.get_default(token, scope, "budget_execution"))["policyVersion"]["revision"] == 1
    attempts = await asyncio.gather(*(service.set_default(token, scope, "budget_execution",
        policy_version=PolicyVersionRef(policy_id="monthly-budget", revision=2), expected_version=1) for _ in range(2)), return_exceptions=True)
    assert sum(isinstance(item, ManagementError) and item.status == 409 for item in attempts) == 1


async def test_policy_rejects_foreign_release_and_unpublished_metric(document_context, index_context):
    from smart_reporting.management.models import ManagementError
    service, payload = await policy_context(document_context, index_context)
    token, first, second = document_context[1:4]
    await service.save_draft(token, second, payload, expected_version=0)
    with pytest.raises(ManagementError) as foreign:
        await service.publish(token, second, "monthly-budget", expected_version=1)
    assert foreign.value.status in (404, 409)
    await service.save_draft(token, first, {**payload, "metricVersions": [{"metricId": "budget", "revision": 2}]}, expected_version=0)
    with pytest.raises(ManagementError) as missing:
        await service.publish(token, first, "monthly-budget", expected_version=1)
    assert missing.value.status == 409
    assert (await service.get(token, first, "monthly-budget"))["published"] is None


async def test_policy_preview_uses_structural_differences_not_chinese_wording(document_context, index_context):
    service, payload = await policy_context(document_context, index_context)
    token, scope = document_context[1:3]
    await service.save_draft(token, scope, payload, expected_version=0)
    await service.publish(token, scope, "monthly-budget", expected_version=1)
    renamed = await service.preview(token, scope, {**payload, "name": "预算执行分析规则"})
    assert renamed["calculationChanged"] is False
    filtered = await service.preview(token, scope, {**payload, "filters": [{
        "fieldRef": "warehouse.test.budget.project_id", "operator": "eq", "values": ["A"],
    }]})
    assert filtered["calculationChanged"] is True
    assert filtered["evidenceChanged"] is False


async def test_retired_metric_keeps_history_but_blocks_new_policy_and_default(document_context, index_context):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting.semantics.models import PolicyVersionRef
    service, payload = await policy_context(document_context, index_context)
    token, scope = document_context[1:3]
    await service.save_draft(token, scope, payload, expected_version=0)
    published = await service.publish(token, scope, "monthly-budget", expected_version=1)
    ref = PolicyVersionRef(policy_id="monthly-budget", revision=1)
    await service.set_default(token, scope, "budget_execution", policy_version=ref, expected_version=0)
    metrics = MetricService(service.scopes)
    original = (await metrics.get(token, scope, "budget"))["published"]
    retired = await metrics.retire(token, scope, "budget", 1, reason="已确认该版存在重复计入")
    assert retired["revision"] == 1
    assert (await metrics.get(token, scope, "budget"))["published"] == original
    current = await service.get_default(token, scope, "budget_execution")
    assert current["policyVersion"] == {"policyId": "monthly-budget", "revision": 1}
    assert current["issues"][0]["code"] == "semantic_asset_retired"
    with pytest.raises(ManagementError) as default:
        await service.set_default(token, scope, "budget_execution", policy_version=ref, expected_version=1)
    assert default.value.code == "management_semantic_asset_retired"
    await service.save_draft(token, scope, {**payload, "name": "另一版"}, expected_version=1)
    with pytest.raises(ManagementError) as publication:
        await service.publish(token, scope, "monthly-budget", expected_version=2)
    assert publication.value.code == "management_semantic_asset_retired"
    assert (await service.get(token, scope, "monthly-budget"))["published"] == {key: published[key] for key in ("revision", "document", "contentHash")}


async def test_policy_retirement_readback_conflict_and_scope(document_context, index_context, monkeypatch):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting.semantics.models import PolicyVersionRef
    service, payload = await policy_context(document_context, index_context)
    token, scope, other = document_context[1:4]
    await service.save_draft(token, scope, payload, expected_version=0)
    await service.publish(token, scope, "monthly-budget", expected_version=1)
    audit = service.scopes.audit
    async def broken_audit(*args, **kwargs):
        raise RuntimeError("isolated audit failure")
    with monkeypatch.context() as patch:
        patch.setattr(service.scopes, "audit", broken_audit)
        with pytest.raises(RuntimeError, match="isolated audit failure"):
            await service.retire(token, scope, "monthly-budget", 1, reason="规则需修正")
    assert service.scopes.audit == audit
    await service.set_default(token, scope, "budget_execution", policy_version=PolicyVersionRef(policy_id="monthly-budget", revision=1), expected_version=0)
    first = await service.retire(token, scope, "monthly-budget", 1, reason="规则需修正")
    assert await service.retire(token, scope, "monthly-budget", 1, reason="规则需修正") == first
    with pytest.raises(ManagementError) as conflicting:
        await service.retire(token, scope, "monthly-budget", 1, reason="另一个原因")
    assert conflicting.value.status == 409
    with pytest.raises(ManagementError) as foreign:
        await service.retire(token, other, "monthly-budget", 1, reason="不属于该组织")
    assert foreign.value.status == 404
    with pytest.raises(ManagementError) as retired:
        await service.set_default(token, scope, "budget_execution", policy_version=PolicyVersionRef(policy_id="monthly-budget", revision=1), expected_version=1)
    assert retired.value.code == "management_semantic_asset_retired"


async def test_default_retains_metric_semantic_issues_without_blocking_publication(document_context, index_context):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.reporting.semantics.models import PolicyVersionRef
    from smart_reporting.reporting.tests.test_semantic_models import ratio_payload
    service, payload = await policy_context(document_context, index_context)
    token, scope = document_context[1:3]
    metrics = MetricService(service.scopes)
    await metrics.save_draft(token, scope, draft(metric_payload("actual", unit="万元")), 0)
    await metrics.publish(token, scope, "actual", expected_version=1)
    await metrics.save_draft(token, scope, draft(ratio_payload()), 0)
    await metrics.publish(token, scope, "rate", expected_version=1)
    await service.save_draft(token, scope, {**payload, "metricVersions": [{"metricId": "rate", "revision": 1}]}, expected_version=0)
    published = await service.publish(token, scope, "monthly-budget", expected_version=1)
    assert published["issues"][0]["code"] == "ratio_unit_mismatch"
    await service.set_default(token, scope, "budget_execution", policy_version=PolicyVersionRef(policy_id="monthly-budget", revision=1), expected_version=0)
    current = await service.get_default(token, scope, "budget_execution")
    assert current["policyVersion"]["revision"] == 1
    assert [(item["code"], item["impact"]) for item in current["issues"]] == [("ratio_unit_mismatch", "unavailable")]


async def test_policy_preview_follows_exact_metric_formula_not_version_number(document_context, index_context):
    from smart_reporting.management.metrics import MetricService
    service, payload = await policy_context(document_context, index_context)
    token, scope = document_context[1:3]
    await service.save_draft(token, scope, payload, expected_version=0)
    await service.publish(token, scope, "monthly-budget", expected_version=1)
    metrics = MetricService(service.scopes)
    await metrics.save_draft(token, scope, draft(metric_payload(name="只改指标名称")), 1)
    await metrics.publish(token, scope, "budget", expected_version=2)
    renamed = {**payload, "metricVersions": [{"metricId": "budget", "revision": 2}]}
    preview = await service.preview(token, scope, renamed)
    assert preview["calculationChanged"] is False
    assert preview["metricVersionsChanged"] is True
    await metrics.save_draft(token, scope, draft(metric_payload(fieldRef="warehouse.test.budget.net_amount")), 2)
    await metrics.publish(token, scope, "budget", expected_version=3)
    formula = await service.preview(token, scope, {**payload, "metricVersions": [{"metricId": "budget", "revision": 3}]})
    assert formula["calculationChanged"] is True
    assert "metrics" in formula["changedFields"]


async def test_policy_publication_audit_and_lost_default_response_are_readable(document_context, index_context, monkeypatch):
    from contextlib import asynccontextmanager

    from smart_reporting.reporting.semantics.models import PolicyVersionRef
    service, payload = await policy_context(document_context, index_context)
    token, scope = document_context[1:3]
    await service.save_draft(token, scope, payload, expected_version=0)
    async def audit_failure(*args, **kwargs):
        raise RuntimeError("synthetic policy audit fault")
    with monkeypatch.context() as patch:
        patch.setattr(service.scopes, "audit", audit_failure)
        with pytest.raises(RuntimeError, match="synthetic policy audit fault"):
            await service.publish(token, scope, "monthly-budget", expected_version=1)
    assert (await service.get(token, scope, "monthly-budget"))["published"] is None
    await service.publish(token, scope, "monthly-budget", expected_version=1)
    transaction = service.scopes.write_transaction
    @asynccontextmanager
    async def lost_response(actor):
        async with transaction(actor) as connection:
            yield connection
        raise ConnectionError("synthetic lost default response")
    with monkeypatch.context() as patch:
        patch.setattr(service.scopes, "write_transaction", lost_response)
        with pytest.raises(ConnectionError, match="synthetic lost default response"):
            await service.set_default(token, scope, "budget_execution", policy_version=PolicyVersionRef(policy_id="monthly-budget", revision=1), expected_version=0)
    readback = await service.get_default(token, scope, "budget_execution")
    assert readback["version"] == 1 and readback["policyVersion"]["revision"] == 1


async def test_default_rejects_revoked_background_and_readback_explains_it(document_context, index_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
    from smart_reporting.reporting.semantics.models import PolicyVersionRef
    from smart_reporting.tests.test_business_document_ingestion import metadata, register
    service, payload = await policy_context(document_context, index_context)
    documents, token, scope = document_context[:3]
    await service.save_draft(token, scope, payload, expected_version=0)
    await service.publish(token, scope, "monthly-budget", expected_version=1)
    await register(document_context, request_id="background-upload", details=metadata(id="project-delay", kind="background"))
    await documents.ingest_revision(await documents.claim_next())
    detail = await documents.get_document(token, scope, "project-delay")
    await documents.review_revision(token, scope, "project-delay", 1, decision="approved", reason="合成背景已核对", expected_version=detail["revisions"][0]["stateVersion"])
    background = await service.evidence.publish(token, scope, request_id="background-release", kind="background", revision_ids=(DocumentRevisionRef(document_id="project-delay", revision=1),))
    ref = PolicyVersionRef(policy_id="monthly-budget", revision=1)
    await service.set_default(token, scope, "budget_execution", policy_version=ref, expected_version=0, background_release_id=background.release_id)
    detail = await documents.get_document(token, scope, "project-delay")
    await documents.review_revision(token, scope, "project-delay", 1, decision="revoked", reason="撤销背景访问", expected_version=detail["revisions"][0]["stateVersion"])
    with pytest.raises(ManagementError) as revoked:
        await service.set_default(token, scope, "budget_execution", policy_version=ref, expected_version=1, background_release_id=background.release_id)
    assert revoked.value.code == "management_policy_background_unavailable"
    current = await service.get_default(token, scope, "budget_execution")
    assert current["version"] == 1 and current["backgroundReleaseId"] == background.release_id
    assert current["issues"][0]["code"] == "policy_background_unavailable"
    assert current["issues"][0]["message"] != "management_policy_background_unavailable"


async def test_policy_impact_paginates_exact_defaults_and_report_bases_without_foreign_scope(document_context, index_context):
    from sqlalchemy import insert

    from smart_reporting.management.business_documents import _digest
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import report_bases
    from smart_reporting.reporting.semantics.models import PolicyVersionRef
    service, payload = await policy_context(document_context, index_context)
    token, scope, other, scope_id, other_id = document_context[1:]
    await service.save_draft(token, scope, payload, expected_version=0)
    published = await service.publish(token, scope, "monthly-budget", expected_version=1)
    await service.set_default(token, scope, "budget_execution", policy_version=PolicyVersionRef(policy_id="monthly-budget", revision=1), expected_version=0)
    # 权威数据库中的登记引用；这里只验证影响读取，不模拟报告工作流完成。
    async with service.repository.transaction() as connection:
        await connection.execute(insert(report_bases).values(scope_id=scope_id, run_id="run-1", basis_id="basis-1",
            policy_id="monthly-budget", policy_revision=1, evidence_release_id=published["document"]["evidenceReleaseId"],
            document={"id": "basis-1"}, content_hash=_digest({"id": "basis-1"}), registered_at=service.scopes.auth.clock()))
    first = await service.impact(token, scope, "monthly-budget", limit=1)
    assert first["items"] == [{"kind": "default", "referenceId": "budget_execution", "policyRevision": 1, "basisId": None}]
    second = await service.impact(token, scope, "monthly-budget", limit=1, after=first["nextCursor"])
    assert second["items"] == [{"kind": "report", "referenceId": "run-1", "policyRevision": 1, "basisId": "basis-1"}]
    assert second["nextCursor"] is None
    with pytest.raises(ManagementError) as foreign:
        await service.impact(token, other, "monthly-budget")
    assert foreign.value.status == 404
