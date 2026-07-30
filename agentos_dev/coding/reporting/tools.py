"""Report worker 工具装配。"""

from typing import Any

from agno.run import RunContext
from agno.tools import Toolkit

from ...workspace import WorkspaceService
from ..execution import WorkspaceCodingToolkit


def build_report_worker_tools(
    workspace_service: WorkspaceService,
    coding_repository: Any,
    validator_registry: Any = None,
    *,
    run_context: RunContext | None = None,
    agent: Any | None = None,
    enable_vision: bool = False,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> list[Toolkit]:
    """Report Worker 只执行 Coding 分析，不持有数据库或 SQL 工具。"""
    toolkit = WorkspaceCodingToolkit(
        workspace_service,
        coding_repository,
        validator_registry=validator_registry,
    )
    if not enable_vision:
        toolkit.functions.pop("view_image", None)
        toolkit.async_functions.pop("view_image", None)
    return [toolkit]
