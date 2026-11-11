"""报告修订反馈与管理裁定；采纳只登记候选改动，不发布规则或批准报告。"""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError, model_validator
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..reporting.semantics.models import (
    CorrectedVersionRef,
    Identity,
    ReportIssueReview,
    SemanticModel,
)
from ..reporting.trace.contracts_v1 import canonical_sha256
from .models import ManagementError
from .repository import audit_events, report_issue_reviews


class IssueSubmission(SemanticModel):
    issue_id: Identity
    object_refs: tuple[Identity, ...] = Field(min_length=1, max_length=50)
    category: Literal['calculation', 'policy', 'data', 'citation', 'interpretation']
    description: str = Field(min_length=1, max_length=10000)

    @model_validator(mode='after')
    def distinct_objects(self):
        if not self.description.strip() or len(set(self.object_refs)) != len(self.object_refs):
            raise ValueError('请提供具体问题及不重复的本报告对象')
        return self


class IssueFixProposal(SemanticModel):
    change_summary: str = Field(min_length=1, max_length=10000)
    counterexample: str = Field(min_length=1, max_length=10000)

    @model_validator(mode='after')
    def explained(self):
        if not self.change_summary.strip() or not self.counterexample.strip():
            raise ValueError('采纳须登记候选改动和具体反例')
        return self


class IssueDecision(SemanticModel):
    expected_version: int = Field(ge=1, strict=True)
    status: Literal['needs_evidence', 'accepted', 'rejected', 'resolved']
    decision_reason: str = Field(min_length=1, max_length=10000)
    proposal: IssueFixProposal | None = None
    corrected_versions: tuple[CorrectedVersionRef, ...] = Field(default=(), max_length=50)
    regression_case_ids: tuple[Identity, ...] = Field(default=(), max_length=50)
    new_report_revision: Identity | None = None
    not_recalculated_reason: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def explained(self):
        if not self.decision_reason.strip() or self.status == 'accepted' and self.proposal is None:
            raise ValueError('裁定须有具体理由，采纳须有候选改动与反例')
        if self.status not in ('accepted', 'resolved') and self.corrected_versions:
            raise ValueError('仅采纳的问题可关联正式修复版本')
        if self.status != 'resolved' and (self.regression_case_ids
                or self.new_report_revision or self.not_recalculated_reason):
            raise ValueError('未解决的候选不能登记为已经修复或重算')
        return self


class IssueRecord(SemanticModel):
    review: ReportIssueReview
    report_id: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1, strict=True)
    run_id: str = Field(min_length=1, max_length=256)
    submitted_by: str = Field(min_length=1, max_length=256)
    submitted_at: datetime
    proposal: IssueFixProposal | None = None
    resolution_request_id: Identity | None = None


def report_revision_identity(report_id, revision):
    return 'editor-revision-' + canonical_sha256({'reportId': report_id, 'revision': revision})


def _parse(model, value):
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise ManagementError('management_issue_invalid', '问题或裁定内容不符合报告反馈契约。', 422) from error


class ReportIssueReviewService:
    def __init__(self, bases):
        self.bases, self.scopes, self.repository = bases, bases.scopes, bases.repository

    async def _report_binding(self, connection, *, run_id, scope, user_id, thread_id, basis_id, report_id, revision):
        if type(revision) is not int or revision < 1 or not isinstance(report_id, str) or not 1 <= len(report_id) <= 256:
            raise ManagementError('management_issue_invalid', '报告修订身份无效。', 422)
        registered, identity = await self.bases._identity(connection, run_id, scope, user_id, thread_id)
        row = await self.bases._basis_row(connection, registered['id'], run_id)
        if row is None or row['basis_id'] != basis_id:
            raise ManagementError('management_issue_scope_mismatch', '反馈与可信报告依据不一致。', 403)
        basis = await self.bases._restore(connection, identity, row)
        return basis, report_revision_identity(report_id, revision)

    @staticmethod
    def _public(row):
        record = _parse(IssueRecord, row['document'])
        review = record.review
        if (review.issue_id, review.status, review.report_revision) != (row['issue_id'], row['status'], row['report_revision']) \
                or review.report_revision != report_revision_identity(record.report_id, record.revision):
            raise ManagementError('management_issue_identity_invalid', '问题登记身份不一致。', 409)
        return {'basisId': row['basis_id'], 'version': row['version'],
            'updatedAt': row['updated_at'].isoformat(), **record.model_dump(mode='json', by_alias=True)}

    async def submit(self, *, allowed_object_refs, payload, **binding):
        submitted = _parse(IssueSubmission, payload)
        if not set(submitted.object_refs) <= set(allowed_object_refs):
            raise ManagementError('management_issue_scope_mismatch', '反馈只能引用本报告修订中的已登记对象。', 403)
        async with self.repository.transaction() as connection:
            basis, revision = await self._report_binding(connection, **binding)
            now = self.scopes.auth.clock()
            review = ReportIssueReview(**submitted.model_dump(), report_revision=revision, status='open')
            document = IssueRecord(review=review, report_id=binding['report_id'], revision=binding['revision'],
                run_id=basis.run_id, submitted_by=binding['user_id'], submitted_at=now).model_dump(mode='json', by_alias=True)
            inserted = (await connection.execute(pg_insert(report_issue_reviews).values(scope_id=basis.scope_id,
                issue_id=review.issue_id, basis_id=basis.id, report_revision=revision, version=1,
                status='open', document=document, updated_at=now)
                .on_conflict_do_nothing(index_elements=['scope_id', 'issue_id']).returning(report_issue_reviews))).mappings().one_or_none()
            if inserted is not None:
                await connection.execute(insert(audit_events).values(id=str(uuid4()), occurred_at=now, actor='report-user',
                    action='report_issue_submitted', details={'scopeId': basis.scope_id, 'basisId': basis.id,
                        'runId': basis.run_id, 'userId': binding['user_id'], 'issueId': review.issue_id, 'reportRevision': revision}))
                return self._public(inserted)
            current = (await connection.execute(select(report_issue_reviews).where(
                report_issue_reviews.c.scope_id == basis.scope_id, report_issue_reviews.c.issue_id == review.issue_id))).mappings().one()
            saved = self._public(current)
            original = saved['review']
            if (current['basis_id'] != basis.id or current['report_revision'] != revision
                    or any(original[name] != document['review'][name]
                        for name in ('issueId', 'objectRefs', 'category', 'description'))):
                raise ManagementError('management_version_conflict', '同一问题身份已登记其他内容，请先读回核对。', 409)
            return saved

    async def report_list(self, *, issue_id=None, limit=50, after=None, **binding):
        async with self.repository.transaction() as connection:
            basis, revision = await self._report_binding(connection, **binding)
            return await self._list(connection, basis.scope_id, revision=revision, basis_id=basis.id,
                issue_id=issue_id, limit=limit, after=after)

    async def admin_list(self, token, scope, *, issue_id=None, limit=50, after=None):
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, token, self.scopes.auth.clock())
            scope_id = (await self.scopes.require_registered(connection, scope))['id']
            return await self._list(connection, scope_id, issue_id=issue_id, limit=limit, after=after)

    async def _list(self, connection, scope_id, *, revision=None, basis_id=None, issue_id=None, limit=50, after=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ManagementError('management_issue_invalid', '问题分页大小无效。', 422)
        query = select(report_issue_reviews).where(report_issue_reviews.c.scope_id == scope_id)
        for column, value in ((report_issue_reviews.c.report_revision, revision), (report_issue_reviews.c.basis_id, basis_id),
                (report_issue_reviews.c.issue_id, issue_id)):
            if value is not None:
                query = query.where(column == value)
        if after is not None:
            query = query.where(report_issue_reviews.c.issue_id > after)
        rows = (await connection.execute(query.order_by(report_issue_reviews.c.issue_id).limit(limit + 1))).mappings().all()
        return {'items': [self._public(row) for row in rows[:limit]],
            'nextCursor': rows[limit - 1]['issue_id'] if len(rows) > limit else None}

    async def decide(self, token, scope, issue_id, payload):
        decision = _parse(IssueDecision, payload)
        actor = await self.scopes.actor(token, scope)
        async with self.scopes.write_transaction(actor) as connection:
            scope_id = (await self.scopes.require_registered(connection, scope))['id']
            row = (await connection.execute(select(report_issue_reviews).where(
                report_issue_reviews.c.scope_id == scope_id, report_issue_reviews.c.issue_id == issue_id))).mappings().one_or_none()
            if row is None:
                raise ManagementError('management_issue_not_found', '该组织未登记此报告问题。', 404)
            self._public(row)
            if row['version'] != decision.expected_version or row['status'] in ('rejected', 'resolved'):
                raise ManagementError('management_version_conflict', '问题已有更新或裁定终态，请先读回核对。', 409)
            if decision.status == 'resolved':
                # 客户端填写的版本号或case ID不是执行证据；关闭须使用当前证据核验入口。
                raise ManagementError('management_issue_resolution_unverified', '请使用正式关闭入口核验当前修复、签认与重算处理证据，不能直接标为已解决。', 409)
            record = IssueRecord.model_validate(row['document'])
            corrected = record.review.corrected_versions
            if 'corrected_versions' in decision.model_fields_set:
                from .report_issue_fixes import validate_fix_versions

                await validate_fix_versions(self, connection, scope, row['basis_id'], record, decision.corrected_versions)
                corrected = decision.corrected_versions
            review = record.review.model_copy(update={'status': decision.status, 'decision_reason': decision.decision_reason,
                'corrected_versions': corrected})
            record = record.model_copy(update={'review': review,
                'proposal': decision.proposal if decision.proposal is not None else record.proposal})
            changed = (await connection.execute(update(report_issue_reviews).where(
                report_issue_reviews.c.scope_id == scope_id, report_issue_reviews.c.issue_id == issue_id,
                report_issue_reviews.c.version == decision.expected_version).values(version=decision.expected_version + 1,
                    status=decision.status, document=record.model_dump(mode='json', by_alias=True), updated_at=self.scopes.auth.clock())
                .returning(report_issue_reviews))).mappings().one_or_none()
            if changed is None:
                raise ManagementError('management_version_conflict', '裁定期间问题已变化，请先读回。', 409)
            await self.scopes.audit(connection, actor, 'report_issue_decided', {'issueId': issue_id,
                'basisId': row['basis_id'], 'reportRevision': row['report_revision'],
                'previousVersion': row['version'], 'version': changed['version'],
                'previousStatus': row['status'], 'status': changed['status'],
                'decisionReason': decision.decision_reason, 'proposal': record.model_dump(mode='json', by_alias=True)['proposal'],
                'previousCorrectedVersions': row['document']['review']['correctedVersions'],
                'correctedVersions': [ref.model_dump(mode='json', by_alias=True) for ref in corrected]})
            return self._public(changed)
