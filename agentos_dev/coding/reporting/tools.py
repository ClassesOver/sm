"""Report worker 工具装配。"""

from typing import Any

from agno.run import RunContext
from agno.tools import Toolkit

from ...task_execution.execution import WorkspaceTaskToolkit
from ...workspace import WorkspaceService
from .repair_guard import ReportRepairGuard


class ReportWorkspaceTaskToolkit(WorkspaceTaskToolkit):
    """Report Worker 的工具门禁；底层执行、锁和审计继续复用通用 Toolkit。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._report_repair_guard = ReportRepairGuard()

    async def _state_admission_rejection(
        self,
        scope: Any,
        tool_name: str,
        arguments: dict[str, Any],
        state: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        rejection = await super()._state_admission_rejection(scope, tool_name, arguments, state)
        if rejection is not None:
            return rejection
        return self._report_repair_guard.admission_rejection(tool_name, arguments, state)

    async def _invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        call: Any,
        run_context: Any,
    ) -> Any:
        result = await super()._invoke(tool_name, arguments, call, run_context)
        session_state = (
            run_context.session_state
            if run_context is not None and isinstance(run_context.session_state, dict)
            else None
        )
        self._report_repair_guard.record_result(tool_name, arguments, result, session_state)
        return result


def build_report_worker_tools(
    workspace_service: WorkspaceService,
    task_repository: Any,
    validator_registry: Any = None,
    *,
    run_context: RunContext | None = None,
    agent: Any | None = None,
    enable_vision: bool = False,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> list[Toolkit]:
    """Report Worker 只执行 Coding 分析，不持有数据库或 SQL 工具。"""
    toolkit = ReportWorkspaceTaskToolkit(
        workspace_service,
        task_repository,
        validator_registry=validator_registry,
    )
    if not enable_vision:
        toolkit.functions.pop("view_image", None)
        toolkit.async_functions.pop("view_image", None)
    return [toolkit]
