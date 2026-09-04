"""Reporting 普通章节生成与分析返工能力。"""

# mypy: disable-error-code="attr-defined"
# 运行时由 toolkit 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agno.run import RunContext
from pydantic import ValidationError

from ...workspace import WorkspaceError, WorkspaceService
from ..delivery.draft_v1 import ReportDraftBlock, validate_report_draft_blocks
from ..models import ReportingError
from ..workflow.checkpoint import (
    AnalysisReworkRequest,
    FileIdentity,
    SectionArtifact,
    SectionClaim,
    SectionClaimSubmission,
    SectionWorkItem,
)
from .phase_output import REPORT_PHASE_OUTPUT_STATE_KEY


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
                        if citation_id in known_citations and citation_id not in citation_ids:
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
        known_citations = {item.citation_id for item in work_item.citations}
        known_charts = {item.chart_id for item in work_item.charts}
        chart_citations = {item.chart_id: item.citation_ids for item in work_item.charts}
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
            unknown_citation_ids = set(block.citation_ids) - known_citations
            if unknown_citation_ids:
                warning_items.append(
                    {
                        "code": "report_section_block_citation_unknown",
                        "message": "正文 block 的未知 citation 已移除，正文内容保留。",
                        "details": {
                            "sectionCode": section_code,
                            "blockId": block.block_id,
                            "unknownCitationIds": sorted(unknown_citation_ids),
                        },
                    }
                )
            unknown_chart_ids = set(block.chart_ids) - known_charts
            if unknown_chart_ids:
                warning_items.append(
                    {
                        "code": "report_section_block_chart_unknown",
                        "message": "正文 block 的未知 chart 已移除，正文内容保留。",
                        "details": {
                            "sectionCode": section_code,
                            "blockId": block.block_id,
                            "unknownChartIds": sorted(unknown_chart_ids),
                        },
                    }
                )
            normalized_blocks.append(
                block.model_copy(
                    update={
                        "citation_ids": tuple(
                            citation_id
                            for citation_id in block.citation_ids
                            if citation_id in known_citations
                        ),
                        "chart_ids": tuple(
                            chart_id for chart_id in block.chart_ids if chart_id in known_charts
                        ),
                        "claim_ids": tuple(
                            claim_id
                            for claim_id in block.claim_ids
                            if claim_id in normalized_claim_ids
                        ),
                    }
                )
            )
        # 图表提交属于当前章节的冻结事实。模型可能只生成正文而遗漏 chartIds；此时不能
        # 让 assemble_report_markdown 静默排除已提交图片，确定性地将未引用图表绑定到首个
        # 正文块，并补齐其 citation，保证最终 Markdown/PDF 消费章节图表。
        referenced_chart_ids = {
            chart_id for block in normalized_blocks for chart_id in block.chart_ids
        }
        unreferenced_charts = tuple(
            chart for chart in work_item.charts if chart.chart_id not in referenced_chart_ids
        )
        if unreferenced_charts and normalized_blocks:
            first_block = normalized_blocks[0]
            chart_ids = list(first_block.chart_ids)
            citation_ids = list(first_block.citation_ids)
            for chart in unreferenced_charts:
                chart_ids.append(chart.chart_id)
                for citation_id in chart.citation_ids:
                    if citation_id in known_citations and citation_id not in citation_ids:
                        citation_ids.append(citation_id)
            normalized_blocks[0] = first_block.model_copy(
                update={"chart_ids": tuple(chart_ids), "citation_ids": tuple(citation_ids)}
            )
            warning_items.append(
                {
                    "code": "report_section_chart_auto_bound",
                    "message": "模型未绑定已提交图表，服务端已将其确定性绑定到首个正文块。",
                    "details": {
                        "sectionCode": section_code,
                        "chartIds": [chart.chart_id for chart in unreferenced_charts],
                    },
                }
            )
        # 未知引用可以局部丢弃，但整章必须仍保留至少一个冻结 citation 作为事实锚点。
        # 这里在 SectionArtifact 结构校验前判断，避免 claims 全部因未知 citation 被省略
        # 时落成泛化的 Pydantic 错误，向模型返回稳定且可重试的领域错误码。
        valid_block_citations = {
            citation_id for block in normalized_blocks for citation_id in block.citation_ids
        }
        valid_block_citations.update(
            citation_id
            for block in normalized_blocks
            for chart_id in block.chart_ids
            for citation_id in chart_citations[chart_id]
            if citation_id in known_citations
        )
        if not valid_block_citations:
            raise ReportingError(
                "report_section_citation_missing", "当前章节没有任何可验证 citation。"
            )
        artifact = SectionArtifact.model_validate(
            {
                "version": "1",
                "sectionCode": section_code,
                "blocks": normalized_blocks,
                "claims": normalized_claims,
                "warnings": warning_items[-500:],
            }
        )
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
                if (set(chart.citation_ids) & known_citations) - set(claim.citation_ids):
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
        normalized_blocks = []
        for block in artifact.blocks:
            bound_citations = list(block.citation_ids)
            for chart_id in block.chart_ids:
                chart = charts_by_id[chart_id]
                unknown_chart_citations = set(chart.citation_ids) - known_citations
                if unknown_chart_citations:
                    warning_items = list(artifact.warnings)
                    warning_items.append(
                        {
                            "code": "report_section_chart_citation_unknown",
                            "message": f"图表 {chart_id} 的未知 citation 已从正文绑定中移除。",
                            "details": {
                                "sectionCode": section_code,
                                "blockId": block.block_id,
                                "chartId": chart_id,
                                "unknownCitationIds": sorted(unknown_chart_citations),
                            },
                        }
                    )
                    artifact = artifact.model_copy(update={"warnings": tuple(warning_items[-500:])})
                for citation_id in chart.citation_ids:
                    if citation_id in known_citations and citation_id not in bound_citations:
                        bound_citations.append(citation_id)
            normalized_blocks.append(
                block.model_copy(update={"citation_ids": tuple(bound_citations)})
            )
        artifact = artifact.model_copy(update={"blocks": tuple(normalized_blocks)})
        referenced_citations = {
            citation_id for block in artifact.blocks for citation_id in block.citation_ids
        }
        if not referenced_citations:
            raise ReportingError(
                "report_section_citation_missing", "当前章节没有任何可验证 citation。"
            )
        missing_citations = known_citations - referenced_citations
        if missing_citations:
            warning_items = list(artifact.warnings)
            warning_items.append(
                {
                    "code": "report_section_citation_missing",
                    "message": "当前章节未覆盖部分相关 evidence citation，已保留正文并记录警告。",
                    "details": {
                        "sectionCode": section_code,
                        "missingCitationIds": sorted(missing_citations),
                    },
                }
            )
            artifact = artifact.model_copy(update={"warnings": tuple(warning_items[-500:])})
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
            scope = await self.runtime.scope(run_context)
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
    async def render_report_section(
        self,
        sectionCode: str,
        blocks: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        try:
            scope = await self.runtime.scope(run_context)
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
