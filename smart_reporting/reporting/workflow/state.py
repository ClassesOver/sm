"""Reporting 运行的耐久状态、命令和服务端 reducer。

模型输出、Agno session_state 和 workspace 镜像都不是状态转移的事实来源。
本模块只接受服务端命令，并返回下一份完整聚合；调用方必须把结果通过
``ReportingRunStateRepository.apply`` 以 CAS 方式保存。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..delivery.draft_v1 import ReportChartRegistration
from .checkpoint import ChartVisualInspectionReceipt, FileIdentity

REPORTING_STATE_SCHEMA_VERSION = 3
MAX_INLINE_APPLIED_COMMANDS = 1000


class ReportingPhase(StrEnum):
    ANALYSIS_COVERAGE = "analysis_coverage"
    ANALYSIS_RUNNING = "analysis_running"
    VISUALIZATION = "visualization"
    ANALYSIS_FREEZING = "analysis_freezing"
    SECTIONS = "sections"
    ANALYSIS_REWORK = "analysis_rework"
    FINALIZE = "finalize"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportingStateError(ValueError):
    """对外稳定的 Reporting 状态错误。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ReportingStateConflict(ReportingStateError):
    def __init__(self, message: str = "Reporting 状态版本冲突。"):
        super().__init__("report_state_conflict", message)


class ReportingStateVersionUnsupported(ReportingStateError):
    def __init__(self, message: str = "Reporting 运行状态版本不受支持。"):
        super().__init__("report_state_version_unsupported", message)


class ReportingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    name: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    command_id: str = Field(alias="commandId", min_length=1, max_length=256)

    @classmethod
    def from_value(cls, value: ReportingCommand | Mapping[str, Any] | str) -> ReportingCommand:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(name=value, commandId=value)
        if not isinstance(value, Mapping):
            raise ReportingStateError("report_command_invalid", "Reporting command 必须是对象。")
        # 内部调用可使用 arguments 作为 payload；命令名称和 payload 仍由服务端白名单校验。
        raw_payload = value.get("payload", value.get("arguments", {}))
        if raw_payload is None:
            raw_payload = {}
        if not isinstance(raw_payload, Mapping):
            raise ReportingStateError("report_command_invalid", "Reporting command payload 无效。")
        command_id = value.get("commandId", value.get("command_id", value.get("id")))
        name = value.get("name", value.get("command"))
        if not isinstance(command_id, str) or not command_id:
            raise ReportingStateError("report_command_invalid", "Reporting command 缺少幂等键。")
        if not isinstance(name, str) or not name:
            raise ReportingStateError("report_command_invalid", "Reporting command 缺少名称。")
        return cls(name=name, payload=dict(raw_payload), commandId=command_id)


class ReportingRunState(BaseModel):
    """数据库行对应的完整 Reporting 聚合。

    业务事实全部保存在 ``payload``。顶层绑定字段不可由模型或 workspace 镜像
    修改；``state_version`` 只由 repository 的 CAS 更新递增。
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    report_run_id: str = Field(alias="reportRunId", min_length=1, max_length=256)
    external_run_id: str = Field(alias="externalRunId", min_length=1, max_length=256)
    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    owner_user_id: str = Field(alias="ownerUserId", min_length=1, max_length=256)
    revision: int = Field(default=1, ge=1)
    schema_version: int = Field(default=REPORTING_STATE_SCHEMA_VERSION, alias="schemaVersion")
    state_version: int = Field(default=0, alias="stateVersion", ge=0)
    phase: ReportingPhase
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @model_validator(mode="after")
    def validate_schema(self) -> ReportingRunState:
        if self.schema_version != REPORTING_STATE_SCHEMA_VERSION:
            raise ReportingStateVersionUnsupported()
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Reporting 状态时间必须包含时区")
        return self

    @classmethod
    def initial(
        cls,
        *,
        report_run_id: str,
        external_run_id: str,
        thread_id: str,
        owner_user_id: str,
        revision: int = 1,
        payload: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ReportingRunState:
        timestamp = now or datetime.now(UTC)
        initial_payload: dict[str, Any] = {
            "analysisIds": [],
            "completedAnalysisIds": [],
            "currentAnalysisId": None,
            "completedSections": [],
            "pendingSections": [],
            "rework": None,
            "errors": [],
            "warnings": [],
            "artifacts": [],
            "profileCoverage": None,
            "profileReadReceipts": [],
            "citations": [],
            "metricDefinitions": [],
            "analysisEvidenceManifest": None,
            "reportBrief": None,
            "writeIntents": {},
            "trace": [],
            "appliedCommands": {},
            "commandReceiptsVersion": 1,
        }
        if payload:
            initial_payload.update(dict(payload))
        return cls(
            reportRunId=report_run_id,
            externalRunId=external_run_id,
            threadId=thread_id,
            ownerUserId=owner_user_id,
            revision=revision,
            schemaVersion=REPORTING_STATE_SCHEMA_VERSION,
            stateVersion=0,
            phase=ReportingPhase.ANALYSIS_COVERAGE,
            payload=initial_payload,
            createdAt=timestamp,
            updatedAt=timestamp,
        )


@dataclass(frozen=True)
class ReportingEffect:
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ReportingReducerResult:
    state: ReportingRunState
    effects: tuple[ReportingEffect, ...] = ()
    idempotent: bool = False


_TRANSITIONS: dict[ReportingPhase, frozenset[ReportingPhase]] = {
    ReportingPhase.ANALYSIS_COVERAGE: frozenset(
        {ReportingPhase.ANALYSIS_RUNNING, ReportingPhase.FAILED}
    ),
    ReportingPhase.ANALYSIS_RUNNING: frozenset(
        {
            ReportingPhase.VISUALIZATION,
            ReportingPhase.ANALYSIS_REWORK,
            # 逐章 Reporting 工作流在本阶段内完成分析、图表和章节成稿；最终 Markdown
            # 由服务端确定性装配并已校验全部章节产物后直接完成，不再经过旧全局阶段。
            ReportingPhase.COMPLETED,
            ReportingPhase.FAILED,
        }
    ),
    ReportingPhase.VISUALIZATION: frozenset(
        {ReportingPhase.ANALYSIS_FREEZING, ReportingPhase.FAILED}
    ),
    ReportingPhase.ANALYSIS_FREEZING: frozenset({ReportingPhase.SECTIONS, ReportingPhase.FAILED}),
    ReportingPhase.SECTIONS: frozenset(
        {ReportingPhase.ANALYSIS_REWORK, ReportingPhase.FINALIZE, ReportingPhase.FAILED}
    ),
    ReportingPhase.ANALYSIS_REWORK: frozenset(
        {ReportingPhase.ANALYSIS_RUNNING, ReportingPhase.SECTIONS, ReportingPhase.FAILED}
    ),
    ReportingPhase.FINALIZE: frozenset({ReportingPhase.COMPLETED, ReportingPhase.FAILED}),
    ReportingPhase.COMPLETED: frozenset(),
    ReportingPhase.FAILED: frozenset(),
}


def _payload_copy(state: ReportingRunState) -> dict[str, Any]:
    return json.loads(json.dumps(state.payload, ensure_ascii=False, default=str))


def _tuple_unique(values: Any) -> list[Any]:
    if not isinstance(values, (list, tuple)):
        return []
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _transition(
    state: ReportingRunState,
    phase: ReportingPhase,
    payload: dict[str, Any],
    effects: list[ReportingEffect],
) -> None:
    if phase == state.phase:
        return
    if phase not in _TRANSITIONS[state.phase]:
        raise ReportingStateError(
            "report_state_transition_invalid",
            f"不能从 {state.phase.value} 转移到 {phase.value}。",
        )
    effects.append(ReportingEffect("phase_changed", {"from": state.phase.value, "to": phase.value}))


def apply(
    state: ReportingRunState,
    command: ReportingCommand | Mapping[str, Any] | str,
    expected_version: int | None = None,
) -> ReportingReducerResult:
    """唯一服务端 reducer。

    ``expected_version`` 用于在 reducer 入口尽早拒绝过期调用；repository 仍必须在
    SQL UPDATE 中再次执行同一 CAS。重复 ``command_id`` 只返回已保存状态，不产生
    新副作用或版本递增。
    """

    if state.schema_version != REPORTING_STATE_SCHEMA_VERSION:
        raise ReportingStateVersionUnsupported()
    command_value = ReportingCommand.from_value(command)
    if expected_version is not None and expected_version != state.state_version:
        raise ReportingStateConflict("Reporting command 使用了过期 stateVersion。")
    payload = _payload_copy(state)
    applied = payload.setdefault("appliedCommands", {})
    if not isinstance(applied, dict):
        raise ReportingStateError("report_state_invalid", "appliedCommands 状态损坏。")
    if command_value.command_id in applied:
        return ReportingReducerResult(state=state, idempotent=True)

    name = command_value.name
    arguments = command_value.payload
    effects: list[ReportingEffect] = []
    next_phase = state.phase

    phase_commands = {
        "start_analysis_coverage": ReportingPhase.ANALYSIS_RUNNING,
        "start_analysis": ReportingPhase.ANALYSIS_RUNNING,
        "start_visualization": ReportingPhase.VISUALIZATION,
        "freeze_analysis": ReportingPhase.ANALYSIS_FREEZING,
        "enter_sections": ReportingPhase.SECTIONS,
        "start_sections": ReportingPhase.SECTIONS,
        "request_analysis_rework": ReportingPhase.ANALYSIS_REWORK,
        "start_analysis_rework": ReportingPhase.ANALYSIS_REWORK,
        "resume_sections": ReportingPhase.SECTIONS,
        "start_finalize": ReportingPhase.FINALIZE,
        "finalize": ReportingPhase.FINALIZE,
        "complete": ReportingPhase.COMPLETED,
        "fail": ReportingPhase.FAILED,
    }
    if name in phase_commands:
        next_phase = phase_commands[name]
        if name in {"request_analysis_rework", "start_analysis_rework"}:
            analysis_ids = _tuple_unique(
                arguments.get("analysisIds", arguments.get("analysis_ids"))
            )
            missing = arguments.get("missingEvidence", arguments.get("missing_evidence", ()))
            if not analysis_ids or not isinstance(missing, (list, tuple)) or not missing:
                raise ReportingStateError(
                    "report_analysis_rework_invalid",
                    "targeted rework 必须包含 analysisIds 和 missingEvidence。",
                )
            payload["rework"] = {
                "analysisIds": analysis_ids,
                "missingEvidence": [str(item) for item in missing],
                "reason": str(arguments.get("reason", "")),
            }
            unknown = set(analysis_ids) - set(_tuple_unique(payload.get("analysisIds")))
            if unknown:
                raise ReportingStateError(
                    "report_analysis_rework_invalid", "targeted rework 引用了未知 analysisId。"
                )
            completed_analysis = _tuple_unique(payload.get("completedAnalysisIds"))
            payload["completedAnalysisIds"] = [
                item for item in completed_analysis if item not in analysis_ids
            ]
            analysis_items = payload.get("analysisItems")
            if isinstance(analysis_items, dict):
                payload["analysisItems"] = {
                    key: value for key, value in analysis_items.items() if key not in analysis_ids
                }
            payload["currentAnalysisId"] = next(
                (
                    item
                    for item in _tuple_unique(payload.get("analysisIds"))
                    if item not in payload["completedAnalysisIds"]
                ),
                None,
            )
            section_artifacts = payload.get("sectionArtifacts")
            invalid_sections: list[str] = []
            if isinstance(section_artifacts, dict):
                for section_code, artifact in list(section_artifacts.items()):
                    bound_ids = (
                        artifact.get("analysisIds") if isinstance(artifact, Mapping) else None
                    )
                    if isinstance(bound_ids, (list, tuple)) and set(bound_ids) & set(analysis_ids):
                        invalid_sections.append(section_code)
                        section_artifacts.pop(section_code, None)
            payload["completedSections"] = [
                item
                for item in _tuple_unique(payload.get("completedSections"))
                if item not in invalid_sections
            ]
            running_sections = payload.get("runningSections")
            if isinstance(running_sections, dict):
                # 返工会重新构造失效章节的 WorkItem，必须先撤销旧运行绑定；
                # 否则新 hash 会被 start_section 的并发冲突保护误判为另一任务。
                payload["runningSections"] = {
                    section_code: work_item_hash
                    for section_code, work_item_hash in running_sections.items()
                    if section_code not in invalid_sections
                }
            payload["pendingSections"] = _tuple_unique(
                [*payload.get("pendingSections", []), *invalid_sections]
            )
            # 返工只作废受影响章节的图表与章节产物；其它章节的 durable 图表事实保持不变。
            visualization_sections = payload.get("visualizationSections")
            if isinstance(visualization_sections, dict):
                for section_code in invalid_sections:
                    visualization_sections.pop(section_code, None)
            completed_visualization = payload.get("completedVisualizationSections")
            if isinstance(completed_visualization, list):
                payload["completedVisualizationSections"] = [
                    item for item in completed_visualization if item not in invalid_sections
                ]
            payload["reportBrief"] = None
            payload["analysisEvidenceManifest"] = None
            workflow_checkpoint = payload.get("workflowCheckpoint")
            if isinstance(workflow_checkpoint, dict):
                # Durable reducer 与 Workflow checkpoint 必须在同一个 CAS 中撤销旧冻结身份；
                # 否则返工后的新 Brief/Manifest 会与旧 checkpoint 合并并被误判为并发冲突。
                payload["workflowCheckpoint"] = {
                    **workflow_checkpoint,
                    "phase": "analysis",
                    "reportBrief": None,
                    "evidenceManifest": None,
                    "analysisManifestFile": None,
                }
                payload["checkpointMirrorFile"] = None
            effects.append(ReportingEffect("analysis_rework_requested", dict(payload["rework"])))
        elif name == "fail":
            error = arguments.get("error", arguments)
            payload["lastError"] = error if isinstance(error, dict) else {"message": str(error)}
            payload.setdefault("errors", []).append(payload["lastError"])
        elif name == "complete":
            payload["result"] = dict(arguments)
            effects.append(ReportingEffect("run_completed", dict(arguments)))
    elif name in {"set_plan", "set_analysis_plan"}:
        analysis_ids = _tuple_unique(arguments.get("analysisIds", arguments.get("analysis_ids")))
        if not analysis_ids:
            raise ReportingStateError("report_analysis_plan_invalid", "分析计划不能为空。")
        payload["analysisIds"] = analysis_ids
        raw_plans = arguments.get("analysisPlans")
        if raw_plans is not None:
            if not isinstance(raw_plans, dict) or set(raw_plans) != set(analysis_ids):
                raise ReportingStateError(
                    "report_analysis_plan_invalid", "分析计划明细与 analysisId 不一致。"
                )
            payload["analysisPlans"] = deepcopy(raw_plans)
        payload["completedAnalysisIds"] = [
            value
            for value in _tuple_unique(payload.get("completedAnalysisIds"))
            if value in analysis_ids
        ]
        payload["currentAnalysisId"] = next(
            (value for value in analysis_ids if value not in payload["completedAnalysisIds"]), None
        )
    elif name in {"complete_analysis_item", "analysis_item_completed"}:
        analysis_id = arguments.get("analysisId", arguments.get("analysis_id"))
        if not isinstance(analysis_id, str) or not analysis_id:
            raise ReportingStateError("report_analysis_item_invalid", "缺少 analysisId。")
        plan = _tuple_unique(payload.get("analysisIds"))
        if plan and analysis_id not in plan:
            raise ReportingStateError(
                "report_analysis_item_unknown", "analysisId 不在服务端计划中。"
            )
        completed = _tuple_unique(payload.get("completedAnalysisIds"))
        if analysis_id in completed:
            raise ReportingStateError("report_analysis_item_duplicate", "analysisId 已完成。")
        evidence = dict(arguments)
        evidence["analysisId"] = analysis_id
        items = payload.setdefault("analysisItems", {})
        if not isinstance(items, dict):
            raise ReportingStateError("report_state_invalid", "analysisItems 状态损坏。")
        items[analysis_id] = evidence
        completed.append(analysis_id)
        payload["completedAnalysisIds"] = completed
        payload["currentAnalysisId"] = next(
            (value for value in plan if value not in completed), None
        )
        effects.append(ReportingEffect("analysis_item_completed", {"analysisId": analysis_id}))
        # 分析期间按章节交错执行图表和成稿；全局 durable phase 保持
        # ANALYSIS_RUNNING，最终汇总前不切换到独立 visualization 阶段。
    elif name in {"set_profile_coverage", "profile_coverage_ready"}:
        payload["profileCoverage"] = arguments.get("manifest", arguments)
    elif name in {"record_profile_receipt", "profile_read"}:
        receipt = arguments.get("receipt", arguments)
        receipts = payload.setdefault("profileReadReceipts", [])
        if not isinstance(receipts, list):
            raise ReportingStateError("report_state_invalid", "profileReadReceipts 状态损坏。")
        receipt_id = receipt.get("receiptId") if isinstance(receipt, Mapping) else None
        if not isinstance(receipt_id, str):
            raise ReportingStateError(
                "report_profile_receipt_invalid", "Profile receipt 缺少 receiptId。"
            )
        if not any(
            isinstance(item, Mapping) and item.get("receiptId") == receipt_id for item in receipts
        ):
            receipts.append(dict(receipt))
    elif name == "record_chart_inspection":
        try:
            receipt = ChartVisualInspectionReceipt.model_validate(
                arguments.get("receipt")
            ).model_dump(mode="json", by_alias=True)
        except ValidationError as error:
            raise ReportingStateError(
                "report_chart_inspection_invalid", "图表视觉检查回执无效。"
            ) from error
        source_path = receipt["sourcePath"]
        sha256 = receipt["sha256"]
        receipts = payload.setdefault("chartInspectionReceipts", [])
        if not isinstance(receipts, list):
            raise ReportingStateError("report_state_invalid", "chartInspectionReceipts 状态损坏。")
        existing = next(
            (
                item
                for item in receipts
                if isinstance(item, Mapping)
                and item.get("sourcePath") == source_path
                and item.get("sha256") == sha256
            ),
            None,
        )
        if existing is not None and dict(existing) != dict(receipt):
            raise ReportingStateError(
                "report_chart_inspection_conflict",
                "同一图表文件身份已绑定不同视觉检查回执。",
            )
        if existing is None:
            receipts.append(dict(receipt))
    elif name == "submit_visualization_charts":
        # 章节图表草案提交允许零图，但 sectionCode 一旦写入就代表该章节已完成；
        # chartId/sourcePath 必须在所有章节中全局唯一，且登记关闭后不得再改变提交事实。
        if state.phase not in {ReportingPhase.ANALYSIS_RUNNING, ReportingPhase.VISUALIZATION}:
            raise ReportingStateError(
                "report_visualization_section_phase_invalid", "章节图表只能在分析运行阶段提交。"
            )
        section_code = arguments.get("sectionCode")
        charts = arguments.get("charts")
        files = arguments.get("files")
        if not isinstance(section_code, str) or not 1 <= len(section_code) <= 128:
            raise ReportingStateError(
                "report_visualization_section_invalid", "章节图表提交缺少有效 sectionCode。"
            )
        if not isinstance(charts, list) or not isinstance(files, list):
            raise ReportingStateError(
                "report_visualization_section_invalid",
                "章节图表提交的 charts 和 files 必须是列表。",
            )
        try:
            parsed_charts = [
                ReportChartRegistration.model_validate(chart).model_dump(mode="json", by_alias=True)
                for chart in charts
            ]
            parsed_files = [
                FileIdentity.model_validate(file).model_dump(mode="json", by_alias=True)
                for file in files
            ]
        except ValidationError as error:
            raise ReportingStateError(
                "report_visualization_section_invalid", "章节图表提交包含无效图表或文件身份。"
            ) from error

        chart_ids = [chart["chartId"] for chart in parsed_charts]
        source_paths = [chart["sourcePath"] for chart in parsed_charts]
        if len(chart_ids) != len(set(chart_ids)) or len(source_paths) != len(set(source_paths)):
            raise ReportingStateError(
                "report_visualization_section_conflict",
                "章节图表提交包含重复 chartId 或 sourcePath。",
            )
        sections = payload.setdefault("visualizationSections", {})
        if not isinstance(sections, dict):
            raise ReportingStateError("report_state_invalid", "visualizationSections 状态损坏。")
        # 工具层的预检只覆盖其读取到的快照；CAS 冲突重试会把同一 command 送入这里的
        # 最新状态。sectionCode 一旦落库即为终态事实：完全一致的重放可继续走幂等路径，
        # 任何 charts/files 差异都必须在写入前拒绝，不能由后来的提交覆盖原章节。
        if section_code in sections:
            existing_section = sections[section_code]
            if not isinstance(existing_section, Mapping):
                raise ReportingStateError(
                    "report_state_invalid", "visualizationSections 状态损坏。"
                )
            existing_charts = existing_section.get("charts")
            existing_files = existing_section.get("files")
            if not isinstance(existing_charts, list) or not isinstance(existing_files, list):
                raise ReportingStateError(
                    "report_state_invalid", "visualizationSections 状态损坏。"
                )
            if existing_charts != parsed_charts or existing_files != parsed_files:
                raise ReportingStateError(
                    "report_visualization_section_conflict",
                    "当前章节已提交不同的图表事实或文件身份。",
                )
        existing_chart_ids: set[str] = set()
        existing_source_paths: set[str] = set()
        for existing_section_code, existing_section in sections.items():
            if existing_section_code == section_code:
                continue
            if not isinstance(existing_section, Mapping):
                raise ReportingStateError(
                    "report_state_invalid", "visualizationSections 状态损坏。"
                )
            existing_charts = existing_section.get("charts", [])
            if not isinstance(existing_charts, list):
                raise ReportingStateError(
                    "report_state_invalid", "visualizationSections 状态损坏。"
                )
            for chart in existing_charts:
                if isinstance(chart, Mapping):
                    chart_id = chart.get("chartId")
                    source_path = chart.get("sourcePath")
                    if isinstance(chart_id, str):
                        existing_chart_ids.add(chart_id)
                    if isinstance(source_path, str):
                        existing_source_paths.add(source_path)
        if set(chart_ids) & existing_chart_ids or set(source_paths) & existing_source_paths:
            raise ReportingStateError(
                "report_visualization_section_conflict",
                "章节图表与既有章节包含重复 chartId 或 sourcePath。",
            )
        sections[section_code] = {"charts": parsed_charts, "files": parsed_files}
        completed = payload.setdefault("completedVisualizationSections", [])
        if not isinstance(completed, list):
            raise ReportingStateError(
                "report_state_invalid", "completedVisualizationSections 状态损坏。"
            )
        if section_code not in completed:
            completed.append(section_code)
    elif name in {"set_analysis_artifact", "set_report_brief"}:
        if "reportBrief" in arguments:
            payload["reportBrief"] = arguments["reportBrief"]
        if "evidenceManifest" in arguments:
            payload["analysisEvidenceManifest"] = arguments["evidenceManifest"]
        if "warnings" in arguments:
            payload["warnings"] = _tuple_unique(
                [*payload.get("warnings", []), *arguments["warnings"]]
            )
    elif name == "set_workflow_checkpoint":
        checkpoint = arguments.get("checkpoint")
        if not isinstance(checkpoint, Mapping):
            raise ReportingStateError("report_checkpoint_invalid", "Workflow checkpoint 无效。")
        payload["workflowCheckpoint"] = dict(checkpoint)
        mirror = arguments.get("mirrorFile")
        if isinstance(mirror, Mapping):
            payload["checkpointMirrorFile"] = dict(mirror)
    elif name == "start_section":
        section_code = arguments.get("sectionCode")
        work_item_hash = arguments.get("workItemHash")
        if not isinstance(section_code, str) or not isinstance(work_item_hash, str):
            raise ReportingStateError("report_section_invalid", "章节启动参数无效。")
        running = payload.setdefault("runningSections", {})
        if not isinstance(running, dict):
            raise ReportingStateError("report_state_invalid", "runningSections 状态损坏。")
        existing = running.get(section_code)
        if existing is not None and existing != work_item_hash:
            raise ReportingStateError(
                "report_section_start_conflict", "sectionCode 已绑定其他 WorkItem。"
            )
        running[section_code] = work_item_hash
    elif name in {"complete_section", "section_completed"}:
        section_code = arguments.get("sectionCode", arguments.get("section_code"))
        if not isinstance(section_code, str) or not section_code:
            raise ReportingStateError("report_section_invalid", "缺少 sectionCode。")
        raw_completed_section_artifacts = payload.get("sectionArtifacts")
        completed_section_artifacts: dict[str, Any] = (
            raw_completed_section_artifacts
            if isinstance(raw_completed_section_artifacts, dict)
            else {}
        )
        existing = completed_section_artifacts.get(section_code)
        if isinstance(existing, Mapping) and dict(existing) != dict(arguments):
            raise ReportingStateError(
                "report_section_completion_conflict",
                "sectionCode 已绑定其他完成产物。",
            )
        completed = payload.setdefault("completedSections", [])
        if section_code not in completed:
            completed.append(section_code)
        payload["sectionArtifacts"] = {
            **completed_section_artifacts,
            section_code: dict(arguments),
        }
        running = payload.get("runningSections")
        if isinstance(running, dict):
            running.pop(section_code, None)
    elif name == "record_write_intent":
        intent = arguments.get("intent", arguments)
        intent_id = intent.get("intentId") if isinstance(intent, Mapping) else None
        if not isinstance(intent_id, str) or not intent_id:
            raise ReportingStateError(
                "report_analysis_write_intent_invalid", "写入意图缺少 intentId。"
            )
        intents = payload.setdefault("writeIntents", {})
        if not isinstance(intents, dict):
            raise ReportingStateError("report_state_invalid", "writeIntents 状态损坏。")
        existing = intents.get(intent_id)
        prepared = {**dict(intent), "status": "pending"}
        if existing is not None and existing != prepared:
            raise ReportingStateError(
                "report_analysis_write_intent_conflict", "写入意图已绑定其他参数或终态。"
            )
        intents[intent_id] = prepared
    elif name == "commit_write_intent":
        intent_id = arguments.get("intentId")
        artifacts = arguments.get("artifacts")
        intents = payload.setdefault("writeIntents", {})
        if (
            not isinstance(intent_id, str)
            or not isinstance(intents, dict)
            or not isinstance(intents.get(intent_id), Mapping)
            or not isinstance(artifacts, list)
        ):
            raise ReportingStateError(
                "report_analysis_write_intent_unknown", "待提交写入意图不存在。"
            )
        current = dict(intents[intent_id])
        if current.get("status") == "committed":
            if current.get("artifacts") != artifacts:
                raise ReportingStateError(
                    "report_analysis_write_identity_mismatch", "写入意图已绑定其他文件身份。"
                )
        else:
            # intent 的映射位置来自 record 顺序，不能代表写入真正完成的先后。首次提交时
            # 冻结 reducer 即将生成的 stateVersion，供恢复读取按耐久提交事实选择最新身份；
            # 已 committed 的幂等重试不得刷新该序号，因为它没有再次执行文件写入。
            current.update(
                {
                    "status": "committed",
                    "artifacts": artifacts,
                    "commitSequence": state.state_version + 1,
                }
            )
            intents[intent_id] = current
    elif name == "record_artifact":
        artifacts = payload.setdefault("artifacts", [])
        if not isinstance(artifacts, list):
            raise ReportingStateError("report_state_invalid", "artifacts 状态损坏。")
        artifact = arguments.get("artifact", arguments)
        if isinstance(artifact, Mapping):
            path = artifact.get("path")
            if isinstance(path, str):
                existing = next(
                    (
                        item
                        for item in artifacts
                        if isinstance(item, Mapping) and item.get("path") == path
                    ),
                    None,
                )
                if existing is not None and dict(existing) != dict(artifact):
                    raise ReportingStateError(
                        "report_artifact_identity_mismatch",
                        "文件路径已绑定其他不可变身份。",
                    )
                if existing is None:
                    artifacts.append(dict(artifact))
    elif name == "trace":
        trace = payload.setdefault("trace", [])
        if isinstance(trace, list):
            trace.append(dict(arguments))
    else:
        raise ReportingStateError("report_command_unknown", f"未知 Reporting command: {name}。")

    _transition(state, next_phase, payload, effects)
    applied[command_value.command_id] = {
        "name": name,
        "resultHash": hashlib.sha256(
            json.dumps(
                {"phase": next_phase.value, "payload": payload},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest(),
    }
    # 只保留最近的幂等键，防止无限增长；状态本身仍以 state_version 作为顺序事实。
    if len(applied) > MAX_INLINE_APPLIED_COMMANDS:
        for key in list(applied)[:-MAX_INLINE_APPLIED_COMMANDS]:
            applied.pop(key, None)
    new_state = state.model_copy(
        update={
            "phase": next_phase,
            "payload": payload,
            "state_version": state.state_version + 1,
            "updated_at": datetime.now(UTC),
        }
    )
    return ReportingReducerResult(state=new_state, effects=tuple(effects))


class ReportingStateReducer:
    """面向依赖注入的 reducer 外观。"""

    @staticmethod
    def apply(
        state: ReportingRunState,
        command: ReportingCommand | Mapping[str, Any] | str,
        expected_version: int | None = None,
    ) -> ReportingReducerResult:
        return apply(state, command, expected_version)
