"""证据发布与管理预览；管理事务只登记身份，不等待embedding。"""

from uuid import NAMESPACE_URL, uuid5

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import and_, case, func, insert, or_, select, update

from ..reporting.business_knowledge.index import (
    EvidenceIndexConflict,
    EvidenceIndexUnavailable,
    IndexDocument,
)
from ..reporting.business_knowledge.models import BusinessDocumentInput, ParsedDocument
from ..reporting.business_knowledge.retrieval import (
    DocumentRevisionRef,
    EvidenceHit,
    EvidenceQuery,
    EvidenceRelease,
    EvidenceSearchReceipt,
    ReleasedDocument,
    ReportEvidenceSearchReceipt,
    is_applicable,
)
from ..reporting.semantics.models import Identity
from .business_documents import BusinessDocumentService, _digest
from .models import ManagementError
from .repository import business_document_revisions as revisions
from .repository import business_evidence_release_documents as members
from .repository import business_evidence_releases as releases
from .repository import business_ingestion_jobs as jobs
from .repository import business_revision_states as states


class BusinessEvidenceService:
    def __init__(self, documents: BusinessDocumentService, index):
        self.documents, self.index = documents, index
        self.scopes, self.repository, self.clock = documents.scopes, documents.repository, documents.clock

    async def _rows(self, connection, scope_id, references):
        result = []
        for ref in references:
            row = (await connection.execute(select(revisions, states.c.version.label("state_version"),
                states.c.review_status, states.c.ingestion_status,
                case((states.c.review_status != "revoked", states.c.parse_receipt), else_=None).label("parse_receipt")).join(states, and_(
                    states.c.scope_id == revisions.c.scope_id, states.c.document_id == revisions.c.document_id,
                    states.c.revision == revisions.c.revision,
                )).where(revisions.c.scope_id == scope_id, revisions.c.document_id == ref.document_id,
                    revisions.c.revision == ref.revision))).mappings().one_or_none()
            if row is None:
                raise ManagementError("management_document_not_found", "该组织不存在所选文档修订。", 404)
            result.append(row)
        return result

    async def _existing(self, connection, scope_id, release_id, input_hash=None):
        row = (await connection.execute(select(releases).where(
            releases.c.scope_id == scope_id, releases.c.release_id == release_id,
        ))).mappings().one_or_none()
        if row is None:
            return None
        release = EvidenceRelease.model_validate(row["document"])
        if _digest(row["document"]) != row["content_hash"] or release.scope_id != scope_id or release.release_id != release_id:
            raise ManagementError("management_evidence_identity_invalid", "证据集合身份校验失败。", 409)
        if input_hash is not None and release.input_hash != input_hash:
            raise ManagementError("management_request_conflict", "请求标识已用于其他文档集合，请先读回核对。", 409)
        return release

    async def get(self, token, scope, release_id) -> EvidenceRelease:
        async with self.repository.transaction() as connection:
            scope_id = (await self.documents._scope_row(connection, token, scope))["id"]
            release = await self._existing(connection, scope_id, release_id)
            if release is None:
                raise ManagementError("management_evidence_not_found", "该组织不存在此已发布证据集合。", 404)
            return release

    async def get_by_request(self, token, scope, request_id) -> EvidenceRelease:
        TypeAdapter(Identity).validate_python(request_id)
        async with self.repository.transaction() as connection:
            scope_id = (await self.documents._scope_row(connection, token, scope))["id"]
        return await self.get(token, scope, str(uuid5(NAMESPACE_URL, f"business-evidence:{scope_id}:{request_id}")))

    async def list_releases(self, token, scope, *, kind=None, query='', limit=50, after=None):
        if (kind not in (None, 'rule_evidence', 'background') or type(limit) is not int or not 1 <= limit <= 100
            or not isinstance(query, str) or len(query) > 200
            or (after is not None and (not isinstance(after, str) or len(after) > 128))):
            raise ManagementError('management_evidence_invalid', '集合目录筛选或分页参数无效。', 422)
        async with self.repository.transaction() as connection:
            scope_id = (await self.documents._scope_row(connection, token, scope))['id']
            listing = select(releases).where(releases.c.scope_id == scope_id)
            if kind is not None:
                listing = listing.where(releases.c.kind == kind)
            if after is not None:
                listing = listing.where(releases.c.release_id > after)
            if query:
                matching_document = select(members.c.release_id).join(revisions, and_(
                    revisions.c.scope_id == members.c.scope_id, revisions.c.document_id == members.c.document_id,
                    revisions.c.revision == members.c.revision,
                )).where(members.c.scope_id == scope_id, members.c.release_id == releases.c.release_id, or_(
                    func.lower(revisions.c.document['metadata']['title'].as_string()).contains(query.lower(), autoescape=True),
                    func.lower(members.c.document_id).contains(query.lower(), autoescape=True),
                )).exists()
                listing = listing.where(or_(
                    func.lower(releases.c.release_id).contains(query.lower(), autoescape=True), matching_document,
                ))
            rows = (await connection.execute(listing.order_by(releases.c.release_id).limit(limit + 1))).mappings().all()
            page = rows[:limit]
            release_ids = [row['release_id'] for row in page]
            current = (await connection.execute(select(members.c.release_id, members.c.document_id, members.c.revision,
                states.c.review_status, states.c.ingestion_status).outerjoin(states, and_(
                    states.c.scope_id == members.c.scope_id, states.c.document_id == members.c.document_id,
                    states.c.revision == members.c.revision,
                )).where(members.c.scope_id == scope_id, members.c.release_id.in_(release_ids)))).mappings().all() if page else []
            statuses = {(r['release_id'], r['document_id'], r['revision']): r for r in current}
            items = []
            for row in page:
                release = EvidenceRelease.model_validate(row['document'])
                if (_digest(row['document']) != row['content_hash'] or release.scope_id != scope_id
                    or release.release_id != row['release_id'] or release.kind != row['kind']):
                    raise ManagementError('management_evidence_identity_invalid', '证据集合身份校验失败。', 409)
                documents = []
                for document in release.documents:
                    state = statuses.get((release.release_id, document.reference.document_id, document.reference.revision))
                    documents.append({'documentId': document.reference.document_id, 'revision': document.reference.revision,
                        'title': document.metadata.title, 'reviewStatus': state['review_status'] if state else 'unavailable',
                        'ingestionStatus': state['ingestion_status'] if state else 'unavailable'})
                items.append({'releaseId': release.release_id, 'kind': release.kind,
                    'publishedAt': release.published_at.isoformat(), 'documents': documents,
                    'availableForSelection': all(d['reviewStatus'] == 'approved' and d['ingestionStatus'] == 'ready' for d in documents)})
            return {'items': items, 'nextCursor': page[-1]['release_id'] if len(rows) > limit else None}

    @staticmethod
    def _require_publishable(rows, kind):
        for row in rows:
            if row["review_status"] != "approved" or row["ingestion_status"] not in ("parsed", "ready") or not row["parse_receipt"]:
                raise ManagementError("management_evidence_not_ready", "所选文档须完整解析并经审核。", 409)
            if row["document"]["metadata"]["kind"] != kind:
                raise ManagementError("management_evidence_kind_mismatch", "制度依据和背景材料须分别发布。", 422)

    async def publish(self, token, scope, *, request_id, kind, revision_ids) -> EvidenceRelease:
        try:
            TypeAdapter(Identity).validate_python(request_id)
            references = tuple(sorted((DocumentRevisionRef.model_validate(ref) for ref in revision_ids),
                key=lambda ref: (ref.document_id, ref.revision)))
            if kind not in ("rule_evidence", "background") or not 1 <= len(references) <= 200 or len(set(references)) != len(references):
                raise ValueError("invalid_release")
        except (ValueError, ValidationError):
            raise ManagementError("management_evidence_invalid", "证据集合参数无效。", 422) from None
        actor = await self.scopes.actor(token, scope)
        input_hash = _digest({"kind": kind, "references": [ref.model_dump(mode="json") for ref in references]})
        async with self.scopes.write_transaction(actor) as connection:
            scope_id = (await self.scopes.require_registered(connection, scope))["id"]
            release_id = str(uuid5(NAMESPACE_URL, f"business-evidence:{scope_id}:{request_id}"))
            existing = await self._existing(connection, scope_id, release_id, input_hash)
            if existing is not None:
                return existing
            rows = await self._rows(connection, scope_id, references)
            self._require_publishable(rows, kind)
        if self.index is None:
            raise ManagementError("management_evidence_index_unavailable", "索引服务尚未配置，本次未发布。", 503)
        indexed = []
        for row in rows:
            await self.documents.read_original(token, scope, row["document_id"], row["revision"])
            parsed = ParsedDocument.model_validate(row["parse_receipt"])
            if parsed.original_hash != row["original_hash"]:
                raise ManagementError("management_evidence_identity_invalid", "原件与解析身份不一致。", 409)
            indexed.append(IndexDocument(document_id=row["document_id"], revision=row["revision"], parsed=parsed))
        try:
            if self.index is None:
                raise EvidenceIndexUnavailable("index_not_configured")
            index_receipt = await self.index.build(scope_id, release_id, tuple(indexed))
        except EvidenceIndexConflict:
            raise ManagementError("management_evidence_build_conflict", "该构建身份已有其他内容，请读回核对。", 409) from None
        except EvidenceIndexUnavailable:
            raise ManagementError("management_evidence_index_unavailable", "索引未完整就绪，本次未发布，请核对后显式重试。", 503) from None
        async with self.scopes.write_transaction(actor) as connection:
            existing = await self._existing(connection, scope_id, release_id, input_hash)
            if existing is not None:
                return existing
            current = await self._rows(connection, scope_id, references)
            self._require_publishable(current, kind)
            if [row["state_version"] for row in current] != [row["state_version"] for row in rows]:
                raise ManagementError("management_version_conflict", "索引期间文档状态已变化，请核对后发布。", 409)
            release = EvidenceRelease(release_id=release_id, scope_id=scope_id, request_id=request_id,
                input_hash=input_hash, kind=kind, index_receipt=index_receipt, published_at=self.clock(),
                documents=tuple(ReleasedDocument(reference=ref, metadata=BusinessDocumentInput.model_validate(row["document"]["metadata"]),
                    recorded_at=row["registered_at"]) for ref, row in zip(references, rows, strict=True)))
            body = release.model_dump(mode="json", by_alias=True)
            await connection.execute(insert(releases).values(scope_id=scope_id, release_id=release_id, kind=kind,
                document=body, content_hash=_digest(body), published_at=release.published_at))
            for ref in references:
                await connection.execute(insert(members).values(scope_id=scope_id, release_id=release_id,
                    document_id=ref.document_id, revision=ref.revision))
                await connection.execute(update(states).where(states.c.scope_id == scope_id, states.c.document_id == ref.document_id,
                    states.c.revision == ref.revision).values(ingestion_status="ready", version=states.c.version + 1))
                await connection.execute(update(jobs).where(jobs.c.scope_id == scope_id, jobs.c.document_id == ref.document_id,
                    jobs.c.revision == ref.revision).values(status="ready", updated_at=self.clock()))
            await self.scopes.audit(connection, actor, "business_evidence_published", {"releaseId": release_id, "count": len(references)})
            return release

    async def _authorized_rows(self, token, scope, release):
        async with self.repository.transaction() as connection:
            scope_id = (await self.documents._scope_row(connection, token, scope))["id"]
            if scope_id != release.scope_id:
                raise ManagementError("management_evidence_not_found", "该组织不存在此证据集合。", 404)
            return await self._rows(connection, scope_id, tuple(doc.reference for doc in release.documents))

    async def search_preview(self, token, scope, release_id, **payload) -> EvidenceSearchReceipt:
        request = EvidenceQuery.model_validate(payload)
        release = await self.get(token, scope, release_id)
        async def authorized_rows():
            return await self._authorized_rows(token, scope, release)

        async def revalidate(saved):
            return await self.revalidate_receipt(token, scope, saved)

        return await self._search_release(release, request, authorized_rows, revalidate)

    async def _search_release(self, release, request, authorized_rows, revalidate):
        rows = await authorized_rows()
        eligible = {f"{doc.reference.document_id}:{doc.reference.revision}": doc for doc in release.documents
                    if is_applicable(doc, release.scope_id, request)}
        revoked = {f"{row['document_id']}:{row['revision']}" for row in rows if row["review_status"] == "revoked"}
        allowed = set(eligible) - revoked
        def receipt(status, hits=(), issues=()):
            return EvidenceSearchReceipt(release_id=release.release_id, request=request, status=status, hits=hits, issue_codes=issues)
        if not allowed:
            return receipt("revoked", issues=("evidence_revoked",)) if set(eligible) & revoked else receipt("inapplicable", issues=("evidence_inapplicable",))
        try:
            if self.index is None:
                raise EvidenceIndexUnavailable("index_not_configured")
            found = await self.index.search(release.index_receipt, request.query, document_keys=tuple(allowed), limit=request.limit)
        except EvidenceIndexUnavailable:
            return receipt("unavailable", issues=("knowledge_unavailable",))
        hits = []
        for hit in found:
            document = eligible.get(f"{hit.document_id}:{hit.revision}")
            if document is None:
                return receipt("unavailable", issues=("evidence_identity_invalid",))
            hits.append(EvidenceHit(**hit.model_dump(), title=document.metadata.title, role=release.kind,
                valid_from=document.metadata.valid_from, valid_to=document.metadata.valid_to,
                recorded_at=document.recorded_at, event_time=document.metadata.event_time, applies_to=document.metadata.applies_to))
        return await revalidate(receipt("matched" if hits else "no_match", tuple(hits), ("evidence_revoked",) if revoked else ()))

    async def revalidate_receipt(self, token, scope, saved: EvidenceSearchReceipt) -> EvidenceSearchReceipt:
        """缓存/恢复同样重新核验当前会话、撤销、适用性和原文，不能直接重放片段。"""
        saved = EvidenceSearchReceipt.model_validate(saved.model_dump())
        release = await self.get(token, scope, saved.release_id)
        async def authorized_rows():
            return await self._authorized_rows(token, scope, release)

        async def read_original(hit, _row):
            await self.documents.read_original(token, scope, hit.document_id, hit.revision)

        return await self._revalidate_release(release, saved, authorized_rows, read_original)

    async def _revalidate_release(self, release, saved, authorized_rows, read_original):
        current = await authorized_rows()
        active = {(row["document_id"], row["revision"]): row for row in current if row["review_status"] != "revoked"}
        members_by_ref = {(doc.reference.document_id, doc.reference.revision): doc for doc in release.documents}
        def rejected(status, code):
            return saved.model_copy(update={"status": status, "hits": (), "issue_codes": (code,)})
        for hit in saved.hits:
            document = members_by_ref.get((hit.document_id, hit.revision))
            if document is None:
                return rejected("unavailable", "evidence_identity_invalid")
            row = active.get((hit.document_id, hit.revision))
            if row is None:
                return rejected("revoked", "evidence_revoked")
            if not is_applicable(document, release.scope_id, saved.request):
                return rejected("inapplicable", "evidence_inapplicable")
            if (hit.title, hit.role, hit.valid_from, hit.valid_to, hit.recorded_at, hit.event_time, hit.applies_to) != (
                document.metadata.title, release.kind, document.metadata.valid_from, document.metadata.valid_to,
                document.recorded_at, document.metadata.event_time, document.metadata.applies_to):
                return rejected("unavailable", "evidence_identity_invalid")
            parsed = ParsedDocument.model_validate(row["parse_receipt"])
            if hit.source_hash != row["original_hash"] or not any(fragment.locator == hit.locator and hit.quote in fragment.text for fragment in parsed.fragments):
                return rejected("unavailable", "evidence_identity_invalid")
            try:
                await read_original(hit, row)
            except ManagementError as error:
                if error.code == "management_document_revoked":
                    return rejected("revoked", "evidence_revoked")
                if error.code == "management_document_original_unavailable":
                    return rejected("unavailable", "evidence_original_unavailable")
                raise
        final = await authorized_rows()
        revoked = {(row["document_id"], row["revision"]) for row in final if row["review_status"] == "revoked"}
        if any((hit.document_id, hit.revision) in revoked for hit in saved.hits):
            return rejected("revoked", "evidence_revoked")
        return saved

    async def _report_access(self, bases, *, run_id, scope, user_id, thread_id, kind):
        """仅供报告服务端调用；集合及时间从PG登记依据解析，调用方不能另传。"""
        if kind not in {'rule_evidence', 'background'}:
            raise ManagementError('report_evidence_kind_invalid', '知识用途无效。', 422)
        basis = await bases.load_report_basis(run_id, scope, user_id=user_id, thread_id=thread_id)
        release_id = basis.evidence_release_id if kind == 'rule_evidence' else basis.background_release_id
        if release_id is None:
            return basis, None, None
        async with self.repository.transaction() as connection:
            release = await bases._release(connection, basis.scope_id, release_id, kind)

        async def authorized_rows():
            async with self.repository.transaction() as connection:
                registered, identity = await bases._identity(connection, run_id, scope, user_id, thread_id)
                row = await bases._basis_row(connection, registered['id'], run_id)
                restored = await bases._restore(connection, identity, row)
                if restored != basis:
                    raise ManagementError('management_basis_identity_invalid', '报告计算依据已变化。', 409)
                return await self._rows(connection, basis.scope_id, tuple(doc.reference for doc in release.documents))

        return basis, release, authorized_rows

    @staticmethod
    def _report_query(basis, query):
        return EvidenceQuery(query=query, metric_ids=tuple(dict.fromkeys(ref.metric_id for ref in basis.metric_versions)),
            period=basis.request_summary.period, knowledge_as_of=basis.knowledge_as_of)

    async def _read_report_original(self, scope_id, _hit, row):
        try:
            await self.documents.originals.read(scope_id, row['original_resource_id'],
                expected_hash=row['original_hash'], expected_size=row['size_bytes'])
        except (OSError, ValueError) as error:
            raise ManagementError('management_document_original_unavailable', '原件缺失或身份已变化，暂时无法读取。', 409) from error

    async def search_report(self, bases, *, run_id, scope, user_id, thread_id, kind, query) -> ReportEvidenceSearchReceipt:
        basis, release, authorized_rows = await self._report_access(bases,
            run_id=run_id, scope=scope, user_id=user_id, thread_id=thread_id, kind=kind)
        if release is None:
            return ReportEvidenceSearchReceipt(basis_id=basis.id, kind=kind, issue_codes=('background_release_unavailable',))
        request = self._report_query(basis, query)

        async def revalidate(saved):
            async def read_original(hit, row):
                await self._read_report_original(basis.scope_id, hit, row)
            return await self._revalidate_release(release, saved, authorized_rows, read_original)

        result = await self._search_release(release, request, authorized_rows, revalidate)
        return ReportEvidenceSearchReceipt(basis_id=basis.id, kind=kind, search=result)

    async def revalidate_report(self, bases, *, run_id, scope, user_id, thread_id,
        saved: ReportEvidenceSearchReceipt) -> ReportEvidenceSearchReceipt:
        saved = ReportEvidenceSearchReceipt.model_validate(saved.model_dump())
        basis, release, authorized_rows = await self._report_access(bases,
            run_id=run_id, scope=scope, user_id=user_id, thread_id=thread_id, kind=saved.kind)
        if saved.basis_id == basis.id and release is None and saved.kind == 'background' and saved.search is None:
            return ReportEvidenceSearchReceipt(basis_id=basis.id, kind=saved.kind, issue_codes=('background_release_unavailable',))
        if (saved.basis_id != basis.id or release is None or saved.search is None
            or saved.search.release_id != release.release_id
            or saved.search.request != self._report_query(basis, saved.search.request.query)):
            return ReportEvidenceSearchReceipt(basis_id=basis.id, kind=saved.kind, issue_codes=('report_evidence_identity_invalid',))

        async def read_original(hit, row):
            await self._read_report_original(basis.scope_id, hit, row)

        result = await self._revalidate_release(release, saved.search, authorized_rows, read_original)
        return ReportEvidenceSearchReceipt(basis_id=basis.id, kind=saved.kind, search=result)
