"""单项分析的固定五阶段 Agno 子流程。"""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from agno.run import RunContext
from agno.workflow import Condition, Loop, Step, Steps
from agno.workflow.types import StepInput, StepOutput
from loguru import logger
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from ...hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ...models import ReportingError
from ..checkpoint import FileIdentity
from .code_generation import CodeGenerationResult

MAX_ANALYSIS_SCRIPT_REPAIRS = 2
MAX_DETERMINISTIC_FACT_BYTES = 10 * 1024 * 1024
DETERMINISTIC_FACT_READ_BYTES = 64 * 1024
SUPPLEMENTAL_EVIDENCE_PAGE_BYTES = 64 * 1024
MAX_SUPPLEMENTAL_EVIDENCE_BYTES = 10 * 1024 * 1024
MAX_ANALYSIS_SUMMARY_PROJECTED_ROWS = 256
_STAGE_NAMES = (
    "read-facts",
    "plan-evidence",
    "execute-script",
    "validate-evidence",
    "complete-analysis",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


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

    @field_validator("reconciliations", mode="before")
    @classmethod
    def require_reconciliation_shape(cls, value: Any) -> Any:
        """只校验机器结构；业务对账不一致由工作流保留为软告警。"""

        if not isinstance(value, (list, tuple)):
            return value
        for reconciliation in value:
            if not isinstance(reconciliation, Mapping):
                raise ValueError("evidence 对账项必须为 JSON 对象")
            name = reconciliation.get("name")
            passed = reconciliation.get("passed")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("evidence 对账项必须包含非空 name")
            if not isinstance(passed, bool):
                raise ValueError("evidence 对账项必须包含布尔 passed")
        return value

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
                or len(columns) != len(set(columns))
                or any(
                    not isinstance(row, (list, tuple)) or len(row) != len(columns) for row in rows
                )
            ):
                raise ValueError("列式 finding 的 columns 与 rows 形状无效")
            if any(
                isinstance(value, float) and not math.isfinite(value)
                for row in rows
                for value in row
            ):
                raise ValueError("列式 finding 不得包含 NaN 或无穷大")
        return value


def _summary_rank_column(columns: list[str], rows: list[list[Any]]) -> int | None:
    del rows
    preferred = (
        "change",
        "difference",
        "diff",
        "variance",
        "contribution",
        "delta",
        "gap",
        "changeamount",
        "contributionamount",
        "yoydiff",
        "changerate",
        "differencerate",
        "variancerate",
        "contributionrate",
        "growthrate",
        "yoyrate",
    )
    normalized = [
        "".join(character for character in column if character.isalnum()).casefold()
        for column in columns
    ]
    for name in preferred:
        if name in normalized:
            return normalized.index(name)
    return None


def _project_tabular_finding(finding: Mapping[str, Any], *, row_limit: int) -> dict[str, Any]:
    columns = list(finding["columns"])
    rows = [list(row) for row in finding["rows"]]
    rank_index = _summary_rank_column(columns, rows)
    if rank_index is None:
        leading = (row_limit + 1) // 2
        selected_indices = set(range(min(leading, len(rows))))
        selected_indices.update(range(max(leading, len(rows) - row_limit // 2), len(rows)))
    else:
        ranked = [
            (index, row[rank_index])
            for index, row in enumerate(rows)
            if rank_index < len(row)
            and isinstance(row[rank_index], (int, float))
            and not isinstance(row[rank_index], bool)
            and math.isfinite(float(row[rank_index]))
        ]
        positive = sorted(
            (item for item in ranked if item[1] >= 0), key=lambda item: (-item[1], item[0])
        )
        negative = sorted(
            (item for item in ranked if item[1] < 0), key=lambda item: (item[1], item[0])
        )
        selected_indices = {index for index, _value in positive[: (row_limit + 1) // 2]}
        selected_indices.update(index for index, _value in negative[: row_limit // 2])
        for index, _value in sorted(ranked, key=lambda item: (-abs(item[1]), item[0])):
            if len(selected_indices) >= row_limit:
                break
            selected_indices.add(index)

    ordered_indices = sorted(selected_indices)
    omitted_indices = [index for index in range(len(rows)) if index not in selected_indices]
    omitted_numeric_sums: dict[str, int | float] = {}
    for column_index, column in enumerate(columns):
        numeric_values = [
            row[column_index]
            for index in omitted_indices
            if column_index < len(rows[index])
            for row in (rows[index],)
            if isinstance(row[column_index], (int, float))
            and not isinstance(row[column_index], bool)
            and math.isfinite(float(row[column_index]))
        ]
        if numeric_values:
            if all(isinstance(value, int) for value in numeric_values):
                omitted_numeric_sums[column] = sum(numeric_values)
            else:
                total = math.fsum(float(value) for value in numeric_values)
                omitted_numeric_sums[column] = int(total) if total.is_integer() else total

    return {
        **{key: deepcopy(value) for key, value in finding.items() if key != "rows"},
        "rows": [rows[index] for index in ordered_indices],
        "view": {
            "format": "ranked_extremes" if rank_index is not None else "head_tail",
            "truncated": bool(omitted_indices),
            "rowCount": len(rows),
            "selectedRowCount": len(ordered_indices),
            "omittedRowCount": len(omitted_indices),
            "rankColumn": columns[rank_index] if rank_index is not None else None,
            "omittedNumericSums": omitted_numeric_sums,
        },
    }


def _project_analysis_summary_payload(
    payload: Mapping[str, Any],
    *,
    max_tokens: int,
    count_tokens: Callable[[Mapping[str, Any]], int],
) -> dict[str, Any]:
    """只投影摘要模型输入；完整 evidence 文件和 durable 状态保持不变。"""

    original = deepcopy(dict(payload))
    original_tokens = count_tokens(original)
    if original_tokens <= max_tokens:
        return original
    raw_evidence = original.get("supplementalEvidence")
    if not isinstance(raw_evidence, Mapping):
        raise ReportingError(
            "report_analysis_summary_context_too_large",
            "单项分析摘要基础事实超过模型输入预算。",
            details={"inputTokens": original_tokens, "inputTokenBudget": max_tokens},
        )
    raw_findings = raw_evidence.get("findings")
    if not isinstance(raw_findings, list):
        raw_findings = list(raw_findings) if isinstance(raw_findings, tuple) else []
    candidates = [
        index
        for index, finding in enumerate(raw_findings)
        if isinstance(finding, Mapping)
        and isinstance(finding.get("columns"), (list, tuple))
        and isinstance(finding.get("rows"), (list, tuple))
        and len(finding["rows"]) > 2
    ]
    candidates.sort(
        key=lambda index: len(
            json.dumps(raw_findings[index], ensure_ascii=False, separators=(",", ":"))
        ),
        reverse=True,
    )

    projected_indices: set[int] = set()
    row_limit = MAX_ANALYSIS_SUMMARY_PROJECTED_ROWS

    def build() -> dict[str, Any]:
        evidence = deepcopy(dict(raw_evidence))
        evidence["findings"] = [
            _project_tabular_finding(finding, row_limit=row_limit)
            if index in projected_indices and isinstance(finding, Mapping)
            else deepcopy(finding)
            for index, finding in enumerate(raw_findings)
        ]
        evidence["sourceFile"] = deepcopy(original.get("supplementalEvidenceSource"))
        evidence["projection"] = {
            "projected": True,
            "originalFindingCount": len(raw_findings),
            "projectedFindingCount": len(projected_indices),
        }
        return {**original, "supplementalEvidence": evidence}

    for index in candidates:
        projected_indices.add(index)
        candidate = build()
        if count_tokens(candidate) <= max_tokens:
            return candidate
    while projected_indices and row_limit > 2:
        row_limit = max(2, row_limit // 2)
        candidate = build()
        if count_tokens(candidate) <= max_tokens:
            return candidate
    candidate = build()
    projected_tokens = count_tokens(candidate)
    if projected_tokens <= max_tokens:
        return candidate
    raise ReportingError(
        "report_analysis_summary_context_too_large",
        "单项分析摘要在保留证据身份和守恒汇总后仍超过模型输入预算。",
        details={
            "inputTokens": original_tokens,
            "projectedTokens": projected_tokens,
            "inputTokenBudget": max_tokens,
            "projectedFindingCount": len(projected_indices),
        },
    )


DecideEvidence = Callable[[Mapping[str, Any]], Awaitable[AnalysisEvidenceDecision]]
GenerateScript = Callable[..., Awaitable[CodeGenerationResult]]
RepairScript = Callable[..., Awaitable[CodeGenerationResult]]
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
    decision: AnalysisEvidenceDecision | None = None
    evidence: SupplementalEvidence | None = None
    evidence_file: FileIdentity | None = None
    recovery: _DurableAnalysisCompletion | None = None
    script_file: FileIdentity | None = None
    failure: Exception | None = None
    warnings: list[str] = field(default_factory=list)
    generation_attempts: int = 0
    repair_count: int = 0
    supplement_abandoned: bool = False


class AnalysisItemWorkflow:
    """用 Agno 3.0.1 组合原语执行固定生命周期，不建立独立持久化 Workflow。"""

    def __init__(
        self,
        *,
        decide_evidence: DecideEvidence,
        generate_script: GenerateScript,
        repair_script: RepairScript,
        summarize: Summarize,
        read_file: ToolCall,
        run_script: ToolCall,
        complete: ToolCall,
    ) -> None:
        self.decide_evidence = decide_evidence
        self.generate_script = generate_script
        self.repair_script = repair_script
        self.summarize = summarize
        self.read_file = read_file
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
            return await self._timed_stage("plan-evidence", state, self._decide_evidence(state))

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
                state.decision is not None and state.decision.requires_supplemental_evidence
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
        interrupted = False
        try:
            output = await operation
        except BaseException as error:
            if not isinstance(error, Exception):
                interrupted = True
                raise
            state.failure = error
            state.statuses[stage_name] = "failed"
            raise
        finally:
            if not interrupted:
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

    async def _decide_evidence(self, state: _AnalysisItemState) -> StepOutput:
        if state.facts is None:
            raise ReportingError("report_analysis_facts_invalid", "固定 facts 尚未通过校验。")
        recovery = state.instruction.get("durableAnalysisItem")
        if isinstance(recovery, Mapping):
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
            state.decision = AnalysisEvidenceDecision(
                requiresSupplementalEvidence=False,
                reason="durable_completion_recovery",
                missingFacts=(),
            )
            state.statuses["plan-evidence"] = "completed"
            return StepOutput(content={"status": "durable_completion_recovery"})
        payload = {
            "currentAnalysis": state.instruction.get("currentAnalysis"),
            "deterministicFacts": self._model_facts(state),
        }
        decision = await self.decide_evidence(payload)
        state.decision = decision
        state.failure = None
        state.statuses["plan-evidence"] = "completed"
        return StepOutput(content=decision.model_dump(mode="json", by_alias=True))

    async def _execute_script(
        self, state: _AnalysisItemState, run_context: RunContext
    ) -> StepOutput:
        decision = state.decision
        if decision is None or not decision.requires_supplemental_evidence:
            raise ReportingError(
                "report_analysis_evidence_decision_invalid", "补充 evidence 决策无效。"
            )
        script_path = self._script_path(state)
        try:
            if state.script_file is None:
                state.generation_attempts += 1
                generated = await self.generate_script(
                    script_path=script_path,
                    task_facts=self._script_task_facts(state),
                    run_context=run_context,
                )
            elif state.failure is not None:
                if state.repair_count >= MAX_ANALYSIS_SCRIPT_REPAIRS:
                    return self._abandon_supplement(state)
                state.repair_count += 1
                generated = await self.repair_script(
                    script_file=state.script_file,
                    diagnostic=self._repair_diagnostic(state),
                    run_context=run_context,
                )
            else:
                raise ReportingError(
                    "report_analysis_script_state_invalid",
                    "补证脚本状态无法进入生成或修复阶段。",
                )
            state.script_file = self._signed_script_file(generated, script_path)
            state.failure = None
            execution = await self.run_script(
                script_path=state.script_file.path,
                run_context=run_context,
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
                output = str(error.details.get("output") or "")
                logger.warning(
                    "report_analysis_script_execution_failed analysis_id={} exit_code={} "
                    "output_truncated={} output_bytes={}",
                    state.instruction.get("currentAnalysisId"),
                    error.details.get("exitCode"),
                    error.details.get("outputTruncated"),
                    len(output.encode("utf-8")),
                )
            state.failure = error
            state.evidence = None
            exhausted = (
                state.script_file is None
                and state.generation_attempts >= MAX_ANALYSIS_SCRIPT_REPAIRS + 1
            ) or (
                state.script_file is not None and state.repair_count >= MAX_ANALYSIS_SCRIPT_REPAIRS
            )
            if exhausted:
                return self._abandon_supplement(state)
            state.statuses["execute-script"] = "retrying"
            return StepOutput(content={"status": "retry", "code": error.code})
        state.statuses["execute-script"] = "completed"
        return StepOutput(content={"status": "executed", "scriptPath": script_path})

    def _script_task_facts(self, state: _AnalysisItemState) -> dict[str, Any]:
        decision = state.decision
        if decision is None:
            raise ReportingError(
                "report_analysis_evidence_decision_invalid", "补充 evidence 决策缺失。"
            )
        return {
            "currentAnalysis": state.instruction.get("currentAnalysis"),
            "evidenceDecision": decision.model_dump(mode="json", by_alias=True),
            "datasets": state.instruction.get("datasets", []),
            "analysisOutputRoot": state.instruction.get("analysisOutputRoot"),
            "scriptPath": self._script_path(state),
            "evidencePath": self._evidence_path(state),
        }

    @staticmethod
    def _signed_script_file(result: CodeGenerationResult, script_path: str) -> FileIdentity:
        if not isinstance(result, CodeGenerationResult) or result.script_file.path != script_path:
            raise ReportingError(
                "report_phase_artifact_changed",
                "补充分析脚本写入回执不是签发路径的唯一文件身份。",
            )
        return result.script_file

    def _repair_diagnostic(self, state: _AnalysisItemState) -> dict[str, Any]:
        decision = state.decision
        script_file = state.script_file
        if decision is None or script_file is None:
            raise ReportingError(
                "report_analysis_script_repair_invalid",
                "脚本修复缺少既有事实缺口或签发文件身份。",
            )
        return {
            **self._repair_error(state.failure),
            "missingFacts": list(decision.missing_facts),
            "scriptPath": script_file.path,
        }

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
            evidence_payload = TypeAdapter(dict[str, Any]).validate_json(content)
            evidence_payload.pop("analysisId", None)
            evidence_payload.pop("analysis_id", None)
            evidence_payload.pop("datasetIds", None)
            evidence_payload.pop("dataset_ids", None)
            current_analysis = state.instruction.get("currentAnalysis")
            evidence = SupplementalEvidence.model_validate(
                {
                    **evidence_payload,
                    "analysisId": (
                        current_analysis.get("analysisId")
                        if isinstance(current_analysis, Mapping)
                        else None
                    ),
                    "datasetIds": self._dataset_ids(state),
                }
            )
        except ValidationError as error:
            rejection = ReportingError(
                "report_analysis_evidence_schema_invalid",
                "补充 evidence 不符合机器结构契约。",
                details={
                    "issues": error.errors(
                        include_url=False,
                        include_context=False,
                        include_input=False,
                    ),
                },
            )
            state.evidence = None
            state.evidence_file = None
            state.failure = rejection
            logger.warning(
                "report_analysis_evidence_validation_rejected analysis_id={} code={}",
                state.instruction.get("currentAnalysisId"),
                rejection.code,
            )
            if state.repair_count >= MAX_ANALYSIS_SCRIPT_REPAIRS:
                state.statuses["validate-evidence"] = "completed"
                return self._abandon_supplement(state)
            state.statuses["validate-evidence"] = "retrying"
            return StepOutput(content={"status": "retry", "code": rejection.code})
        except ReportingError as error:
            state.evidence = None
            state.evidence_file = None
            state.failure = error
            logger.warning(
                "report_analysis_evidence_validation_rejected analysis_id={} code={}",
                state.instruction.get("currentAnalysisId"),
                error.code,
            )
            if state.repair_count >= MAX_ANALYSIS_SCRIPT_REPAIRS:
                state.statuses["validate-evidence"] = "completed"
                return self._abandon_supplement(state)
            state.statuses["validate-evidence"] = "retrying"
            return StepOutput(content={"status": "retry", "code": error.code})
        state.evidence = evidence
        failed_reconciliations = [
            str(item["name"]) for item in evidence.reconciliations if item["passed"] is False
        ]
        if failed_reconciliations:
            state.warnings.append(
                "report_analysis_evidence_reconciliation_warning: "
                f"补充 evidence 业务对账未通过：{'、'.join(failed_reconciliations)}。"
            )
            logger.warning(
                "report_analysis_evidence_reconciliation_warning analysis_id={} failed_count={}",
                state.instruction.get("currentAnalysisId"),
                len(failed_reconciliations),
            )
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
        if sha256 is None:
            raise ReportingError(
                "report_analysis_evidence_changed",
                "补充 evidence 文件缺少冻结摘要。",
            )
        state.evidence_file = FileIdentity(
            path=self._evidence_path(state),
            size=total_bytes,
            sha256=sha256,
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
            "supplementalEvidenceSource": (
                state.evidence_file.model_dump(mode="json", by_alias=True)
                if state.evidence is not None and state.evidence_file is not None
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
        # 执行端口的成功回执可能不含统一 ok 字段；明确的 false 才是拒绝。
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
    "AnalysisItemWorkflow",
    "AnalysisItemWorkflowResult",
    "AnalysisSummaryDraft",
    "MAX_ANALYSIS_SCRIPT_REPAIRS",
]
