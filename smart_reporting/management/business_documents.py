"""组织原件登记、审核与持久解析任务；不在事务内解析文件或等待模型。"""

import asyncio
import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from loguru import logger
from pydantic import TypeAdapter
from sqlalchemy import and_, func, insert, or_, select, update

from ..async_utils import complete_cleanup
from ..reporting.business_knowledge.ingestion import inspect_upload, parse_document
from ..reporting.business_knowledge.models import (
    BusinessDocumentInput,
    DocumentReceipt,
    IngestionLease,
    IngestionReceipt,
)
from ..reporting.business_knowledge.originals import BusinessOriginalStore
from ..reporting.semantics.models import Identity
from .models import ManagementError, ManagementScope
from .repository import (
    business_document_revisions as revisions,
)
from .repository import (
    business_documents as documents,
)
from .repository import (
    business_ingestion_jobs as jobs,
)
from .repository import (
    business_revision_states as states,
)
from .scopes import ScopeService

LEASE_SECONDS = 120


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class BusinessDocumentService:
    def __init__(self, scopes: ScopeService, originals: BusinessOriginalStore):
        self.scopes, self.repository, self.originals = scopes, scopes.repository, originals
        self.clock = scopes.auth.clock

    @staticmethod
    def _document_receipt(row) -> DocumentReceipt:
        return DocumentReceipt(
            document_id=row["document_id"], revision=row["revision"], version=row["revision"],
            job_id=row["job_id"], status=row["status"], issue_codes=tuple(row["issues"]),
        )

    @staticmethod
    def _job_receipt(row) -> IngestionReceipt:
        return IngestionReceipt(
            job_id=row["job_id"], document_id=row["document_id"], revision=row["revision"],
            attempt=row["attempts"], status=row["status"], issue_codes=tuple(row["issues"]),
        )

    @staticmethod
    def _check_existing(row, input_hash: str):
        if row is not None and row["input_hash"] != input_hash:
            raise ManagementError("management_request_conflict", "该请求标识已用于不同内容，请先核对保存结果。", 409)
        return row

    async def register_document(
        self, token: str, scope: ManagementScope, upload: bytes, *, filename: str,
        metadata: BusinessDocumentInput, request_id: str, expected_version: int,
    ) -> DocumentReceipt:
        actor = await self.scopes.actor(token, scope)
        try:
            TypeAdapter(Identity).validate_python(request_id)
            if type(expected_version) is not int or expected_version < 0:
                raise ValueError("invalid_version")
            media_type = inspect_upload(upload, filename=filename)
        except ValueError as error:
            raise ManagementError("management_document_invalid", "文件名、类型、大小或登记参数无效。", 422) from error
        original_hash = hashlib.sha256(upload).hexdigest()
        body = {"metadata": metadata.model_dump(mode="json", by_alias=True), "filename": filename}
        input_hash = _digest({**body, "originalHash": original_hash, "expectedVersion": expected_version})
        async with self.scopes.write_transaction(actor) as connection:
            scope_id = (await self.scopes.require_registered(connection, scope))["id"]
            existing = self._check_existing((await connection.execute(select(jobs).where(
                jobs.c.scope_id == scope_id, jobs.c.request_id == request_id,
            ))).mappings().one_or_none(), input_hash)
            if existing:
                return self._document_receipt(existing)
        resource_id, job_id = str(uuid4()), str(uuid4())
        committed = False
        try:
            await self.originals.put(scope_id, resource_id, upload)
            async with self.scopes.write_transaction(actor) as connection:
                existing = self._check_existing((await connection.execute(select(jobs).where(
                    jobs.c.scope_id == scope_id, jobs.c.request_id == request_id,
                ))).mappings().one_or_none(), input_hash)
                if existing:
                    return self._document_receipt(existing)
                current = (await connection.execute(select(documents).where(
                    documents.c.scope_id == scope_id, documents.c.document_id == metadata.id,
                ))).mappings().one_or_none()
                if (current["version"] if current else 0) != expected_version:
                    raise ManagementError("management_version_conflict", "文档已有新修订，请核对后重新登记。", 409)
                revision = expected_version + 1
                if current:
                    await connection.execute(update(documents).where(
                        documents.c.scope_id == scope_id, documents.c.document_id == metadata.id,
                        documents.c.version == expected_version,
                    ).values(version=revision, title=metadata.title))
                else:
                    await connection.execute(insert(documents).values(
                        scope_id=scope_id, document_id=metadata.id, version=revision,
                        title=metadata.title, created_at=self.clock(),
                    ))
                recorded = {**body, "recordedAt": self.clock().isoformat()}
                await connection.execute(insert(revisions).values(
                    scope_id=scope_id, document_id=metadata.id, revision=revision,
                    original_resource_id=resource_id, original_hash=original_hash,
                    media_type=media_type, size_bytes=len(upload), document=recorded,
                    content_hash=_digest(recorded), registered_at=self.clock(),
                ))
                await connection.execute(insert(states).values(
                    scope_id=scope_id, document_id=metadata.id, revision=revision,
                    version=1, ingestion_status="queued", review_status="pending",
                ))
                row = (await connection.execute(insert(jobs).values(
                    scope_id=scope_id, job_id=job_id, document_id=metadata.id, revision=revision,
                    request_id=request_id, input_hash=input_hash, status="queued", attempts=0,
                    issues=[], updated_at=self.clock(),
                ).returning(jobs))).mappings().one()
                await self.scopes.audit(connection, actor, "business_document_registered", {
                    "documentId": metadata.id, "revision": revision, "jobId": job_id,
                    "originalHash": original_hash,
                })
                receipt = self._document_receipt(row)
            committed = True
            return receipt
        finally:
            if not committed:
                await complete_cleanup(self._discard_unregistered_original(scope_id, resource_id))

    async def _discard_unregistered_original(self, scope_id: str, resource_id: str) -> None:
        # 提交响应丢失不代表事务回滚；先查实际引用，再决定是否清理本次暂存原件。
        try:
            async with self.repository.transaction() as connection:
                registered = await connection.scalar(select(revisions.c.document_id).where(
                    revisions.c.scope_id == scope_id, revisions.c.original_resource_id == resource_id,
                ))
        except ManagementError:
            logger.warning("business_document_cleanup_deferred resource_id={}", resource_id)
            return
        if registered is None:
            await self.originals.discard(scope_id, resource_id)

    async def _scope_row(self, connection, token, scope):
        await self.repository.authenticate_in_transaction(connection, token, self.clock())
        return await self.scopes.require_registered(connection, scope)

    async def list_documents(self, token, scope, *, query='', kind=None, review_status=None, limit=50, after=None):
        if (not isinstance(query, str) or len(query) > 200 or kind not in (None, 'rule_evidence', 'background')
            or review_status not in (None, 'pending', 'approved', 'rejected', 'revoked')
            or type(limit) is not int or not 1 <= limit <= 100
            or (after is not None and (not isinstance(after, str) or len(after) > 128))):
            raise ManagementError('management_document_invalid', '原件目录筛选或分页参数无效。', 422)
        async with self.repository.transaction() as connection:
            scope_id = (await self._scope_row(connection, token, scope))['id']
            kind_column = revisions.c.document['metadata']['kind'].as_string()
            listing = select(documents.c.document_id, documents.c.title, documents.c.version,
                revisions.c.revision, revisions.c.registered_at, kind_column.label('kind'),
                states.c.review_status, states.c.ingestion_status).join(revisions, and_(
                    revisions.c.scope_id == documents.c.scope_id, revisions.c.document_id == documents.c.document_id,
                    revisions.c.revision == documents.c.version,
                )).join(states, and_(states.c.scope_id == revisions.c.scope_id,
                    states.c.document_id == revisions.c.document_id, states.c.revision == revisions.c.revision,
                )).where(documents.c.scope_id == scope_id)
            if query:
                listing = listing.where(or_(func.lower(documents.c.title).contains(query.lower(), autoescape=True),
                    func.lower(documents.c.document_id).contains(query.lower(), autoescape=True)))
            if kind is not None:
                listing = listing.where(kind_column == kind)
            if review_status is not None:
                listing = listing.where(states.c.review_status == review_status)
            if after is not None:
                listing = listing.where(documents.c.document_id > after)
            rows = (await connection.execute(listing.order_by(documents.c.document_id).limit(limit + 1))).mappings().all()
            page = rows[:limit]
            return {'items': [{'documentId': r['document_id'], 'title': r['title'], 'version': r['version'],
                'revision': r['revision'], 'kind': r['kind'], 'recordedAt': r['registered_at'].isoformat(),
                'reviewStatus': r['review_status'], 'ingestionStatus': r['ingestion_status']} for r in page],
                'nextCursor': page[-1]['document_id'] if len(rows) > limit else None}

    async def get_document(self, token: str, scope: ManagementScope, document_id: str) -> dict:
        async with self.repository.transaction() as connection:
            scope_id = (await self._scope_row(connection, token, scope))["id"]
            document = (await connection.execute(select(documents).where(
                documents.c.scope_id == scope_id, documents.c.document_id == document_id,
            ))).mappings().one_or_none()
            if document is None:
                raise ManagementError("management_document_not_found", "该组织未登记此文档。", 404)
            rows = (await connection.execute(select(revisions, states.c.version.label("state_version"),
                states.c.ingestion_status, states.c.review_status, states.c.parse_receipt, states.c.review_receipt,
            ).join(states, and_(
                states.c.scope_id == revisions.c.scope_id, states.c.document_id == revisions.c.document_id,
                states.c.revision == revisions.c.revision,
            )).where(revisions.c.scope_id == scope_id, revisions.c.document_id == document_id)
                .order_by(revisions.c.revision.desc()))).mappings().all()
            return {
                "documentId": document_id, "title": document["title"], "version": document["version"],
                "revisions": [{
                    "revision": row["revision"], "metadata": row["document"]["metadata"],
                    "originalHash": row["original_hash"], "mediaType": row["media_type"],
                    "sizeBytes": row["size_bytes"], "recordedAt": row["registered_at"].isoformat(),
                    "stateVersion": row["state_version"], "ingestionStatus": row["ingestion_status"],
                    "reviewStatus": row["review_status"],
                    "parseReceipt": row["parse_receipt"] if row["review_status"] != "revoked" else None,
                    "reviewReceipt": row["review_receipt"],
                } for row in rows],
            }

    async def get_registration(self, token: str, scope: ManagementScope, request_id: str) -> dict:
        try:
            TypeAdapter(Identity).validate_python(request_id)
        except ValueError:
            raise ManagementError('management_document_invalid', '原件登记请求标识无效。', 422) from None
        async with self.repository.transaction() as connection:
            scope_id = (await self._scope_row(connection, token, scope))['id']
            row = (await connection.execute(select(jobs, revisions.c.document, revisions.c.content_hash,
                revisions.c.original_hash).join(revisions, and_(
                    revisions.c.scope_id == jobs.c.scope_id, revisions.c.document_id == jobs.c.document_id,
                    revisions.c.revision == jobs.c.revision,
                )).where(jobs.c.scope_id == scope_id, jobs.c.request_id == request_id))).mappings().one_or_none()
            if row is None:
                raise ManagementError('management_registration_not_found', '该组织尚未登记此上传请求。', 404)
            recorded = row['document']
            metadata = BusinessDocumentInput.model_validate(recorded['metadata'])
            expected_version = row['revision'] - 1
            identity = {'metadata': metadata.model_dump(mode='json', by_alias=True), 'filename': recorded['filename'],
                'originalHash': row['original_hash'], 'expectedVersion': expected_version}
            if (_digest(recorded) != row['content_hash'] or _digest(identity) != row['input_hash']
                or metadata.id != row['document_id']):
                raise ManagementError('management_registration_identity_invalid', '原件登记身份校验失败，请保留原请求核对。', 409)
            return {'requestId': request_id, 'receipt': self._document_receipt(row).model_dump(mode='json', by_alias=True),
                'expectedVersion': expected_version, 'filename': recorded['filename'],
                'metadata': identity['metadata'], 'originalHash': row['original_hash']}

    async def read_revision_impact(self, token, scope, document_id, revision, *, limit=50, after=None):
        from .business_document_impact import read_document_impact

        return await read_document_impact(self, token, scope, document_id, revision, limit=limit, after=after)

    async def list_revision_jobs(self, token, scope, document_id, revision, *, limit=50, after=None):
        if type(revision) is not int or revision < 1 or type(limit) is not int or not 1 <= limit <= 100 or (after is not None and (not isinstance(after, str) or len(after) > 128)):
            raise ManagementError("management_document_invalid", "修订任务查询参数无效。", 422)
        async with self.repository.transaction() as connection:
            scope_id = (await self._scope_row(connection, token, scope))["id"]
            exists = await connection.scalar(select(revisions.c.revision).where(
                revisions.c.scope_id == scope_id, revisions.c.document_id == document_id, revisions.c.revision == revision))
            if exists is None:
                raise ManagementError("management_document_not_found", "该组织不存在此原件修订。", 404)
            query = select(jobs).where(jobs.c.scope_id == scope_id, jobs.c.document_id == document_id, jobs.c.revision == revision)
            if after is not None:
                query = query.where(jobs.c.job_id > after)
            rows = (await connection.execute(query.order_by(jobs.c.job_id).limit(limit + 1))).mappings().all()
            return {"items": [self._job_receipt(row).model_dump(mode="json", by_alias=True) for row in rows[:limit]],
                "nextCursor": rows[limit - 1]["job_id"] if len(rows) > limit else None}

    async def get_job(self, token: str, scope: ManagementScope, job_id: str) -> IngestionReceipt:
        async with self.repository.transaction() as connection:
            scope_id = (await self._scope_row(connection, token, scope))["id"]
            row = (await connection.execute(select(jobs).where(jobs.c.scope_id == scope_id, jobs.c.job_id == job_id))).mappings().one_or_none()
            if row is None:
                raise ManagementError("management_ingestion_job_not_found", "该组织不存在此入库任务。", 404)
            return self._job_receipt(row)

    async def read_original(self, token: str, scope: ManagementScope, document_id: str, revision: int) -> bytes:
        async with self.repository.transaction() as connection:
            scope_id = (await self._scope_row(connection, token, scope))["id"]
            row = (await connection.execute(select(revisions, states.c.review_status).join(states, and_(
                states.c.scope_id == revisions.c.scope_id, states.c.document_id == revisions.c.document_id,
                states.c.revision == revisions.c.revision,
            )).where(revisions.c.scope_id == scope_id, revisions.c.document_id == document_id, revisions.c.revision == revision))).mappings().one_or_none()
            if row is None:
                raise ManagementError("management_document_not_found", "该组织不存在此原件修订。", 404)
            if row["review_status"] == "revoked":
                raise ManagementError("management_document_revoked", "此原件访问已撤销。", 403)
        try:
            content = await self.originals.read(scope_id, row["original_resource_id"], expected_hash=row["original_hash"], expected_size=row["size_bytes"])
        except (OSError, ValueError) as error:
            raise ManagementError("management_document_original_unavailable", "原件缺失或身份已变化，暂时无法读取。", 409) from error
        # 文件I/O期间会话或授权可能变化；交付字节前再核对当前状态。
        async with self.repository.transaction() as connection:
            await self._scope_row(connection, token, scope)
            status = await connection.scalar(select(states.c.review_status).where(
                states.c.scope_id == scope_id, states.c.document_id == document_id, states.c.revision == revision,
            ))
            if status == "revoked":
                raise ManagementError("management_document_revoked", "此原件访问已撤销。", 403)
        return content

    async def review_revision(
        self, token: str, scope: ManagementScope, document_id: str, revision: int,
        *, decision: str, reason: str, expected_version: int,
    ) -> dict:
        if decision not in ("approved", "rejected", "revoked") or not reason.strip() or len(reason) > 4000:
            raise ManagementError("management_review_invalid", "审核决定和理由无效。", 422)
        actor = await self.scopes.actor(token, scope)
        async with self.scopes.write_transaction(actor) as connection:
            scope_id = (await self.scopes.require_registered(connection, scope))["id"]
            row = (await connection.execute(select(states).where(
                states.c.scope_id == scope_id, states.c.document_id == document_id, states.c.revision == revision,
            ))).mappings().one_or_none()
            if row is None:
                raise ManagementError("management_document_not_found", "该组织不存在此修订。", 404)
            if row["version"] != expected_version:
                raise ManagementError("management_version_conflict", "文档状态已变化，请核对后审核。", 409)
            if decision == "approved" and (row["ingestion_status"] not in ("parsed", "ready") or not row["parse_receipt"]):
                raise ManagementError("management_document_not_parsed", "原件尚未完整解析，不能批准为业务依据。", 409)
            if row["review_status"] == "revoked" and decision != "revoked":
                raise ManagementError("management_document_revoked", "已撤销修订不得重新启用，请登记新修订。", 409)
            review = {"decision": decision, "reason": reason, "reviewedAt": self.clock().isoformat()}
            await connection.execute(update(states).where(
                states.c.scope_id == scope_id, states.c.document_id == document_id,
                states.c.revision == revision, states.c.version == expected_version,
            ).values(version=expected_version + 1, review_status=decision, review_receipt=review))
            await self.scopes.audit(connection, actor, "business_document_reviewed", {
                "documentId": document_id, "revision": revision, "decision": decision,
            })
            return {"stateVersion": expected_version + 1, "reviewStatus": decision, "ingestionStatus": row["ingestion_status"]}

    async def claim_next(self) -> IngestionLease | None:
        """内部worker使用；不是管理HTTP入口，不接受浏览器自报的租约owner。"""
        now = self.clock()
        async with self.repository.transaction() as connection:
            row = (await connection.execute(select(jobs).where(or_(
                jobs.c.status == "queued",
                and_(jobs.c.status == "running", jobs.c.lease_until <= now),
            )).order_by(jobs.c.updated_at, jobs.c.job_id).limit(1).with_for_update(skip_locked=True))).mappings().one_or_none()
            if row is None:
                return None
            owner, until = uuid4().hex, now + timedelta(seconds=LEASE_SECONDS)
            await connection.execute(update(jobs).where(jobs.c.scope_id == row["scope_id"], jobs.c.job_id == row["job_id"]).values(
                status="running", attempts=row["attempts"] + 1, lease_owner=owner, lease_until=until, updated_at=now,
            ))
            await connection.execute(update(states).where(
                states.c.scope_id == row["scope_id"], states.c.document_id == row["document_id"], states.c.revision == row["revision"],
            ).values(ingestion_status="running", version=states.c.version + 1))
            return IngestionLease(scope_id=row["scope_id"], job_id=row["job_id"], document_id=row["document_id"],
                revision=row["revision"], attempt=row["attempts"] + 1, lease_owner=owner, lease_until=until)

    async def _require_lease(self, connection, lease: IngestionLease):
        row = (await connection.execute(select(jobs).where(
            jobs.c.scope_id == lease.scope_id, jobs.c.job_id == lease.job_id,
            jobs.c.document_id == lease.document_id, jobs.c.revision == lease.revision,
            jobs.c.status == "running", jobs.c.attempts == lease.attempt,
            jobs.c.lease_owner == lease.lease_owner, jobs.c.lease_until > self.clock(),
        ))).mappings().one_or_none()
        if row is None:
            raise ManagementError("management_ingestion_lease_lost", "入库任务租约已变化，请读取当前任务结果。", 409)
        return row

    async def renew_lease(self, lease: IngestionLease) -> None:
        async with self.repository.transaction() as connection:
            await self._require_lease(connection, lease)
            await connection.execute(update(jobs).where(jobs.c.scope_id == lease.scope_id, jobs.c.job_id == lease.job_id).values(
                lease_until=self.clock() + timedelta(seconds=LEASE_SECONDS),
            ))

    async def ingest_revision(self, lease: IngestionLease) -> IngestionReceipt:
        async with self.repository.transaction() as connection:
            await self._require_lease(connection, lease)
            original = (await connection.execute(select(revisions, states.c.review_status).join(states, and_(
                states.c.scope_id == revisions.c.scope_id, states.c.document_id == revisions.c.document_id,
                states.c.revision == revisions.c.revision,
            )).where(revisions.c.scope_id == lease.scope_id, revisions.c.document_id == lease.document_id,
                revisions.c.revision == lease.revision))).mappings().one()
        parsed, issues, status = None, [], "failed"
        try:
            if original["review_status"] == "revoked":
                raise ValueError("revoked")
            content = await self.originals.read(lease.scope_id, original["original_resource_id"], expected_hash=original["original_hash"], expected_size=original["size_bytes"])
            parsed = await asyncio.to_thread(parse_document, content, filename=original["document"]["filename"])
            if parsed.original_hash != original["original_hash"]:
                raise ValueError("identity_changed")
            status, issues = parsed.status, list(parsed.issue_codes)
        except Exception as error:
            logger.warning("business_document_ingestion_failed job_id={} error_type={}", lease.job_id, type(error).__name__)
            issues = ["document_parse_failed"]
        async with self.repository.transaction() as connection:
            await self._require_lease(connection, lease)
            current_review = await connection.scalar(select(states.c.review_status).where(
                states.c.scope_id == lease.scope_id, states.c.document_id == lease.document_id, states.c.revision == lease.revision,
            ))
            if current_review == "revoked":
                parsed, status, issues = None, "failed", ["document_revoked"]
            row = (await connection.execute(update(jobs).where(
                jobs.c.scope_id == lease.scope_id, jobs.c.job_id == lease.job_id,
            ).values(status=status, issues=issues, lease_owner=None, lease_until=None, updated_at=self.clock()).returning(jobs))).mappings().one()
            await connection.execute(update(states).where(
                states.c.scope_id == lease.scope_id, states.c.document_id == lease.document_id, states.c.revision == lease.revision,
            ).values(ingestion_status=status, parse_receipt=parsed.model_dump(mode="json", by_alias=True) if parsed else None, version=states.c.version + 1))
            return self._job_receipt(row)

    async def retry_job(self, token: str, scope: ManagementScope, job_id: str, *, expected_attempt: int) -> IngestionReceipt:
        actor = await self.scopes.actor(token, scope)
        async with self.scopes.write_transaction(actor) as connection:
            scope_id = (await self.scopes.require_registered(connection, scope))["id"]
            row = (await connection.execute(select(jobs).where(jobs.c.scope_id == scope_id, jobs.c.job_id == job_id))).mappings().one_or_none()
            if row is None:
                raise ManagementError("management_ingestion_job_not_found", "该组织不存在此任务。", 404)
            if row["status"] != "failed" or row["attempts"] != expected_attempt:
                raise ManagementError("management_version_conflict", "任务已变化，请先核对状态。", 409)
            review_status = await connection.scalar(select(states.c.review_status).where(
                states.c.scope_id == scope_id, states.c.document_id == row["document_id"], states.c.revision == row["revision"],
            ))
            if review_status == "revoked":
                raise ManagementError("management_document_revoked", "原件访问已撤销，不能重试读取。", 403)
            updated = (await connection.execute(update(jobs).where(jobs.c.scope_id == scope_id, jobs.c.job_id == job_id)
                .values(status="queued", issues=[], updated_at=self.clock()).returning(jobs))).mappings().one()
            await connection.execute(update(states).where(
                states.c.scope_id == scope_id, states.c.document_id == row["document_id"], states.c.revision == row["revision"],
            ).values(ingestion_status="queued", version=states.c.version + 1))
            await self.scopes.audit(connection, actor, "business_document_retry_requested", {"jobId": job_id, "attempt": expected_attempt})
            return self._job_receipt(updated)
