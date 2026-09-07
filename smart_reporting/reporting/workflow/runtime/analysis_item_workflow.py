"""单项分析的固定五阶段 Agno 子流程。"""

from __future__ import annotations

import difflib
import shlex
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from agno.run import RunContext
from agno.workflow import Condition, Loop, Step, Steps
from agno.workflow.types import StepInput, StepOutput
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ....task_execution import MAX_READ_FILE_BYTES
from ...hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ...models import ReportingError

MAX_ANALYSIS_SCRIPT_REPAIRS = 2
MAX_DETERMINISTIC_FACT_BYTES = 10 * 1024 * 1024
DETERMINISTIC_FACT_READ_BYTES = 64 * 1024
SUPPLEMENTAL_EVIDENCE_PAGE_BYTES = 64 * 1024
MAX_SUPPLEMENTAL_EVIDENCE_BYTES = 10 * 1024 * 1024
_STAGE_NAMES = (
    "read-facts",
    "plan-evidence",
    "execute-script",
    "validate-evidence",
    "complete-analysis",
)


def _script_patch(path: str, content: str, previous: str | None) -> str:
    """生成标准 unified diff；首次写入以 /dev/null 作为基线。"""
    # 结构化模型输出中的脚本通常不带末尾换行；difflib 不会自动补写 Git 所需的
    # no-newline 标记，导致语法可解析的 diff 在 git apply 阶段被判为 corrupt。
    # 服务端统一签发 POSIX 文本，后续修复读取到的基线也因此保持同一格式。
    if content and not content.endswith("\n"):
        content += "\n"
    before = [] if previous is None else previous.splitlines(keepends=True)
    after = content.splitlines(keepends=True)
    if previous is None:
        before_name, after_name = "/dev/null", f"b/{path}"
    else:
        before_name, after_name = f"a/{path}", f"b/{path}"
    return "".join(difflib.unified_diff(before, after, fromfile=before_name, tofile=after_name))


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class AnalysisEvidencePlan(_StrictModel):
    """模型只决定事实缺口与最小脚本；输出路径由服务端固定。"""

    requires_supplemental_evidence: bool = Field(alias="requiresSupplementalEvidence")
    reason: str = Field(min_length=1, max_length=2_000)
    missing_facts: tuple[str, ...] = Field(alias="missingFacts", max_length=20)
    script: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_empty_missing_facts(cls, value: Any) -> Any:
        """固定事实明确足够时，把模型遗漏的空数组规范化为唯一合法值。"""

        if not isinstance(value, Mapping):
            return value
        requires_supplement = value.get(
            "requiresSupplementalEvidence",
            value.get("requires_supplemental_evidence"),
        )
        if (
            requires_supplement is False
            and value.get("script") is None
            and "missingFacts" not in value
            and "missing_facts" not in value
        ):
            return {**value, "missingFacts": []}
        return value

    @model_validator(mode="after")
    def validate_supplement(self) -> AnalysisEvidencePlan:
        if self.requires_supplemental_evidence:
            if not self.missing_facts or not self.script or not self.script.strip():
                raise ValueError("需要补充 evidence 时必须明确事实缺口并提供脚本")
        elif self.missing_facts or self.script is not None:
            raise ValueError("固定事实足够时不得提供事实缺口或脚本")
        return self


class AnalysisEvidenceDecision(_StrictModel):
    """只判断固定事实是否存在必要缺口，不承载代码。"""

    requires_supplemental_evidence: bool = Field(alias="requiresSupplementalEvidence")
    reason: str = Field(min_length=1, max_length=2_000)
    missing_facts: tuple[str, ...] = Field(alias="missingFacts", max_length=20)

    @model_validator(mode="before")
    @classmethod
    def normalize_empty_missing_facts(cls, value: Any) -> Any:
        """固定事实明确足够时，把模型遗漏的空数组规范化为唯一合法值。"""

        if not isinstance(value, Mapping):
            return value
        requires_supplement = value.get(
            "requiresSupplementalEvidence",
            value.get("requires_supplemental_evidence"),
        )
        if (
            requires_supplement is False
            and "missingFacts" not in value
            and "missing_facts" not in value
        ):
            return {**value, "missingFacts": []}
        return value

    @model_validator(mode="after")
    def validate_decision(self) -> AnalysisEvidenceDecision:
        if self.requires_supplemental_evidence and not self.missing_facts:
            raise ValueError("需要补充 evidence 时必须明确事实缺口")
        if not self.requires_supplemental_evidence and self.missing_facts:
            raise ValueError("固定事实足够时不得声明事实缺口")
        return self


class AnalysisScriptDraft(_StrictModel):
    """根据已冻结事实缺口生成的单一脚本。"""

    script: str = Field(min_length=1)


class AnalysisSummaryDraft(_StrictModel):
    summary: str = Field(min_length=1, max_length=16_000)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)


class _DurableAnalysisCompletion(_StrictModel):
    analysis_id: str = Field(alias="analysisId", pattern=r"^analysis_[0-9]{3,6}$")
    summary: str = Field(min_length=1, max_length=16_000)
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=100)
    evidence_paths: tuple[str, ...] = Field(alias="evidencePaths", min_length=1, max_length=100)
    citation_ids: tuple[str, ...] = Field(alias="citationIds", max_length=500)
    profile_read_receipt_ids: tuple[str, ...] = Field(alias="profileReadReceiptIds", max_length=500)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)
    chart_ids: tuple[str, ...] = Field(alias="chartIds", default=(), max_length=100)


class SupplementalEvidence(_StrictModel):
    analysis_id: str = Field(alias="analysisId", pattern=r"^analysis_[0-9]{3,6}$")
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=100)
    findings: tuple[dict[str, Any], ...] = Field(min_length=1, max_length=500)
    reconciliations: tuple[dict[str, Any], ...] = Field(min_length=1, max_length=100)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("findings", mode="before")
    @classmethod
    def require_compact_tabular_findings(cls, value: Any) -> Any:
        """表格明细只接受列式结构，避免同一协议存在两种编码。"""

        if not isinstance(value, (list, tuple)):
            return value
        for finding in value:
            if not isinstance(finding, Mapping):
                continue
            rows = finding.get("rows")
            if not isinstance(rows, (list, tuple)) or not rows:
                continue
            if "columns" not in finding or any(isinstance(row, Mapping) for row in rows):
                raise ValueError("表格 finding 必须使用 columns + rows 列式结构")
            columns = finding.get("columns")
            if (
                not isinstance(columns, (list, tuple))
                or not columns
                or any(not isinstance(column, str) or not column for column in columns)
                or any(
                    not isinstance(row, (list, tuple)) or len(row) != len(columns) for row in rows
                )
            ):
                raise ValueError("列式 finding 的 columns 与 rows 形状无效")
        return value

    @model_validator(mode="after")
    def validate_reconciliations(self) -> SupplementalEvidence:
        if any(item.get("passed") is not True for item in self.reconciliations):
            raise ValueError("补充 evidence 对账未通过")
        return self


PlanEvidence = Callable[..., Awaitable[AnalysisEvidencePlan]]
Summarize = Callable[[Mapping[str, Any]], Awaitable[AnalysisSummaryDraft]]
ToolCall = Callable[..., Awaitable[dict[str, Any]]]


@dataclass
class AnalysisItemWorkflowResult:
    output: StepOutput
    stage_statuses: tuple[tuple[str, str], ...]


@dataclass
class _AnalysisItemState:
    instruction: dict[str, Any]
    statuses: dict[str, str] = field(
        default_factory=lambda: {name: "pending" for name in _STAGE_NAMES}
    )
    facts: DeterministicAnalysisBundle | None = None
    plan: AnalysisEvidencePlan | None = None
    evidence: SupplementalEvidence | None = None
    recovery: _DurableAnalysisCompletion | None = None
    script_sha256: str | None = None
    failure: Exception | None = None
    warnings: list[str] = field(default_factory=list)
    repair_count: int = 0
    supplement_abandoned: bool = False


class AnalysisItemWorkflow:
    """用 Agno 3.0.1 组合原语执行固定生命周期，不建立独立持久化 Workflow。"""

    def __init__(
        self,
        *,
        plan_evidence: PlanEvidence,
        summarize: Summarize,
        read_file: ToolCall,
        apply_patch: ToolCall,
        run_script: ToolCall,
        complete: ToolCall,
    ) -> None:
        self.plan_evidence = plan_evidence
        self.summarize = summarize
        self.read_file = read_file
        self.apply_patch = apply_patch
        self.run_script = run_script
        self.complete = complete

    async def run(
        self, instruction: Mapping[str, Any], run_context: RunContext
    ) -> AnalysisItemWorkflowResult:
        state = _AnalysisItemState(instruction=dict(instruction))
        pipeline = self._pipeline(state, run_context)
        output = await pipeline.aexecute(
            StepInput(input=state.instruction),
            run_context=run_context,
            session_id=run_context.session_id,
            user_id=run_context.user_id,
        )
        if state.failure is not None:
            raise state.failure
        if state.statuses["complete-analysis"] != "completed":
            raise ReportingError(
                "report_analysis_workflow_incomplete", "单项分析五阶段子流程未完成。"
            )
        return AnalysisItemWorkflowResult(
            output=output,
            stage_statuses=tuple((name, state.statuses[name]) for name in _STAGE_NAMES),
        )

    def _pipeline(self, state: _AnalysisItemState, run_context: RunContext) -> Steps:
        async def read_facts(_step_input: StepInput) -> StepOutput:
            return await self._timed_stage(
                "read-facts", state, self._read_facts(state, run_context)
            )

        async def plan_evidence(_step_input: StepInput) -> StepOutput:
            return await self._timed_stage(
                "plan-evidence", state, self._plan_evidence(state, repair=False)
            )

        async def execute_script(_step_input: StepInput) -> StepOutput:
            return await self._timed_stage(
                "execute-script", state, self._execute_script(state, run_context)
            )

        async def validate_evidence(_step_input: StepInput) -> StepOutput:
            return await self._timed_stage(
                "validate-evidence", state, self._validate_evidence(state, run_context)
            )

        async def skip_script(_step_input: StepInput) -> StepOutput:
            state.statuses["execute-script"] = "skipped"
            return StepOutput(content={"status": "skipped", "reason": "fixed_facts_sufficient"})

        async def skip_evidence(_step_input: StepInput) -> StepOutput:
            state.statuses["validate-evidence"] = "skipped"
            return StepOutput(content={"status": "skipped", "reason": "fixed_facts_sufficient"})

        async def complete_analysis(_step_input: StepInput) -> StepOutput:
            return await self._timed_stage(
                "complete-analysis", state, self._complete_analysis(state, run_context)
            )

        supplement = Condition(
            name="supplemental-evidence",
            evaluator=lambda _input: bool(
                state.plan is not None and state.plan.requires_supplemental_evidence
            ),
            steps=[
                Loop(
                    name="script-repair-loop",
                    steps=[
                        Step(
                            step_id="execute-script",
                            name="execute-script",
                            executor=execute_script,
                            max_retries=0,
                        ),
                        Step(
                            step_id="validate-evidence",
                            name="validate-evidence",
                            executor=validate_evidence,
                            max_retries=0,
                        ),
                    ],
                    max_iterations=MAX_ANALYSIS_SCRIPT_REPAIRS + 1,
                    end_condition=lambda _outputs: (
                        state.evidence is not None
                        or (
                            state.failure is None
                            and state.statuses["validate-evidence"] == "completed"
                        )
                    ),
                )
            ],
            else_steps=[
                Step(
                    step_id="execute-script-skipped",
                    name="execute-script",
                    executor=skip_script,
                    max_retries=0,
                ),
                Step(
                    step_id="validate-evidence-skipped",
                    name="validate-evidence",
                    executor=skip_evidence,
                    max_retries=0,
                ),
            ],
        )
        return Steps(
            name="analysis-item-five-stage",
            steps=[
                Step(
                    step_id="read-facts",
                    name="read-facts",
                    executor=read_facts,
                    max_retries=0,
                ),
                Step(
                    step_id="plan-evidence",
                    name="plan-evidence",
                    executor=plan_evidence,
                    max_retries=0,
                ),
                supplement,
                Step(
                    step_id="complete-analysis",
                    name="complete-analysis",
                    executor=complete_analysis,
                    max_retries=0,
                ),
            ],
        )

    @staticmethod
    async def _timed_stage(
        stage_name: str,
        state: _AnalysisItemState,
        operation: Awaitable[StepOutput],
    ) -> StepOutput:
        started_at = perf_counter()
        logger.info(
            "report_analysis_item_stage_started stage_name={} analysis_id={}",
            stage_name,
            state.instruction.get("currentAnalysisId"),
        )
        try:
            output = await operation
        except Exception as error:
            state.failure = error
            state.statuses[stage_name] = "failed"
            raise
        finally:
            logger.info(
                "report_analysis_item_stage_completed stage_name={} analysis_id={} "
                "status={} duration_ms={}",
                stage_name,
                state.instruction.get("currentAnalysisId"),
                state.statuses[stage_name],
                max(0, round((perf_counter() - started_at) * 1000)),
            )
        return output

    async def _read_facts(self, state: _AnalysisItemState, run_context: RunContext) -> StepOutput:
        identity = state.instruction.get("deterministicFactFile")
        path = identity.get("path") if isinstance(identity, Mapping) else None
        expected_size = identity.get("size") if isinstance(identity, Mapping) else None
        expected_sha256 = identity.get("sha256") if isinstance(identity, Mapping) else None
        if (
            not isinstance(path, str)
            or not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or not 0 < expected_size <= MAX_DETERMINISTIC_FACT_BYTES
            or not isinstance(expected_sha256, str)
        ):
            raise ReportingError(
                "report_analysis_facts_invalid", "单项分析缺少固定 facts 文件身份。"
            )
        chunks: list[str] = []
        offset = 0
        while offset < expected_size:
            result = await self.read_file(
                path=path,
                offset=offset,
                max_bytes=DETERMINISTIC_FACT_READ_BYTES,
                run_context=run_context,
            )
            self._require_ok(result, default_code="report_analysis_facts_read_failed")
            next_offset = result.get("nextOffset")
            if (
                result.get("sha256") != expected_sha256
                or result.get("totalBytes") != expected_size
                or not isinstance(next_offset, int)
                or isinstance(next_offset, bool)
                or not offset < next_offset <= expected_size
                or not isinstance(result.get("content"), str)
            ):
                raise ReportingError(
                    "report_analysis_facts_changed", "固定 facts 文件身份或读取游标无效。"
                )
            chunks.append(result["content"])
            offset = next_offset
        content = "".join(chunks)
        if len(content.encode("utf-8")) != expected_size:
            raise ReportingError(
                "report_analysis_facts_changed", "固定 facts 文件读取长度与签发值不一致。"
            )
        try:
            facts = DeterministicAnalysisBundle.model_validate_json(content)
        except Exception as error:
            raise ReportingError(
                "report_analysis_facts_invalid", "固定 facts 文件内容不符合契约。"
            ) from error
        if facts.analysis_id != state.instruction.get("currentAnalysisId"):
            raise ReportingError(
                "report_analysis_facts_invalid", "固定 facts 文件与当前分析项身份不一致。"
            )
        state.facts = facts
        state.statuses["read-facts"] = "completed"
        return StepOutput(content={"analysisId": facts.analysis_id, "status": "validated"})

    async def _plan_evidence(self, state: _AnalysisItemState, *, repair: bool) -> StepOutput:
        if state.facts is None:
            raise ReportingError("report_analysis_facts_invalid", "固定 facts 尚未通过校验。")
        recovery = state.instruction.get("durableAnalysisItem")
        if not repair and isinstance(recovery, Mapping):
            try:
                durable = _DurableAnalysisCompletion.model_validate(recovery)
            except Exception as error:
                raise ReportingError(
                    "report_analysis_completion_recovery_invalid",
                    "已冻结单项分析完成 payload 无效。",
                ) from error
            if durable.analysis_id != state.instruction.get("currentAnalysisId"):
                raise ReportingError(
                    "report_analysis_completion_recovery_invalid",
                    "已冻结完成 payload 与当前分析项身份不一致。",
                )
            state.recovery = durable
            state.plan = AnalysisEvidencePlan(
                requiresSupplementalEvidence=False,
                reason="durable_completion_recovery",
                missingFacts=(),
                script=None,
            )
            state.statuses["plan-evidence"] = "completed"
            return StepOutput(content={"status": "durable_completion_recovery"})
        payload = {
            "currentAnalysis": state.instruction.get("currentAnalysis"),
            "deterministicFacts": self._model_facts(state),
            "datasets": state.instruction.get("datasets", []),
            "analysisOutputRoot": state.instruction.get("analysisOutputRoot"),
            "scriptPath": self._script_path(state),
            "evidencePath": self._evidence_path(state),
            **(
                {
                    "correction": {
                        "attempt": state.repair_count + 1,
                        "previousPlan": (
                            state.plan.model_dump(mode="json", by_alias=True)
                            if state.plan is not None
                            else None
                        ),
                        "error": self._repair_error(state.failure),
                    }
                }
                if repair
                else {}
            ),
        }
        plan = await self.plan_evidence(payload, repair=repair)
        if repair and not plan.requires_supplemental_evidence:
            raise ReportingError(
                "report_analysis_script_repair_invalid", "脚本修复不得绕过既有事实缺口。"
            )
        state.plan = plan
        state.failure = None
        state.statuses["plan-evidence"] = "completed"
        return StepOutput(content=plan.model_dump(mode="json", by_alias=True))

    async def _execute_script(
        self, state: _AnalysisItemState, run_context: RunContext
    ) -> StepOutput:
        if state.failure is not None:
            if state.repair_count >= MAX_ANALYSIS_SCRIPT_REPAIRS:
                return self._abandon_supplement(state)
            state.repair_count += 1
            await self._plan_evidence(state, repair=True)
        plan = state.plan
        if plan is None or not plan.requires_supplemental_evidence or plan.script is None:
            raise ReportingError(
                "report_analysis_evidence_plan_invalid", "补充 evidence 计划缺少可执行脚本。"
            )
        script_path = self._script_path(state)
        previous = None
        if state.script_sha256 is not None:
            previous = await self._read_existing_script(state, script_path, run_context)
        patch = _script_patch(script_path, plan.script, previous)
        if not patch:
            state.failure = ReportingError(
                "report_analysis_script_repair_no_change",
                "补证脚本修复结果与失败脚本完全相同。",
                details={"repairCount": state.repair_count},
            )
            state.evidence = None
            if state.repair_count >= MAX_ANALYSIS_SCRIPT_REPAIRS:
                return self._abandon_supplement(state)
            state.statuses["execute-script"] = "retrying"
            return StepOutput(content={"status": "retry", "code": state.failure.code})
        write = await self.apply_patch(
            patch=patch,
            expected_sha256=({script_path: state.script_sha256} if state.script_sha256 else None),
            run_context=run_context,
        )
        try:
            self._require_ok(write, default_code="report_analysis_script_write_failed")
            artifacts = write.get("artifacts")
            identity = artifacts[0] if isinstance(artifacts, list) and artifacts else None
            sha256 = identity.get("sha256") if isinstance(identity, Mapping) else None
            if not isinstance(sha256, str):
                raise ReportingError(
                    "report_analysis_script_write_failed", "补充分析脚本缺少写入身份回执。"
                )
            state.script_sha256 = sha256
            execution = await self.run_script(
                command=f"python3 {shlex.quote(script_path)}", run_context=run_context
            )
            exit_code = execution.get("exitCode", execution.get("exit_code"))
            if execution.get("ok") is False or exit_code != 0:
                output = str(execution.get("output") or "")
                raise ReportingError(
                    "report_analysis_script_failed",
                    "补充分析脚本执行失败。",
                    details={
                        "exitCode": exit_code,
                        "output": output[:4000],
                        "outputTruncated": len(output) > 4000,
                        "toolCode": execution.get("code"),
                        "toolMessage": execution.get("message"),
                    },
                )
        except ReportingError as error:
            if error.code == "report_analysis_script_failed" and isinstance(error.details, Mapping):
                logger.error(
                    "report_analysis_script_execution_failed analysis_id={} exit_code={} "
                    "output_truncated={} output={}",
                    state.instruction.get("currentAnalysisId"),
                    error.details.get("exitCode"),
                    error.details.get("outputTruncated"),
                    error.details.get("output"),
                )
            state.failure = error
            state.evidence = None
            if state.repair_count >= MAX_ANALYSIS_SCRIPT_REPAIRS:
                return self._abandon_supplement(state)
            state.statuses["execute-script"] = "retrying"
            return StepOutput(content={"status": "retry", "code": error.code})
        state.statuses["execute-script"] = "completed"
        return StepOutput(content={"status": "executed", "scriptPath": script_path})

    async def _read_existing_script(
        self,
        state: _AnalysisItemState,
        script_path: str,
        run_context: RunContext,
    ) -> str:
        """在工具单次读取上限内恢复待修复脚本，并验证读取期间身份不变。"""

        chunks: list[str] = []
        offset = 0
        total_bytes: int | None = None
        while total_bytes is None or offset < total_bytes:
            current = await self.read_file(
                path=script_path,
                offset=offset,
                max_bytes=MAX_READ_FILE_BYTES,
                run_context=run_context,
            )
            self._require_ok(current, default_code="report_analysis_script_read_failed")
            content = current.get("content")
            next_offset = current.get("nextOffset")
            current_total = current.get("totalBytes")
            if (
                not isinstance(content, str)
                or not isinstance(next_offset, int)
                or isinstance(next_offset, bool)
                or not isinstance(current_total, int)
                or isinstance(current_total, bool)
                or not offset < next_offset <= current_total
                or (total_bytes is not None and current_total != total_bytes)
                or current.get("sha256") != state.script_sha256
            ):
                raise ReportingError(
                    "report_analysis_script_read_failed",
                    "待修复脚本的身份、大小或读取游标无效。",
                )
            chunks.append(content)
            offset = next_offset
            total_bytes = current_total
        return "".join(chunks)

    async def _validate_evidence(
        self, state: _AnalysisItemState, run_context: RunContext
    ) -> StepOutput:
        if state.supplement_abandoned:
            state.statuses["validate-evidence"] = "completed"
            return StepOutput(content={"status": "skipped_after_repair_exhausted"})
        if state.failure is not None:
            state.statuses["validate-evidence"] = "retrying"
            return StepOutput(content={"status": "skipped_after_script_error"})
        try:
            content = await self._read_supplemental_evidence(state, run_context)
            evidence = SupplementalEvidence.model_validate_json(content)
            analysis_id = state.instruction.get("currentAnalysisId")
            if evidence.analysis_id != analysis_id:
                raise ReportingError(
                    "report_analysis_evidence_identity_mismatch",
                    "补充 evidence 与当前分析项身份不一致。",
                )
            expected = self._dataset_ids(state)
            if set(evidence.dataset_ids) != set(expected):
                raise ReportingError(
                    "report_analysis_evidence_dataset_mismatch",
                    "补充 evidence 未精确绑定当前分析项 Dataset。",
                )
        except ReportingError as error:
            state.evidence = None
            state.warnings.append(f"{error.code}: {error.message}")
            logger.warning(
                "report_analysis_evidence_validation_warning analysis_id={} code={}",
                state.instruction.get("currentAnalysisId"),
                error.code,
            )
            state.statuses["validate-evidence"] = "completed"
            return StepOutput(content={"status": "warning", "code": error.code})
        except Exception:
            warning_code = "report_analysis_evidence_reconciliation_failed"
            state.evidence = None
            state.warnings.append(f"{warning_code}: 补充 evidence 结构无效或对账未通过。")
            logger.warning(
                "report_analysis_evidence_validation_warning analysis_id={} code={}",
                state.instruction.get("currentAnalysisId"),
                warning_code,
            )
            state.statuses["validate-evidence"] = "completed"
            return StepOutput(content={"status": "warning", "code": warning_code})
        state.evidence = evidence
        state.statuses["validate-evidence"] = "completed"
        return StepOutput(
            content={"status": "validated", "evidencePath": self._evidence_path(state)}
        )

    async def _read_supplemental_evidence(
        self, state: _AnalysisItemState, run_context: RunContext
    ) -> str:
        """分页读取完整补证，同时固定首次读取签发的文件身份。"""

        chunks: list[str] = []
        offset = 0
        total_bytes: int | None = None
        sha256: str | None = None
        while total_bytes is None or offset < total_bytes:
            result = await self.read_file(
                path=self._evidence_path(state),
                offset=offset,
                max_bytes=SUPPLEMENTAL_EVIDENCE_PAGE_BYTES,
                run_context=run_context,
            )
            self._require_ok(result, default_code="report_analysis_evidence_read_failed")
            content = result.get("content")
            current_total = result.get("totalBytes")
            current_sha256 = result.get("sha256")
            next_offset = result.get("nextOffset")
            if current_total is None and isinstance(content, str):
                current_total = len(content.encode("utf-8"))
            if (
                next_offset is None
                and isinstance(content, str)
                and current_total == len(content.encode("utf-8"))
            ):
                next_offset = current_total
            if total_bytes is None:
                if (
                    not isinstance(current_total, int)
                    or isinstance(current_total, bool)
                    or current_total <= 0
                    or current_total > MAX_SUPPLEMENTAL_EVIDENCE_BYTES
                ):
                    raise ReportingError(
                        "report_analysis_evidence_too_large",
                        "补充 evidence 超过 10 MiB 安全上限或大小无效。",
                    )
                total_bytes = current_total
                sha256 = current_sha256 if isinstance(current_sha256, str) else None
            if (
                result.get("outputTruncated") is True
                or not isinstance(content, str)
                or not isinstance(next_offset, int)
                or isinstance(next_offset, bool)
                or not offset < next_offset <= total_bytes
                or current_total != total_bytes
                or not sha256
                or current_sha256 != sha256
            ):
                raise ReportingError(
                    "report_analysis_evidence_changed",
                    "补充 evidence 文件身份、大小或读取游标无效。",
                )
            chunks.append(content)
            offset = next_offset
        joined = "".join(chunks)
        if len(joined.encode("utf-8")) != total_bytes:
            raise ReportingError(
                "report_analysis_evidence_changed",
                "补充 evidence 完整读取长度与冻结大小不一致。",
            )
        return joined

    @staticmethod
    def _abandon_supplement(state: _AnalysisItemState) -> StepOutput:
        error = state.failure
        code = error.code if isinstance(error, ReportingError) else type(error).__name__
        message = error.message if isinstance(error, ReportingError) else str(error)
        state.warnings.append(
            f"report_analysis_supplement_abandoned: 补证脚本修复耗尽，"
            f"仅使用确定性事实完成分析（{code}: {message}）。"
        )
        state.failure = None
        state.evidence = None
        state.supplement_abandoned = True
        state.statuses["execute-script"] = "completed"
        return StepOutput(content={"status": "degraded", "code": code})

    async def _complete_analysis(
        self, state: _AnalysisItemState, run_context: RunContext
    ) -> StepOutput:
        if state.failure is not None:
            raise state.failure
        if state.recovery is not None:
            durable = state.recovery
            result = await self.complete(
                **durable.model_dump(mode="json", by_alias=True),
                run_context=run_context,
            )
            self._validate_completion_result(result)
            state.statuses["complete-analysis"] = "completed"
            return StepOutput(content={"status": "accepted", "recovered": True})
        summary_payload = {
            "currentAnalysis": state.instruction.get("currentAnalysis"),
            "deterministicFacts": (self._model_facts(state) if state.facts is not None else None),
            "supplementalEvidence": (
                state.evidence.model_dump(mode="json", by_alias=True)
                if state.evidence is not None
                else None
            ),
            "reviewFeedback": state.instruction.get("reviewFeedback"),
            "analysisReworkRequest": state.instruction.get("analysisReworkRequest"),
            "evidenceWarnings": list(state.warnings),
        }
        draft = await self.summarize(summary_payload)
        warnings = list(dict.fromkeys((*draft.warnings, *state.warnings)))
        if state.evidence is not None:
            warnings = list(dict.fromkeys((*warnings, *state.evidence.warnings)))
        result = await self.complete(
            analysisId=str(state.instruction.get("currentAnalysisId") or ""),
            summary=draft.summary,
            datasetIds=self._dataset_ids(state),
            evidencePaths=([self._evidence_path(state)] if state.evidence is not None else []),
            citationIds=self._citation_ids(state),
            profileReadReceiptIds=[],
            warnings=warnings,
            chartIds=[],
            run_context=run_context,
        )
        self._validate_completion_result(result)
        state.statuses["complete-analysis"] = "completed"
        return StepOutput(content={"status": "accepted"})

    @classmethod
    def _validate_completion_result(cls, result: Mapping[str, Any]) -> None:
        cls._require_ok(result, default_code="report_analysis_completion_failed")
        if result.get("status") != "accepted" or result.get("taskFinished") is not True:
            raise ReportingError(
                "report_analysis_completion_failed", "单项分析完成调用未通过 Task 验收。"
            )

    @staticmethod
    def _require_ok(result: Mapping[str, Any], *, default_code: str) -> None:
        # 底层 terminal 成功回执历史上没有统一 ok 字段；明确的 false 才是拒绝。
        if result.get("ok") is not False:
            return
        raise ReportingError(
            str(result.get("code") or default_code),
            str(result.get("message") or "单项分析工具调用失败。"),
            details=(
                dict(details) if isinstance((details := result.get("details")), Mapping) else None
            ),
        )

    @staticmethod
    def _repair_error(error: Exception | None) -> dict[str, Any] | None:
        if error is None:
            return None
        if isinstance(error, ReportingError):
            return {
                "code": error.code,
                "message": error.message,
                **({"details": error.details} if error.details is not None else {}),
            }
        return {"code": type(error).__name__, "message": str(error)[:4_000]}

    @staticmethod
    def _dataset_ids(state: _AnalysisItemState) -> list[str]:
        current = state.instruction.get("currentAnalysis")
        values = current.get("datasetIds") if isinstance(current, Mapping) else None
        return list(dict.fromkeys(value for value in values or () if isinstance(value, str)))

    @staticmethod
    def _citation_ids(state: _AnalysisItemState) -> list[str]:
        registry = state.instruction.get("citationRegistry")
        return list(
            dict.fromkeys(
                item["citationId"]
                for item in registry or ()
                if isinstance(item, Mapping) and isinstance(item.get("citationId"), str)
            )
        )

    @staticmethod
    def _model_facts(state: _AnalysisItemState) -> dict[str, Any]:
        projected = state.instruction.get("deterministicFacts")
        if not isinstance(projected, Mapping):
            raise ReportingError(
                "report_analysis_facts_invalid", "单项分析缺少已签发的模型 facts 投影。"
            )
        return dict(projected)

    @staticmethod
    def _script_path(state: _AnalysisItemState) -> str:
        return f"{str(state.instruction.get('analysisOutputRoot') or '').rstrip('/')}/supplement.py"

    @staticmethod
    def _evidence_path(state: _AnalysisItemState) -> str:
        return (
            f"{str(state.instruction.get('analysisOutputRoot') or '').rstrip('/')}/supplement.json"
        )


__all__ = [
    "AnalysisEvidenceDecision",
    "AnalysisEvidencePlan",
    "AnalysisItemWorkflow",
    "AnalysisItemWorkflowResult",
    "AnalysisScriptDraft",
    "AnalysisSummaryDraft",
    "MAX_ANALYSIS_SCRIPT_REPAIRS",
]
