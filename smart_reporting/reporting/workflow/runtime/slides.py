"""原生 Agno PPT 编排；只从冻结分析证据生成页面，不运行文档成稿。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from time import monotonic
from types import SimpleNamespace
from typing import Any, Literal

from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput
from loguru import logger
from pydantic import Field

from ...contract import REPORT_DELIVERY_FORMATS, StrictModel
from ...delivery.artifacts_v1 import ArtifactFile
from ...delivery.draft_v1 import HeadingNumber, ReportDraftBlock
from ...hospital_operation.findings import FindingGraph
from ...models import ReportingError
from ...semantics.presentation import semantic_issue_message
from ...trace.contracts_v1 import ChartTraceV1, derive_resource_id
from ...trace.semantic_bindings import anchor_bound_numbers
from ...trace.subject_builder import build_claim_subject_bindings
from ..analysis_summaries import AnalysisSummarySection, build_analysis_summary_section
from ..checkpoint import (
    AnalysisArtifact,
    AnalysisEvidenceManifest,
    FileIdentity,
    ReportingCheckpoint,
)
from ..state import ReportingCommand, ReportingPhase
from .base import (
    REPORT_ARTIFACTS_STATE_KEY,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_REQUEST_CONTEXT_STATE_KEY,
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    REPORT_WORKFLOW_RESULT_STATE_KEY,
    DatasetHandle,
    DatasetLineage,
    DetailedAnalysisPlan,
    ReportingWorkflowInput,
    _frozen_outline,
    _source_warnings_from_state,
    authoritative_citations,
    parse_reporting_workflow_input,
)
from .sections import _evidence_and_computation_layers
from .slide_bindings import registered_slide_summary


class SlideContent(StrictModel):
    slide_id: str = Field(alias="slideId", min_length=1)
    title: str = Field(min_length=1)
    bullets: tuple[str, ...] = Field(min_length=1)
    finding_ids: tuple[str, ...] = Field(alias="findingIds", min_length=1)
    evidence_ids: tuple[str, ...] = Field(alias="evidenceIds", min_length=1)
    chart_ids: tuple[str, ...] = Field(default=(), alias="chartIds")
    summary_block: ReportDraftBlock | None = Field(default=None, alias='summaryBlock')


class SlideOutline(StrictModel):
    version: Literal["1"] = "1"
    title: str = Field(min_length=1)
    snapshot_hash: str = Field(alias="snapshotHash", pattern=r"^[0-9a-f]{64}$")
    slides: tuple[SlideContent, ...] = Field(min_length=1)
    analysis_summaries: tuple[AnalysisSummarySection, ...] = Field(default=(), alias='analysisSummaries', max_length=200)


def slide_summary_sources(outline, manifest):
    included, selected = set(), []
    for section in outline.sections:
        evidence = tuple(item for item in manifest.evidence
            if item.analysis_id in section.analysis_ids and item.analysis_id not in included)
        if evidence:
            selected.append((section, evidence))
            included.update(item.analysis_id for item in evidence)
    return tuple(selected)


def validate_slide_summaries(summaries, outline, manifest, view):
    expected = tuple((section.code, tuple((item.analysis_id, item.summary.strip()) for item in evidence))
        for section, evidence in slide_summary_sources(outline, manifest))
    actual = tuple((item.section_code, tuple((block.block_id, block.markdown) for block in item.blocks))
        for item in summaries)
    if actual != expected or any((item.basis_id, item.report_revision, item.period) !=
            (view.basis_id, view.report_revision, view.request.period) for item in summaries):
        raise ReportingError('report_slide_evidence_invalid', '幻灯片说明必须完整绑定本修订、章节、分析及原文。')


def build_slide_outline(
    graph: FindingGraph, manifest: AnalysisEvidenceManifest, *, title: str,
    fact_contents: Mapping[str, bytes] | None = None,
    analysis_summaries: tuple[AnalysisSummarySection, ...] = (),
) -> SlideOutline:
    """按核验发现分配页面，并把每页绑定到其自身的分析与引用。"""
    evidence = {item.analysis_id: item for item in manifest.evidence}
    seen = set()
    for summary in analysis_summaries:
        for block in summary.blocks:
            source = evidence.get(block.block_id)
            if block.block_id in seen or source is None or block.markdown != source.summary.strip():
                raise ReportingError('report_slide_evidence_invalid', '幻灯片分析说明与冻结原文不一致。')
            seen.add(block.block_id)
    if any(set(card.analysis_ids) - evidence.keys() for card in graph.findings):
        raise ReportingError("report_slide_evidence_invalid", "幻灯片发现缺少冻结证据。")
    registered_charts = tuple(getattr(manifest, "charts", ()))
    chart_owners = {}
    for chart in registered_charts:
        explicit = {item.analysis_id for item in manifest.evidence if chart.chart_id in item.chart_ids}
        possible = {
            analysis_id for card in graph.findings for analysis_id in card.analysis_ids
            if set(chart.citation_ids).intersection(card.citation_ids)
            and set(chart.metric_codes).intersection(card.metric_codes)
            and chart.source_dataset_id in evidence[analysis_id].dataset_ids
        }
        chart_owners[chart.chart_id] = explicit or (possible if len(possible) == 1 else set())
    slides = []
    for index, card in enumerate(graph.findings, 1):
        citations = tuple(dict.fromkeys(
            citation for analysis_id in card.analysis_ids for citation in evidence[analysis_id].citation_ids
        ))
        if set(card.citation_ids) - set(citations):
            raise ReportingError("report_slide_evidence_invalid", "幻灯片引用超出冻结证据范围。")
        charts = tuple(chart.chart_id for chart in registered_charts
            if chart_owners[chart.chart_id].intersection(card.analysis_ids))
        summary = registered_slide_summary(card, fact_contents)
        slides.append(SlideContent(
            slideId=f"slide_{index:03d}", title=card.title,
            bullets=(summary.markdown[2:] if summary else card.summary,
                *(semantic_issue_message(item) for item in card.limitations)), findingIds=(card.finding_id,),
            evidenceIds=(*card.analysis_ids, *card.citation_ids), chartIds=charts,
            summaryBlock=summary,
        ))
    return SlideOutline(title=title, snapshotHash=graph.snapshot_hash, slides=tuple(slides),
        analysisSummaries=analysis_summaries)


class RuntimeSlidesMixin:
    async def normalize_delivery_request(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        """先恢复耐久格式，再复用澄清；首次判断即写入 reducer，重试不再推断。"""
        state = self._state(run_context)
        durable = await self.state_repository.get(str(run_context.run_id))
        frozen = durable.payload.get("deliveryFormat") if durable is not None else None
        if frozen is not None:
            if frozen not in REPORT_DELIVERY_FORMATS:
                raise ReportingError("report_delivery_format_invalid", "冻结交付格式无效。")
            if REPORT_REQUEST_CONTEXT_STATE_KEY not in state:
                workflow_input = (
                    parse_reporting_workflow_input(step_input.input)
                    if isinstance(step_input.input, str)
                    else ReportingWorkflowInput.model_validate(step_input.input)
                )
                request = workflow_input.request()
                original_goal = getattr(request, "report_goal", None) or request.prompt
                state[REPORT_REQUEST_CONTEXT_STATE_KEY] = {
                    "originalGoal": original_goal, "feedback": [],
                }
            state[REPORT_REQUEST_CONTEXT_STATE_KEY]["deliveryFormat"] = frozen
        output = await self.normalize_report_request(step_input, run_context)
        delivery_format = state[REPORT_REQUEST_CONTEXT_STATE_KEY]["deliveryFormat"]
        await self._apply_durable_command(run_context, ReportingCommand(
            name="freeze_delivery_format", commandId=f"delivery-format:{delivery_format}",
            payload={"deliveryFormat": delivery_format},
        ))
        return output

    async def select_delivery_steps(self, step_input: StepInput, run_context: RunContext, step_choices: list[Any]):
        durable = await self.state_repository.get(str(run_context.run_id))
        delivery_format = durable.payload.get("deliveryFormat") if durable is not None else None
        if delivery_format not in REPORT_DELIVERY_FORMATS:
            raise ReportingError("report_delivery_format_invalid", "交付格式尚未冻结。")
        self._state(run_context).setdefault(REPORT_REQUEST_CONTEXT_STATE_KEY, {})["deliveryFormat"] = delivery_format
        # XLSX 沿用文档编排（章节成稿后在渲染阶段生成工作簿），仅 PPTX 走幻灯片分支。
        branch = "pptx" if delivery_format == "pptx" else "document"
        return [next(step for step in step_choices if step.name == branch)]

    async def restore_delivery_format(self, _step_input: StepInput, run_context: RunContext) -> None:
        """仅供末端恢复迁移旧运行；读取已存格式，缺字段的历史报告沿用 document。"""
        durable = await self.state_repository.get(str(run_context.run_id))
        if durable is None or durable.payload.get("deliveryFormat") is not None:
            return
        state = self._state(run_context)
        request = state.get(REPORT_REQUEST_CONTEXT_STATE_KEY, {})
        envelope = state.get(REPORT_WORKFLOW_INPUT_STATE_KEY, {})
        delivery_format = request.get("deliveryFormat") or envelope.get("deliveryFormat") or "document"
        if delivery_format not in REPORT_DELIVERY_FORMATS:
            raise ReportingError("report_delivery_format_invalid", "历史交付格式无效。")
        await self._apply_durable_command(run_context, ReportingCommand(
            name="freeze_delivery_format", commandId=f"delivery-format:{delivery_format}",
            payload={"deliveryFormat": delivery_format},
        ))

    async def _slide_checkpoint(self, run_context: RunContext, *, execution=None):
        if execution is None:
            durable = await self.state_repository.get(str(run_context.run_id))
        else:
            from ..revision_execution import require_revision_execution

            durable = await require_revision_execution(self, run_context, execution)
            if execution.requested_outputs != ('pptx',) or durable.payload.get('deliveryFormat') != 'pptx':
                raise ReportingError('report_revision_execution_mismatch', '幻灯片仅接受明确选择PPTX的新修订。')
        stored = durable.payload.get("workflowCheckpoint") if durable is not None else None
        if not isinstance(stored, Mapping):
            raise ReportingError("report_checkpoint_invalid", "PPT 缺少冻结分析检查点。")
        return durable, ReportingCheckpoint.model_validate(stored)

    async def generate_slide_outline(self, _step_input: StepInput, run_context: RunContext, *, execution=None) -> StepOutput:
        execution_options = {} if execution is None else {'execution': execution}
        durable, checkpoint = await self._slide_checkpoint(run_context, **execution_options)
        run_id = str(run_context.run_id) if execution is None else execution.execution_run_id
        if execution is not None:
            from ..revision_execution import load_revision_outline

            source_outline = await load_revision_outline(self, run_context, execution)
            if checkpoint.evidence_manifest is None or checkpoint.analysis_manifest_file is None:
                raise ReportingError('report_analysis_evidence_incomplete', '新幻灯片必须先冻结本修订的分析证据。')
            registered = durable.payload.get('artifacts', ())
            if any(file.model_dump(mode='json', by_alias=True) not in registered
                    for file in (checkpoint.analysis_manifest_file, checkpoint.finding_graph_file, checkpoint.slide_outline_file)
                    if file is not None):
                raise ReportingError('report_revision_execution_mismatch', '幻灯片只能使用本修订登记证据。')
        else:
            source_outline = _frozen_outline(self._state(run_context))
        entered_sections = False
        scope = self._scope(run_context)
        if checkpoint.finding_graph_file is None:
            raise ReportingError("report_finding_graph_unavailable", "PPT 缺少冻结发现图谱。")
        graph = await self._read_identity_model(scope["threadId"], checkpoint.finding_graph_file, FindingGraph)
        if graph.snapshot_hash != checkpoint.finding_graph_hash:
            raise ReportingError("report_checkpoint_conflict", "PPT 发现图谱快照不一致。")
        if checkpoint.evidence_manifest is None:
            state = self._state(run_context)
            plan = DetailedAnalysisPlan.model_validate(state[REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY])
            lineage = tuple(DatasetLineage.model_validate(item) for item in state[REPORT_DATASET_LINEAGE_STATE_KEY])
            if durable.phase is ReportingPhase.NARRATIVE_PLANNING:
                await self._apply_durable_command(run_context, ReportingCommand(
                    name="complete_narrative_planning", commandId=f"slide-planning-start:{checkpoint.revision}",
                ))
                entered_sections = True
            validation_context = next(
                (item for item in reversed(checkpoint.files) if item.path.endswith(".validation-context.json")), None,
            )
            if validation_context is None:
                raise ReportingError("report_checkpoint_invalid", "PPT 可视化缺少冻结校验上下文。")
            for section in _frozen_outline(state).sections:
                await self._run_visualization_section_task(section.code, context={
                    "run_context": run_context, "checkpoint": checkpoint,
                    "revision": checkpoint.revision, "sandbox_id": scope["threadId"],
                    "external_run_id": str(run_context.run_id), "thread_id": scope["threadId"],
                    "validation_context_file": validation_context,
                    "fact_files": checkpoint.deterministic_fact_files,
                    "visual_inspection_mode": "vision" if self._vision_enabled else "deterministic",
                    "visualization_deadline": monotonic() + getattr(self, "visualization_total_deadline_seconds", 600),
                    "max_charts": None,
                })
            checkpoint = await self._current_reporting_checkpoint(run_context, checkpoint)
            artifact = await self._build_reporting_artifact(
                run_context, analysis_ids=tuple(item.analysis_id for item in plan.analyses),
                detailed_plan=plan, fact_files=checkpoint.deterministic_fact_files,
                citation_bindings=authoritative_citations(lineage),
            )
            content = artifact.model_dump_json(by_alias=True).encode("utf-8")
            identity = await self._write_immutable_artifact(
                scope["threadId"], f"报表/智能分析/{run_context.run_id}/slides/revision-{checkpoint.revision}/evidence.json", content,
            )
            checkpoint = self._update_reporting_checkpoint(
                checkpoint, evidence_manifest=artifact.evidence_manifest, report_brief=artifact.report_brief,
                analysis_manifest_file=identity, files=self._merge_checkpoint_files(checkpoint.files, identity),
            )
            checkpoint = await self._persist_reporting_checkpoint(run_context, checkpoint)
        artifact = await self._read_identity_model(scope["threadId"], checkpoint.analysis_manifest_file, AnalysisArtifact)
        if (artifact.evidence_manifest != checkpoint.evidence_manifest
                or (execution is not None and artifact.report_brief != checkpoint.report_brief)):
            raise ReportingError("report_checkpoint_conflict", "PPT 冻结证据与检查点不一致。")
        fact_contents = {key: await self._read_identity_bytes(scope['threadId'], identity)
            for key, identity in checkpoint.deterministic_fact_files.items()}
        view = (await self._metric_planning_context(run_context,
            report_revision=execution.report_revision if execution is not None else 'initial')
            if getattr(self, 'report_basis_service', None) is not None else None)
        if checkpoint.slide_outline_file is not None:
            stored_outline = await self._read_identity_model(scope["threadId"], checkpoint.slide_outline_file, SlideOutline)
            summaries = stored_outline.analysis_summaries
            if view is not None:
                validate_slide_summaries(summaries, source_outline, checkpoint.evidence_manifest, view)
            outline = build_slide_outline(graph, checkpoint.evidence_manifest, title=source_outline.title,
                fact_contents=fact_contents, analysis_summaries=summaries)
            if stored_outline != outline:
                raise ReportingError("report_checkpoint_conflict", "幻灯片提纲与冻结证据不一致。")
            outline = stored_outline
        else:
            path = f"报表/智能分析/{run_id}/slides/revision-{checkpoint.revision}/outline.json"
            if not (await self.workspace_service.abatch_hash_files(scope['threadId'], [path]))[0].get('missing'):
                raise ReportingError('report_slide_outcome_unknown', '幻灯片提纲已有文件但登记未完成，需核对结果，禁止自动重跑。')
            summaries = tuple([await build_analysis_summary_section(self, run_context,
                section=section, evidence=evidence, view=view)
                for section, evidence in slide_summary_sources(source_outline, checkpoint.evidence_manifest)]) if view is not None else ()
            if view is not None:
                validate_slide_summaries(summaries, source_outline, checkpoint.evidence_manifest, view)
            outline = build_slide_outline(graph, checkpoint.evidence_manifest, title=source_outline.title,
                fact_contents=fact_contents, analysis_summaries=summaries)
            identity = await self._write_immutable_artifact(
                scope["threadId"], path,
                outline.model_dump_json(by_alias=True).encode("utf-8"),
            )
            checkpoint = self._update_reporting_checkpoint(
                checkpoint, slide_outline_file=identity, files=self._merge_checkpoint_files(checkpoint.files, identity),
            )
            await self._apply_durable_command(run_context, ReportingCommand(name='record_artifact',
                commandId=f'revision-slide-outline:{identity.sha256}',
                payload={'artifact': identity.model_dump(mode='json', by_alias=True)}), **execution_options)
            await self._persist_reporting_checkpoint(run_context, checkpoint, **execution_options)
        if not entered_sections and durable.phase is ReportingPhase.NARRATIVE_PLANNING:
            await self._apply_durable_command(run_context, ReportingCommand(
                name="complete_narrative_planning", commandId=f"slide-planning-start:{checkpoint.revision}",
            ), **execution_options)
        return StepOutput(content={"status": "completed", "slideCount": len(outline.slides)})

    async def assemble_slides(self, _step_input: StepInput, run_context: RunContext, *, execution=None) -> StepOutput:
        """将冻结页面、图片及作图数据交给现有 manifest/trace 服务归档。"""
        execution_options = {} if execution is None else {'execution': execution}
        if execution is not None:
            await self.generate_slide_outline(_step_input, run_context, execution=execution)
        _durable, checkpoint = await self._slide_checkpoint(run_context, **execution_options)
        run_id = str(run_context.run_id) if execution is None else execution.execution_run_id
        if execution is not None and checkpoint.phase == 'completed':
            result = _durable.payload.get('result', {})
            for item in (result.get('markdown'), result.get('manifest'), *result.get('charts', ())):
                await self._read_identity_bytes(execution.source_scope.workspace_key, FileIdentity.model_validate(item))
            return StepOutput(content={'status': 'completed', 'markdownPath': result['markdown']['path']})
        scope = self._scope(run_context)
        if checkpoint.slide_outline_file is None or checkpoint.evidence_manifest is None:
            raise ReportingError("report_slide_outline_missing", "PPT 缺少冻结幻灯片提纲或证据。")
        outline = await self._read_identity_model(scope["threadId"], checkpoint.slide_outline_file, SlideOutline)
        root = PurePosixPath(f"报表/智能分析/{run_id}/slides/revision-{checkpoint.revision}")
        charts = {item.chart_id: item for item in checkpoint.evidence_manifest.charts}
        chart_files = []
        trace_files = []
        chart_traces = []
        chart_destinations = {}
        for index, chart_id in enumerate(dict.fromkeys(ref for slide in outline.slides for ref in slide.chart_ids), 1):
            chart = charts[chart_id]
            image = await self._write_immutable_artifact(
                scope["threadId"], root.joinpath(f"chart-{index:03d}{PurePosixPath(chart.source_file.path).suffix}").as_posix(),
                await self._read_identity_bytes(scope["threadId"], chart.source_file),
            )
            chart_files.append(image)
            chart_destinations[chart_id] = image.path
            plots = []
            for plot_index, plot in enumerate(chart.plot_data_files, 1):
                identity = await self._write_immutable_artifact(
                    scope["threadId"], root.joinpath(f"chart-{index:03d}-{plot_index}.chart-input.json").as_posix(),
                    await self._read_identity_bytes(scope["threadId"], plot),
                )
                plots.append(identity)
                trace_files.append(identity)
            if plots:
                chart_traces.append(ChartTraceV1(
                    chartId=chart_id, imageFileResourceId=derive_resource_id(image.path),
                    plotDataFileResourceIds=tuple(derive_resource_id(item.path) for item in plots),
                    datasetIds=(chart.source_dataset_id,),
                    transformNotes=("复用冻结 Matplotlib 图片及同一份 chart-input/v1 作图数据",),
                ))
        if execution is None:
            source_outline = _frozen_outline(self._state(run_context))
        else:
            from ..revision_execution import load_revision_outline

            source_outline = await load_revision_outline(self, run_context, execution)
        graph = await self._read_identity_model(scope['threadId'], checkpoint.finding_graph_file, FindingGraph)
        fact_directory = {card.fact_refs[0]: (ref.analysis_id, ref.pointer)
            for card in graph.findings if len(card.fact_refs) == 1
            for ref in card.source_refs if ref.pointer.startswith('/metricContext/')}
        section_artifacts = []
        lines = [f"# {outline.title}"]
        for section in source_outline.sections:
            lines.extend(["", f"## {section.section_number} {section.title}"])
            blocks = []
            for slide in outline.slides:
                if not set(section.analysis_ids).intersection(slide.evidence_ids):
                    continue
                lines.extend(["", f"### {slide.title}", ""])
                if slide.summary_block is not None:
                    block = slide.summary_block
                    blocks.append(block)
                    lines.append(anchor_bound_numbers(block.markdown, block.number_references, block.review_notices))
                    lines.extend(['', *[f'- {text}' for text in slide.bullets[1:]]])
                else:
                    lines.extend(f'- {text}' for text in slide.bullets)
                lines.extend(f"[[analysis:{ref}]]" for ref in slide.evidence_ids if ref.startswith("analysis_"))
                for chart_id in slide.chart_ids:
                    chart = charts[chart_id]
                    citations = " ".join(f"[[citation:{ref}]]" for ref in chart.citation_ids)
                    lines.extend(["", f"![{chart.alt_text}]({PurePosixPath(chart_destinations[chart_id]).name}) {citations}"])
            for summary in outline.analysis_summaries:
                if summary.section_code != section.code:
                    continue
                for block in summary.blocks:
                    blocks.append(block)
                    lines.extend(['', anchor_bound_numbers(block.markdown, block.narrative_references, block.review_notices)])
            section_artifacts.append(SimpleNamespace(section_code=section.code, blocks=tuple(blocks), claims=()))
        markdown = chr(10).join(lines).encode("utf-8")
        markdown_file = await self._write_immutable_artifact(scope["threadId"], root.joinpath("slides.md").as_posix(), markdown)
        if execution is None:
            state = self._state(run_context)
            result = self._workflow_result(state)
            binding_stage = 'load'
            try:
                tool_context = self._tool_context(run_context)
                job = self.report_tools._load_job(str(result['jobId']), tool_context)
                job['render'] = {**job.get('render', {}),
                    'markdown': markdown_file.model_dump(mode='json', by_alias=True)}
                binding_stage = 'store'
                self.report_tools._store_job(job, tool_context)
            except Exception as error:
                logger.warning('pptx_markdown_job_binding_failed stage={} error_type={}',
                    binding_stage, type(error).__name__)
                state.setdefault('report_quality_issues', []).append({
                    'code': 'pptx_markdown_job_binding_failed', 'revision': checkpoint.revision,
                    'message': '幻灯片 Markdown 修订身份未能写入编辑任务；已有文件仍可下载，缺少清单时无法进行正式原生偏好验收。',
                    'details': {'stage': binding_stage, 'errorType': type(error).__name__},
                })
            handles = tuple(DatasetHandle.from_state(item) for item in result.get('datasets', ()))
            lineage = tuple(DatasetLineage.model_validate(item) for item in state[REPORT_DATASET_LINEAGE_STATE_KEY])
        else:
            state, result = {}, {}
            handles = await self._registered_metric_dataset_handles(run_context, report_revision=execution.report_revision)
            lineage = tuple(DatasetLineage(datasetId=item.dataset_id, sourceId=item.source_id,
                requirementId=item.requirement_id, sqlHash=item.sql_hash, rowCount=item.row_count,
                size=item.size, sha256=item.sha256, periodRoles=item.period_roles, queryWindowId=item.query_window_id)
                for item in handles)
        manifest_path = root.joinpath("slides.manifest.json").as_posix()
        computations, computation_files = _evidence_and_computation_layers(checkpoint.evidence_manifest)
        manifest = await self._build_and_write_artifact_manifest(
            manifest_path, accepted_artifacts=[item.model_dump(mode="json", by_alias=True) for item in (markdown_file, *chart_files)],
            handles=handles,
            fact_files={key: ArtifactFile(**item.model_dump(), mediaType="application/json")
                        for key, item in checkpoint.deterministic_fact_files.items()},
            chart_trace_files=tuple((*chart_files, *trace_files)), chart_traces=tuple(chart_traces),
            computation_files=computation_files, computations=computations,
            subject_bindings=build_claim_subject_bindings(section_artifacts, fact_directory,
                {key: derive_resource_id(identity.path) for key, identity in checkpoint.deterministic_fact_files.items()}),
            markdown_path=markdown_file.path, lineage=lineage, revision=checkpoint.revision,
            task_key=f"pptx-{run_id}",
            section_numbers=tuple(section.section_number for section in source_outline.sections),
            heading_numbers=tuple(HeadingNumber(
                level=2, number=section.section_number, title=section.title, sectionCode=section.code,
                anchor=f"report-section-{section.code}",
            ) for section in source_outline.sections),
            source_warnings=_source_warnings_from_state(state), run_context=run_context, **execution_options,
            section_finding_ids={section.code: tuple(
                ref for slide in outline.slides if set(section.analysis_ids).intersection(slide.evidence_ids)
                for ref in slide.finding_ids
            ) for section in source_outline.sections},
        )
        manifest_file = await self.workspace_service.ahash_file(scope["threadId"], manifest_path)
        already_completed = checkpoint.phase == "completed"
        checkpoint = self._update_reporting_checkpoint(
            checkpoint, phase="completed" if already_completed else "finalize", pending_sections=(),
            files=self._merge_checkpoint_files(
                checkpoint.files, markdown_file, *chart_files, *trace_files,
                FileIdentity.model_validate(manifest_file),
                *((FileIdentity(path=manifest.trace_index.path, size=manifest.trace_index.size,
                    sha256=manifest.trace_index.sha256),) if manifest.trace_index is not None else ()),
            ),
        )
        if execution is not None:
            for file in checkpoint.files:
                await self._apply_durable_command(run_context, ReportingCommand(name='record_artifact',
                    commandId=f'revision-slide-output:{derive_resource_id(file.path)}:{file.sha256}',
                    payload={'artifact': file.model_dump(mode='json', by_alias=True)}), **execution_options)
        await self._persist_reporting_checkpoint(run_context, checkpoint, **execution_options)
        if not already_completed:
            await self._apply_durable_command(run_context, ReportingCommand(
                name="complete", commandId=f"slides-complete:{checkpoint.revision}:{manifest_file['sha256']}",
                payload={
                    "markdown": markdown_file.model_dump(mode="json", by_alias=True),
                    "manifest": manifest_file,
                    "charts": [item.model_dump(mode="json", by_alias=True) for item in chart_files],
                },
            ), **execution_options)
        checkpoint = self._update_reporting_checkpoint(checkpoint, phase="completed")
        await self._persist_reporting_checkpoint(run_context, checkpoint, **execution_options)
        result.update({
            "markdownPath": markdown_file.path, "deliveryFormat": "pptx", "artifactManifestPath": manifest_path,
            "revision": checkpoint.revision,
            "artifactManifest": {**manifest_file, "mediaType": "application/json"},
        })
        state[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
        state[REPORT_ARTIFACTS_STATE_KEY] = {"draft": manifest.model_dump(mode="json", by_alias=True)}
        return StepOutput(content={"status": "completed", "markdownPath": markdown_file.path})

    async def validate_slides(self, _step_input: StepInput, run_context: RunContext, *, execution=None) -> StepOutput:
        if execution is None:
            return StepOutput(content=await self._render_and_validate(run_context))
        from ..revision_execution import load_revision_outline, require_revision_execution

        durable = await require_revision_execution(self, run_context, execution)
        path = f'报表/智能分析/{execution.execution_run_id}/slides/revision-{execution.output_revision}/report.pptx'
        if any(item.get('path') == path for item in durable.payload.get('artifacts', ())):
            return StepOutput(content=await self._render_pptx(run_context,
                {'revision': execution.output_revision}, None, execution=execution))
        await self.generate_slide_outline(_step_input, run_context, execution=execution)
        durable, checkpoint = await self._slide_checkpoint(run_context, execution=execution)
        result = durable.payload.get('result', {})
        if checkpoint.phase != 'completed' or not result.get('markdown') or not result.get('manifest'):
            raise ReportingError('report_revision_execution_mismatch', '新PPTX必须先完成本修订内容组装。')
        for file in (result['markdown'], result['manifest'], *result.get('charts', ())):
            await self._read_identity_bytes(execution.source_scope.workspace_key, FileIdentity.model_validate(file))
        outline = await load_revision_outline(self, run_context, execution)
        return StepOutput(content=await self._render_pptx(run_context, {
            'revision': execution.output_revision, 'markdownPath': result['markdown']['path'],
            'artifactManifestPath': result['manifest']['path'],
            'artifactManifest': {**result['manifest'], 'mediaType': 'application/json'},
        }, outline, execution=execution))
