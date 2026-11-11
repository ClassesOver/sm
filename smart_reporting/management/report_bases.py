"""可信运行的不可变计算依据；登记事务不执行模型、检索或业务取数。"""

import hashlib
import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import insert, select, update

from ..reporting.business_knowledge.retrieval import EvidenceRelease
from ..reporting.contract import ReportRequestEnvelope
from ..reporting.data_source.starrocks import parse_starrocks_source
from ..reporting.data_sources import REPORT_DATASET_HANDLES_STATE_KEY
from ..reporting.models import ReportingError
from ..reporting.semantics.basis import (
    BasisCalculationReceipt,
    BasisDatasetSnapshot,
    BasisExecutionContext,
    BasisKnowledgeReceipt,
    BasisReceipt,
    BasisSelectionReceipt,
    BasisWorkspaceBinding,
)
from ..reporting.semantics.models import (
    BuildIdentity,
    PolicyVersionRef,
    ReportBasis,
    ReportRequestSummary,
    RunIdentity,
    SourceVersionRef,
    StatisticalPolicy,
)
from ..reporting.semantics.request import summarize_report_request
from ..reporting.semantics.request_types import ReportScenarioCandidate
from ..reporting.semantics.selection import MetricSelectionRequest, select_metric_candidates
from ..reporting.workflow.scope import reporting_scope_keys
from ..workspace import WorkspaceError
from .business_documents import _digest
from .catalog import CatalogService
from .data_sources.releases import split_version
from .data_sources.service import SourceService
from .models import ManagementError
from .repository import (
    audit_events,
    business_evidence_releases,
    catalog_versions,
    report_bases,
    report_basis_receipts,
    reporting_policy_defaults,
    runtime_snapshots,
    source_credentials,
    source_versions,
    sources,
    statistical_policy_versions,
)
from .semantic_retirements import require_active
from .statistical_policies import StatisticalPolicyService


class ReportBasisService:
    def __init__(self, scopes):
        self.scopes, self.repository = scopes, scopes.repository
        self.policies = StatisticalPolicyService(scopes, None)

    async def _audit(self, connection, basis, action, **details):
        await connection.execute(insert(audit_events).values(id=str(uuid4()),
            occurred_at=self.scopes.auth.clock(), actor="report-runtime", action=action,
            details={"scopeId": basis.scope_id, "runId": basis.run_id, "basisId": basis.id, **details}))

    async def _identity(self, connection, run_id, scope, user_id, thread_id):
        TypeAdapter(RunIdentity).validate_python(run_id)
        registered = await self.scopes.require_registered(connection, scope)
        row = (await connection.execute(select(runtime_snapshots).where(
            runtime_snapshots.c.scope_id == registered["id"], runtime_snapshots.c.run_id == run_id,
        ))).mappings().one_or_none()
        if row is None:
            raise ManagementError("management_run_identity_missing", "运行尚未登记可信组织身份。", 403)
        if (row["user_id"], row["thread_id"]) != (user_id, thread_id):
            raise ManagementError("management_run_identity_conflict", "运行身份与已登记记录不一致。", 403)
        if row["references"] is not None and row["references"].get("contract") != "semantic-v1":
            raise ManagementError("report_contract_retired", "旧报告契约已停用，请创建新报告。", 409)
        return registered, row

    @staticmethod
    async def _basis_row(connection, scope_id, run_id):
        return (await connection.execute(select(report_bases).where(
            report_bases.c.scope_id == scope_id, report_bases.c.run_id == run_id,
        ))).mappings().one_or_none()

    @staticmethod
    def _reference(basis, digest):
        return {"contract": "semantic-v1", "basisId": basis.id, "basisHash": digest}

    @staticmethod
    async def _policy(connection, scope_id, ref):
        row = (await connection.execute(select(statistical_policy_versions).where(
            statistical_policy_versions.c.scope_id == scope_id,
            statistical_policy_versions.c.policy_id == ref.policy_id,
            statistical_policy_versions.c.revision == ref.revision,
        ))).mappings().one_or_none()
        if row is None:
            raise ManagementError("management_policy_not_found", "该组织不存在所选已发布口径。", 404)
        policy = StatisticalPolicy.model_validate(row["document"])
        if (policy.scope_id, policy.id, policy.revision, policy.evidence_release_id) != (
            scope_id, ref.policy_id, ref.revision, row["evidence_release_id"],
        ) or _digest(row["document"]) != row["content_hash"]:
            raise ManagementError("management_basis_identity_invalid", "口径身份不一致。", 409)
        return policy

    @staticmethod
    async def _release(connection, scope_id, release_id, kind):
        row = (await connection.execute(select(business_evidence_releases).where(
            business_evidence_releases.c.scope_id == scope_id,
            business_evidence_releases.c.release_id == release_id,
        ))).mappings().one_or_none()
        if row is None:
            raise ManagementError("management_evidence_not_found", "该组织不存在所选证据集合。", 404)
        release = EvidenceRelease.model_validate(row["document"])
        if (release.scope_id, release.release_id, release.kind) != (scope_id, release_id, kind) or (
            row["kind"] != kind or _digest(row["document"]) != row["content_hash"]
        ):
            raise ManagementError("management_basis_identity_invalid", "证据集合身份不一致。", 409)
        # 不读取原文。撤销和适用性在检索/恢复引用时按当前授权重新检查。
        return release

    @staticmethod
    async def _source(connection, scope_id, source_id, revision):
        enabled = await connection.scalar(select(sources.c.enabled).where(
            sources.c.scope_id == scope_id, sources.c.source_id == source_id,
        ))
        if enabled != 1:
            raise ManagementError("management_source_disabled", "数据源已停用或不属于当前组织。", 403)
        row = (await connection.execute(select(source_versions).where(
            source_versions.c.scope_id == scope_id, source_versions.c.source_id == source_id,
            source_versions.c.revision == revision,
        ))).mappings().one_or_none()
        if row is None or row["execution_parameters"] is None:
            raise ManagementError("management_source_version_not_found", "已发布数据源或执行参数不存在。", 409)
        if row["profile_version_id"] is not None:
            raise ManagementError("management_source_contract_retired", "旧数据源业务契约已停用，请重新登记连接与目录。", 409)
        public = {"name": row["name"], "type": row["source_type"], "database": row["database"],
            "metadataVersionId": row["metadata_version_id"]}
        if SourceService._config_hash(public, row["credential_revision"], row["execution_parameters"]) != row["content_hash"]:
            raise ManagementError("management_basis_identity_invalid", "数据源内容身份不一致。", 409)
        catalog_source, catalog_revision = split_version(row["metadata_version_id"])
        catalog = (await connection.execute(select(catalog_versions).where(
            catalog_versions.c.scope_id == scope_id, catalog_versions.c.source_id == source_id,
            catalog_versions.c.revision == catalog_revision, catalog_versions.c.status == "published",
        ))).mappings().one_or_none()
        credential = (await connection.execute(select(source_credentials.c.revision).where(
            source_credentials.c.scope_id == scope_id, source_credentials.c.source_id == source_id,
            source_credentials.c.credential_ref == row["credential_ref"],
            source_credentials.c.revision == row["credential_revision"],
        ))).first()
        if catalog_source != source_id or catalog is None or credential is None:
            raise ManagementError("management_basis_dependency_missing", "数据源的目录或凭据版本不可用。", 409)
        if CatalogService._hash(catalog["catalog"]) != catalog["content_hash"]:
            raise ManagementError("management_basis_identity_invalid", "目录内容身份不一致。", 409)
        CatalogService.validate_snapshot(catalog["catalog"], source_id, row["database"])
        identity = catalog["catalog"].get("connectionIdentity")
        if identity is not None and identity != {"database": row["database"],
            "credentialRef": row["credential_ref"], "credentialRevision": row["credential_revision"]}:
            raise ManagementError("management_catalog_connection_mismatch", "目录不属于所选连接版本。", 409)
        return (SourceVersionRef(source_id=source_id, revision=revision, content_hash=row["content_hash"]),
            SourceVersionRef(source_id=source_id, revision=catalog_revision, content_hash=catalog["content_hash"]))

    async def _restore(self, connection, identity, row):
        basis = ReportBasis.model_validate(row["document"])
        digest = _digest(row["document"])
        if digest != row["content_hash"] or (basis.scope_id, basis.run_id, basis.id,
            basis.policy_version.policy_id, basis.policy_version.revision, basis.evidence_release_id,
            basis.background_release_id, basis.registered_at) != (row["scope_id"], row["run_id"], row["basis_id"],
            row["policy_id"], row["policy_revision"], row["evidence_release_id"], row["background_release_id"], row["registered_at"]):
            raise ManagementError("management_basis_identity_invalid", "报告计算依据身份不一致。", 409)
        reference = self._reference(basis, digest)
        if identity["references"] != reference or identity["reference_hash"] != _digest(reference):
            raise ManagementError("management_basis_identity_invalid", "运行与计算依据登记不一致。", 409)
        policy = await self._policy(connection, basis.scope_id, basis.policy_version)
        graph = await self.policies._metric_graph(connection, basis.scope_id, policy, require_available=False)
        if set(graph) != set(basis.metric_versions) or policy.evidence_release_id != basis.evidence_release_id:
            raise ManagementError("management_basis_identity_invalid", "计算依据依赖不一致。", 409)
        await self._release(connection, basis.scope_id, basis.evidence_release_id, "rule_evidence")
        if basis.background_release_id is not None:
            await self._release(connection, basis.scope_id, basis.background_release_id, "background")
        catalogs = {ref.source_id: ref for ref in basis.catalog_refs}
        for ref in basis.source_versions:
            source, catalog = await self._source(connection, basis.scope_id, ref.source_id, ref.revision)
            if source != ref or catalog != catalogs[ref.source_id]:
                raise ManagementError("management_basis_identity_invalid", "数据源或目录版本身份已变化。", 409)
        return basis

    async def scenario_candidates(self, run_id, scope, *, user_id, thread_id):
        async with self.repository.transaction() as connection:
            registered, _ = await self._identity(connection, run_id, scope, user_id, thread_id)
            rows = (await connection.execute(select(
                reporting_policy_defaults.c.scenario, statistical_policy_versions.c.document,
            ).join(statistical_policy_versions,
                (statistical_policy_versions.c.scope_id == reporting_policy_defaults.c.scope_id)
                & (statistical_policy_versions.c.policy_id == reporting_policy_defaults.c.policy_id)
                & (statistical_policy_versions.c.revision == reporting_policy_defaults.c.policy_revision)
            ).where(reporting_policy_defaults.c.scope_id == registered["id"])
                .order_by(reporting_policy_defaults.c.scenario))).mappings().all()
            return tuple(ReportScenarioCandidate(scenario=row["scenario"],
                name=StatisticalPolicy.model_validate(row["document"]).name) for row in rows)

    async def register_request_basis(self, run_id, scope, *, user_id, thread_id, request, build_identity):
        envelope = ReportRequestEnvelope.from_untrusted(request)
        async with self.repository.transaction() as connection:
            registered, _ = await self._identity(connection, run_id, scope, user_id, thread_id)
            summary = summarize_report_request(envelope, organization=registered["id"])
        return await self.register_report_basis(run_id, scope, user_id=user_id, thread_id=thread_id,
            request_summary=summary, build_identity=build_identity,
            policy_version=envelope.statistical_policy_version, source_ids=envelope.source_ids,
            knowledge_as_of=envelope.knowledge_as_of)

    async def register_report_basis(self, run_id, scope, *, user_id, thread_id, request_summary,
        build_identity, policy_version=None, knowledge_as_of=None, source_ids=None):
        summary = ReportRequestSummary.model_validate(request_summary)
        build = BuildIdentity.model_validate(build_identity)
        selected = PolicyVersionRef.model_validate(policy_version) if policy_version is not None else None
        async with self.repository.transaction() as connection:
            registered, identity = await self._identity(connection, run_id, scope, user_id, thread_id)
            scope_id = registered["id"]
            if summary.organization != scope_id:
                raise ManagementError("management_basis_scope_mismatch", "请求与可信运行组织不一致。", 403)
            existing = await self._basis_row(connection, scope_id, run_id)
            if existing is not None:
                basis = await self._restore(connection, identity, existing)
                if source_ids is not None and set(source_ids) != {ref.source_id for ref in basis.source_versions}:
                    raise ManagementError("management_basis_selection_conflict", "运行已登记其他数据源，请创建新修订。", 409)
                if basis.request_summary != summary or (selected is not None and selected != basis.policy_version) or (
                    knowledge_as_of is not None and knowledge_as_of != basis.knowledge_as_of
                ):
                    raise ManagementError("management_basis_selection_conflict", "运行已登记其他计算条件，请创建新修订。", 409)
                return basis
            if identity["references"] is not None:
                raise ManagementError("management_basis_identity_invalid", "运行引用缺少对应计算依据。", 409)
            default = (await connection.execute(select(reporting_policy_defaults).where(
                reporting_policy_defaults.c.scope_id == scope_id,
                reporting_policy_defaults.c.scenario == summary.scenario,
            ))).mappings().one_or_none()
            if selected is None:
                if default is None:
                    raise ManagementError("management_policy_default_missing", "当前场景尚未登记默认统计口径。", 422)
                selected = PolicyVersionRef(policy_id=default["policy_id"], revision=default["policy_revision"])
            policy = await self._policy(connection, scope_id, selected)
            if policy.scenario != summary.scenario:
                raise ManagementError("management_policy_scenario_mismatch", "口径与报告场景不一致。", 422)
            await require_active(connection, scope_id, "statistical_policy", selected.policy_id, selected.revision)
            graph = await self.policies._metric_graph(connection, scope_id, policy)
            await self._release(connection, scope_id, policy.evidence_release_id, "rule_evidence")
            background = default["background_release_id"] if default is not None and (
                default["policy_id"], default["policy_revision"]) == (selected.policy_id, selected.revision) else None
            if background is not None:
                await self._release(connection, scope_id, background, "background")
            source_refs, catalog_refs = [], []
            selected_sources = source_ids if source_ids is not None else registered["default_source_ids"]
            if not selected_sources:
                raise ManagementError("management_default_source_missing", "组织尚未选用已发布数据源。", 422)
            for source_id in sorted(set(selected_sources)):
                revision = await connection.scalar(select(sources.c.published_revision).where(
                    sources.c.scope_id == scope_id, sources.c.source_id == source_id,
                ))
                source, catalog = await self._source(connection, scope_id, source_id, revision)
                source_refs.append(source)
                catalog_refs.append(catalog)
            now = self.scopes.auth.clock()
            if knowledge_as_of is not None and knowledge_as_of > now:
                raise ManagementError("management_knowledge_time_invalid", "知识截止时间不能晚于报告登记时间。", 422)
            basis = ReportBasis(id=str(uuid5(NAMESPACE_URL, f"report-basis:{scope_id}:{run_id}")),
                run_id=run_id, scope_id=scope_id, policy_version=selected,
                metric_versions=tuple(sorted(graph, key=lambda ref: (ref.metric_id, ref.revision))),
                source_versions=tuple(source_refs), catalog_refs=tuple(catalog_refs),
                evidence_release_id=policy.evidence_release_id, background_release_id=background,
                request_summary=summary, build_identity=build, knowledge_as_of=knowledge_as_of or now, registered_at=now)
            body = basis.model_dump(mode="json", by_alias=True)
            digest = _digest(body)
            await connection.execute(insert(report_bases).values(scope_id=scope_id, run_id=run_id,
                basis_id=basis.id, policy_id=selected.policy_id, policy_revision=selected.revision,
                evidence_release_id=basis.evidence_release_id, background_release_id=background,
                document=body, content_hash=digest, registered_at=now))
            reference = self._reference(basis, digest)
            await connection.execute(update(runtime_snapshots).where(runtime_snapshots.c.scope_id == scope_id,
                runtime_snapshots.c.run_id == run_id).values(references=reference, reference_hash=_digest(reference)))
            await self._audit(connection, basis, "report_basis_registered")
            return basis

    async def load_report_basis(self, run_id, scope, *, user_id, thread_id):
        async with self.repository.transaction() as connection:
            registered, identity = await self._identity(connection, run_id, scope, user_id, thread_id)
            row = await self._basis_row(connection, registered["id"], run_id)
            if row is None:
                raise ManagementError("management_basis_not_found", "运行尚未登记计算依据。", 404)
            return await self._restore(connection, identity, row)

    async def load_execution_context(self, run_id, scope, *, user_id, thread_id, vault):
        async with self.repository.transaction() as connection:
            registered, identity = await self._identity(connection, run_id, scope, user_id, thread_id)
            row = await self._basis_row(connection, registered["id"], run_id)
            if row is None:
                raise ManagementError("management_basis_not_found", "运行尚未登记计算依据。", 404)
            basis = await self._restore(connection, identity, row)
            policy = await self._policy(connection, basis.scope_id, basis.policy_version)
            graph = await self.policies._metric_graph(connection, basis.scope_id, policy, require_available=False)
            configs, metadata = {}, {}
            catalogs = {ref.source_id: ref for ref in basis.catalog_refs}
            for ref in basis.source_versions:
                source = (await connection.execute(select(source_versions).where(
                    source_versions.c.scope_id == basis.scope_id, source_versions.c.source_id == ref.source_id,
                    source_versions.c.revision == ref.revision,
                ))).mappings().one()
                credential = (await connection.execute(select(source_credentials).where(
                    source_credentials.c.scope_id == basis.scope_id, source_credentials.c.source_id == ref.source_id,
                    source_credentials.c.credential_ref == source["credential_ref"],
                    source_credentials.c.revision == source["credential_revision"],
                ))).mappings().one()
                dsn = vault.decrypt(credential["key_id"], json.loads(credential["ciphertext"]).encode())
                if hashlib.sha256(dsn.encode()).hexdigest() != credential["secret_hash"]:
                    raise ManagementError("management_basis_identity_invalid", "数据源凭据身份不一致。", 409)
                configs[ref.source_id] = parse_starrocks_source({
                    "id": ref.source_id, "type": source["source_type"], "name": source["name"],
                    "database": source["database"], "dsnEnv": "MANAGED_DSN", **source["execution_parameters"],
                }, {"MANAGED_DSN": dsn})
                catalog = await connection.scalar(select(catalog_versions.c.catalog).where(
                    catalog_versions.c.scope_id == basis.scope_id, catalog_versions.c.source_id == ref.source_id,
                    catalog_versions.c.revision == catalogs[ref.source_id].revision,
                ))
                metadata[ref.source_id] = CatalogService.validate_snapshot(catalog, ref.source_id, source["database"])
            return BasisExecutionContext(basis, policy, tuple(graph[ref] for ref in basis.metric_versions), configs, metadata)

    @staticmethod
    def _workspace_binding(run_id, scope, user_id, thread_id, dataset_store, run_context, workflow_scope):
        if workflow_scope is None or run_context is None or dataset_store is None or (
            workflow_scope.run_id, workflow_scope.database, workflow_scope.company_id,
            workflow_scope.user_id, workflow_scope.caller_thread_id
        ) != (run_id, scope.database, scope.company_id, user_id, thread_id) or (
            run_context.run_id != run_id or run_context.session_id != workflow_scope.workspace_key
        ):
            raise ManagementError("management_basis_workspace_mismatch", "计算快照工作区与可信运行不一致。", 403)
        keys = reporting_scope_keys(database=scope.database, company_id=scope.company_id,
            user_id=user_id, thread_id=thread_id, run_id=run_id)
        if (workflow_scope.workspace_key, workflow_scope.thread_lease_key) != (keys.workspace_key, keys.thread_lease_key):
            raise ManagementError("management_basis_workspace_mismatch", "工作区标识与可信运行派生身份不一致。", 403)
        identity = dataset_store.service.registry.resolve(workflow_scope)
        return BasisWorkspaceBinding(workspace_key=identity.workspace_key, session_id=identity.workflow_session_id,
            scope_fingerprint=identity.scope_fingerprint)

    @staticmethod
    async def _verify_snapshots(snapshots, dataset_store, binding):
        try:
            for snapshot in snapshots:
                current = await dataset_store.service.ahash_file(binding.workspace_key, snapshot.file.path)
                if current.get("sha256") != snapshot.file.sha256 or current.get("size") != snapshot.file.size:
                    raise ManagementError("management_basis_snapshot_unavailable", "原始CSV快照身份已变化，不能复核。", 409)
        except (ReportingError, WorkspaceError, OSError):
            raise ManagementError("management_basis_snapshot_unavailable", "原始CSV快照缺失或无法核验，不能复核。", 409) from None

    async def append_basis_receipt(self, run_id, scope, *, user_id, thread_id, receipt_id,
        report_revision, request, results, readiness=(), dataset_handles=(), dataset_store=None,
        run_context=None, workflow_scope=None):
        snapshots, binding = (), None
        if dataset_handles:
            # 先检查可信运行，再访问文件；文件核验不占用管理事务。提交时重新检查依据。
            basis = await self.load_report_basis(run_id, scope, user_id=user_id, thread_id=thread_id)
            binding = self._workspace_binding(run_id, scope, user_id, thread_id, dataset_store, run_context, workflow_scope)
            try:
                snapshots = tuple(BasisDatasetSnapshot.from_handle(handle) for handle in dataset_handles)
            except (ValidationError, ValueError):
                raise ManagementError("management_basis_receipt_invalid", "CSV快照登记结构无效。", 422) from None
            if any(item.source_id not in {ref.source_id for ref in basis.source_versions} for item in snapshots):
                raise ManagementError("management_basis_receipt_invalid", "CSV来源不属于已登记数据源。", 403)
            await self._verify_snapshots(snapshots, dataset_store, binding)
        async with self.repository.transaction() as connection:
            registered, identity = await self._identity(connection, run_id, scope, user_id, thread_id)
            row = await self._basis_row(connection, registered["id"], run_id)
            if row is None:
                raise ManagementError("management_basis_not_found", "运行尚未登记计算依据。", 404)
            basis = await self._restore(connection, identity, row)
            try:
                receipt = BasisCalculationReceipt(receipt_id=receipt_id, basis_id=basis.id,
                    report_revision=report_revision, request=request, results=results, readiness=readiness,
                    datasets=snapshots, workspace=binding,
                    created_at=self.scopes.auth.clock())
            except ValidationError:
                raise ManagementError("management_basis_receipt_invalid", "计算回执身份或结构无效。", 422) from None
            allowed = set(basis.metric_versions)
            if receipt.request.metric_version not in allowed or any(result.metric_version not in allowed
                for result in receipt.results) or any(check.metric_version not in allowed for check in receipt.readiness):
                raise ManagementError("management_basis_receipt_invalid", "计算回执引用未登记的指标版本。", 403)
            if receipt.request.period not in (basis.request_summary.period, basis.request_summary.comparison_period):
                raise ManagementError("management_basis_receipt_invalid", "计算期间不属于已登记的报告请求。", 422)
            policy = await self._policy(connection, basis.scope_id, basis.policy_version)
            graph = await self.policies._metric_graph(connection, basis.scope_id, policy, require_available=False)
            if receipt.request.metric_version not in policy.metric_versions or any(
                result.unit != graph[result.metric_version].unit or (result.status == "computed"
                    and tuple(value.dimension_id for value in result.dimensions) != receipt.request.dimensions)
                for result in receipt.results
            ):
                raise ManagementError("management_basis_receipt_invalid", "计算单位或维度与登记请求不一致。", 422)
            current = (await connection.execute(select(report_basis_receipts).where(
                report_basis_receipts.c.scope_id == basis.scope_id,
                report_basis_receipts.c.basis_id == basis.id,
                report_basis_receipts.c.receipt_id == receipt_id,
            ))).mappings().one_or_none()
            if current is not None:
                stored = self._receipt(current, basis.id)
                if stored.model_dump(exclude={"created_at"}) != receipt.model_dump(exclude={"created_at"}):
                    raise ManagementError("management_basis_receipt_conflict", "该回执标识已登记其他计算结果。", 409)
                return stored
            body = receipt.model_dump(mode="json", by_alias=True)
            await connection.execute(insert(report_basis_receipts).values(scope_id=basis.scope_id,
                basis_id=basis.id, receipt_id=receipt.receipt_id, report_revision=report_revision,
                document=body, content_hash=_digest(body), created_at=receipt.created_at))
            await self._audit(connection, basis, "report_basis_receipt_appended",
                receiptId=receipt.receipt_id, reportRevision=report_revision)
            return receipt

    @staticmethod
    def _receipt(row, basis_id):
        receipt = TypeAdapter(BasisReceipt).validate_python(row["document"])
        if _digest(row["document"]) != row["content_hash"] or (receipt.basis_id, receipt.receipt_id,
            receipt.report_revision, receipt.created_at) != (basis_id, row["receipt_id"],
            row["report_revision"], row["created_at"]):
            raise ManagementError("management_basis_identity_invalid", "计算回执身份不一致。", 409)
        return receipt

    async def policy_adoption_options(self, run_id, scope, **options):
        from .report_policy_adoption import policy_adoption_options

        return await policy_adoption_options(self, run_id, scope, **options)

    async def preview_policy_adoption(self, run_id, scope, **options):
        from .report_policy_adoption import preview_policy_adoption

        return await preview_policy_adoption(self, run_id, scope, **options)

    async def register_policy_adoption(self, run_id, scope, **options):
        from .report_policy_adoption import register_policy_adoption

        return await register_policy_adoption(self, run_id, scope, **options)

    async def read_policy_adoption(self, run_id, scope, **options):
        from .report_policy_adoption import read_policy_adoption

        return await read_policy_adoption(self, run_id, scope, **options)

    async def register_adoption_selections(self, run_id, scope, **options):
        from .report_policy_adoption import register_adoption_selections

        return await register_adoption_selections(self, run_id, scope, **options)

    async def calculate_adoption_metrics(self, run_id, scope, **options):
        from .report_adoption_calculations import calculate_adoption_metrics

        return await calculate_adoption_metrics(self, run_id, scope, **options)

    async def refresh_calculation(self, run_id, scope, **options):
        from .report_calculations import refresh_calculation

        return await refresh_calculation(self, run_id, scope, **options)

    async def load_refresh_planning_context(self, run_id, scope, **options):
        from .report_calculations import load_refresh_planning_context

        return await load_refresh_planning_context(self, run_id, scope, **options)

    async def refresh_revision(self, run_id, scope, **options):
        from .report_refresh_revisions import refresh_revision

        return await refresh_revision(self, run_id, scope, **options)

    async def register_refresh_revision(self, run_id, scope, **options):
        from .report_refresh_revisions import register_refresh_revision

        return await register_refresh_revision(self, run_id, scope, **options)

    async def load_revision_planning_context(self, run_id, scope, **options):
        from .report_refresh_revisions import load_revision_planning_context

        return await load_revision_planning_context(self, run_id, scope, **options)

    async def load_revision_dataset_handles(self, run_id, scope, **options):
        from .report_refresh_revisions import load_revision_dataset_handles

        return await load_revision_dataset_handles(self, run_id, scope, **options)

    async def load_registered_revision_planning_context(self, run_id, scope, **options):
        from .report_refresh_revisions import load_registered_revision_planning_context

        return await load_registered_revision_planning_context(self, run_id, scope, **options)

    async def load_basis_receipts(self, run_id, scope, *, user_id, thread_id, report_revision):
        TypeAdapter(RunIdentity).validate_python(report_revision)
        async with self.repository.transaction() as connection:
            registered, identity = await self._identity(connection, run_id, scope, user_id, thread_id)
            basis_row = await self._basis_row(connection, registered["id"], run_id)
            if basis_row is None:
                raise ManagementError("management_basis_not_found", "运行尚未登记计算依据。", 404)
            basis = await self._restore(connection, identity, basis_row)
            rows = (await connection.execute(select(report_basis_receipts).where(
                report_basis_receipts.c.scope_id == basis.scope_id,
                report_basis_receipts.c.basis_id == basis.id,
                report_basis_receipts.c.report_revision == report_revision,
            ).order_by(report_basis_receipts.c.created_at, report_basis_receipts.c.receipt_id))).mappings().all()
            return tuple(self._receipt(row, basis.id) for row in rows)

    async def verify_receipt_datasets(self, run_id, scope, *, user_id, thread_id, report_revision,
        dataset_store, run_context, workflow_scope):
        receipts = await self.load_basis_receipts(run_id, scope, user_id=user_id, thread_id=thread_id,
            report_revision=report_revision)
        binding = self._workspace_binding(run_id, scope, user_id, thread_id, dataset_store, run_context, workflow_scope)
        snapshots = {}
        for receipt in receipts:
            if not isinstance(receipt, BasisCalculationReceipt):
                continue
            if receipt.datasets and receipt.workspace != binding:
                raise ManagementError("management_basis_workspace_mismatch", "原始CSV快照不属于当前运行工作区。", 403)
            for snapshot in receipt.datasets:
                previous = snapshots.get(snapshot.dataset.dataset_id)
                if previous is not None and previous != snapshot:
                    raise ManagementError("management_basis_identity_invalid", "计算回执中的数据集身份冲突。", 409)
                snapshots[snapshot.dataset.dataset_id] = snapshot
        await self._verify_snapshots(tuple(snapshots.values()), dataset_store, binding)
        return tuple(item.to_handle() for item in snapshots.values())

    async def restore_receipt_datasets(self, run_id, scope, *, user_id, thread_id, report_revision,
        dataset_store, run_context, workflow_scope):
        # 会话中的旧句柄并非权威来源，恢复时不与其合并。单纯核验不改探索数据句柄。
        if run_context.session_state is None:
            run_context.session_state = {}
        run_context.session_state.pop(REPORT_DATASET_HANDLES_STATE_KEY, None)
        handles = await self.verify_receipt_datasets(run_id, scope, user_id=user_id, thread_id=thread_id,
            report_revision=report_revision, dataset_store=dataset_store, run_context=run_context,
            workflow_scope=workflow_scope)
        # 全部核验成功后才恢复现有句柄状态；客户端状态不参与授权或文件定位。
        dataset_store._store_handles(handles, run_context)
        return handles

    async def append_selection_receipt(self, run_id, scope, *, user_id, thread_id, receipt_id,
        report_revision, requests, vault):
        try:
            choices = TypeAdapter(tuple[MetricSelectionRequest, ...]).validate_python(requests)
            TypeAdapter(RunIdentity).validate_python(report_revision)
        except ValidationError:
            raise ManagementError("management_basis_receipt_invalid", "指标选择请求结构无效。", 422) from None
        context = await self.load_execution_context(run_id, scope, user_id=user_id, thread_id=thread_id, vault=vault)
        questions = {item.id for item in context.basis.request_summary.questions}
        if len(choices) != len(questions) or {item.question_id for item in choices} != questions:
            raise ManagementError("management_basis_receipt_invalid", "每个已登记问题都必须有明确选择或未解决状态。", 422)
        selections = tuple(select_metric_candidates(item.question_id, context, candidates=item.candidates,
            explicit=item.explicit, clarified=item.clarified) for item in choices)
        async with self.repository.transaction() as connection:
            registered, identity = await self._identity(connection, run_id, scope, user_id, thread_id)
            row = await self._basis_row(connection, registered["id"], run_id)
            if row is None:
                raise ManagementError("management_basis_not_found", "运行尚未登记计算依据。", 404)
            basis = await self._restore(connection, identity, row)
            if basis != context.basis:
                raise ManagementError("management_basis_identity_invalid", "选择期间计算依据发生变化。", 409)
            try:
                receipt = BasisSelectionReceipt(receipt_id=receipt_id, basis_id=basis.id,
                    report_revision=report_revision, selections=selections, created_at=self.scopes.auth.clock())
            except ValidationError:
                raise ManagementError("management_basis_receipt_invalid", "指标选择回执结构无效。", 422) from None
            current = (await connection.execute(select(report_basis_receipts).where(
                report_basis_receipts.c.scope_id == basis.scope_id, report_basis_receipts.c.basis_id == basis.id,
                report_basis_receipts.c.receipt_id == receipt_id,
            ))).mappings().one_or_none()
            if current is not None:
                stored = self._receipt(current, basis.id)
                if stored.model_dump(exclude={"created_at"}) != receipt.model_dump(exclude={"created_at"}):
                    raise ManagementError("management_basis_receipt_conflict", "该回执标识已登记其他选择结果。", 409)
                return stored
            body = receipt.model_dump(mode="json", by_alias=True)
            await connection.execute(insert(report_basis_receipts).values(scope_id=basis.scope_id,
                basis_id=basis.id, receipt_id=receipt.receipt_id, report_revision=report_revision,
                document=body, content_hash=_digest(body), created_at=receipt.created_at))
            await self._audit(connection, basis, "report_metric_selection_registered",
                receiptId=receipt.receipt_id, reportRevision=report_revision)
            return receipt

    async def append_knowledge_receipt(self, run_id, scope, *, user_id, thread_id, receipt_id,
        report_revision, section_code, kind, query, evidence_service):
        """只登记服务端检索结果；外部片段不能作为待登记输入。"""
        try:
            TypeAdapter(RunIdentity).validate_python(report_revision)
            # 用严格模型校验边界；未绑定背景的结构同样需要合法的查询及身份。
            from ..reporting.business_knowledge.retrieval import ReportEvidenceSearchReceipt

            basis = await self.load_report_basis(run_id, scope, user_id=user_id, thread_id=thread_id)
            candidate = BasisKnowledgeReceipt(receipt_id=receipt_id, basis_id=basis.id,
                report_revision=report_revision, section_code=section_code, query=query,
                evidence=ReportEvidenceSearchReceipt(basis_id=basis.id, kind=kind,
                    issue_codes=('knowledge_pending',)), created_at=self.scopes.auth.clock())
        except ValidationError:
            raise ManagementError('management_basis_receipt_invalid', '知识回执请求结构无效。', 422) from None

        def existing(row):
            stored = self._receipt(row, basis.id)
            if not isinstance(stored, BasisKnowledgeReceipt) or (
                stored.report_revision, stored.section_code, stored.query, stored.evidence.kind
            ) != (report_revision, section_code, query, kind):
                raise ManagementError('management_basis_receipt_conflict', '该回执标识已用于其他知识请求。', 409)
            return stored

        async def current_row(connection):
            return (await connection.execute(select(report_basis_receipts).where(
                report_basis_receipts.c.scope_id == basis.scope_id, report_basis_receipts.c.basis_id == basis.id,
                report_basis_receipts.c.receipt_id == receipt_id,
            ))).mappings().one_or_none()

        async with self.repository.transaction() as connection:
            row = await current_row(connection)
            if row is not None:
                return existing(row)
        evidence = await evidence_service.search_report(self, run_id=run_id, scope=scope,
            user_id=user_id, thread_id=thread_id, kind=kind, query=query)
        receipt = BasisKnowledgeReceipt(**candidate.model_dump(exclude={'evidence', 'created_at'}),
            evidence=evidence, created_at=self.scopes.auth.clock())
        async with self.repository.transaction() as connection:
            registered, identity = await self._identity(connection, run_id, scope, user_id, thread_id)
            basis_row = await self._basis_row(connection, registered['id'], run_id)
            if basis_row is None or await self._restore(connection, identity, basis_row) != basis:
                raise ManagementError('management_basis_identity_invalid', '检索期间报告计算依据发生变化。', 409)
            row = await current_row(connection)
            if row is not None:
                return existing(row)
            body = receipt.model_dump(mode='json', by_alias=True)
            await connection.execute(insert(report_basis_receipts).values(scope_id=basis.scope_id,
                basis_id=basis.id, receipt_id=receipt.receipt_id, report_revision=report_revision,
                document=body, content_hash=_digest(body), created_at=receipt.created_at))
            await self._audit(connection, basis, 'report_knowledge_registered',
                receiptId=receipt.receipt_id, reportRevision=report_revision, sectionCode=section_code)
            return receipt
