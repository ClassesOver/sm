"""Reporting 章节、返工与图表登记能力。"""

# mypy: disable-error-code="attr-defined"
# 运行时由 toolkit 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from agno.run import RunContext
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from ...workspace import WorkspaceError, WorkspaceService
from ..delivery.draft_v1 import (
    ReportChartRegistration,
    ReportDraftBlock,
    validate_report_draft_blocks,
)
from ..models import ReportingError
from ..phase import (
    REPORTING_TASK_DEPENDENCY,
    REPORTING_VISUALIZATION_SCRIPT_FAILURE_PENDING_STATE_KEY,
)
from ..workflow.checkpoint import (
    AnalysisReworkRequest,
    ChartVisualInspectionReceipt,
    FileIdentity,
    SectionArtifact,
    SectionClaim,
    SectionClaimSubmission,
    SectionWorkItem,
)
from .phase_output import REPORT_PHASE_OUTPUT_STATE_KEY
from .validation import _stable_digest

MAX_REPORT_CHART_BYTES = 10 * 1024 * 1024
# 174mm 来源于 A4 纸张宽度 210mm 减去现有左右各 18mm 页边距，仅作质量估算，不能作为发布门禁。
MIN_REPORT_CHART_WIDTH = 1200
MIN_REPORT_CHART_HEIGHT = 675
MIN_REPORT_CHART_EFFECTIVE_DPI = 150
REPORT_BODY_WIDTH_INCHES = 174 / 25.4


class RuntimeSectionsMixin:
    @staticmethod
    def _normalize_section_claims(
        *,
        section_code: str,
        claims: list[dict[str, Any]],
        work_item: SectionWorkItem,
    ) -> tuple[tuple[SectionClaim, ...], tuple[dict[str, Any], ...]]:
        warnings: list[dict[str, Any]] = []
        submissions: list[SectionClaimSubmission] = []
        seen_claim_ids: set[str] = set()
        for index, item in enumerate(claims):
            try:
                submission = SectionClaimSubmission.model_validate(item)
            except ValidationError as error:
                warnings.append(
                    {
                        "code": "report_section_claim_invalid",
                        "message": "章节 claim 结构无效，已省略该 claim。",
                        "details": {
                            "index": index,
                            "errors": error.errors(
                                include_url=False,
                                include_context=False,
                                include_input=False,
                            ),
                        },
                    }
                )
                continue
            if submission.claim_id in seen_claim_ids:
                warnings.append(
                    {
                        "code": "report_section_claim_duplicate",
                        "message": "章节 claimId 重复，已保留首次提交。",
                        "details": {"claimId": submission.claim_id},
                    }
                )
                continue
            seen_claim_ids.add(submission.claim_id)
            submissions.append(submission)
        metrics_by_code = {item.code: item for item in work_item.metric_definitions}
        charts_by_id = {item.chart_id: item for item in work_item.charts}
        known_citations = {item.citation_id for item in work_item.citations}
        questions_by_ref = {
            item.ref: item.question
            for item in getattr(work_item, "management_question_catalog", ())
        }
        normalized: list[SectionClaim] = []

        for submission in submissions:
            metric = metrics_by_code.get(submission.metric_code)
            if metric is None:
                warnings.append(
                    {
                        "code": "report_section_claim_metric_unknown",
                        "message": "章节 claim 引用了未冻结指标，已保留正文并标记警告。",
                        "details": {
                            "sectionCode": section_code,
                            "claimId": submission.claim_id,
                            "metricCode": submission.metric_code,
                            "expectedMetricCodes": sorted(metrics_by_code),
                        },
                    }
                )
            management_question = questions_by_ref.get(submission.management_question_ref)
            if management_question is None:
                warnings.append(
                    {
                        "code": "report_section_claim_question_unknown",
                        "message": "章节 claim 未匹配当前章节管理问题，已保留并标记警告。",
                        "details": {
                            "sectionCode": section_code,
                            "claimId": submission.claim_id,
                            "managementQuestionRef": submission.management_question_ref,
                            "expectedManagementQuestionRefs": list(questions_by_ref),
                        },
                    }
                )
                management_question = f"未绑定管理问题（{submission.management_question_ref}）"
            unknown_citations = set(submission.citation_ids) - known_citations
            citation_ids = [
                citation_id
                for citation_id in submission.citation_ids
                if citation_id in known_citations
            ]
            if unknown_citations:
                warnings.append(
                    {
                        "code": "report_section_claim_citation_unknown",
                        "message": "章节 claim 的未知 citation 已从绑定中移除。",
                        "details": {
                            "sectionCode": section_code,
                            "claimId": submission.claim_id,
                            "unknownCitationIds": sorted(unknown_citations),
                        },
                    }
                )
            unknown_charts = set(submission.chart_ids) - set(charts_by_id)
            chart_ids = tuple(
                chart_id for chart_id in submission.chart_ids if chart_id in charts_by_id
            )
            if unknown_charts:
                warnings.append(
                    {
                        "code": "report_section_claim_chart_unknown",
                        "message": "章节 claim 的未知 chart 已从绑定中移除。",
                        "details": {
                            "sectionCode": section_code,
                            "claimId": submission.claim_id,
                            "unknownChartIds": sorted(unknown_charts),
                        },
                    }
                )
            if not citation_ids:
                warnings.append(
                    {
                        "code": "report_section_claim_citation_missing",
                        "message": "章节 claim 没有可验证 citation，已省略该 claim。",
                        "details": {"sectionCode": section_code, "claimId": submission.claim_id},
                    }
                )
                continue

            selected_charts = tuple(charts_by_id[item] for item in chart_ids)
            if selected_charts:
                # 图表周期与可比性来自分析阶段冻结契约，不能让章节模型重新转录或覆盖。
                # 同一 claim 绑定多图时只有完全相同的语义才可确定性派生；冲突时保留
                # 首张图的冻结语义并记录警告，避免模型原样重试阻塞整个章节。
                semantic_keys = {
                    (
                        chart.current_period,
                        chart.comparison_period,
                        chart.comparison_type,
                        chart.comparability,
                    )
                    for chart in selected_charts
                }
                if len(semantic_keys) != 1:
                    warnings.append(
                        {
                            "code": "report_section_claim_chart_semantics_conflict",
                            "message": "同一 claim 的图表语义不一致，已使用首张图表的冻结语义。",
                            "details": {
                                "sectionCode": section_code,
                                "claimId": submission.claim_id,
                                "chartIds": list(chart_ids),
                            },
                        }
                    )
                    selected_charts = selected_charts[:1]
                    chart_ids = (selected_charts[0].chart_id,)
                first_chart = selected_charts[0]
                current_period, comparison_period, comparison_type, comparability = (
                    first_chart.current_period,
                    first_chart.comparison_period,
                    first_chart.comparison_type,
                    first_chart.comparability,
                )
                for chart in selected_charts:
                    for citation_id in chart.citation_ids:
                        if citation_id not in citation_ids:
                            citation_ids.append(citation_id)
            else:
                if submission.current_period is None:
                    warnings.append(
                        {
                            "code": "report_section_claim_period_missing",
                            "message": "章节 claim 未声明 currentPeriod，已使用指标期间口径。",
                            "details": {
                                "sectionCode": section_code,
                                "claimId": submission.claim_id,
                            },
                        }
                    )
                current_period = submission.current_period or (
                    metric.period_basis if metric is not None else "未声明期间"
                )
                comparison_period = submission.comparison_period
                comparison_type = submission.comparison_type
                comparability = submission.comparability

            try:
                normalized_claim = SectionClaim(
                    claimId=submission.claim_id,
                    metricCode=submission.metric_code,
                    value=submission.value,
                    periodBasis=(
                        metric.period_basis
                        if metric is not None
                        else submission.current_period or "未冻结指标口径"
                    ),
                    comparison=submission.comparison,
                    managementQuestion=management_question,
                    currentPeriod=current_period,
                    comparisonPeriod=comparison_period,
                    comparisonType=comparison_type,
                    citationIds=tuple(citation_ids),
                    chartIds=chart_ids,
                    comparability=comparability,
                    conclusionType=submission.conclusion_type,
                    aggregationGrain=submission.aggregation_grain,
                    entityGrain=submission.entity_grain,
                )
            except ValidationError as error:
                warnings.append(
                    {
                        "code": "report_section_claim_invalid",
                        "message": "章节 claim 归一化后仍不满足结构约束，已省略该 claim。",
                        "details": {
                            "claimId": submission.claim_id,
                            "errors": error.errors(
                                include_url=False,
                                include_context=False,
                                include_input=False,
                            ),
                        },
                    }
                )
                continue
            normalized.append(normalized_claim)
        return tuple(normalized), tuple(warnings)

    @staticmethod
    def _require_analysis_rework_constraints(
        *,
        contract: Mapping[str, Any],
        work_item: SectionWorkItem,
        analysis_ids: tuple[str, ...],
    ) -> None:
        raw_constraints = contract.get("analysisReworkConstraints")
        evidence_by_id = {item.analysis_id: item for item in work_item.evidence}
        if not isinstance(raw_constraints, Mapping) or set(raw_constraints) != set(
            work_item.analysis_ids
        ):
            raise ReportingError(
                "report_analysis_rework_invalid",
                "返工请求缺少当前 SectionWorkItem 的冻结补算约束。",
            )
        for analysis_id in analysis_ids:
            constraint = raw_constraints.get(analysis_id)
            evidence = evidence_by_id.get(analysis_id)
            if not isinstance(constraint, Mapping) or evidence is None:
                raise ReportingError(
                    "report_analysis_rework_invalid",
                    "返工请求没有绑定当前冻结 analysis。",
                )
            dataset_ids = constraint.get("datasetIds")
            periods = constraint.get("periods")
            metrics = constraint.get("metrics")
            profile_datasets = constraint.get("profileDatasets")
            plan_hash = constraint.get("planHash")
            if (
                not isinstance(dataset_ids, list)
                or not dataset_ids
                or any(not isinstance(item, str) or not item for item in dataset_ids)
                or len(dataset_ids) != len(set(dataset_ids))
                or set(dataset_ids) != set(evidence.dataset_ids)
                or not isinstance(periods, list)
                or any(not isinstance(item, str) for item in periods)
                or not isinstance(metrics, list)
                or any(not isinstance(item, str) for item in metrics)
                or not isinstance(profile_datasets, list)
                or not isinstance(plan_hash, str)
                or len(plan_hash) != 64
                or any(character not in "0123456789abcdef" for character in plan_hash)
            ):
                raise ReportingError(
                    "report_analysis_rework_invalid",
                    "返工请求与冻结 Dataset、期间或指标约束不一致。",
                )
            rows_by_dataset: dict[str, int] = {}
            for profile in profile_datasets:
                if not isinstance(profile, Mapping):
                    raise ReportingError(
                        "report_analysis_rework_invalid",
                        "返工请求缺少受信 Profile Dataset 回执。",
                    )
                dataset_id = profile.get("datasetId")
                row_count = profile.get("rowCount")
                snapshot_hash = profile.get("profileSnapshotHash")
                if (
                    not isinstance(dataset_id, str)
                    or dataset_id in rows_by_dataset
                    or isinstance(row_count, bool)
                    or not isinstance(row_count, int)
                    or row_count < 0
                    or not isinstance(snapshot_hash, str)
                    or len(snapshot_hash) != 64
                    or any(character not in "0123456789abcdef" for character in snapshot_hash)
                ):
                    raise ReportingError(
                        "report_analysis_rework_invalid",
                        "返工请求的 Profile Dataset 回执无效。",
                    )
                rows_by_dataset[dataset_id] = row_count
            if set(rows_by_dataset) != set(dataset_ids):
                raise ReportingError(
                    "report_analysis_rework_invalid",
                    "返工请求没有精确绑定当前 analysis 的全部 Profile Dataset。",
                )
            if all(rows_by_dataset[dataset_id] == 0 for dataset_id in dataset_ids):
                raise ReportingError(
                    "report_analysis_rework_unresolvable",
                    "当前 analysis 绑定的 Dataset 均为零行，重复补算不能产生新证据。",
                )

    async def _section_work_item(
        self,
        *,
        scope: Any,
        contract: dict[str, Any],
    ) -> SectionWorkItem:
        inline = contract.get("sectionWorkItem")
        if isinstance(inline, dict):
            return SectionWorkItem.model_validate(inline)
        payload = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=contract.get("sectionWorkItemFile"),
            identity_code="report_section_work_item_changed",
            structure_code="report_section_work_item_invalid",
        )
        return SectionWorkItem.model_validate(payload)

    async def _section_evidence_read_rejection(
        self,
        *,
        scope: Any,
        path: Any,
    ) -> dict[str, Any] | None:
        try:
            if self._active_reporting_phase(scope) != "section":
                return None
            _parameters, contract = self._phase_parameters(scope, "section")
            work_item = await self._section_work_item(scope=scope, contract=contract)
            normalized_path = WorkspaceService.normalize_path(path, allow_root=False)[0]
            allowed_paths = {
                evidence_file.path
                for evidence in work_item.evidence
                for evidence_file in evidence.evidence_files
            }
            if normalized_path in allowed_paths:
                return None
            # 章节 run 的事实边界就是当前 WorkItem 冻结的 evidenceFiles。即使模型猜到
            # 其他章节或分析上下文的真实路径，也不能把那些内容重新带入当前章节历史。
            return self._failure(
                ReportingError(
                    "report_section_evidence_path_forbidden",
                    "section phase 只能读取当前 SectionWorkItem 授权的 evidence 文件。",
                ),
                retryable=False,
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)

    async def _render_isolated_section(
        self,
        *,
        scope: Any,
        section_code: str,
        blocks: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        state: dict[str, Any] | None,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        parameters, contract = self._phase_parameters(scope, "section")
        output_path = parameters.get("sectionOutputPath")
        work_item = await self._section_work_item(scope=scope, contract=contract)
        if not isinstance(output_path, str) or section_code != work_item.section_code:
            raise ReportingError(
                "report_section_order_invalid", "当前 Task 只能提交 SectionWorkItem 指定章节。"
            )
        # 章节一旦签发完成就可能被 durable checkpoint 直接恢复，因此必须在写文件和
        # complete_section 之前拒绝服务端保留标记。模型仍可在当前 section run 内根据
        # 明确回执重试，只通过 chartIds 登记图表。
        parsed_blocks = tuple(ReportDraftBlock.model_validate(item) for item in blocks)
        validate_report_draft_blocks(parsed_blocks)
        normalized_claims, claim_warnings = self._normalize_section_claims(
            section_code=section_code,
            claims=claims,
            work_item=work_item,
        )
        referenced_claim_ids = {claim_id for block in parsed_blocks for claim_id in block.claim_ids}
        normalized_claims = tuple(
            claim for claim in normalized_claims if claim.claim_id in referenced_claim_ids
        )
        normalized_claim_ids = {claim.claim_id for claim in normalized_claims}
        normalized_blocks: list[ReportDraftBlock] = []
        warning_items = list(claim_warnings)
        for block in parsed_blocks:
            unknown_claim_ids = set(block.claim_ids) - normalized_claim_ids
            if unknown_claim_ids:
                warning_items.append(
                    {
                        "code": "report_section_block_claim_unknown",
                        "message": "正文 block 的无效 claim 引用已移除。",
                        "details": {
                            "sectionCode": section_code,
                            "blockId": block.block_id,
                            "unknownClaimIds": sorted(unknown_claim_ids),
                        },
                    }
                )
            normalized_blocks.append(
                block.model_copy(
                    update={
                        "claim_ids": tuple(
                            claim_id
                            for claim_id in block.claim_ids
                            if claim_id in normalized_claim_ids
                        )
                    }
                )
            )
        artifact_version = (
            "2"
            if normalized_claims and all(block.claim_ids for block in normalized_blocks)
            else "1"
        )
        artifact = SectionArtifact.model_validate(
            {
                "version": artifact_version,
                "sectionCode": section_code,
                "blocks": normalized_blocks,
                "claims": normalized_claims,
                "warnings": warning_items[-500:],
            }
        )
        known_citations = {item.citation_id for item in work_item.citations}
        known_charts = {item.chart_id for item in work_item.charts}
        metrics_by_code = {item.code: item for item in work_item.metric_definitions}
        charts_by_id = {item.chart_id: item for item in work_item.charts}
        citation_datasets = {item.citation_id: item.dataset_id for item in work_item.citations}
        management_questions = {
            item.question for item in getattr(work_item, "management_question_catalog", ())
        }
        reference_claim_ids = {
            claim.claim_id for claim in artifact.claims if claim.comparability == "reference_only"
        }
        normalized_reference_blocks = []
        for block in artifact.blocks:
            markdown = block.markdown
            if reference_claim_ids.intersection(block.claim_ids) and "参考" not in markdown:
                markdown = f"{markdown}\n\n> 注：相关比较仅作参考性对比。"
            normalized_reference_blocks.append(block.model_copy(update={"markdown": markdown}))
        artifact = artifact.model_copy(update={"blocks": tuple(normalized_reference_blocks)})
        semantic_conflicts: list[dict[str, Any]] = []
        for claim in artifact.claims:
            metric = metrics_by_code.get(claim.metric_code)
            if metric is None:
                semantic_conflicts.append(
                    {
                        "code": "report_section_claim_metric_unknown",
                        "sectionCode": section_code,
                        "claimId": claim.claim_id,
                        "metricCode": claim.metric_code,
                        "expectedMetricCodes": sorted(metrics_by_code),
                    }
                )
            elif claim.period_basis != metric.period_basis:
                semantic_conflicts.append(
                    {
                        "code": "report_period_basis_conflict",
                        "sectionCode": section_code,
                        "claimId": claim.claim_id,
                        "metricCode": claim.metric_code,
                        "conflictType": "period_basis",
                        "expectedPeriodBasis": metric.period_basis,
                        "actualPeriodBasis": claim.period_basis,
                    }
                )
            if claim.management_question not in management_questions:
                semantic_conflicts.append(
                    {
                        "code": "report_section_claim_brief_conflict",
                        "sectionCode": section_code,
                        "claimId": claim.claim_id,
                        "conflictType": "management_question",
                        "expectedManagementQuestions": sorted(management_questions),
                        "actualManagementQuestion": claim.management_question,
                    }
                )
            claim_datasets = {citation_datasets[citation_id] for citation_id in claim.citation_ids}
            for chart_id in claim.chart_ids:
                chart = charts_by_id[chart_id]
                # 每类冲突都返回冻结值和模型提交值，模型可据此修正单个字段；不能只给
                # 一个复合布尔结果，否则 chart citation/期间冲突会反复消耗同一 run。
                chart_details = {
                    "sectionCode": section_code,
                    "claimId": claim.claim_id,
                    "chartId": chart_id,
                }
                if claim.metric_code not in chart.metric_codes:
                    semantic_conflicts.append(
                        {
                            "code": "report_section_claim_chart_conflict",
                            **chart_details,
                            "conflictType": "metric_code",
                            "expectedMetricCodes": list(chart.metric_codes),
                            "actualMetricCode": claim.metric_code,
                        }
                    )
                if set(chart.citation_ids) - set(claim.citation_ids):
                    semantic_conflicts.append(
                        {
                            "code": "report_section_claim_chart_conflict",
                            **chart_details,
                            "conflictType": "citation_ids",
                            "expectedCitationIds": list(chart.citation_ids),
                            "actualCitationIds": list(claim.citation_ids),
                        }
                    )
                if chart.source_dataset_id not in claim_datasets:
                    semantic_conflicts.append(
                        {
                            "code": "report_section_claim_chart_conflict",
                            **chart_details,
                            "conflictType": "source_dataset_id",
                            "expectedSourceDatasetId": chart.source_dataset_id,
                            "actualCitationDatasetIds": sorted(claim_datasets),
                        }
                    )
                if chart.current_period != claim.current_period:
                    semantic_conflicts.append(
                        {
                            "code": "report_section_claim_chart_conflict",
                            **chart_details,
                            "conflictType": "current_period",
                            "expectedCurrentPeriod": chart.current_period,
                            "actualCurrentPeriod": claim.current_period,
                        }
                    )
                if chart.comparison_period != claim.comparison_period:
                    semantic_conflicts.append(
                        {
                            "code": "report_section_claim_chart_conflict",
                            **chart_details,
                            "conflictType": "comparison_period",
                            "expectedComparisonPeriod": chart.comparison_period,
                            "actualComparisonPeriod": claim.comparison_period,
                        }
                    )
                if chart.comparison_type != claim.comparison_type:
                    semantic_conflicts.append(
                        {
                            "code": "report_section_claim_chart_conflict",
                            **chart_details,
                            "conflictType": "comparison_type",
                            "expectedComparisonType": chart.comparison_type,
                            "actualComparisonType": claim.comparison_type,
                        }
                    )
                if (
                    chart.comparability == "reference_only"
                    and claim.comparability != "reference_only"
                ):
                    semantic_conflicts.append(
                        {
                            "code": "report_cross_source_inference_unsupported",
                            **chart_details,
                            "conflictType": "comparability",
                            "expectedComparability": "reference_only",
                            "actualComparability": claim.comparability,
                        }
                    )
            if claim.comparability == "reference_only":
                claim_blocks = [
                    block for block in artifact.blocks if claim.claim_id in block.claim_ids
                ]
                if not claim_blocks or any("参考" not in block.markdown for block in claim_blocks):
                    semantic_conflicts.append(
                        {
                            "code": "report_cross_source_inference_unsupported",
                            "sectionCode": section_code,
                            "claimId": claim.claim_id,
                            "conflictType": "reference_marker",
                            "expectedMarker": "参考",
                            "actualMarker": None,
                        }
                    )
        if semantic_conflicts:
            messages = {
                "report_section_claim_metric_unknown": "章节 claim 引用了未冻结指标。",
                "report_period_basis_conflict": "章节 claim 的期间口径与冻结指标不一致。",
                "report_section_claim_brief_conflict": "章节 claim 未绑定 ReportBrief 的管理问题。",
                "report_section_claim_chart_conflict": "章节 claim 与冻结图表的指标、来源或期间语义不一致。",
                "report_cross_source_inference_unsupported": "reference_only claim 的正文必须明确标记为参考。",
            }
            warning_items = list(artifact.warnings)
            warning_items.extend(
                {
                    "code": str(conflict["code"]),
                    "message": messages[str(conflict["code"])],
                    "details": {key: value for key, value in conflict.items() if key != "code"},
                }
                for conflict in semantic_conflicts
            )
            artifact = artifact.model_copy(update={"warnings": tuple(warning_items[-500:])})
        referenced_citations = {
            citation_id for block in artifact.blocks for citation_id in block.citation_ids
        }
        if referenced_citations - known_citations:
            raise ReportingError(
                "report_section_citation_unknown", "当前章节引用了 SectionWorkItem 外的 citation。"
            )
        referenced_charts = {chart_id for block in artifact.blocks for chart_id in block.chart_ids}
        if referenced_charts - known_charts:
            raise ReportingError(
                "report_section_chart_unknown", "当前章节引用了 SectionWorkItem 外的 chart。"
            )
        normalized_blocks = []
        for block in artifact.blocks:
            bound_citations = list(block.citation_ids)
            for chart_id in block.chart_ids:
                chart = charts_by_id[chart_id]
                unknown_chart_citations = set(chart.citation_ids) - known_citations
                if unknown_chart_citations:
                    raise ReportingError(
                        "report_section_chart_citation_unknown",
                        f"图表 {chart_id} 引用了当前章节外的 citation。",
                        details={
                            "sectionCode": section_code,
                            "blockId": block.block_id,
                            "chartId": chart_id,
                            "unknownCitationIds": sorted(unknown_chart_citations),
                        },
                    )
                for citation_id in chart.citation_ids:
                    if citation_id not in bound_citations:
                        bound_citations.append(citation_id)
            normalized_blocks.append(
                block.model_copy(update={"citation_ids": tuple(bound_citations)})
            )
        artifact = artifact.model_copy(update={"blocks": tuple(normalized_blocks)})
        referenced_citations = {
            citation_id for block in artifact.blocks for citation_id in block.citation_ids
        }
        if known_citations - referenced_citations:
            raise ReportingError(
                "report_section_citation_missing", "当前章节没有覆盖全部相关 evidence citation。"
            )
        phase_state = state.get(REPORT_PHASE_OUTPUT_STATE_KEY) if isinstance(state, dict) else None
        serialized = artifact.model_dump(mode="json", by_alias=True)
        if isinstance(phase_state, dict):
            if phase_state.get("phase") != "section" or phase_state.get("payload") != serialized:
                raise ReportingError(
                    "report_section_already_submitted", "当前独立章节 run 已提交，不能替换正文。"
                )
            identity = FileIdentity.model_validate(phase_state.get("artifactFile")).model_dump(
                mode="json", by_alias=True
            )
        else:
            identity = await self._write_phase_json(
                scope=scope,
                path=output_path,
                payload=serialized,
                run_context=run_context,
            )
            if state is not None:
                state[REPORT_PHASE_OUTPUT_STATE_KEY] = {
                    "phase": "section",
                    "payload": serialized,
                    "artifactFile": identity,
                }
        return await self._finish_phase_task(
            scope=scope,
            phase="section",
            identity=identity,
            summary=f"章节 {section_code} 已按冻结证据完成。",
            state=state,
            run_context=run_context,
            extra={"sectionCode": section_code},
        )

    async def request_analysis_rework(
        self,
        analysisIds: list[str],
        reason: str,
        missingEvidence: list[str],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
            parameters, contract = self._phase_parameters(scope, "section")
            output_path = parameters.get("reworkRequestPath")
            work_item = await self._section_work_item(scope=scope, contract=contract)
            requested_analysis_ids = tuple(analysisIds)
            if (
                not isinstance(output_path, str)
                or not requested_analysis_ids
                or len(requested_analysis_ids) != len(set(requested_analysis_ids))
                or not set(requested_analysis_ids).issubset(work_item.analysis_ids)
            ):
                raise ReportingError(
                    "report_analysis_rework_invalid",
                    "返工请求只能引用当前 SectionWorkItem 的 analysisIds。",
                )
            self._require_analysis_rework_constraints(
                contract=contract,
                work_item=work_item,
                analysis_ids=requested_analysis_ids,
            )
            request = AnalysisReworkRequest(
                sectionCode=work_item.section_code,
                analysisIds=requested_analysis_ids,
                reason=reason,
                missingEvidence=tuple(missingEvidence),
            )
            serialized = request.model_dump(mode="json", by_alias=True)
            phase_state = (
                state.get(REPORT_PHASE_OUTPUT_STATE_KEY) if isinstance(state, dict) else None
            )
            if isinstance(phase_state, dict):
                if (
                    phase_state.get("phase") != "analysis_rework"
                    or phase_state.get("payload") != serialized
                ):
                    raise ReportingError(
                        "report_section_already_submitted",
                        "当前章节 run 已产生阶段产物。",
                    )
                identity = FileIdentity.model_validate(phase_state.get("artifactFile")).model_dump(
                    mode="json", by_alias=True
                )
            else:
                identity = await self._write_phase_json(
                    scope=scope,
                    path=output_path,
                    payload=serialized,
                    run_context=run_context,
                )
                if state is not None:
                    state[REPORT_PHASE_OUTPUT_STATE_KEY] = {
                        "phase": "analysis_rework",
                        "payload": serialized,
                        "artifactFile": identity,
                    }
            return await self._finish_phase_task(
                scope=scope,
                phase="analysis_rework",
                identity=identity,
                summary=f"章节 {work_item.section_code} 已提交分析补证请求。",
                state=state,
                run_context=run_context,
                extra={"sectionCode": work_item.section_code},
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            result = self._failure(error)
            if (
                isinstance(error, ReportingError)
                and error.code == "report_analysis_rework_unresolvable"
            ):
                result["requiredActions"] = [
                    "停止重复补算；基于冻结零行事实提交明确披露数据限制的 v2 claim 和正文。"
                ]
            return result

    @staticmethod
    def _chart_output_root(contract: Mapping[str, Any]) -> str:
        workspace = contract.get("visualizationWorkspace")
        raw_root = workspace.get("chartOutputRoot") if isinstance(workspace, Mapping) else None
        try:
            return WorkspaceService.normalize_path(raw_root, allow_root=False)[0]
        except (TypeError, WorkspaceError) as error:
            raise ReportingError(
                "report_phase_contract_invalid",
                "visualization chartOutputRoot 无效。",
            ) from error

    @staticmethod
    def _section_chart_draft_catalog(
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """读取 durable 章节图表草案;状态损坏或含重复身份时失败关闭,不猜测。"""

        raw_sections = payload.get("visualizationSections", {})
        if not isinstance(raw_sections, Mapping):
            raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
        charts_by_id: dict[str, dict[str, Any]] = {}
        files_by_path: dict[str, dict[str, Any]] = {}
        for section_code, section_draft in raw_sections.items():
            if not isinstance(section_code, str) or not isinstance(section_draft, Mapping):
                raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
            raw_charts = section_draft.get("charts", ())
            raw_files = section_draft.get("files", ())
            if not isinstance(raw_charts, list) or not isinstance(raw_files, list):
                raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
            for chart in raw_charts:
                if not isinstance(chart, Mapping) or not isinstance(chart.get("chartId"), str):
                    raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
                if chart["chartId"] in charts_by_id:
                    raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
                charts_by_id[chart["chartId"]] = dict(chart)
            for file in raw_files:
                if not isinstance(file, Mapping) or not isinstance(file.get("path"), str):
                    raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
                if file["path"] in files_by_path:
                    raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
                files_by_path[file["path"]] = dict(file)
        return charts_by_id, files_by_path

    @staticmethod
    def _require_chart_output_path(path: str, output_root: str) -> str:
        try:
            normalized = WorkspaceService.normalize_path(path, allow_root=False)[0]
        except (TypeError, WorkspaceError) as error:
            raise ReportingError("report_chart_source_invalid", "图表源路径无效。") from error
        if not normalized.startswith(f"{output_root}/"):
            raise ReportingError(
                "report_chart_source_path_forbidden",
                "图表只能读取当前 visualization Task 的签发输出目录。",
            )
        return normalized

    async def _inspect_chart_file(
        self,
        *,
        thread_id: str,
        path: str,
    ) -> dict[str, Any]:
        source_path, remote = self.kernel.service.normalize_path(path, allow_root=False)
        async with self.kernel.service._async_client() as client:
            sandbox = await self.kernel.service._asandbox_for(client, thread_id)
            try:
                await self.kernel.service._avalidate_existing_path(sandbox, source_path)
            except WorkspaceError as error:
                # 图表文件未生成(SKIP)时给出可恢复的字段级回执:模型移除该
                # 图或先生成再提交。不得让 WorkspaceError 穿透为 run 级失败,
                # 否则 error continuation 会注入全量任务上下文并滚入
                # tool_no_progress 8 连败终态(见 2026-08-31 真实运行分析)。
                raise ReportingError(
                    "report_chart_file_missing",
                    "图表源文件不存在;未生成的图表不得提交登记。",
                    details={"sourcePath": source_path},
                ) from error
            info = await self.kernel.service._ainfo(sandbox, remote)
            if not self.kernel.service._is_regular_file(info):
                raise ReportingError("report_chart_source_invalid", "图表源路径必须指向普通文件。")
            size = int(getattr(info, "size", 0) or 0)
            if not 0 < size <= MAX_REPORT_CHART_BYTES:
                raise ReportingError(
                    "report_chart_source_invalid", "单张图表必须大于 0 且不超过 10 MiB。"
                )
            content = await self.kernel.service._adownload_file(
                sandbox, remote, MAX_REPORT_CHART_BYTES
            )
        digest = hashlib.sha256(content).hexdigest()
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.load()
                image_format = str(image.format or "").upper()
                width, height = image.size
                colors = image.convert("RGBA").getcolors(maxcolors=2)
        except (UnidentifiedImageError, OSError) as error:
            raise ReportingError(
                "report_chart_source_invalid", "图表源文件无法解码或图片签名无效。"
            ) from error
        suffix = PurePosixPath(source_path).suffix.lower()
        if image_format == "PNG" and suffix == ".png":
            media_type = "image/png"
            extension = ".png"
        elif image_format == "JPEG" and suffix in {".jpg", ".jpeg"}:
            media_type = "image/jpeg"
            extension = ".jpg"
        else:
            raise ReportingError(
                "report_chart_source_invalid", "图表仅允许签名与扩展名一致的 PNG 或 JPEG。"
            )
        if width < 1 or height < 1 or (colors is not None and len(colors) <= 1):
            raise ReportingError("report_chart_blank", "图表图片完全空白，不能登记。")
        return {
            "sourcePath": source_path,
            "size": len(content),
            "sha256": digest,
            "format": image_format,
            "mediaType": media_type,
            "extension": extension,
            "width": width,
            "height": height,
        }

    async def _inspect_chart(
        self,
        *,
        thread_id: str,
        registration: ReportChartRegistration,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        file_identity = await self._inspect_chart_file(
            thread_id=thread_id,
            path=registration.source_path,
        )
        width = int(file_identity["width"])
        height = int(file_identity["height"])
        warnings: list[dict[str, Any]] = []
        if width < MIN_REPORT_CHART_WIDTH or height < MIN_REPORT_CHART_HEIGHT:
            warnings.append(
                {
                    "code": "chart_low_resolution",
                    "chartId": registration.chart_id,
                    "width": width,
                    "height": height,
                    "minimumWidth": MIN_REPORT_CHART_WIDTH,
                    "minimumHeight": MIN_REPORT_CHART_HEIGHT,
                    "message": "图表尺寸偏低，仅作为非阻断质量告警。",
                }
            )
        raw_effective_dpi = width / REPORT_BODY_WIDTH_INCHES
        if raw_effective_dpi < MIN_REPORT_CHART_EFFECTIVE_DPI:
            warnings.append(
                {
                    "code": "chart_low_effective_dpi",
                    "chartId": registration.chart_id,
                    "width": width,
                    "height": height,
                    "effectiveDpi": round(raw_effective_dpi, 1),
                    "minimumDpi": MIN_REPORT_CHART_EFFECTIVE_DPI,
                    "message": "按 A4 正文全宽估算的有效分辨率偏低，仅作为非阻断质量告警。",
                }
            )
        ratio = width / height
        if ratio > 4 or ratio < 0.25:
            warnings.append(
                {
                    "code": "chart_extreme_aspect_ratio",
                    "chartId": registration.chart_id,
                    "width": width,
                    "height": height,
                    "message": "图表宽高比极端，已进入发布质量审核。",
                }
            )
        return (
            {
                **registration.model_dump(mode="json", by_alias=True),
                **file_identity,
            },
            warnings,
        )

    async def inspect_chart(
        self,
        path: str,
        detail: str = "high",
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        try:
            scope = await self.kernel.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset({"analysis"}),
                tool_name="inspect_chart",
                run_context=run_context,
                task_kinds=frozenset({"visualization_section"}),
            )
            if self._active_reporting_task_kind(scope) != "visualization_section":
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "inspect_chart 只允许 visualization_section Task 调用。",
                )
            if detail not in {"high", "original"}:
                raise ReportingError("report_chart_inspection_invalid", "图片 detail 无效。")
            _parameters, contract = self._phase_parameters(scope, "analysis")
            if contract.get("visualInspectionMode", "vision") != "vision":
                raise ReportingError(
                    "report_phase_tool_forbidden",
                    "deterministic 图表检查模式不允许调用 inspect_chart。",
                )
            output_root = self._chart_output_root(contract)
            source_path = self._require_chart_output_path(path, output_root)
            reviewer = self._vision_reviewer
            if reviewer is None:
                raise WorkspaceError("当前 Reporting Worker 未启用图片视觉审查。")
            identity = await self._inspect_chart_file(thread_id=scope.thread_id, path=source_path)
            receipt = ChartVisualInspectionReceipt.model_validate(
                await reviewer.review(scope.thread_id, source_path, detail=detail)
            )
            # 文件在像素检查和模型审查之间发生变化时，两份哈希会不一致。此时任何一份
            # 视觉结论都不能证明当前候选图表，必须失败关闭并要求重新检查。
            if receipt.sha256 != identity["sha256"]:
                raise ReportingError(
                    "report_chart_inspection_changed",
                    "图表在视觉审查期间发生变化，请重新检查最终文件。",
                )
            await self._apply_durable(
                scope,
                name="record_chart_inspection",
                payload={"receipt": receipt.model_dump(mode="json", by_alias=True)},
                command_id=(
                    f"chart-inspection:{identity['sha256']}:"
                    f"{_stable_digest(receipt.model_dump(mode='json', by_alias=True))}"
                ),
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)
        return {
            "ok": True,
            "status": "reviewed",
            "receipt": receipt.model_dump(mode="json", by_alias=True),
        }

    async def register_report_charts(
        self,
        charts: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        try:
            scope = await self.kernel.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset({"analysis"}),
                tool_name="register_report_charts",
                run_context=run_context,
                task_kinds=frozenset({"visualization_finalize"}),
            )
            if self._active_reporting_task_kind(scope) != "visualization_finalize":
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "register_report_charts 只允许 visualization_finalize Task 调用。",
                )
            await self._ensure_visualization_terminal_settled(scope)
            state = self._session_state(run_context)
            dependencies = (
                run_context.dependencies
                if run_context is not None and isinstance(run_context.dependencies, Mapping)
                else {}
            )
            task_binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
            external_run_id = (
                task_binding.get("externalRunId") if isinstance(task_binding, Mapping) else None
            )
            task_identity = (
                f"{external_run_id or ''}:{run_context.run_id if run_context is not None else ''}"
            )
            pending = (
                state.get(REPORTING_VISUALIZATION_SCRIPT_FAILURE_PENDING_STATE_KEY)
                if isinstance(state, Mapping)
                else None
            )
            pending_failure = pending.get(task_identity) if isinstance(pending, Mapping) else None
            if pending_failure is None and isinstance(external_run_id, str) and external_run_id:
                prefix = f"{external_run_id}:"
                for key, value in (
                    reversed(tuple(pending.items())) if isinstance(pending, Mapping) else ()
                ):
                    if key == external_run_id or key.startswith(prefix):
                        pending_failure = value
                        break
            if (
                isinstance(pending_failure, Mapping)
                and pending_failure.get("lastScriptFailed") is True
            ):
                raise ReportingError(
                    "report_visualization_script_failed",
                    "最近一次可视化脚本执行包含失败项，修正脚本并重新执行成功后才能登记图表。",
                    details={
                        "diagnostics": list(pending_failure.get("diagnostics", ()))[:20],
                    },
                )
            _parameters, phase_contract = self._phase_parameters(scope, "analysis")
            output_root = self._chart_output_root(phase_contract)
            visual_inspection_mode = phase_contract.get("visualInspectionMode", "vision")
            if visual_inspection_mode not in {"vision", "deterministic"}:
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "Analysis Task 图表检查模式无效。",
                )
            raw_citation_ids = phase_contract.get("citationIds")
            if (
                not isinstance(raw_citation_ids, list)
                or len(raw_citation_ids) != len(set(raw_citation_ids))
                or any(not isinstance(item, str) or not item for item in raw_citation_ids)
            ):
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "Analysis Task citation 注册表无效。",
                )
            citation_ids = tuple(raw_citation_ids)
            raw_citation_datasets = phase_contract.get("citationDatasetIds")
            if not isinstance(raw_citation_datasets, Mapping) or any(
                not isinstance(citation_id, str) or not isinstance(dataset_id, str)
                for citation_id, dataset_id in raw_citation_datasets.items()
            ):
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "Analysis Task 缺少权威 citation 注册表。",
                )
            citation_datasets = dict(raw_citation_datasets)
            if set(citation_datasets) != set(citation_ids):
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "Analysis Task citation 注册表未精确覆盖 citationIds。",
                )
            parsed = tuple(ReportChartRegistration.model_validate(item) for item in charts)
            raw_allowed_metric_codes = phase_contract.get("allowedMetricCodes")
            if raw_allowed_metric_codes is not None and (
                not isinstance(raw_allowed_metric_codes, list)
                or any(not isinstance(code, str) or not code for code in raw_allowed_metric_codes)
                or len(raw_allowed_metric_codes) != len(set(raw_allowed_metric_codes))
            ):
                raise ReportingError(
                    "report_phase_contract_invalid", "Analysis Task 指标注册表无效。"
                )
            if isinstance(raw_allowed_metric_codes, list):
                allowed_metric_codes = set(raw_allowed_metric_codes)
                unknown_metric_codes = sorted(
                    {
                        code
                        for item in parsed
                        for code in item.metric_codes
                        if code not in allowed_metric_codes
                    }
                )
                if unknown_metric_codes:
                    raise ReportingError(
                        "report_chart_metric_unknown",
                        "图表引用了当前冻结 facts 未声明的指标代码。",
                        details={"unknownMetricCodes": unknown_metric_codes},
                    )
            if len({item.chart_id for item in parsed}) != len(parsed):
                raise ReportingError(
                    "report_chart_registration_duplicate", "同一次登记的 chartId 不能重复。"
                )
            raw_retained_chart_ids = phase_contract.get("retainedChartIds", [])
            if (
                not isinstance(raw_retained_chart_ids, list)
                or len(raw_retained_chart_ids) != len(set(raw_retained_chart_ids))
                or any(not isinstance(item, str) or not item for item in raw_retained_chart_ids)
            ):
                raise ReportingError(
                    "report_phase_contract_invalid", "Analysis Task 保留图表注册表无效。"
                )
            retained_chart_ids = set(raw_retained_chart_ids)
            if retained_chart_ids & {item.chart_id for item in parsed}:
                raise ReportingError(
                    "report_chart_registration_duplicate",
                    "返工只能登记缺失图表，不得重新生成或检查保留图表。",
                    details={"retainedChartIds": sorted(retained_chart_ids)},
                )
            if any(set(item.citation_ids) - set(citation_ids) for item in parsed):
                raise ReportingError("report_chart_citation_unknown", "图表引用了未注册 citation。")
            for item in parsed:
                cited_dataset_ids = {
                    citation_datasets[citation_id] for citation_id in item.citation_ids
                }
                if item.source_dataset_id not in cited_dataset_ids:
                    raise ReportingError(
                        "report_chart_citation_dataset_mismatch",
                        "图表主 Dataset 必须至少由一个 citation 绑定。",
                        details={
                            "chartId": item.chart_id,
                            "sourceDatasetId": item.source_dataset_id,
                            "citationDatasetIds": sorted(cited_dataset_ids)[:100],
                        },
                    )
            durable = await self._durable_state(scope)
            registry = {
                item["chartId"]: item
                for item in durable.payload.get("charts", ())
                if isinstance(item, dict) and isinstance(item.get("chartId"), str)
            }
            # 章节草案消费门禁:register 只能登记 durable visualizationSections 中
            # 章节 worker 已提交的图表,且 chartId、sourcePath、全部注册元数据必须与
            # 草案逐字一致。未提交路径、篡改元数据以及被 fresh attempt 作废的旧
            # attempt 路径(草案已被新 attempt 替换)都会在落库前被确定性拒绝。
            draft_charts_by_id, draft_files_by_path = self._section_chart_draft_catalog(
                durable.payload
            )
            for registration in parsed:
                draft_chart = draft_charts_by_id.get(registration.chart_id)
                if draft_chart is None:
                    raise ReportingError(
                        "report_chart_draft_unknown",
                        "图表不在 durable 章节草案中；只能登记章节 worker 已提交的图表。",
                        details={
                            "chartId": registration.chart_id,
                            "sourcePath": registration.source_path,
                        },
                    )
                if draft_chart != registration.model_dump(mode="json", by_alias=True):
                    raise ReportingError(
                        "report_chart_draft_conflict",
                        "图表登记元数据与 durable 章节草案不一致。",
                        details={
                            "chartId": registration.chart_id,
                            "sourcePath": registration.source_path,
                        },
                    )
                if registration.source_path not in draft_files_by_path:
                    raise ReportingError(
                        "report_chart_draft_conflict",
                        "图表登记缺少 durable 章节草案的文件身份。",
                        details={
                            "chartId": registration.chart_id,
                            "sourcePath": registration.source_path,
                        },
                    )
            warnings: list[dict[str, Any]] = []
            registered: list[dict[str, Any]] = []
            inspected: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
            for registration in parsed:
                self._require_chart_output_path(registration.source_path, output_root)
                identity, chart_warnings = await self._inspect_chart(
                    thread_id=scope.thread_id,
                    registration=registration,
                )
                # 文件身份复核:登记时实际文件的 size/sha256 必须与章节提交草案时
                # 冻结的身份一致;文件在提交后被改写即拒绝,防止陈旧文件混入 manifest。
                draft_file = draft_files_by_path[identity["sourcePath"]]
                if (
                    draft_file.get("size") != identity["size"]
                    or draft_file.get("sha256") != identity["sha256"]
                ):
                    raise ReportingError(
                        "report_chart_draft_conflict",
                        "图表文件身份与 durable 章节草案不一致。",
                        details={
                            "chartId": registration.chart_id,
                            "sourcePath": identity["sourcePath"],
                        },
                    )
                if visual_inspection_mode == "deterministic":
                    parsed_receipt = ChartVisualInspectionReceipt(
                        sourcePath=identity["sourcePath"],
                        sha256=identity["sha256"],
                        inspectionMode="deterministic",
                        visualReviewStatus="not_run",
                        inspectorId="deterministic-raster-inspector-v1",
                        modelId=None,
                        reviewed=True,
                        requiresRevision=False,
                        summary="已通过确定性图片文件检查；未运行模型视觉审查。",
                        warnings=("未运行模型视觉审查。",),
                    )
                    chart_warnings.append(
                        {
                            "code": "chart_visual_review_not_run",
                            "chartId": registration.chart_id,
                            "message": "未运行模型视觉审查；图表仅通过确定性图片文件检查。",
                        }
                    )
                else:
                    raw_receipts = durable.payload.get("chartInspectionReceipts")
                    receipts = raw_receipts if isinstance(raw_receipts, list) else []
                    same_path = [
                        item
                        for item in receipts
                        if isinstance(item, Mapping)
                        and item.get("sourcePath") == identity["sourcePath"]
                    ]
                    receipt = next(
                        (item for item in same_path if item.get("sha256") == identity["sha256"]),
                        None,
                    )
                    if receipt is None:
                        code = (
                            "report_chart_inspection_changed"
                            if same_path
                            else "report_chart_inspection_missing"
                        )
                        raise ReportingError(
                            code,
                            "正式图表缺少绑定当前文件哈希的视觉检查回执。",
                        )
                    parsed_receipt = ChartVisualInspectionReceipt.model_validate(receipt)
                    has_critical_issue = any(
                        item.severity == "critical" for item in parsed_receipt.issues
                    )
                    if (
                        parsed_receipt.inspection_mode != "vision"
                        or parsed_receipt.visual_review_status != "passed"
                        or parsed_receipt.reviewed is not True
                        or parsed_receipt.requires_revision is True
                        or has_critical_issue
                    ):
                        raise ReportingError(
                            "report_chart_inspection_failed",
                            "图表视觉检查未通过，修正并重新检查后才能登记。",
                        )
                identity["visualInspectionReceipt"] = parsed_receipt.model_dump(
                    mode="json", by_alias=True
                )
                existing = registry.get(registration.chart_id)
                if isinstance(existing, dict):
                    immutable_file_keys = {
                        "sourcePath",
                        "size",
                        "sha256",
                        "format",
                        "mediaType",
                        "extension",
                        "width",
                        "height",
                    }
                    if any(existing.get(key) != identity.get(key) for key in immutable_file_keys):
                        raise ReportingError(
                            "report_chart_registration_conflict",
                            f"chartId {registration.chart_id} 已绑定不同图表身份。",
                        )
                inspected.append((identity, chart_warnings))
            registration_digest = _stable_digest([identity for identity, _ in inspected])
            await self._apply_durable(
                scope,
                name="register_charts",
                payload={"charts": [identity for identity, _ in inspected]},
                command_id=f"charts:{registration_digest}",
            )
            for identity, chart_warnings in inspected:
                warnings.extend(chart_warnings)
                registered.append(
                    {
                        "chartId": identity["chartId"],
                        "sourcePath": identity["sourcePath"],
                        "size": identity["size"],
                        "sha256": identity["sha256"],
                        "format": identity["format"],
                        "width": identity["width"],
                        "height": identity["height"],
                    }
                )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)
        return {
            "ok": True,
            "status": "completed",
            "charts": registered,
            "warnings": warnings,
            "mutation_sequence": getattr(scope.task, "mutation_sequence", 0),
        }

    async def submit_visualization_charts(
        self,
        sectionCode: str,
        charts: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """章节 worker 终态:提交该章图表草案(允许零图)并按章收口。"""
        try:
            scope = await self.kernel.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset({"analysis"}),
                tool_name="submit_visualization_charts",
                run_context=run_context,
                task_kinds=frozenset({"visualization_section"}),
            )
            _parameters, phase_contract = self._phase_parameters(scope, "analysis")
            contract_section_code = phase_contract.get("sectionCode")
            if not isinstance(contract_section_code, str) or contract_section_code != sectionCode:
                raise ReportingError(
                    "report_visualization_section_invalid",
                    "sectionCode 与当前章节 Task 契约不匹配。",
                )
            output_root = self._chart_output_root(phase_contract)
            parsed = tuple(ReportChartRegistration.model_validate(item) for item in charts)
            inspected: list[dict[str, Any]] = []
            files: list[dict[str, Any]] = []
            for registration in parsed:
                source_path = self._require_chart_output_path(registration.source_path, output_root)
                identity = await self._inspect_chart_file(
                    thread_id=scope.thread_id,
                    path=source_path,
                )
                inspected.append(registration.model_dump(mode="json", by_alias=True))
                files.append(
                    FileIdentity(
                        path=identity["sourcePath"],
                        size=identity["size"],
                        sha256=identity["sha256"],
                    ).model_dump(mode="json", by_alias=True)
                )
            digest = _stable_digest({"charts": inspected, "files": files})
            durable = await self._durable_state(scope)
            await self._apply_durable(
                scope,
                name="submit_visualization_charts",
                payload={"sectionCode": sectionCode, "charts": list(inspected), "files": files},
                command_id=f"viz-section:{durable.revision}:{sectionCode}:{digest}",
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)
        return {
            "ok": True,
            "status": "committed",
            "sectionCode": sectionCode,
            "chartCount": len(inspected),
        }

    async def render_report_section(
        self,
        sectionCode: str,
        blocks: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
            if self._active_reporting_phase(scope) != "section":
                raise ReportingError(
                    "report_phase_tool_forbidden",
                    "render_report_section 只允许 section Task 调用。",
                )
            return await self._render_isolated_section(
                scope=scope,
                section_code=sectionCode,
                blocks=blocks,
                claims=claims,
                state=state,
                run_context=run_context,
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)
