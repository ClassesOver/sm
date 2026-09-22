# mypy: disable-error-code="attr-defined"
# 运行时由 facade 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。
from __future__ import annotations

from functools import partial

from .base import (
    DOMAIN_CODES,
    MAX_REPORT_INPUTS,
    REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY,
    REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY,
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_APPROVED_QUERIES_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATA_SHAPES_STATE_KEY,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_PROFILE_COVERAGE_STATE_KEY,
    REPORT_WORKFLOW_RESULT_STATE_KEY,
    AnalysisItem,
    Any,
    ApprovedQuery,
    DatasetAnalysisContext,
    DatasetHandle,
    DetailedAnalysisItem,
    DetailedAnalysisPlan,
    FileIdentity,
    Mapping,
    ProfileCoverageManifest,
    QueryRequirement,
    ReportingCommand,
    ReportingError,
    RunContext,
    SourceSchemaSnapshot,
    StepInput,
    StepOutput,
    ValidationError,
    _payload_sha256,
    _source_warnings_from_state,
    anyio,
    build_profile_coverage_manifest,
    hashlib,
    profile_csv_dataset,
    project_measure_semantics_to_query_outputs,
    time_series_diagnostics_requested,
)
from .validation import (
    _available_tables,
)

PROFILE_TRANSFER_TIMEOUT_SECONDS = 5 * 60
PROFILE_GENERATION_TIMEOUT_SECONDS = 5 * 60


async def _run_profile_job(profile_job: Any, limiter: anyio.CapacityLimiter) -> Any:
    # 串行排队不消耗当前数据集的计算预算。
    async with limiter:
        try:
            with anyio.fail_after(PROFILE_GENERATION_TIMEOUT_SECONDS):
                return await anyio.to_thread.run_sync(
                    profile_job,
                    abandon_on_cancel=True,
                    limiter=anyio.CapacityLimiter(1),
                )
        except TimeoutError as error:
            raise ReportingError(
                "report_analysis_profile_timeout", "CSV 数据集画像生成超时。"
            ) from error


class RuntimeDatasetsMixin:
    async def materialize_datasets(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        approved = tuple(
            ApprovedQuery.model_validate(item)
            for item in self._state(run_context)[REPORT_APPROVED_QUERIES_STATE_KEY]
        )
        attachments = self._envelope(run_context).file_inputs
        if len(approved) + len(attachments) > MAX_REPORT_INPUTS:
            raise ReportingError(
                "report_dataset_count_invalid", "SQL 数据集与 URL CSV 附件总数超过限制。"
            )
        adapters = {
            source.id: self._adapter(source, run_context) for source in self._sources(run_context)
        }
        try:
            handles, lineage = await self.datasets.materialize_batch(
                approved, adapters, run_context=self._tool_context(run_context)
            )
        finally:
            for adapter in adapters.values():
                await adapter.aclose()
        attachment_handles, attachment_lineage = await self.datasets.register_external_csv(
            attachments,
            run_context=self._tool_context(run_context),
        )
        handles = (*handles, *attachment_handles)
        lineage = (*lineage, *attachment_lineage)
        prepared = await self.report_tools.report_prepare_dataset(
            [item.dataset_id for item in handles], run_context=self._tool_context(run_context)
        )
        await self.report_tools.bind_page_layout(
            str(prepared["jobId"]),
            self._profile(run_context).page_layout.model_dump(mode="json", by_alias=True),
            run_context=self._tool_context(run_context),
        )
        state = self._state(run_context)
        datasets = [item.public_dict() for item in handles]
        state[REPORT_DATASET_LINEAGE_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in lineage
        ]
        state[REPORT_WORKFLOW_RESULT_STATE_KEY] = {
            "datasets": datasets,
            "jobId": prepared["jobId"],
            "revision": 0,
        }
        return StepOutput(content={"datasets": datasets, "jobId": prepared["jobId"]})

    async def prepare_analysis_context(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        """并发生成完整 Profile 文件，并只把同源模型视图保存在 Workflow state。"""
        state = self._state(run_context)
        result = self._workflow_result(state)
        handles = tuple(DatasetHandle.from_state(item) for item in result.get("datasets", ()))
        if not handles:
            raise ReportingError("report_analysis_context_unavailable", "没有可分析的数据集。")
        scope = self._scope(run_context)
        thread_id = scope["threadId"]
        run_id = str(run_context.run_id or "report")
        snapshots = self._snapshots(run_context)
        requirements = {
            item.requirement_id: item
            for item in (
                QueryRequirement.model_validate(value)
                for value in state.get(REPORT_DATA_REQUIREMENTS_STATE_KEY, ())
            )
        }
        approved_queries = {
            (item.source_id, item.requirement_id, item.query_window_id): item
            for item in (
                ApprovedQuery.model_validate(value)
                for value in state.get(REPORT_APPROVED_QUERIES_STATE_KEY, ())
            )
        }
        metric_semantics_by_dataset: dict[str, tuple[dict[str, Any], ...]] = {}
        for handle in handles:
            requirement = requirements.get(handle.requirement_id)
            if requirement is None or handle.source_type == "url_csv":
                metric_semantics_by_dataset[handle.dataset_id] = ()
                continue
            measure_field_refs = _requirement_measure_field_refs(requirement, snapshots)
            semantics = tuple(
                item
                for snapshot in snapshots
                for item in snapshot.measure_semantics
                if item.field_ref.lower() in measure_field_refs
            )
            query = approved_queries.get(
                (handle.source_id, handle.requirement_id, handle.query_window_id)
            )
            if query is None or query.sql_hash != handle.sql_hash:
                raise ReportingError(
                    "report_analysis_context_invalid",
                    "Dataset 无法绑定对应的已批准 SQL。",
                )
            # fieldRef 始终保留权威物理字段身份；datasetField 只能来自已批准
            # SQL 的列级血缘，供后续事实引擎读取别名列，禁止按列名相似度猜测。
            metric_semantics_by_dataset[handle.dataset_id] = (
                project_measure_semantics_to_query_outputs(query, semantics)
            )
        try:
            cached_contexts = {
                item.dataset_id: item
                for item in (
                    DatasetAnalysisContext.model_validate(value)
                    for value in state.get(REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY, ())
                )
            }
        except (TypeError, ValueError, ValidationError) as error:
            raise ReportingError(
                "report_analysis_context_invalid", "已保存的分析数据上下文无效。"
            ) from error
        contexts: list[DatasetAnalysisContext | None] = [None] * len(handles)
        errors: list[Exception | None] = [None] * len(handles)
        profile_limiter = anyio.CapacityLimiter(1)
        source_warning_messages = tuple(
            str(item.message)
            for item in _source_warnings_from_state(state)
            if getattr(item, "message", None)
        )
        enable_time_series_diagnostics = time_series_diagnostics_requested(
            self._envelope(run_context).report_goal
        )

        def profile_path(handle: DatasetHandle) -> str:
            return f"报表/分析计划/{run_id}/profiles/{handle.dataset_id}.profile.json"

        def cached_context(handle: DatasetHandle) -> DatasetAnalysisContext | None:
            candidate = cached_contexts.get(handle.dataset_id)
            if (
                candidate is None
                or candidate.path != handle.path
                or candidate.size != handle.size
                or candidate.sha256 != handle.sha256
                or candidate.row_count != handle.row_count
                or candidate.profile_file.path != profile_path(handle)
                or candidate.metric_semantics != metric_semantics_by_dataset[handle.dataset_id]
            ):
                return None
            return candidate

        async def prepare_one(index: int, handle: DatasetHandle) -> None:
            try:
                cached = cached_context(handle)
                if cached is not None:
                    try:
                        stored_profile = await self.workspace_service.read_limited_regular_file(
                            thread_id,
                            cached.profile_file.path,
                            max_bytes=cached.profile_file.size,
                        )
                    except Exception:
                        stored_profile = b""
                    if (
                        len(stored_profile) == cached.profile_file.size
                        and hashlib.sha256(stored_profile).hexdigest()
                        == cached.profile_file.sha256
                    ):
                        contexts[index] = cached
                        return

                content = await self.workspace_service.read_limited_regular_file(
                    thread_id,
                    handle.path,
                    max_bytes=handle.size,
                )
                if (
                    len(content) != handle.size
                    or hashlib.sha256(content).hexdigest() != handle.sha256
                ):
                    raise ReportingError("stale_dataset", "分析数据集已变化。")
                requirement = requirements.get(handle.requirement_id)
                requirement_tables = (
                    {table.table.lower() for table in requirement.tables}
                    if requirement is not None
                    else set()
                )
                profile_job = partial(
                    profile_csv_dataset,
                    content,
                    dataset_id=handle.dataset_id,
                    path=handle.path,
                    expected_sha256=handle.sha256,
                    profile_path=profile_path(handle),
                    period_fields=(
                        tuple(dict.fromkeys(table.period_column for table in requirement.tables))
                        if requirement is not None
                        else ()
                    ),
                    schema={
                        "sourceId": handle.source_id,
                        "requirementId": handle.requirement_id,
                        "tables": [
                            table.model_dump(mode="json", by_alias=True)
                            for snapshot in snapshots
                            for table in snapshot.tables
                            if table.source_id == handle.source_id
                            and (
                                not requirement_tables
                                or f"{table.database}.{table.name}".lower()
                                in requirement_tables
                                or table.name.lower() in requirement_tables
                            )
                        ],
                    },
                    organization_grain=(
                        tuple(requirement.grain_columns) if requirement is not None else ()
                    ),
                    metric_semantics=metric_semantics_by_dataset[handle.dataset_id],
                    source_warnings=source_warning_messages,
                    enable_time_series_diagnostics=enable_time_series_diagnostics,
                )
                # fg-data-profiling 内部已有列级并行；外层串行避免嵌套进程池。
                profiled = await _run_profile_job(profile_job, profile_limiter)
                self.workspace_service.validate_content(profiled.profile_content)
                with anyio.fail_after(PROFILE_TRANSFER_TIMEOUT_SECONDS):
                    await self.workspace_service.awrite_bytes(
                        thread_id,
                        profiled.context.profile_file.path,
                        profiled.profile_content,
                        overwrite=True,
                    )
                stored_profile = await self.workspace_service.read_limited_regular_file(
                    thread_id,
                    profiled.context.profile_file.path,
                    max_bytes=profiled.context.profile_file.size,
                )
                if (
                    len(stored_profile) != profiled.context.profile_file.size
                    or hashlib.sha256(stored_profile).hexdigest()
                    != profiled.context.profile_file.sha256
                ):
                    raise ReportingError(
                        "report_analysis_profile_changed",
                        "完整数据画像写入后发生变化。",
                    )
                contexts[index] = profiled.context
            except Exception as error:
                errors[index] = error

        async with anyio.create_task_group() as task_group:
            for index, handle in enumerate(handles):
                task_group.start_soon(prepare_one, index, handle)

        failure = next((item for item in errors if item is not None), None)
        if failure is not None:
            if isinstance(failure, ReportingError):
                raise failure
            raise ReportingError(
                "report_analysis_context_invalid", "CSV 数据集画像生成失败。"
            ) from failure
        completed_contexts = tuple(item for item in contexts if item is not None)
        if len(completed_contexts) != len(handles):
            raise ReportingError("report_analysis_context_invalid", "CSV 数据集画像结果不完整。")
        state[REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in completed_contexts
        ]
        try:
            coverage = build_profile_coverage_manifest(
                dataset_handles=[item.public_dict() for item in handles],
                dataset_contexts=state[REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY],
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ReportingError(
                "report_profile_coverage_invalid",
                "完整 Profile 没有精确覆盖全部授权数据集和字段。",
            ) from error
        state[REPORT_PROFILE_COVERAGE_STATE_KEY] = coverage.model_dump(mode="json", by_alias=True)
        self._assert_state_safe(state)
        return StepOutput(
            content={"datasetContexts": state[REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY]}
        )

    async def generate_detailed_analysis_plan(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        """把已批准分析范围与 Profile 索引编排成可执行计划。"""
        state = self._state(run_context)
        raw_contexts = state.get(REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY, ())
        if not raw_contexts:
            raise ReportingError("report_analysis_context_unavailable", "分析数据上下文缺失。")
        contexts = tuple(DatasetAnalysisContext.model_validate(value) for value in raw_contexts)
        try:
            profile_coverage = ProfileCoverageManifest.model_validate(
                state.get(REPORT_PROFILE_COVERAGE_STATE_KEY)
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ReportingError(
                "report_profile_coverage_invalid", "完整 Profile coverage 状态缺失或无效。"
            ) from error
        envelope = self._envelope(run_context)
        requested_domains = set(envelope.domains or DOMAIN_CODES)
        initial = tuple(
            AnalysisItem.model_validate(item)
            for item in state.get(REPORT_ANALYSIS_PLAN_STATE_KEY, ())
            if isinstance(item, dict)
        )
        if not initial:
            raise ReportingError("report_analysis_plan_invalid", "已批准分析计划缺失。")

        domains = tuple(code for code in DOMAIN_CODES if code in requested_domains)

        result = self._workflow_result(state)
        handles = tuple(DatasetHandle.from_state(item) for item in result.get("datasets", ()))
        context_by_id = {item.dataset_id: item for item in contexts}
        if (
            not handles
            or len(context_by_id) != len(contexts)
            or {item.dataset_id for item in handles} != set(context_by_id)
        ):
            raise ReportingError(
                "report_analysis_context_invalid",
                "分析数据上下文没有精确绑定本轮不可变数据集。",
            )

        profile_warnings = tuple(
            dict.fromkeys(
                warning
                for context in contexts
                for warning in (*context.source_warnings, *context.quality_warnings)
            )
        )
        context_payload = {
            "version": 1,
            "datasetIds": [item.dataset_id for item in contexts],
            "datasetContexts": [item.model_dump(mode="json", by_alias=True) for item in contexts],
            "profileCoverageManifest": profile_coverage.model_dump(mode="json", by_alias=True),
            "initialRequirements": state.get(REPORT_DATA_REQUIREMENTS_STATE_KEY, []),
            "reportGoal": envelope.report_goal,
            "analysisGoal": envelope.report_goal,
            "allowedDomains": list(domains),
            "dataShapes": state.get(REPORT_DATA_SHAPES_STATE_KEY, []),
            "warnings": list(profile_warnings),
        }
        context_path = f"报表/分析计划/{run_context.run_id}/detailed-analysis-context.json"
        context_file = await self._write_artifact_validation_context(
            self._scope(run_context)["threadId"], context_path, context_payload
        )
        state[REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY] = context_file

        analyses: list[DetailedAnalysisItem] = []
        covered_dataset_ids: set[str] = set()
        plan_warnings = list(profile_warnings)
        role_labels = {"current": "本期", "yoy": "同比", "mom": "环比"}
        for initial_item in initial:
            requirement_ids = set(initial_item.requirement_ids)
            referenced_handles = tuple(
                handle
                for handle in handles
                if handle.requirement_id in requirement_ids or handle.source_type == "url_csv"
            )
            if not referenced_handles:
                raise ReportingError(
                    "report_analysis_plan_invalid",
                    "已批准分析项没有绑定本轮不可变数据集。",
                )
            referenced_contexts = tuple(
                context_by_id[handle.dataset_id] for handle in referenced_handles
            )
            covered_dataset_ids.update(handle.dataset_id for handle in referenced_handles)

            if initial_item.domain in domains:
                domain = initial_item.domain
            elif len(domains) == 1:
                # 兼容已持久化的单领域旧计划；多领域计划禁止重新猜测归属。
                domain = domains[0]
            else:
                raise ReportingError(
                    "report_analysis_plan_invalid",
                    "多领域分析项缺少语义确定的 domain。",
                )

            field_candidates: list[str] = []
            metric_candidates: list[str] = []
            periods: list[str] = []
            for context in referenced_contexts:
                field_candidates.extend(context.organization_grain)
                if context.time_series_sort_field:
                    field_candidates.append(context.time_series_sort_field)
                field_candidates.extend(context.numeric_fields)
                field_candidates.extend(context.fields)
                semantic_metrics = [
                    str(item.get("fieldRef", "")).rsplit(".", 1)[-1]
                    for item in context.metric_semantics
                    if isinstance(item, Mapping) and item.get("fieldRef")
                ]
                metric_candidates.extend(semantic_metrics or context.numeric_fields)
                period_values = list(context.period_values)
                periods.extend(
                    period_values
                    if len(period_values) <= 24
                    else [period_values[0], period_values[-1]]
                )
            indexed_fields = tuple(dict.fromkeys(field_candidates))
            metrics = tuple(dict.fromkeys(metric_candidates))
            if len(indexed_fields) > 100:
                plan_warnings.append(
                    f"分析项 {initial_item.code} 的字段索引超过 100 个；计划保留前 100 个关键字段，完整字段仍保存在 Profile 索引中。"
                )
            if len(metrics) > 100:
                plan_warnings.append(
                    f"分析项 {initial_item.code} 的指标索引超过 100 个；计划保留前 100 个指标，完整指标仍保存在 Profile 索引中。"
                )
            comparison_basis = tuple(
                dict.fromkeys(
                    role_labels[role]
                    for handle in referenced_handles
                    for role in handle.period_roles
                )
            )
            actions = ["核验数据范围、指标口径和 Profile 告警"]
            actions.append(
                "仅当 deterministicFacts 未覆盖当前管理问题的必需事实时，"
                "从不可变 CSV 复算并保存补充 evidence"
            )
            if periods:
                actions.append("分析期间趋势、变化幅度和比较基准")
            if any(context.organization_grain for context in referenced_contexts):
                actions.append("按组织粒度下钻贡献与异常")
            if len(referenced_contexts) > 1:
                actions.append("校验跨数据集期间、粒度和口径的可比性")

            item_warnings = tuple(
                dict.fromkeys(
                    warning
                    for context in referenced_contexts
                    for warning in (*context.source_warnings, *context.quality_warnings)
                )
            )
            profile_coverages = tuple(
                coverage
                for context in referenced_contexts
                for coverage in (context.profile_model_view.get("coverage"),)
                if isinstance(coverage, Mapping)
            )
            correlation_methods = tuple(
                dict.fromkeys(
                    str(method)
                    for coverage in profile_coverages
                    for method in coverage.get("correlationMethods", ())
                    if isinstance(method, str)
                )
            )
            profile_signal = (
                "Profile 定位信号包含 "
                f"{sum(int(item.get('variableCount', 0)) for item in profile_coverages)} 个变量、"
                f"{sum(int(item.get('alertCount', 0)) for item in profile_coverages)} 条告警、"
                f"{sum(int(item.get('timeSeriesFieldCount', 0)) for item in profile_coverages)} 个时序字段"
                f"和相关性方法 {', '.join(correlation_methods) or '无'}；"
                "先检查 coverage 与 alerts，再按变量、相关性和时序 Pointer 定点读取完整 Profile。"
            )
            recommended_charts = [
                str(opportunity["label"])
                for context in referenced_contexts
                for opportunity in context.profile_model_view.get("chartOpportunities", ())
                if isinstance(opportunity, Mapping) and isinstance(opportunity.get("label"), str)
            ]
            if periods:
                recommended_charts.append("月度趋势带或同比哑铃图")
            if any(context.organization_grain for context in referenced_contexts):
                recommended_charts.append("组织贡献排名、Pareto 图或结构图")
            if len(referenced_contexts) > 1:
                recommended_charts.append("跨域散点、相关矩阵或气泡象限图")
            lowered_fields = {
                field.casefold() for context in referenced_contexts for field in context.fields
            }
            if any("budget" in field for field in lowered_fields) and any(
                "actual" in field for field in lowered_fields
            ):
                recommended_charts.append("预算与实际子弹图或偏差瀑布图")
            if all(
                any(token in field for field in lowered_fields)
                for token in ("budget", "contract", "pay")
            ):
                recommended_charts.append("预算、合同与付款转化漏斗图")
            recommended_charts = list(dict.fromkeys(recommended_charts))[:12]
            description = initial_item.description.rstrip("。？?")
            analyses.append(
                DetailedAnalysisItem(
                    analysisId=f"analysis_{len(analyses) + 1:03d}",
                    domain=domain,
                    managementQuestion=(initial_item.management_question),
                    primaryMetricFamily=initial_item.primary_metric_family,
                    datasetIds=tuple(handle.dataset_id for handle in referenced_handles),
                    fields=indexed_fields[:100],
                    metrics=metrics[:100],
                    periods=tuple(dict.fromkeys(periods)),
                    comparisonBasis=comparison_basis,
                    organizationGrain=tuple(
                        dict.fromkeys(
                            grain
                            for context in referenced_contexts
                            for grain in context.organization_grain
                        )
                    ),
                    actions=tuple(actions),
                    evidenceSummary=(
                        f"计划绑定 {len(referenced_contexts)} 个不可变数据集、"
                        f"{sum(context.row_count for context in referenced_contexts)} 行记录；"
                        f"{profile_signal}deterministicFacts 覆盖当前管理问题时直接提交；"
                        "仅在必需事实缺口时由 Reporting 从 CSV 复算并保存补充 evidence。"
                    ),
                    limitations=item_warnings[:100],
                    recommendedTables=("按期间与组织粒度汇总关键指标",),
                    recommendedCharts=tuple(recommended_charts),
                    suggestedSection=(description or domain)[:128],
                    completionConditions=(
                        "核验全部绑定数据集的路径、大小和 SHA-256",
                        "deterministicFacts 覆盖当前管理问题时立即且只调用一次 "
                        "complete_analysis_item，evidencePaths 传空数组",
                        "仅当 deterministicFacts 未覆盖当前管理问题的必需事实时，按 analysisId "
                        "从 CSV 复算并保存最小补充 evidence",
                        "正文、表格和图表只绑定已登记 citationId",
                    ),
                )
            )

        if covered_dataset_ids != set(context_by_id):
            raise ReportingError(
                "report_analysis_plan_invalid",
                "已批准分析计划没有覆盖全部授权数据集。",
            )
        unique_warnings = tuple(dict.fromkeys(plan_warnings))
        if len(unique_warnings) > 500:
            unique_warnings = unique_warnings[:499] + (
                f"另有 {len(unique_warnings) - 499} 条完整 Warning 保存在分析数据上下文中。",
            )
        plan = DetailedAnalysisPlan(
            analyses=tuple(analyses),
            datasetIds=tuple(context.dataset_id for context in contexts),
            reportGoal=envelope.report_goal,
            analysisGoal=envelope.report_goal,
            warnings=unique_warnings,
        )
        state[REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY] = plan.model_dump(mode="json", by_alias=True)
        await self._apply_durable_command(
            run_context,
            ReportingCommand(
                name="set_analysis_plan",
                commandId=f"analysis-plan:{_payload_sha256(plan.model_dump(mode='json', by_alias=True))}",
                payload={
                    "analysisIds": [item.analysis_id for item in plan.analyses],
                    "datasetIds": list(plan.dataset_ids),
                    "analysisPlans": {
                        item.analysis_id: {
                            "analysisId": item.analysis_id,
                            "domain": item.domain,
                            "step": item.management_question,
                            "primaryMetricFamily": item.primary_metric_family,
                            "datasetIds": list(item.dataset_ids),
                        }
                        for item in plan.analyses
                    },
                },
            ),
        )
        self._assert_state_safe(state)
        return StepOutput(content=plan)


def _analysis_context_payload(outline_context: Any) -> dict[str, Any]:
    if not isinstance(outline_context, Mapping):
        return {}
    context: dict[str, Any] = {}
    profile = outline_context.get("profile")
    if isinstance(profile, Mapping):
        context["profile"] = {
            key: profile[key]
            for key in (
                "profileId",
                "revision",
                "effectiveProfileHash",
                "dimensions",
                "metrics",
                "reconciliations",
            )
            if key in profile
        }
    for key in ("capabilities", "terms", "reconciliations"):
        if key in outline_context:
            context[key] = outline_context[key]
    tables = outline_context.get("tables")
    if isinstance(tables, list):
        context["observedDataFacts"] = [
            {
                key: table[key]
                for key in (
                    "sourceId",
                    "table",
                    "periodGranularity",
                    "periodRowCount",
                    "periodCoverage",
                    "missingPeriods",
                )
                if key in table
            }
            for table in tables
            if isinstance(table, Mapping)
        ]
    return context


def _profile_coverage_instruction_projection(
    manifest: ProfileCoverageManifest,
    analysis_context_file: FileIdentity,
    *,
    dataset_ids: set[str] | None = None,
) -> dict[str, Any]:
    """投影高优先级 coverage 事实；长序列和完整字段仍从受信文件定点恢复。"""

    def bounded_periods(values: tuple[str, ...]) -> tuple[list[str], bool]:
        if len(values) <= 24:
            return list(values), False
        return [*values[:12], *values[-12:]], True

    def bounded_warnings(values: tuple[str, ...]) -> tuple[list[str], bool]:
        return list(values[:10]), len(values) > 10

    datasets: list[dict[str, Any]] = []
    for item in manifest.datasets:
        if dataset_ids is not None and item.dataset_id not in dataset_ids:
            continue
        periods, periods_truncated = bounded_periods(item.period_coverage)
        source_warnings, source_warnings_truncated = bounded_warnings(item.source_warnings)
        quality_warnings, quality_warnings_truncated = bounded_warnings(item.quality_warnings)
        datasets.append(
            {
                "datasetId": item.dataset_id,
                "fieldCount": item.field_count,
                "coverageStart": item.period_coverage[0] if item.period_coverage else None,
                "coverageEnd": item.period_coverage[-1] if item.period_coverage else None,
                "coveragePeriodCount": len(item.period_coverage),
                "periodCoverage": periods,
                "periodCoverageTruncated": periods_truncated,
                "sourceWarnings": source_warnings,
                "sourceWarningsTruncated": source_warnings_truncated,
                "qualityWarnings": quality_warnings,
                "qualityWarningsTruncated": quality_warnings_truncated,
            }
        )

    return {
        "manifestFile": analysis_context_file.model_dump(mode="json", by_alias=True),
        "manifestPointer": "/profileCoverageManifest",
        "authorizedDatasetCount": len(datasets),
        "coveredDatasetCount": len(datasets),
        "datasets": datasets,
    }


def _requirement_measure_field_refs(
    requirement: QueryRequirement,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> set[str]:
    """把 Requirement 的裸指标列绑定到结构快照中的标准四段 fieldRef。"""

    available_tables = _available_tables(snapshots)
    field_refs: set[str] = set()
    for table in requirement.tables:
        table_ref = table.table.lower()
        matches = [
            model
            for (source_id, qualified), model in available_tables.items()
            if source_id == requirement.source_id
            and (qualified == table_ref or qualified.endswith(f".{table_ref}"))
        ]
        # 裸表名只能在当前 source 下唯一命中。多义时不绑定任何指标语义，避免把
        # 同名表的聚合规则混入不可变 Dataset；前置计划校验会把该歧义作为错误关闭。
        if len(matches) != 1:
            continue
        model = matches[0]
        available_columns = {column.name.lower() for column in model.columns}
        field_refs.update(
            f"{model.source_id}.{model.database}.{model.name}.{measure}".lower()
            for measure in table.measure_columns
            if measure.lower() in available_columns
        )
    return field_refs
