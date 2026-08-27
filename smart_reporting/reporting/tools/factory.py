"""Reporting Worker Toolkit 的阶段化装配。"""

from __future__ import annotations

from typing import Any

from agno.run import RunContext
from agno.tools import Toolkit

from ...workspace import WorkspaceService
from ..phase import (
    reporting_phase_allows_tool,
    reporting_phase_from_run_context,
    reporting_task_kind_from_run_context,
)
from ..vision import ReportVisionReviewer
from ..workflow.repository import ReportingStateRepository
from .toolkit import REPORT_WORKER_TOOLKIT_INSTRUCTIONS, ReportWorkspaceTaskToolkit
from .validation import ANALYSIS_WRITE_TOOL_NAMES


def build_report_worker_tools(
    workspace_service: WorkspaceService,
    task_repository: Any,
    validator_registry: Any = None,
    *,
    state_repository: ReportingStateRepository,
    run_context: RunContext | None = None,
    agent: Any | None = None,
    vision_reviewer: ReportVisionReviewer | None = None,
) -> list[Toolkit]:
    """Report Worker 只执行 Coding 分析，不持有数据库或 SQL 工具。"""
    toolkit = ReportWorkspaceTaskToolkit(
        workspace_service,
        task_repository,
        state_repository=state_repository,
        validator_registry=validator_registry,
        vision_reviewer=vision_reviewer,
    )
    if vision_reviewer is None:
        for functions in (toolkit.functions, toolkit.async_functions):
            functions.pop("view_image", None)
            functions.pop("inspect_chart", None)
    phase = reporting_phase_from_run_context(run_context)
    task_kind = reporting_task_kind_from_run_context(run_context)
    if phase is not None:
        # Agent callable-tools 缓存键已包含 phase/taskKind，因此这里可以让实际
        # Toolkit、工具说明和模型 schema 使用同一最小能力集。执行入口仍保留受信
        # phase 复核，不能通过直接方法调用绕过服务端边界。finish_task 是阶段提交
        # 工具在服务端收尾时依赖的内部函数对象，即使当前模型不应直接调用，也不能
        # 从 Toolkit 删除；write_analysis_files 同样依赖四个底层写入原语完成校验与
        # 提交。模型请求层会按 phase 白名单继续隐藏这些内部依赖。
        for functions in (toolkit.functions, toolkit.async_functions):
            for name in tuple(functions):
                internal_dependency = name == "finish_task" or (
                    phase == "analysis" and name in ANALYSIS_WRITE_TOOL_NAMES
                )
                if not internal_dependency and not reporting_phase_allows_tool(
                    phase, name, task_kind=task_kind
                ):
                    functions.pop(name, None)
        toolkit.instructions = REPORT_WORKER_TOOLKIT_INSTRUCTIONS
    return [toolkit]
