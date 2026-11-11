"""真实隔离管理PG和向量PG验证发布及撤销；合成向量不验中文语义。"""

from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import event, func, select

from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
from smart_reporting.reporting.semantics.models import Period
from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_document_ingestion import metadata, register
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def approved_document(context):
    service, token, first, _, _, _ = context
    uploaded = await register(context, body="执行额合计÷预算额合计，不能平均各组比率。".encode())
    await service.ingest_revision(await service.claim_next())
    detail = await service.get_document(token, first, uploaded.document_id)
    await service.review_revision(token, first, uploaded.document_id, 1, decision="approved",
        reason="核对合成原文", expected_version=detail["revisions"][0]["stateVersion"])
    return uploaded


def evidence_service(context, index_context):
    from smart_reporting.management.business_evidence import BusinessEvidenceService
    return BusinessEvidenceService(context[0], index_context[0])


async def publish(service, context, request_id="release-1"):
    return await service.publish(context[1], context[2], request_id=request_id, kind="rule_evidence",
        revision_ids=(DocumentRevisionRef(document_id="budget-rules", revision=1),))


async def search(service, context, release_id):
    return await service.search_preview(context[1], context[2], release_id, query="执行率如何计算",
        metric_ids=("execution-rate",), period=Period(start=date(2026, 1, 1), end=date(2026, 10, 1)),
        knowledge_as_of=context[0].clock())


async def test_release_is_immutable_idempotent_and_scope_bound(document_context, index_context, auth_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import business_evidence_releases
    await approved_document(document_context)
    service = evidence_service(document_context, index_context)
    release = await publish(service, document_context)
    assert await publish(service, document_context) == release
    found = await search(service, document_context, release.release_id)
    assert found.status == "matched"
    assert found.hits[0].quote == "执行额合计÷预算额合计，不能平均各组比率。"
    with pytest.raises(ManagementError) as foreign:
        await service.get(document_context[1], document_context[3], release.release_id)
    assert foreign.value.status == 404
    async with auth_context[1].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(business_evidence_releases)) == 1


async def test_unreviewed_or_failed_index_never_creates_release(document_context, index_context, auth_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import business_evidence_releases
    service = evidence_service(document_context, index_context)
    await register(document_context)
    with pytest.raises(ManagementError) as unreviewed:
        await publish(service, document_context)
    assert unreviewed.value.status == 409
    documents, token, scope, _, _, _ = document_context
    await documents.ingest_revision(await documents.claim_next())
    detail = await documents.get_document(token, scope, "budget-rules")
    await documents.review_revision(token, scope, "budget-rules", 1, decision="approved", reason="原文核对",
        expected_version=detail["revisions"][0]["stateVersion"])
    index_context[2].failure = "empty"
    with pytest.raises(ManagementError) as unavailable:
        await publish(service, document_context)
    assert unavailable.value.status == 503
    async with auth_context[1].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(business_evidence_releases)) == 0
    index_context[2].failure = None
    assert (await publish(service, document_context)).release_id


async def test_search_distinguishes_unavailable_from_revoked_and_revalidates_inflight(document_context, index_context, monkeypatch):
    await approved_document(document_context)
    service = evidence_service(document_context, index_context)
    release = await publish(service, document_context)
    index_context[2].failure = "error"
    failed = await search(service, document_context, release.release_id)
    assert failed.status == "unavailable" and failed.hits == ()
    index_context[2].failure = None
    original_search = index_context[0].search

    async def revoke_during_search(*args, **kwargs):
        hits = await original_search(*args, **kwargs)
        documents, token, scope, _, _, _ = document_context
        detail = await documents.get_document(token, scope, "budget-rules")
        await documents.review_revision(token, scope, "budget-rules", 1, decision="revoked", reason="撤销访问",
            expected_version=detail["revisions"][0]["stateVersion"])
        return hits

    monkeypatch.setattr(index_context[0], "search", revoke_during_search)
    revoked = await search(service, document_context, release.release_id)
    assert revoked.status == "revoked" and revoked.hits == ()
    assert "不能平均" not in str(revoked.model_dump())


async def test_publication_audit_failure_rolls_back_release_and_ready_state(document_context, index_context, monkeypatch):
    await approved_document(document_context)
    service = evidence_service(document_context, index_context)
    original_audit = service.scopes.audit

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit fault")

    monkeypatch.setattr(service.scopes, "audit", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit fault"):
        await publish(service, document_context)
    detail = await document_context[0].get_document(document_context[1], document_context[2], "budget-rules")
    assert detail["revisions"][0]["ingestionStatus"] == "parsed"
    monkeypatch.setattr(service.scopes, "audit", original_audit)
    assert (await publish(service, document_context)).release_id


async def test_revocation_during_build_cannot_publish(document_context, index_context, monkeypatch, auth_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import business_evidence_releases
    await approved_document(document_context)
    service = evidence_service(document_context, index_context)
    original_build = index_context[0].build

    async def revoke_after_build(*args, **kwargs):
        receipt = await original_build(*args, **kwargs)
        documents, token, scope, _, _, _ = document_context
        detail = await documents.get_document(token, scope, "budget-rules")
        await documents.review_revision(token, scope, "budget-rules", 1, decision="revoked", reason="撤销访问",
            expected_version=detail["revisions"][0]["stateVersion"])
        return receipt

    monkeypatch.setattr(index_context[0], "build", revoke_after_build)
    with pytest.raises(ManagementError) as rejected:
        await publish(service, document_context)
    assert rejected.value.status == 409
    async with auth_context[1].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(business_evidence_releases)) == 0


@pytest.mark.parametrize("restriction", ["expired", "future_recorded", "other_metric", "other_project"])
async def test_inapplicable_documents_do_not_enter_search(document_context, index_context, restriction):
    changes = {"validTo": "2026-02-01"} if restriction == "expired" else {}
    if restriction in ("other_metric", "other_project"):
        changes["appliesTo"] = [{"kind": "metric" if restriction == "other_metric" else "project", "id": "other-object"}]
    documents, token, scope, _, _, _ = document_context
    await register(document_context, details=metadata(**changes))
    await documents.ingest_revision(await documents.claim_next())
    detail = await documents.get_document(token, scope, "budget-rules")
    await documents.review_revision(token, scope, "budget-rules", 1, decision="approved", reason="原文核对",
        expected_version=detail["revisions"][0]["stateVersion"])
    service = evidence_service(document_context, index_context)
    release = await publish(service, document_context)
    result = await service.search_preview(token, scope, release.release_id, query="执行率", metric_ids=("execution-rate",),
        period=Period(start=date(2026, 1, 1), end=date(2026, 10, 1)),
        knowledge_as_of=documents.clock() - timedelta(days=1) if restriction == "future_recorded" else documents.clock())
    assert result.status == "inapplicable" and result.hits == ()


async def test_cached_receipt_revalidates_current_authorization_and_original_quote(document_context, index_context):
    await approved_document(document_context)
    service = evidence_service(document_context, index_context)
    release = await publish(service, document_context)
    cached = await search(service, document_context, release.release_id)
    changed_hit = cached.hits[0].model_copy(update={"quote": "制度没有说过的结论"})
    forged = cached.model_copy(update={"hits": (changed_hit,)})
    invalid = await service.revalidate_receipt(document_context[1], document_context[2], forged)
    assert invalid.status == "unavailable" and invalid.hits == ()
    documents, token, scope, _, _, _ = document_context
    detail = await documents.get_document(token, scope, "budget-rules")
    await documents.review_revision(token, scope, "budget-rules", 1, decision="revoked", reason="恢复前撤销",
        expected_version=detail["revisions"][0]["stateVersion"])
    revoked = await service.revalidate_receipt(token, scope, cached)
    assert revoked.status == "revoked" and revoked.hits == ()
    assert "不能平均" not in str(revoked.model_dump())


async def test_response_lost_after_commit_reads_back_same_release(document_context, index_context, monkeypatch, auth_context):
    from smart_reporting.management.repository import business_evidence_releases
    await approved_document(document_context)
    service = evidence_service(document_context, index_context)
    original_transaction = service.scopes.write_transaction
    transactions = 0

    @asynccontextmanager
    async def response_lost(actor):
        nonlocal transactions
        async with original_transaction(actor) as connection:
            yield connection
        transactions += 1
        if transactions == 2:
            raise ConnectionError("synthetic response lost")

    monkeypatch.setattr(service.scopes, "write_transaction", response_lost)
    with pytest.raises(ConnectionError, match="synthetic response lost"):
        await publish(service, document_context)
    monkeypatch.setattr(service.scopes, "write_transaction", original_transaction)
    recovered = await publish(service, document_context)
    assert (await service.get(document_context[1], document_context[2], recovered.release_id)) == recovered
    async with auth_context[1].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(business_evidence_releases)) == 1


async def test_revoked_member_text_is_not_read_when_searching_active_member(document_context, index_context):
    await approved_document(document_context)
    documents, token, scope, _, _, _ = document_context
    uploaded = await register(document_context, request_id="second-upload", body=b"active rule", details=metadata(id="active-rules"))
    await documents.ingest_revision(await documents.claim_next())
    detail = await documents.get_document(token, scope, uploaded.document_id)
    await documents.review_revision(token, scope, uploaded.document_id, 1, decision="approved", reason="核对",
        expected_version=detail["revisions"][0]["stateVersion"])
    service = evidence_service(document_context, index_context)
    release = await service.publish(token, scope, request_id="two-rules", kind="rule_evidence", revision_ids=(
        DocumentRevisionRef(document_id="budget-rules", revision=1), DocumentRevisionRef(document_id="active-rules", revision=1)))
    detail = await documents.get_document(token, scope, "budget-rules")
    await documents.review_revision(token, scope, "budget-rules", 1, decision="revoked", reason="撤销",
        expected_version=detail["revisions"][0]["stateVersion"])
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "SELECT" in statement and "semantic_probe" in statement:
            statements.append((statement, parameters))

    event.listen(index_context[1].db_engine, "before_cursor_execute", capture)
    try:
        found = await search(service, document_context, release.release_id)
    finally:
        event.remove(index_context[1].db_engine, "before_cursor_execute", capture)
    assert found.status == "matched"
    assert {hit.document_id for hit in found.hits} == {"active-rules"}
    assert statements
    assert all("document_key" in statement or "document_key" in str(parameters) for statement, parameters in statements)


async def test_real_empty_search_has_no_match_status(document_context, index_context, monkeypatch):
    await approved_document(document_context)
    service = evidence_service(document_context, index_context)
    release = await publish(service, document_context)
    index_context[1].similarity_threshold = 0.8
    monkeypatch.setattr(index_context[2], "get_embedding", lambda query: [0.0, 1.0] + [0.0] * 6)
    found = await search(service, document_context, release.release_id)
    assert found.status == "no_match" and found.hits == ()
    assert "knowledge_unavailable" not in found.issue_codes


async def test_missing_original_invalidates_live_and_cached_evidence(document_context, index_context):
    from smart_reporting.management.repository import business_document_revisions
    await approved_document(document_context)
    service = evidence_service(document_context, index_context)
    release = await publish(service, document_context)
    cached = await search(service, document_context, release.release_id)
    documents, token, scope, _, scope_id, _ = document_context
    async with documents.repository.transaction() as connection:
        resource_id = await connection.scalar(select(business_document_revisions.c.original_resource_id).where(
            business_document_revisions.c.scope_id == scope_id))
    await documents.originals.discard(scope_id, resource_id)
    live = await search(service, document_context, release.release_id)
    restored = await service.revalidate_receipt(token, scope, cached)
    assert live.status == restored.status == "unavailable"
    assert live.hits == restored.hits == ()
