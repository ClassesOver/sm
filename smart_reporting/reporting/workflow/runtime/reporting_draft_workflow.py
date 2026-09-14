"""按章节编排 Reporting 分析、图表提交和章节成稿。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

from agno.run import RunContext
from agno.workflow import Parallel, Step, Steps, Workflow
from agno.workflow.types import StepInput, StepOutput
from loguru import logger

ReportingExecutionMode = Literal["sequential", "parallel"]
AnalysisRunner = Callable[[Mapping[str, Any], RunContext], Awaitable[StepOutput]]
VisualizationRunner = Callable[[Mapping[str, Any], RunContext], Awaitable[StepOutput]]
DraftRunner = Callable[[Mapping[str, Any], RunContext], Awaitable[StepOutput]]
ReworkRunner = Callable[[Mapping[str, Any], RunContext], Awaitable[StepOutput]]


@dataclass(frozen=True)
class ReportingDraftWorkflowResult:
    """章节工作流的服务端结果；不依赖模型历史。"""

    section_code: str
    analysis_outputs: tuple[StepOutput, ...]
    visualization_output: StepOutput
    draft_output: StepOutput


class ReportingDraftWorkflow(Workflow):
    """执行一个章节的固定三阶段流程。

    ``report_goal`` 和 ``section_goal`` 在每个子任务的输入中重复注入，保证恢复、
    并行和新 Task 都使用同一份冻结契约。分析并发受共享 semaphore 限制，避免章节
    并行时嵌套 Parallel 放大总并发。
    """

    def __init__(
        self,
        *,
        report_goal: str,
        section_goal: Mapping[str, Any],
        analysis_ids: Sequence[str],
        run_analysis: AnalysisRunner,
        submit_visualization: VisualizationRunner,
        draft_section: DraftRunner,
        rework_analysis: ReworkRunner | None = None,
        execution_mode: ReportingExecutionMode = "sequential",
        analysis_limiter: asyncio.Semaphore | None = None,
    ) -> None:
        if execution_mode not in {"sequential", "parallel"}:
            raise ValueError("execution_mode 必须是 sequential 或 parallel")
        if not analysis_ids:
            raise ValueError("章节必须至少包含一个 analysisId")
        self.report_goal = report_goal
        self.section_goal = dict(section_goal)
        self.analysis_ids = tuple(analysis_ids)
        self.run_analysis = run_analysis
        self.submit_visualization = submit_visualization
        self.draft_section = draft_section
        self.rework_analysis = rework_analysis
        self.execution_mode = execution_mode
        self.analysis_limiter = analysis_limiter
        self._analysis_outputs: dict[str, StepOutput] | None = None
        super().__init__(
            id=f"coding-draft-{self.section_goal.get('sectionCode', 'section')}",
            name="章节分析、可视化与成稿",
            steps=[],
            add_workflow_history_to_steps=False,
            stream_executor_events=False,
            telemetry=False,
        )

    def _instruction(self, *, analysis_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "reportGoal": self.report_goal,
            "sectionGoal": self.section_goal,
            "sectionCode": self.section_goal.get("sectionCode"),
        }
        if analysis_id is not None:
            payload["analysisId"] = analysis_id
        return payload

    async def _run_analysis_one(self, analysis_id: str, context: RunContext) -> StepOutput:
        async def invoke() -> StepOutput:
            return await self.run_analysis(self._instruction(analysis_id=analysis_id), context)

        if self.analysis_limiter is None:
            output = await invoke()
        else:
            async with self.analysis_limiter:
                output = await invoke()
        if self._analysis_outputs is not None:
            self._analysis_outputs[analysis_id] = output
        return output

    async def _run_rework_analysis(
        self, instruction: Mapping[str, Any], context: RunContext
    ) -> StepOutput:
        assert self.rework_analysis is not None
        if self.analysis_limiter is None:
            return await self.rework_analysis(instruction, context)
        async with self.analysis_limiter:
            return await self.rework_analysis(instruction, context)

    async def execute_section(self, run_context: RunContext) -> ReportingDraftWorkflowResult:
        started_at = perf_counter()
        section_code = str(self.section_goal.get("sectionCode", ""))
        logger.info("report_section_started section_code={}", section_code)
        logger.info(
            "report_section_base_info section={}",
            json.dumps(
                {
                    "sectionNumber": self.section_goal.get("sectionNumber"),
                    "sectionCode": section_code,
                    "title": self.section_goal.get("title"),
                    "analysisCount": len(self.analysis_ids),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        self._analysis_outputs = {}
        try:
            analysis_plan = build_reporting_draft_steps(self, run_context)
            await analysis_plan.aexecute(
                StepInput(input=self._instruction()),
                run_context=run_context,
                session_id=run_context.session_id,
                user_id=run_context.user_id,
                add_workflow_history_to_steps=False,
            )
            analysis_outputs = [
                self._analysis_outputs.get(analysis_id) for analysis_id in self.analysis_ids
            ]
        finally:
            self._analysis_outputs = None
        if any(output is None for output in analysis_outputs):
            raise RuntimeError("章节分析项未全部执行")
        for analysis_id, output in zip(self.analysis_ids, analysis_outputs, strict=True):
            assert output is not None
            if output.success is False:
                raise RuntimeError(f"分析项 {analysis_id} 执行失败")

        visualization_input = self._instruction()
        visualization_input["analysisIds"] = list(self.analysis_ids)
        visualization_output = await self.submit_visualization(visualization_input, run_context)
        if visualization_output.success is False:
            raise RuntimeError("章节可视化提交失败")

        draft_input = self._instruction()
        draft_input["analysisIds"] = list(self.analysis_ids)
        draft_input["visualizationSubmitted"] = True
        draft_input["analysisReworkAllowed"] = True
        draft_output = await self.draft_section(draft_input, run_context)
        if draft_output.success is False:
            raise RuntimeError("章节成稿失败")
        if (
            isinstance(draft_output.content, Mapping)
            and draft_output.content.get("status") == "rework"
        ):
            if self.rework_analysis is None:
                raise RuntimeError("章节补证执行器未配置")
            rework = draft_output.content.get("rework")
            if not isinstance(rework, Mapping):
                raise RuntimeError("章节补证请求无效")
            rework_input = self._instruction()
            rework_input["rework"] = dict(rework)
            rework_output = await self._run_rework_analysis(rework_input, run_context)
            if rework_output.success is False:
                raise RuntimeError("章节补证分析失败")
            visualization_output = await self.submit_visualization(visualization_input, run_context)
            if visualization_output.success is False:
                raise RuntimeError("章节补证后的可视化提交失败")
            draft_input["analysisReworkAllowed"] = False
            draft_input["rework"] = dict(rework)
            draft_output = await self.draft_section(draft_input, run_context)
            if draft_output.success is False:
                raise RuntimeError("章节补证后的成稿失败")
            if (
                isinstance(draft_output.content, Mapping)
                and draft_output.content.get("status") == "rework"
            ):
                logger.warning(
                    "report_section_degraded_draft_retry section_code={}", section_code
                )
                draft_input["forceDegradedDraft"] = True
                draft_output = await self.draft_section(draft_input, run_context)
                if draft_output.success is False:
                    raise RuntimeError("章节强制降级成稿失败")
            if not (
                isinstance(draft_output.content, Mapping)
                and draft_output.content.get("status") == "completed"
            ):
                raise RuntimeError("章节强制降级成稿未完成")
        result = ReportingDraftWorkflowResult(
            section_code=section_code,
            analysis_outputs=tuple(output for output in analysis_outputs if output is not None),
            visualization_output=visualization_output,
            draft_output=draft_output,
        )
        logger.info(
            "report_section_completed section_code={} duration_ms={}",
            section_code,
            max(0, round((perf_counter() - started_at) * 1000)),
        )
        return result


class ReportingAnalysisAndDraftWorkflow(Workflow):
    """根据冻结提纲运行全部章节，并汇总章节结果。"""

    def __init__(
        self,
        *,
        report_goal: str,
        sections: Sequence[Mapping[str, Any]],
        run_analysis: AnalysisRunner,
        submit_visualization: VisualizationRunner,
        draft_section: DraftRunner,
        rework_analysis: ReworkRunner | None = None,
        execution_mode: ReportingExecutionMode = "sequential",
        section_concurrency: int = 1,
        analysis_concurrency: int = 1,
    ) -> None:
        if section_concurrency < 1 or analysis_concurrency < 1:
            raise ValueError("并发度必须大于 0")
        self.execution_mode = execution_mode
        self.section_concurrency = section_concurrency
        limiter = asyncio.Semaphore(analysis_concurrency)
        built_sections: list[ReportingDraftWorkflow] = []
        assigned_analysis_ids: set[str] = set()
        for section in sections:
            analysis_ids = tuple(section.get("analysisIds", ()))
            duplicate_ids = assigned_analysis_ids.intersection(analysis_ids)
            if duplicate_ids:
                duplicate = sorted(duplicate_ids)[0]
                raise ValueError(f"analysisId {duplicate} 不能归属于多个章节")
            assigned_analysis_ids.update(analysis_ids)
            built_sections.append(
                ReportingDraftWorkflow(
                    report_goal=report_goal,
                    section_goal=section,
                    analysis_ids=analysis_ids,
                    run_analysis=run_analysis,
                    submit_visualization=submit_visualization,
                    draft_section=draft_section,
                    rework_analysis=rework_analysis,
                    execution_mode=execution_mode,
                    analysis_limiter=limiter,
                )
            )
        self.sections = tuple(built_sections)
        super().__init__(
            id="coding-analysis-and-draft",
            name="Reporting 分析与成稿",
            steps=[
                Step(
                    step_id="coding-sections",
                    name="逐章分析、可视化与成稿",
                    # Agno 在执行 Step 时按参数名注入当前 RunContext；其公开
                    # StepExecutor 类型尚未描述该运行时注入，故仅在此处豁免。
                    executor=self._execute_sections,  # type: ignore[arg-type]
                    max_retries=0,
                )
            ],
            add_workflow_history_to_steps=False,
            stream_executor_events=False,
            telemetry=False,
        )

    async def _run_sections(
        self, run_context: RunContext
    ) -> tuple[ReportingDraftWorkflowResult, ...]:
        async def execute_batch(
            batch: Sequence[ReportingDraftWorkflow], *, parallel: bool
        ) -> list[ReportingDraftWorkflowResult]:
            results: list[ReportingDraftWorkflowResult] = []

            async def execute_section(
                _input: StepInput, section: ReportingDraftWorkflow, **_kwargs: Any
            ) -> StepOutput:
                result = await section.execute_section(run_context)
                results.append(result)
                return StepOutput(content=result)

            steps = []
            for section in batch:

                async def run_section(
                    value: StepInput, section: ReportingDraftWorkflow = section, **kwargs: Any
                ) -> StepOutput:
                    return await execute_section(value, section, **kwargs)

                steps.append(
                    Step(
                        step_id=f"{section.id}-run",
                        name=section.name,
                        executor=run_section,
                        max_retries=0,
                    )
                )
            container: Steps | Parallel = (
                # Agno 3.0.0 运行时要求展开列表；其类型标注与实现不一致。
                Parallel(*steps, name="coding-sections-batch")  # type: ignore[arg-type]
                if parallel
                else Steps(name="coding-sections", steps=steps)
            )
            container_output = await container.aexecute(
                StepInput(
                    input={"reportGoal": self.sections[0].report_goal if self.sections else ""}
                ),
                run_context=run_context,
                session_id=run_context.session_id,
                user_id=run_context.user_id,
                add_workflow_history_to_steps=False,
            )
            # Agno 会把子步骤异常转换为 success=False；批次边界必须显式阻断，
            # 否则失败章节可能被误当作完成并继续下一批。
            if container_output.success is False or any(
                output.success is False
                for output in (container_output.steps or ())
                if isinstance(output, StepOutput)
            ):
                failed_steps = [
                    output.step_name
                    for output in (container_output.steps or ())
                    if isinstance(output, StepOutput) and output.success is False
                ]
                detail = ", ".join(name for name in failed_steps if name) or "章节批次"
                raise RuntimeError(f"Agno 章节步骤执行失败: {detail}")
            return results

        if self.execution_mode == "sequential":
            return tuple(await execute_batch(self.sections, parallel=False))
        results: list[ReportingDraftWorkflowResult] = []
        for offset in range(0, len(self.sections), self.section_concurrency):
            batch = self.sections[offset : offset + self.section_concurrency]
            results.extend(await execute_batch(batch, parallel=True))
        # Parallel completion order is nondeterministic; output remains outline order.
        by_code = {result.section_code: result for result in results}
        return tuple(
            by_code[str(section.section_goal.get("sectionCode", ""))] for section in self.sections
        )

    async def _execute_sections(self, _input: Any, run_context: RunContext) -> StepOutput:
        results = await self._run_sections(run_context)
        return StepOutput(
            content={
                "sections": [
                    {
                        "sectionCode": result.section_code,
                        "analysisCount": len(result.analysis_outputs),
                        "visualizationSubmitted": result.visualization_output.success is not False,
                        "draftCompleted": result.draft_output.success is not False,
                    }
                    for result in results
                ]
            }
        )


def build_reporting_draft_steps(
    workflow: ReportingDraftWorkflow,
    run_context: RunContext,
) -> Steps | Parallel:
    """构造可供 Agno 运行器使用的 Steps/Parallel 计划。

    运行器仍由 ``ReportingDraftWorkflow.execute_section`` 执行门禁；该函数用于检查和测试步骤
    结构，所有自定义 Step 均关闭隐式重试。
    """

    steps = []
    for analysis_id in workflow.analysis_ids:

        async def run_analysis(
            _input: StepInput, analysis_id: str = analysis_id, **_kwargs: Any
        ) -> StepOutput:
            return await workflow._run_analysis_one(analysis_id, run_context)

        steps.append(
            Step(
                step_id=f"analysis-{analysis_id}",
                name=f"分析 {analysis_id}",
                executor=run_analysis,
                max_retries=0,
            )
        )
    if workflow.execution_mode == "parallel":
        # Agno 3.0.0 运行时要求展开列表；其类型标注与实现不一致。
        return Parallel(*steps, name="coding-analysis-items")  # type: ignore[arg-type]
    return Steps(name="coding-analysis-items", steps=steps)
