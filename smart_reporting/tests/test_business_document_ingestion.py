"""原件登记、审核和可恢复解析；真实PG与真实文件，不依赖业务库。"""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from sqlalchemy import select

from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_semantic_assets_persistence import setup_scopes

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def document_context(auth_context, tmp_path):
    from smart_reporting.management.business_documents import BusinessDocumentService
    from smart_reporting.management.models import ManagementScope
    from smart_reporting.reporting.business_knowledge.originals import BusinessOriginalStore
    scopes, login, first, second, _ = await setup_scopes(auth_context)
    service = BusinessDocumentService(scopes, BusinessOriginalStore(tmp_path / "originals"))
    return service, login.raw_token, ManagementScope("warehouse", "a"), ManagementScope("warehouse", "b"), first, second


def metadata(**changes):
    from smart_reporting.reporting.business_knowledge.models import BusinessDocumentInput
    return BusinessDocumentInput.model_validate({
        "id": "budget-rules", "title": "合成预算制度", "kind": "rule_evidence",
        "validFrom": "2026-01-01", "validTo": "2027-01-01", **changes,
    })


async def register(context, request_id="upload-1", *, body=b"budget definition", expected_version=0, details=None):
    service, token, first, _, _, _ = context
    return await service.register_document(
        token, first, body, filename="rules.txt", metadata=details or metadata(),
        request_id=request_id, expected_version=expected_version,
    )


async def test_upload_readback_is_idempotent_and_original_is_scope_bound(document_context, auth_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import (
        business_document_revisions,
        business_ingestion_jobs,
    )
    service, token, first, second, _, _ = document_context
    receipt = await register(document_context, body="正式制度：执行额合计÷预算合计".encode())
    same = await register(document_context, body="正式制度：执行额合计÷预算合计".encode())
    assert receipt == same
    assert receipt.status == "queued"
    assert receipt.revision == 1
    original = await service.read_original(token, first, receipt.document_id, 1)
    assert original == "正式制度：执行额合计÷预算合计".encode()
    with pytest.raises(ManagementError) as foreign:
        await service.read_original(token, second, receipt.document_id, 1)
    assert foreign.value.status == 404
    with pytest.raises(ManagementError) as changed:
        await register(document_context, body=b"different")
    assert changed.value.status == 409
    _, repository, _ = auth_context
    async with repository.engine.connect() as connection:
        assert len((await connection.execute(select(business_document_revisions))).all()) == 1
        assert len((await connection.execute(select(business_ingestion_jobs))).all()) == 1
    assert "originals" not in str(receipt.model_dump())


async def test_parsing_and_review_are_separate_from_index_readiness(document_context):
    from smart_reporting.management.models import ManagementError
    service, token, first, _, scope_id, _ = document_context
    receipt = await register(document_context, body="执行率采用合计比值".encode())
    with pytest.raises(ManagementError) as unparsed:
        await service.review_revision(token, first, receipt.document_id, 1, decision="approved", reason="已核对", expected_version=1)
    assert unparsed.value.status == 409
    job = await service.claim_next()
    parsed = await service.ingest_revision(job)
    assert parsed.status == "parsed"
    state = await service.get_document(token, first, receipt.document_id)
    assert state["revisions"][0]["ingestionStatus"] == "parsed"
    reviewed = await service.review_revision(
        token, first, receipt.document_id, 1, decision="approved", reason="已核对合成原文",
        expected_version=state["revisions"][0]["stateVersion"],
    )
    assert reviewed["reviewStatus"] == "approved"
    assert reviewed["ingestionStatus"] == "parsed"
    assert await service.claim_next() is None


async def test_duplicate_workers_and_expired_lease_cannot_overwrite_new_attempt(document_context, auth_context):
    from smart_reporting.management.models import ManagementError
    service, _, _, _, _, _ = document_context
    await register(document_context)
    claimed = await asyncio.gather(service.claim_next(), service.claim_next())
    old = next(item for item in claimed if item is not None)
    assert sum(item is not None for item in claimed) == 1
    _, _, clock = auth_context
    clock[0] += timedelta(seconds=121)
    new = await service.claim_next()
    assert new.attempt == old.attempt + 1
    assert new.lease_owner != old.lease_owner
    with pytest.raises(ManagementError) as expired:
        await service.ingest_revision(old)
    assert expired.value.status == 409
    assert (await service.ingest_revision(new)).status == "parsed"


async def test_parse_failure_requires_explicit_retry_and_preserves_original(document_context, monkeypatch):
    import smart_reporting.management.business_documents as module
    service, token, first, _, _, _ = document_context
    receipt = await register(document_context)
    real_parse = module.parse_document

    def broken(*args, **kwargs):
        raise RuntimeError("parser sensitive body must not be returned")

    monkeypatch.setattr(module, "parse_document", broken)
    failed = await service.ingest_revision(await service.claim_next())
    assert failed.status == "failed"
    assert failed.issue_codes == ("document_parse_failed",)
    assert await service.claim_next() is None
    assert "sensitive" not in str(await service.get_job(token, first, receipt.job_id))
    assert await service.read_original(token, first, receipt.document_id, 1) == b"budget definition"
    monkeypatch.setattr(module, "parse_document", real_parse)
    await service.retry_job(token, first, receipt.job_id, expected_attempt=1)
    assert (await service.ingest_revision(await service.claim_next())).status == "parsed"


async def test_revision_cas_audit_failure_and_bad_upload_leave_no_silent_write(document_context, auth_context, monkeypatch):
    from smart_reporting.management.models import ManagementError
    service, _, _, _, _, _ = document_context
    await register(document_context)
    attempts = await asyncio.gather(*(
        register(document_context, name, expected_version=1, body=name.encode())
        for name in ("revision-a", "revision-b")
    ), return_exceptions=True)
    assert sum(isinstance(item, ManagementError) and item.status == 409 for item in attempts) == 1
    original_files = sorted(service.originals.root.rglob("*.bin"))

    async def failed_audit(*args, **kwargs):
        raise RuntimeError("audit fault")

    monkeypatch.setattr(service.scopes, "audit", failed_audit)
    with pytest.raises(RuntimeError, match="audit fault"):
        await register(document_context, "rollback", expected_version=2)
    assert sorted(service.originals.root.rglob("*.bin")) == original_files
    with pytest.raises(ManagementError) as invalid:
        await service.register_document(
            document_context[1], document_context[2], b"not PDF", filename="fake.pdf",
            metadata=metadata(), request_id="bad", expected_version=2,
        )
    assert invalid.value.status == 422


async def test_review_conflict_and_revocation_are_explicit(document_context):
    from smart_reporting.management.models import ManagementError
    service, token, first, _, _, _ = document_context
    receipt = await register(document_context)
    await service.ingest_revision(await service.claim_next())
    revision = (await service.get_document(token, first, receipt.document_id))["revisions"][0]
    approved = await service.review_revision(
        token, first, receipt.document_id, 1, decision="approved", reason="核对通过",
        expected_version=revision["stateVersion"],
    )
    with pytest.raises(ManagementError) as conflict:
        await service.review_revision(token, first, receipt.document_id, 1, decision="revoked", reason="撤销", expected_version=revision["stateVersion"])
    assert conflict.value.status == 409
    await service.review_revision(
        token, first, receipt.document_id, 1, decision="revoked", reason="已撤销原文访问",
        expected_version=approved["stateVersion"],
    )
    with pytest.raises(ManagementError) as revoked:
        await service.read_original(token, first, receipt.document_id, 1)
    assert revoked.value.status == 403


async def test_unknown_commit_outcome_keeps_registered_original_for_readback(document_context, monkeypatch):
    from smart_reporting.management.models import ManagementError
    service, token, first, _, _, _ = document_context
    original_transaction = service.scopes.write_transaction
    calls = 0

    @asynccontextmanager
    async def response_lost(actor):
        nonlocal calls
        calls += 1
        number = calls
        async with original_transaction(actor) as connection:
            yield connection
        if number == 2:
            raise ManagementError("management_unavailable", "提交响应丢失", 503)

    monkeypatch.setattr(service.scopes, "write_transaction", response_lost)
    with pytest.raises(ManagementError):
        await register(document_context)
    monkeypatch.setattr(service.scopes, "write_transaction", original_transaction)
    readback = await register(document_context)
    assert readback.revision == 1
    assert await service.read_original(token, first, readback.document_id, 1) == b"budget definition"


@pytest.mark.parametrize("fault", ["missing", "tampered", "symlink"])
async def test_original_identity_fault_is_unavailable_without_exposing_other_file(document_context, tmp_path, fault):
    from smart_reporting.management.models import ManagementError

    service, token, scope, *_ = document_context
    receipt = await register(document_context)
    path = next(service.originals.root.rglob("*.bin"))
    path.unlink()
    if fault == "tampered":
        path.write_bytes(b"different identity")
    elif fault == "symlink":
        foreign = tmp_path / "foreign.txt"
        foreign.write_bytes(b"secret content")
        path.symlink_to(foreign)
    with pytest.raises(ManagementError) as unavailable:
        await service.read_original(token, scope, receipt.document_id, 1)
    assert unavailable.value.status == 409
    assert unavailable.value.code == "management_document_original_unavailable"


async def test_revocation_during_original_read_prevents_delivery(document_context, monkeypatch):
    from smart_reporting.management.models import ManagementError

    service, token, scope, *_ = document_context
    receipt = await register(document_context)
    read = service.originals.read

    async def revoke_after_read(*args, **kwargs):
        content = await read(*args, **kwargs)
        await service.review_revision(token, scope, receipt.document_id, 1,
            decision="revoked", reason="读取期间撤销", expected_version=1)
        return content

    monkeypatch.setattr(service.originals, "read", revoke_after_read)
    with pytest.raises(ManagementError) as revoked:
        await service.read_original(token, scope, receipt.document_id, 1)
    assert revoked.value.status == 403


async def test_revocation_during_parse_drops_text_and_result(document_context, monkeypatch):
    service, token, scope, *_ = document_context
    receipt = await register(document_context)
    lease = await service.claim_next()
    read = service.originals.read

    async def revoke_after_read(*args, **kwargs):
        content = await read(*args, **kwargs)
        state = (await service.get_document(token, scope, receipt.document_id))["revisions"][0]
        await service.review_revision(token, scope, receipt.document_id, 1,
            decision="revoked", reason="解析期间撤销", expected_version=state["stateVersion"])
        return content

    monkeypatch.setattr(service.originals, "read", revoke_after_read)
    result = await service.ingest_revision(lease)
    assert result.status == "failed"
    assert result.issue_codes == ("document_revoked",)
    state = (await service.get_document(token, scope, receipt.document_id))["revisions"][0]
    assert state["parseReceipt"] is None
