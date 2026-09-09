"""Reporting 工具的公共运行时与 Agno Toolkit 基类。"""

# mypy: disable-error-code="attr-defined"
# Toolkit 由领域 mixin 组合，公共包装会调用其他 mixin 提供的门禁方法；Mypy 无法解析该 MRO 注入。

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any, cast

from agno.run import RunContext
from agno.tools import Toolkit
from pydantic import ValidationError

from ...agent_control import AGENT_PLAN_STATE_KEY, validated_agent_plan
from ...task_execution import (
    DEFAULT_TERMINAL_TIMEOUT,
    MAX_READ_FILE_BYTES,
    MAX_TOOL_OUTPUT_READ_BYTES,
    TERMINAL_EXECUTION_STATUSES,
)
from ...workspace import (
    WorkspaceError,
    WorkspaceService,
)
from ..models import ReportingError
from ..phase import ReportingPhase, ReportingTaskKind, reporting_phase_allows_tool
from ..workflow.checkpoint import FileIdentity
from ..workflow.state import (
    ReportingCommand,
    ReportingReducerResult,
    ReportingRunState,
    ReportingStateError,
)
from .visualization import MAX_VISUALIZATION_SCRIPT_BYTES
from .workspace_adapter import WorkspaceServiceReportingRuntime

SUPPLEMENTAL_EVIDENCE_READ_BYTES = 128 * 1024


class ReportingToolRuntime(WorkspaceServiceReportingRuntime):
    """将中立任务内核和 Reporting 工作区端口组合为工具运行时。"""


class ReportingToolkitBase(Toolkit):
    """Reporting Toolkit 的统一执行包装、持久化状态与错误回执边界。"""

    @staticmethod
    def failure(error: Exception, *, retryable: bool = True) -> dict[str, Any]:
        code = str(getattr(error, "code", "report_tool_failed"))
        message = str(getattr(error, "message", error))[:1000]
        details = getattr(error, "details", None)
        return {
            "ok": False,
            "status": "rejected",
            "code": code,
            "message": message,
            "details": details if isinstance(details, dict) else {},
            "retryable": retryable,
        }

    async def run_python_script(
        self,
        script_path: str,
        timeout: int = DEFAULT_TERMINAL_TIMEOUT,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self._invoke(
            "run_python_script",
            {"script_path": script_path, "timeout": timeout},
            lambda scope: self.runtime.execute_script(
                script_path,
                timeout=timeout,
                _scope=scope,
            ),
            run_context,
        )

    async def read_file(
        self,
        path: str,
        offset: int = 0,
        max_bytes: int = MAX_TOOL_OUTPUT_READ_BYTES,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise WorkspaceError("read_file offset 必须是大于等于 0 的整数。")
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 1 <= max_bytes <= MAX_READ_FILE_BYTES
        ):
            raise WorkspaceError(
                f"read_file max_bytes 必须是 1 至 {MAX_READ_FILE_BYTES} 之间的整数。"
            )

        async def call(scope: Any) -> dict[str, Any]:
            content, _mime = await self.runtime.workspace.afile_bytes(scope.thread_id, path)
            if offset > len(content):
                raise WorkspaceError("read_file offset 超过文件大小。")
            end = min(len(content), offset + max_bytes)
            while end > offset:
                try:
                    selected = content[offset:end].decode("utf-8")
                    break
                except UnicodeDecodeError:
                    end -= 1
            else:
                selected = ""
            if not selected and offset < len(content):
                raise WorkspaceError("read_file max_bytes 不足以读取下一个 UTF-8 字符。")
            return {
                "path": WorkspaceService.normalize_path(path, allow_root=False)[0],
                "offset": offset,
                "nextOffset": end,
                "totalBytes": len(content),
                "content": selected,
                "hasMore": end < len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }

        return await self._invoke(
            "read_file",
            {"path": path, "offset": offset, "max_bytes": max_bytes},
            call,
            run_context,
        )

    async def view_image(
        self,
        path: str,
        detail: str = "high",
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if detail not in {"high", "original"}:
            raise WorkspaceError("图片 detail 必须是 high 或 original。")
        reviewer = self._vision_reviewer
        if reviewer is None:
            raise WorkspaceError("当前 Reporting Agent 未启用图片视觉审查。")

        async def call(scope: Any) -> dict[str, Any]:
            return await reviewer.review(
                scope.thread_id,
                path,
                detail=detail,
            )

        return await self._invoke("view_image", {"path": path, "detail": detail}, call, run_context)

    @staticmethod
    def _session_state(run_context: RunContext | None) -> dict[str, Any] | None:
        if run_context is not None and isinstance(run_context.session_state, dict):
            return run_context.session_state
        return None

    @staticmethod
    def _artifact_parameters(scope: Any) -> dict[str, Any]:
        acceptance_contract = scope.task.acceptance_contract
        requirements = (
            acceptance_contract.get("requirements")
            if isinstance(acceptance_contract, dict)
            else None
        )
        requirement = (
            requirements[0] if isinstance(requirements, list) and len(requirements) == 1 else None
        )
        parameters = requirement.get("parameters") if isinstance(requirement, dict) else None
        if not isinstance(parameters, dict):
            raise ReportingError(
                "report_draft_contract_missing", "当前 Reporting Task 缺少服务端验收参数。"
            )
        return parameters

    @classmethod
    def _active_reporting_phase(cls, scope: Any) -> ReportingPhase:
        phase = cls._artifact_parameters(scope).get("phase")
        if phase not in {"analysis", "section"}:
            raise ReportingError("report_phase_contract_invalid", "Reporting phase 参数无效。")
        return cast(ReportingPhase, phase)

    @classmethod
    def _active_reporting_task_kind(cls, scope: Any) -> ReportingTaskKind:
        parameters = cls._artifact_parameters(scope)
        phase_contract = parameters.get("phaseContract")
        task_kind = phase_contract.get("taskKind") if isinstance(phase_contract, dict) else None
        if task_kind not in {
            "analysis_item",
            "visualization_section",
            "section",
        }:
            raise ReportingError("report_phase_contract_invalid", "Reporting taskKind 参数无效。")
        return cast(ReportingTaskKind, task_kind)

    @classmethod
    def _require_phase_tool(
        cls,
        scope: Any,
        *,
        allowed: frozenset[str],
        tool_name: str,
        run_context: RunContext | None = None,
        task_kinds: frozenset[ReportingTaskKind] | None = None,
    ) -> None:
        phase = cls._active_reporting_phase(scope)
        if phase not in allowed:
            raise ReportingError(
                "report_phase_tool_forbidden",
                f"phase={phase} 不能调用 {tool_name}。",
            )
        task_kind = cls._active_reporting_task_kind(scope)
        if task_kinds is not None and task_kind not in task_kinds:
            raise ReportingError(
                "report_phase_tool_forbidden",
                f"taskKind={task_kind} 不能调用 {tool_name}。",
            )

    def _retain_bounded_tool_result(self, scope: Any, tool_name: str) -> bool:
        phase = self._active_reporting_phase(scope)
        return (phase == "analysis" and tool_name not in {"read_tool_output", "finish_task"}) or (
            phase == "section" and tool_name == "read_file"
        )

    def _tool_preview_bytes(
        self,
        scope: Any,
        tool_name: str,
        arguments: Mapping[str, Any],
        result: Any,
    ) -> int | None:
        _ = result
        if tool_name != "read_file":
            return None
        if self._active_reporting_phase(scope) == "section":
            # SectionWorkflow 直接消费结构化分页回执；这里必须覆盖单页正文及 JSON
            # 元数据，不能让通用预览层把 content 改写为 output 或截断后仍推进游标。
            return MAX_READ_FILE_BYTES
        if self._active_reporting_phase(scope) != "analysis":
            return None
        task_kind = self._active_reporting_task_kind(scope)
        try:
            requested = WorkspaceService.normalize_path(arguments.get("path"), allow_root=False)[0]
            _parameters, contract = self._phase_parameters(scope, "analysis")
            if task_kind == "analysis_item":
                analysis_id = contract.get("currentAnalysisId")
                fact_files = contract.get("deterministicFactFiles")
                fact_file = (
                    fact_files.get(analysis_id)
                    if isinstance(analysis_id, str) and isinstance(fact_files, Mapping)
                    else None
                )
                signed = WorkspaceService.normalize_path(
                    fact_file.get("path") if isinstance(fact_file, Mapping) else None,
                    allow_root=False,
                )[0]
                # 五阶段子流程会直接校验完整固定 facts；仅该签发文件可避开
                # 通用模型回显截断。预算必须覆盖 64 KiB 正文外的结构化游标、
                # size 和 SHA 元数据，否则压缩器会把整份回执改写成 output 字符串。
                if requested == signed:
                    return MAX_READ_FILE_BYTES
                evidence_root = contract.get("analysisOutputRoot")
                evidence_path = WorkspaceService.normalize_path(
                    f"{str(evidence_root or '').rstrip('/')}/supplement.json",
                    allow_root=False,
                )[0]
                return SUPPLEMENTAL_EVIDENCE_READ_BYTES if requested == evidence_path else None
            if task_kind != "visualization_section":
                return None
            workspace = contract.get("visualizationWorkspace")
            script_path = workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
            signed = WorkspaceService.normalize_path(script_path, allow_root=False)[0]
        except WorkspaceError:
            return None
        return MAX_VISUALIZATION_SCRIPT_BYTES if requested == signed else None

    def _no_progress_exempt(
        self,
        *,
        scope: Any,
        tool_name: str,
        arguments: Mapping[str, Any],
        run_context: RunContext | None,
    ) -> bool:
        _ = scope, tool_name, arguments, run_context
        return False

    async def _bound_analysis_result(
        self,
        *,
        scope: Any,
        tool_name: str,
        result: dict[str, Any],
        run_context: RunContext | None,
        preview_bytes: int | None = None,
    ) -> dict[str, Any]:
        if (
            self._active_reporting_phase(scope) != "analysis"
            or tool_name == "read_tool_output"
            or isinstance(result.get("outputHandle"), str)
        ):
            return result
        return await self.runtime.bound_tool_result(
            scope,
            result,
            run_context,
            retain=True,
            preview_bytes=preview_bytes,
        )

    async def _record_and_bound_profile_result(
        self,
        *,
        scope: Any,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        run_context: RunContext | None,
        preview_bytes: int | None = None,
    ) -> dict[str, Any]:
        bounded = await self._bound_analysis_result(
            scope=scope,
            tool_name=tool_name,
            result=result,
            run_context=run_context,
            preview_bytes=preview_bytes,
        )
        return bounded

    async def read_tool_output(
        self,
        handle: str,
        offset: int = 0,
        max_bytes: int = MAX_TOOL_OUTPUT_READ_BYTES,
        _agno_run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """用 Agno 内部注入上下文原子累计恢复分页。"""

        result = await self._invoke(
            "read_tool_output",
            {"handle": handle, "offset": offset, "max_bytes": max_bytes},
            lambda scope: self.runtime.read_tool_output(
                handle,
                offset,
                max_bytes,
                _agno_run_context,
                _scope=scope,
            ),
            _agno_run_context,
        )
        return result

    async def _read_trusted_json(
        self,
        *,
        thread_id: str,
        identity: Any,
        identity_code: str,
        structure_code: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(identity, dict)
            or not isinstance(identity.get("path"), str)
            or not isinstance(identity.get("size"), int)
            or identity["size"] <= 0
            or not isinstance(identity.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]) is None
        ):
            raise ReportingError(identity_code, "受信 JSON 文件身份缺失或无效。")
        content, _mime = await self.runtime.workspace.afile_bytes(thread_id, identity["path"])
        if (
            len(content) != identity["size"]
            or hashlib.sha256(content).hexdigest() != identity["sha256"]
        ):
            raise ReportingError(identity_code, "受信 JSON 文件身份校验失败。")
        try:
            value = json.loads(content)
        except (TypeError, ValueError) as error:
            raise ReportingError(structure_code, "受信 JSON 文件无法解析。") from error
        if not isinstance(value, dict):
            raise ReportingError(structure_code, "受信 JSON 文件必须为对象。")
        return value

    async def _write_phase_json(
        self,
        *,
        scope: Any,
        path: str,
        payload: dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.runtime.workspace.validate_content(content)
        current = (await self.runtime.workspace.batch_hash_files(scope.thread_id, [path]))[0]
        mode = "create" if current.get("missing") is True else "overwrite"
        result = await self.runtime.patch(
            mode,
            path,
            None,
            None,
            False,
            None,
            run_context,
            content=content.decode("utf-8"),
            expected_sha256=current.get("sha256") if mode == "overwrite" else None,
            _scope=scope,
        )
        if result.get("ok") is not True:
            raise ReportingError("report_phase_artifact_write_failed", "阶段产物写入失败。")
        identity = await self.runtime.workspace.hash_file(scope.thread_id, path)
        if (
            identity.get("missing")
            or identity.get("size") != len(content)
            or identity.get("sha256") != hashlib.sha256(content).hexdigest()
        ):
            raise ReportingError("report_phase_artifact_changed", "阶段产物写入后发生变化。")
        return FileIdentity.model_validate(identity).model_dump(mode="json", by_alias=True)

    @staticmethod
    def _phase_parameters(scope: Any, expected_phase: str) -> tuple[dict[str, Any], dict[str, Any]]:
        parameters = ReportingToolkitBase._artifact_parameters(scope)
        phase_contract = parameters.get("phaseContract")
        if parameters.get("phase") != expected_phase or not isinstance(phase_contract, dict):
            raise ReportingError(
                "report_phase_contract_invalid", f"当前 Task 不是有效的 {expected_phase} 阶段。"
            )
        return parameters, phase_contract

    @staticmethod
    def _require_current_analysis_dataset(contract: Mapping[str, Any], dataset_id: str) -> None:
        """analysis item 只能读取当前计划项绑定的 Dataset。"""

        if contract.get("taskKind") != "analysis_item":
            return
        current_analysis_id = contract.get("currentAnalysisId")
        datasets_by_analysis = contract.get("analysisDatasetIds")
        allowed = (
            datasets_by_analysis.get(current_analysis_id)
            if isinstance(current_analysis_id, str) and isinstance(datasets_by_analysis, Mapping)
            else None
        )
        if not isinstance(allowed, list) or any(not isinstance(item, str) for item in allowed):
            raise ReportingError(
                "report_phase_contract_invalid",
                "analysis item 缺少当前 Dataset 授权范围。",
            )
        if dataset_id not in allowed:
            raise ReportingError(
                "report_profile_dataset_unknown",
                "datasetId 不属于当前 analysis item。",
            )

    async def _durable_state(self, scope: Any) -> ReportingRunState:
        parameters = self._artifact_parameters(scope)
        contract = parameters.get("phaseContract")
        report_run_id = contract.get("reportRunId") if isinstance(contract, dict) else None
        if not isinstance(report_run_id, str) or not report_run_id:
            raise ReportingError(
                "report_phase_contract_invalid", "phase contract 缺少 reportRunId。"
            )
        state = await self._state_repository.get(report_run_id)
        if state is None:
            raise ReportingError("report_state_not_found", "Reporting 运行状态不存在。")
        return state

    async def _ensure_visualization_script_settled(self, scope: Any) -> None:
        """拒绝在签发脚本的受控 execution 仍运行时推进生产阶段。

        Agno 可能并发执行同一批工具，模型随后可能在脚本尚未结束时提交图表。文件尚未写完
        时，登记会得到 Daytona NotFound。执行记录是服务端唯一受信的完成状态，因此这里按
        当前 externalRunId、internalRunId 和底层 terminal kind 精确筛选未终态执行；该 kind
        只是执行账本分类，不是对模型暴露旧 terminal(command) 工具。
        """

        repository = getattr(self.runtime, "repository", None)
        list_executions = getattr(repository, "list_executions", None)
        external_run_id = getattr(scope, "external_run_id", None)
        internal_run_id = getattr(scope, "internal_run_id", None)
        if (
            not callable(list_executions)
            or not isinstance(external_run_id, str)
            or not external_run_id
            or not isinstance(internal_run_id, str)
            or not internal_run_id
        ):
            return
        executions = await list_executions(external_run_id)
        pending = [
            execution
            for execution in executions
            if getattr(execution, "internal_run_id", None) == internal_run_id
            and getattr(execution, "kind", None) == "terminal"
            and isinstance(getattr(execution, "operation_receipt", None), Mapping)
            and execution.operation_receipt.get("runner") == "python"
            and getattr(execution, "status", None) not in TERMINAL_EXECUTION_STATUSES
        ]
        if pending:
            raise ReportingError(
                "report_visualization_script_running",
                "可视化脚本仍在执行，请等待当前 run_python_script 完成后再登记或完成。",
                details={
                    "executions": [
                        {
                            "executionId": str(getattr(item, "execution_id", "")),
                            "status": str(getattr(item, "status", "")),
                        }
                        for item in pending[:10]
                    ]
                },
            )

    @staticmethod
    def _analysis_output_root(contract: Mapping[str, Any]) -> str:
        value = contract.get("analysisOutputRoot")
        if not isinstance(value, str) or not value:
            raise ReportingError(
                "report_phase_contract_invalid", "analysis item 缺少专属输出目录。"
            )
        try:
            return WorkspaceService.normalize_path(value, allow_root=False)[0]
        except WorkspaceError as error:
            raise ReportingError(
                "report_phase_contract_invalid", "analysis item 专属输出目录无效。"
            ) from error

    @classmethod
    def _require_analysis_output_paths(
        cls,
        contract: Mapping[str, Any],
        paths: Iterable[str],
    ) -> None:
        root = cls._analysis_output_root(contract)
        prefix = f"{root}/"
        for value in paths:
            try:
                path = WorkspaceService.normalize_path(value, allow_root=False)[0]
            except (TypeError, WorkspaceError) as error:
                raise ReportingError(
                    "report_analysis_output_path_invalid", "analysis 输出路径无效。"
                ) from error
            if not path.startswith(prefix):
                raise ReportingError(
                    "report_analysis_output_path_invalid",
                    "analysis 补充文件必须写入当前 analysisId 的专属目录。",
                    details={"outputRoot": root, "path": path},
                )

    @classmethod
    def _require_analysis_task_output_paths(
        cls,
        contract: Mapping[str, Any],
        paths: Iterable[str],
    ) -> None:
        if contract.get("taskKind") == "analysis_item":
            cls._require_analysis_output_paths(contract, paths)
            return
        if contract.get("taskKind") == "visualization_section":
            workspace = contract.get("visualizationWorkspace")
            script_path = workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
            try:
                normalized_script = WorkspaceService.normalize_path(script_path, allow_root=False)[
                    0
                ]
            except WorkspaceError as error:
                raise ReportingError(
                    "report_phase_contract_invalid", "visualization scriptPath 无效。"
                ) from error
            normalized_paths = tuple(
                WorkspaceService.normalize_path(path, allow_root=False)[0] for path in paths
            )
            if normalized_paths != (normalized_script,):
                raise ReportingError(
                    "report_visualization_write_forbidden",
                    "visualization 只允许写入签发的图表脚本。",
                    details={"scriptPath": normalized_script},
                )

    @staticmethod
    def _latest_committed_write_identity(
        payload: Mapping[str, Any], path: str
    ) -> dict[str, Any] | None:
        """返回同一路径最后一次 committed write intent 冻结的文件身份。"""

        latest_sequenced: dict[str, Any] | None = None
        latest_sequence: int | None = None
        latest_legacy: dict[str, Any] | None = None
        intents = payload.get("writeIntents")
        if not isinstance(intents, Mapping):
            return None
        # intent 的映射位置只反映 record 顺序。新状态以 reducer 冻结的 commitSequence
        # 为提交顺序事实；旧状态没有该字段时才按历史映射顺序回退，避免升级后中断恢复。
        for intent in intents.values():
            if not isinstance(intent, Mapping) or intent.get("status") != "committed":
                continue
            artifacts = intent.get("artifacts")
            if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
                continue
            for artifact in artifacts:
                if isinstance(artifact, Mapping) and artifact.get("path") == path:
                    identity = {
                        "path": path,
                        "size": artifact.get("size"),
                        "sha256": artifact.get("sha256"),
                    }
                    commit_sequence = intent.get("commitSequence")
                    if (
                        isinstance(commit_sequence, int)
                        and not isinstance(commit_sequence, bool)
                        and commit_sequence >= 0
                    ):
                        if latest_sequence is None or commit_sequence > latest_sequence:
                            latest_sequence = commit_sequence
                            latest_sequenced = identity
                    else:
                        latest_legacy = identity
        return latest_sequenced if latest_sequence is not None else latest_legacy

    async def _visualization_evidence_read_rejection(
        self, *, scope: Any, path: Any
    ) -> dict[str, Any] | None:
        if (
            self._active_reporting_phase(scope) != "analysis"
            or self._active_reporting_task_kind(scope) != "visualization_section"
        ):
            return None
        try:
            normalized = WorkspaceService.normalize_path(path, allow_root=False)[0]
            durable = await self._durable_state(scope)
            expected = None
            committed_script = self._latest_committed_write_identity(durable.payload, normalized)
            if committed_script is not None:
                _parameters, contract = self._phase_parameters(scope, "analysis")
                workspace = contract.get("visualizationWorkspace")
                script_path = (
                    workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
                )
                normalized_script = WorkspaceService.normalize_path(script_path, allow_root=False)[
                    0
                ]
                if normalized == normalized_script:
                    expected = committed_script
            if expected is None:
                raise ReportingError(
                    "report_visualization_evidence_path_forbidden",
                    "visualization 只能读取签发的最新已提交脚本；冻结事实只能通过查询工具访问。",
                )
            current = (
                await self.runtime.workspace.batch_hash_files(scope.thread_id, [normalized])
            )[0]
            actual = {
                "path": current.get("path"),
                "size": current.get("size"),
                "sha256": current.get("sha256"),
            }
            if current.get("missing") is True or actual != expected:
                raise ReportingError(
                    "report_visualization_script_identity_changed",
                    "visualization 签发脚本身份已变化。",
                )
            return None
        except (ReportingError, WorkspaceError) as error:
            return self._failure(error, retryable=False)

    async def _visualization_script_rejection(
        self, *, scope: Any, script_path: Any
    ) -> dict[str, Any] | None:
        if self._active_reporting_task_kind(scope) != "visualization_section":
            return None
        try:
            _parameters, contract = self._phase_parameters(scope, "analysis")
            workspace = contract.get("visualizationWorkspace")
            signed_script_path = (
                workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
            )
            normalized_script = WorkspaceService.normalize_path(
                signed_script_path, allow_root=False
            )[0]
            requested_script = WorkspaceService.normalize_path(script_path, allow_root=False)[0]
            if requested_script != normalized_script:
                raise ReportingError(
                    "report_visualization_script_path_forbidden",
                    "visualization 只允许执行签发的 Python 脚本。",
                    details={"scriptPath": normalized_script},
                )
            durable = await self._durable_state(scope)
            latest_committed = self._latest_committed_write_identity(
                durable.payload, normalized_script
            )
            current = (
                await self.runtime.workspace.batch_hash_files(scope.thread_id, [normalized_script])
            )[0]
            if (
                current.get("missing") is True
                or latest_committed is None
                or latest_committed.get("size") != current.get("size")
                or latest_committed.get("sha256") != current.get("sha256")
            ):
                raise ReportingError(
                    "report_visualization_script_identity_changed",
                    "签发脚本身份未提交或已发生变化。",
                )
            return None
        except (ReportingError, WorkspaceError, ValueError) as error:
            return self._failure(error, retryable=False)

    async def _analysis_item_script_rejection(
        self, *, scope: Any, script_path: Any
    ) -> dict[str, Any] | None:
        if self._active_reporting_task_kind(scope) != "analysis_item":
            return None
        try:
            _parameters, contract = self._phase_parameters(scope, "analysis")
            signed_script = f"{self._analysis_output_root(contract)}/supplement.py"
            requested_script = WorkspaceService.normalize_path(script_path, allow_root=False)[0]
            if requested_script != signed_script:
                raise ReportingError(
                    "report_analysis_script_path_forbidden",
                    "analysis item 只允许执行签发的补充分析脚本。",
                    details={"scriptPath": signed_script},
                )
            durable = await self._durable_state(scope)
            latest_committed = self._latest_committed_write_identity(durable.payload, signed_script)
            current = (
                await self.runtime.workspace.batch_hash_files(scope.thread_id, [signed_script])
            )[0]
            if (
                current.get("missing") is True
                or latest_committed is None
                or latest_committed.get("size") != current.get("size")
                or latest_committed.get("sha256") != current.get("sha256")
            ):
                raise ReportingError(
                    "report_analysis_script_identity_changed",
                    "签发的补充分析脚本身份未提交或已发生变化。",
                )
            return None
        except (ReportingError, WorkspaceError, ValueError) as error:
            return self._failure(error, retryable=False)

    async def _apply_durable_command(
        self,
        scope: Any,
        *,
        name: str,
        payload: dict[str, Any],
        command_id: str,
    ) -> ReportingReducerResult:
        """应用持久化 command，并保留 CAS 重试后的幂等语义。"""

        command = ReportingCommand(name=name, payload=payload, commandId=command_id)
        for _ in range(3):
            state = await self._durable_state(scope)
            try:
                result = await self._state_repository.apply(
                    state.report_run_id,
                    command,
                    expected_version=state.state_version,
                )
                return result
            except ReportingStateError as error:
                if error.code == "report_state_conflict":
                    continue
                raise ReportingError(error.code, error.message) from error
        raise ReportingError("report_state_conflict", "Reporting 状态并发更新冲突，请重试。")

    async def _apply_durable(
        self,
        scope: Any,
        *,
        name: str,
        payload: dict[str, Any],
        command_id: str,
    ) -> ReportingRunState:
        """兼容既有工具调用方，只返回持久化后的状态。"""

        result = await self._apply_durable_command(
            scope,
            name=name,
            payload=payload,
            command_id=command_id,
        )
        return result.state

    async def _invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        call: Callable[[Any], Awaitable[Any]],
        run_context: RunContext | None,
    ) -> Any:
        async def guarded_call(scope: Any) -> Any:
            phase = self._active_reporting_phase(scope)
            task_kind = self._active_reporting_task_kind(scope)
            if phase is not None and not reporting_phase_allows_tool(
                phase, tool_name, task_kind=task_kind
            ):
                # Toolkit 为避免 Agno 跨 run 缓存污染而保留能力全集，但执行权限只来自
                # 当前 Task 的受信 acceptance contract；模型投影或旧历史都不能绕过。
                return self._failure(
                    ReportingError(
                        "report_phase_tool_forbidden",
                        f"phase={phase} 不能调用 {tool_name}。",
                    ),
                    retryable=False,
                )
            if tool_name in {"read_file", "read_lines"}:
                rejection = await self._section_evidence_read_rejection(
                    scope=scope,
                    path=arguments.get("path"),
                )
                if rejection is not None:
                    return rejection
                rejection = await self._visualization_evidence_read_rejection(
                    scope=scope, path=arguments.get("path")
                )
                if rejection is not None:
                    return rejection
            if phase == "analysis" and tool_name == "run_python_script":
                # 受控 runner 的公开边界只有签发路径；不得把路径重新拼成 shell 命令，
                # 否则会重新引入解释器选择、workdir 和参数解析两套不一致的授权语义。
                script_path = arguments.get("script_path")
                analysis_rejection = await self._analysis_item_script_rejection(
                    scope=scope, script_path=script_path
                )
                if analysis_rejection is not None:
                    return analysis_rejection
                visualization_rejection = await self._visualization_script_rejection(
                    scope=scope, script_path=script_path
                )
                if visualization_rejection is not None:
                    return visualization_rejection
                dependency_rejection = await self._analysis_python_dependency_rejection(
                    scope=scope,
                    script_path=script_path,
                )
                if dependency_rejection is not None:
                    return dependency_rejection
            result = await call(scope)
            return result

        return await self.runtime.invoke(self, tool_name, arguments, guarded_call, run_context)

    async def _state_admission_rejection(
        self,
        scope: Any,
        tool_name: str,
        arguments: dict[str, Any],
        state: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Reporting 不进入通用 Reporting 的 mutation/verify/finish 状态机。"""

        # Report Agent 必须在同一 mutation 上连续完成脚本写入、执行、evidence
        # 落盘和 checkpoint；其 verify 工具已被移除，事实校验由当前 phase 白名单、
        # analysis recovery/cursor、文件 SHA-256、阶段提交工具和 Workflow 最终验收共同
        # 承担。若继续继承通用门禁，首次写文件后下一次脚本执行会被要求调用一个并不
        # 存在的 verify，形成不可恢复活锁。这里只关闭那套互斥状态机，所有 Reporting
        # 专属门禁仍由上面的 guarded_call 和各阶段提交工具执行，不能从此入口绕过。
        _ = scope, tool_name, arguments, state
        return None

    @staticmethod
    def _complete_phase_plan(state: dict[str, Any] | None) -> None:
        if state is None:
            return
        plan = validated_agent_plan(state.get(AGENT_PLAN_STATE_KEY))
        if plan is None or all(item["status"] == "completed" for item in plan["plan"]):
            return
        # phase 产物已通过严格 schema、文件身份和幂等冻结校验，此时当前 run 的工作
        # 已由服务端确认完成。必须在签发 finish_task 前同步关闭模型计划，否则通用
        # Reporting 门禁会要求模型在冻结后继续 update_plan，而 Reporting 又不暴露 verify。
        state[AGENT_PLAN_STATE_KEY] = {
            "plan": [{"step": item["step"], "status": "completed"} for item in plan["plan"]],
            "explanation": plan["explanation"],
        }

    async def _finish_phase_task(
        self,
        *,
        scope: Any,
        phase: str,
        identity: dict[str, Any],
        summary: str,
        state: dict[str, Any] | None,
        run_context: RunContext | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._complete_phase_plan(state)
        finish_result = await self.runtime.finish_task(
            summary,
            [identity["path"]],
            None,
            [],
            run_context,
            self._finish_function,
            _scope=scope,
        )
        if finish_result.get("status") != "accepted":
            return finish_result
        return {
            "ok": True,
            "status": "accepted",
            "phase": phase,
            "artifactFile": identity,
            "taskFinished": True,
            **(extra or {}),
        }

    @staticmethod
    def _failure(error: Exception, *, retryable: bool = True) -> dict[str, Any]:
        if not isinstance(error, (ReportingError, ValidationError)):
            # 只有稳定的业务拒绝和严格 schema 错误可以进入模型上下文。Workspace、
            # Daytona、文件解码、图片解析及其他运行时异常必须保留原对象，交给外层
            # tool hook 和 Agno Agent retry；否则包装回执会把基础设施故障误判成模型错误。
            raise error
        validation_errors: list[dict[str, str]] = []
        if isinstance(error, ReportingError):
            code = error.code
            message = error.message
        else:
            code = "report_tool_arguments_invalid"
            message = "Reporting 工具参数不符合严格 schema。"
            # 只返回定位修复所需的稳定结构，不回显 input、ctx 或文档 URL。
            for item in error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )[:20]:
                path = "arguments"
                for part in item["loc"]:
                    path += f"[{part}]" if isinstance(part, int) else f".{part}"
                validation_errors.append(
                    {
                        "path": path,
                        "code": str(item["type"]),
                        "message": str(item["msg"])[:300],
                    }
                )
            validation_errors = [
                item
                for item in validation_errors
                if not any(
                    other["path"].startswith((f"{item['path']}.", f"{item['path']}["))
                    for other in validation_errors
                    if other is not item
                )
            ]
        if code in {
            "report_analysis_already_submitted",
            "report_section_already_submitted",
            "report_chart_registration_closed",
        }:
            retryable = False
        result: dict[str, Any] = {
            "ok": False,
            "status": "rejected",
            "code": code,
            "message": message,
            "requiredActions": ["按服务端错误反馈修正后重试。"],
            "retryable": retryable,
        }
        if (
            code == "report_analysis_write_path_conflict"
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            paths = error.details.get("paths")
            if isinstance(paths, list):
                result["details"] = {
                    "paths": [path for path in paths if isinstance(path, str)],
                    "currentFiles": error.details.get("currentFiles", []),
                    "recoveryOperation": error.details.get("recoveryOperation"),
                }
            result["requiredActions"] = [
                "基于 details.currentFiles 反映的当前文件状态重新生成标准 unified diff。"
            ]
        elif (
            code == "report_analysis_dependency_missing"
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            result["details"] = {
                key: error.details[key]
                for key in ("scriptPath", "missingModules", "missingPaths")
                if key in error.details
            }
        elif (
            code in {"report_replace_target_not_found", "report_replace_target_ambiguous"}
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            result["details"] = {
                key: error.details[key]
                for key in ("path", "matchCount", "preview")
                if key in error.details
            }
        elif (
            code == "report_chart_citation_dataset_mismatch"
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            result["details"] = {
                key: error.details[key]
                for key in ("chartId", "sourceDatasetId", "citationDatasetIds")
                if key in error.details
            }
        elif (
            code
            in {
                "report_period_basis_conflict",
                "report_section_claim_brief_conflict",
                "report_section_claim_chart_conflict",
                "report_cross_source_inference_unsupported",
            }
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            # Section 语义校验可能一次发现多个 claim/chart 冲突；完整保留受信
            # expected/actual 字段，避免模型只能看到第一个错误后重新生成整个章节。
            result["details"] = dict(error.details)
        elif (
            code
            in {
                "report_draft_heading_parent_missing",
                "report_draft_heading_title_too_long",
            }
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            issues = error.details.get("issues")
            if isinstance(issues, list):
                stable_issues: list[dict[str, Any]] = []
                for issue in issues[:20]:
                    if (
                        not isinstance(issue, Mapping)
                        or not isinstance(issue.get("path"), str)
                        or re.fullmatch(
                            r"(?:\$\.markdown|\$\.blocks\[[0-9]+\]\.markdown)",
                            issue["path"],
                        )
                        is None
                        or not isinstance(issue.get("type"), str)
                        or not isinstance(issue.get("message"), str)
                    ):
                        continue
                    stable_issue: dict[str, Any] = {
                        "path": issue["path"],
                        "type": issue["type"],
                        "message": issue["message"],
                    }
                    if code == "report_draft_heading_title_too_long":
                        max_length = issue.get("maxLength")
                        actual_length = issue.get("actualLength")
                        if (
                            not isinstance(max_length, int)
                            or isinstance(max_length, bool)
                            or not isinstance(actual_length, int)
                            or isinstance(actual_length, bool)
                        ):
                            continue
                        stable_issue["maxLength"] = max_length
                        stable_issue["actualLength"] = actual_length
                    stable_issues.append(stable_issue)
                if stable_issues:
                    result["details"] = {"issues": stable_issues}
        elif (
            code
            in {
                "report_analysis_write_intent_invalid",
                "report_analysis_python_syntax_invalid",
                "report_python_source_shape_invalid",
                "report_analysis_evidence_missing",
                "report_analysis_evidence_not_registered",
                "report_analysis_evidence_identity_mismatch",
                "report_analysis_overwrite_target_missing",
                "report_profile_query_invalid",
                "report_analysis_context_query_invalid",
                "report_analysis_facts_query_invalid",
            }
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            result["details"] = dict(error.details)
        if validation_errors:
            result["validationErrors"] = validation_errors
            result["requiredActions"] = ["仅修正 validationErrors 指向的字段后重新调用当前工具。"]
        elif code == "report_draft_heading_title_too_long":
            result["requiredActions"] = [
                "只缩短 details.issues 指向的标题，保留对应 Markdown 正文及其他有效内容后重试。"
            ]
        elif code == "report_analysis_evidence_missing":
            result["requiredActions"] = [
                "先使用 apply_analysis_patch 写入真实 evidence，再重试当前 analysis 提交。"
            ]
        elif code == "report_analysis_evidence_not_registered":
            result["requiredActions"] = [
                "通过 apply_analysis_patch 对 details.missingRegistration 中的文件做幂等登记，"
                "再重试当前 analysis 提交。"
            ]
        elif code == "report_analysis_evidence_identity_mismatch":
            result["requiredActions"] = [
                "文件已在登记后发生变化；通过 apply_analysis_patch 提交当前内容和 SHA-256，"
                "再重试当前 analysis 提交。"
            ]
        elif code == "report_analysis_overwrite_target_missing":
            result["requiredActions"] = ["改用 apply_analysis_patch 创建该目标文件。"]
        elif code == "report_analysis_dependency_missing":
            result["requiredActions"] = [
                "只创建 details.missingPaths 指向的缺失本地模块，再运行原脚本。"
            ]
        elif code == "report_analysis_write_intent_invalid":
            result["requiredActions"] = [
                "保持 toolName 不变，只按 details.expectedFields 和 details.path 修正 arguments；"
                "不要在 arguments 内嵌套 toolName 或第二层 arguments。"
            ]
        elif code == "report_analysis_python_syntax_invalid":
            result["requiredActions"] = [
                "修正 details.path 指向的 Python 语法错误后，使用原 operation 重新提交。"
            ]
        elif code == "report_python_source_shape_invalid":
            result["requiredActions"] = [
                "修正 details.path 指向的签发 Python 源码形状后，使用原 operation 重新提交。"
            ]
        elif code == "report_chart_registration_closed":
            result["requiredActions"] = ["图表已完成不可变登记；不要改图或重复提交。"]
        elif (
            code
            in {
                "report_analysis_script_path_forbidden",
                "report_visualization_script_path_forbidden",
            }
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            script_path = error.details.get("scriptPath")
            if isinstance(script_path, str) and script_path:
                result["details"] = {"scriptPath": script_path}
            result["requiredActions"] = [
                "仅将 details.scriptPath 原样作为 run_python_script.script_path；"
                "不要传入解释器、workdir 或 shell 命令。"
            ]
        elif (
            code == "report_chart_file_missing"
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            # 图表源文件未生成时给模型明确可恢复指引:不得原样重试触发
            # tool_no_progress 终态。details 只回显 sourcePath,便于定位清单项。
            result["details"] = {
                "sourcePath": error.details.get("sourcePath"),
            }
            result["requiredActions"] = [
                "从清单中移除该图表,或先生成 chartOutputRoot 下的真实 PNG 后再提交登记。"
            ]
        elif code in {
            "report_profile_query_invalid",
            "report_analysis_context_query_invalid",
            "report_analysis_facts_query_invalid",
        }:
            result["requiredActions"] = [
                "只使用 details.supportedFunctions 中的标准 JMESPath 函数改写 query。"
            ]
        result["recovery"] = ReportingToolkitBase._recovery_for_failure(
            code=code,
            details=result.get("details"),
            validation_errors=validation_errors,
        )
        if result["requiredActions"] == ["按服务端错误反馈修正后重试。"]:
            result["requiredActions"] = [
                "只依据 details 和 recovery 指向的受信字段修正当前提交；不得原样重试。"
            ]
        return result

    @staticmethod
    def _recovery_for_failure(
        *,
        code: str,
        details: Any,
        validation_errors: Sequence[Mapping[str, str]],
    ) -> dict[str, Any]:
        """构造与文案分离的恢复事实，避免调度层或模型改写具体纠错步骤。

        ``requiredActions`` 面向模型阅读，允许按上下文补充；本字段则只表达服务端已知的
        稳定恢复目标。无法安全推导参数变换时保留定位信息，禁止猜测并自动改写业务参数。
        """

        normalized_details = details if isinstance(details, Mapping) else {}
        tool_name = normalized_details.get("toolName")
        path = normalized_details.get("path")
        validator = normalized_details.get("validator")
        expected_fields = normalized_details.get("expectedFields")
        if validation_errors:
            return {
                "kind": "schema_validation",
                "validationErrors": [dict(item) for item in validation_errors],
            }
        if (
            code == "report_analysis_write_intent_invalid"
            and isinstance(tool_name, str)
            and isinstance(path, str)
            and isinstance(validator, str)
        ):
            recovery: dict[str, Any] = {
                "kind": "schema_validation",
                "toolName": tool_name,
                "path": path,
                "validator": validator,
            }
            if isinstance(expected_fields, list):
                recovery["expectedFields"] = [
                    field for field in expected_fields if isinstance(field, str)
                ]
            return recovery
        if code == "report_analysis_write_path_conflict":
            return {
                "kind": "apply_patch_current_file",
                "toolName": "apply_analysis_patch",
                "currentFiles": normalized_details.get("currentFiles", []),
            }
        if code == "report_analysis_overwrite_target_missing":
            return {
                "kind": "apply_patch_missing_file",
                "toolName": "apply_analysis_patch",
                "paths": normalized_details.get("paths", []),
            }
        if code == "report_analysis_dependency_missing":
            return {
                "kind": "create_missing_dependencies",
                "missingPaths": normalized_details.get("missingPaths", []),
            }
        if code in {
            "report_profile_query_invalid",
            "report_analysis_context_query_invalid",
            "report_analysis_facts_query_invalid",
        }:
            return {
                "kind": "rewrite_jmespath_query",
                "supportedFunctions": normalized_details.get("supportedFunctions", []),
            }
        if code == "report_analysis_evidence_missing":
            return {"kind": "create_required_evidence"}
        if code == "report_analysis_evidence_not_registered":
            return {
                "kind": "register_evidence",
                "missingRegistration": normalized_details.get("missingRegistration", []),
            }
        if code == "report_analysis_evidence_identity_mismatch":
            return {"kind": "refresh_evidence_identity"}
        if code == "report_analysis_python_syntax_invalid":
            return {
                "kind": "fix_python_syntax",
                "path": normalized_details.get("path"),
                "line": normalized_details.get("line"),
            }
        if code == "report_chart_file_missing":
            return {
                "kind": "generate_or_remove_chart",
                "sourcePath": normalized_details.get("sourcePath"),
            }
        if code == "report_analysis_rework_unresolvable":
            return {"kind": "submit_limited_claim"}
        return {
            "kind": "review_error_details",
            "code": code,
        }


__all__ = ["ReportingToolkitBase", "ReportingToolRuntime"]
