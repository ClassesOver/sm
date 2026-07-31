"""直接执行顶层 Agno Reporting Workflow 的 CLI。"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from agno.run.base import RunStatus
from agno.workflow import OnReject
from pydantic import BaseModel

from ...async_utils import complete_cleanup
from ...execution_context import close_execution_resources, create_execution_context
from ...settings import AgentSettings
from .agentos import create_report_agentos_components
from .contract import ReportingWorkflowInput
from .controller import REPORT_WORKFLOW_SCOPE_DEPENDENCY
from .models import ReportingError
from .runtime import REPORT_WORKFLOW_SCOPE_STATE_KEY


def read_report_input(*, read: Callable[[str], str] = input) -> str:
    lines: list[str] = []
    while True:
        line = read("" if lines else "自然语言或 ReportRequestEnvelope JSON（/run 提交）:\n")
        if line.strip() == "/run":
            break
        lines.append(line)
    value = "\n".join(lines).strip()
    if not value:
        raise ReportingError("report_request_invalid", "报表请求不能为空。")
    return value


def parse_report_input(value: str) -> dict[str, Any]:
    normalized = str(value or "").strip()
    if not normalized:
        raise ReportingError("report_request_invalid", "报表请求不能为空。")
    try:
        parsed = json.loads(normalized)
    except ValueError:
        parsed = {"version": "1", "prompt": normalized}
    if not isinstance(parsed, dict):
        raise ReportingError("report_request_invalid", "报表请求不符合 v1 契约。")
    try:
        request = ReportingWorkflowInput.model_validate(parsed)
    except Exception as error:
        raise ReportingError("report_request_invalid", "报表请求不符合 v1 契约。") from error
    return request.model_dump(mode="json", by_alias=True, exclude_none=True)


def resolve_requirement(
    requirement: Any,
    *,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> str:
    content = getattr(getattr(requirement, "step_output", None), "content", None)
    if isinstance(content, BaseModel):
        content = content.model_dump(mode="json", by_alias=True)
    message = str(getattr(requirement, "output_review_message", "") or "请审核工作流输出。")
    write(message)
    if content is not None:
        write(json.dumps(content, ensure_ascii=False, indent=2, default=str))

    if (
        str(getattr(requirement, "step_id", "")) == "normalize-report-request"
        and isinstance(content, dict)
        and content.get("clarificationQuestion")
    ):
        feedback = read("提交补充信息: ").strip()
        if not feedback:
            raise ValueError("补充信息不能为空。")
        requirement.reject(feedback=feedback)
        return "continue"

    agents = content.get("agents") if isinstance(content, dict) else None
    if isinstance(agents, list) and agents:
        allowed = {
            item.get("code")
            for item in agents
            if isinstance(item, dict) and isinstance(item.get("code"), str)
        }
        agent_id = read("选择 Agent code（取消输入 c）: ").strip()
        if agent_id.lower() == "c":
            requirement.on_reject = OnReject.cancel
            requirement.reject(feedback="用户取消报表工作流。")
            return "cancel"
        if agent_id not in allowed:
            raise ValueError("所选报表 Agent 不在候选列表中。")
        requirement.reject(feedback=f"agentId:{agent_id}")
        return "continue"

    action = read("批准 [a] / 拒绝 [r] / 取消 [c]: ").strip().lower()
    if action == "a":
        requirement.confirm()
        return "continue"
    if action == "r":
        feedback = read("修改意见: ").strip()
        if not feedback:
            raise ValueError("拒绝时必须提供修改意见。")
        requirement.reject(feedback=feedback)
        return "continue"
    if action == "c":
        requirement.on_reject = OnReject.cancel
        requirement.reject(feedback="用户取消报表工作流。")
        return "cancel"
    raise ValueError("未知审核操作。")


async def drive_workflow(
    workflow: Any,
    runtime: Any,
    report_input: dict[str, Any],
    *,
    run_id: str,
    session_id: str,
    user_id: str,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> dict[str, Any]:
    scope = {"externalRunId": run_id, "threadId": session_id, "userId": user_id}
    dependencies = {REPORT_WORKFLOW_SCOPE_DEPENDENCY: scope}
    output = await workflow.arun(
        report_input,
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        session_state={REPORT_WORKFLOW_SCOPE_STATE_KEY: scope},
        dependencies=dependencies,
        stream=False,
    )

    while _status(output) == "paused":
        requirements = list(getattr(output, "step_requirements", None) or [])
        unresolved = [
            item for item in requirements if not bool(getattr(item, "is_resolved", False))
        ]
        if not unresolved:
            raise ReportingError("report_workflow_review_invalid", "报表工作流没有待处理审核项。")
        resolve_requirement(unresolved[-1], read=read, write=write)
        output = await workflow.acontinue_run(
            run_response=output,
            step_requirements=requirements,
            dependencies=dependencies,
            stream=False,
        )

    status = _status(output)
    content = getattr(output, "content", None)
    if status == "cancelled":
        await runtime.cleanup_cancelled(scope, session_id, run_id)
    return {
        "status": status,
        "runId": run_id,
        "sessionId": session_id,
        "content": content,
    }


async def run_cli(
    *,
    settings: AgentSettings | None = None,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> None:
    report_input = parse_report_input(read_report_input(read=read))
    context = create_execution_context(settings)
    reporting_agent, workflow, report_worker, runtime, _controller = (
        create_report_agentos_components(context, context.settings)
    )
    workflow = runtime.workflow(publication_issuer=runtime.issue_cli_publication)
    run_id = f"cli-report-v2-{uuid4().hex}"
    session_id = f"cli-report-v2-{uuid4().hex}"
    try:
        result = await drive_workflow(
            workflow,
            runtime,
            report_input,
            run_id=run_id,
            session_id=session_id,
            user_id="cli-v2",
            read=read,
            write=write,
        )
        write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        await complete_cleanup(close_execution_resources(context, reporting_agent, report_worker))


def _status(output: Any) -> str:
    value = getattr(output, "status", None)
    normalized = value.value if isinstance(value, RunStatus) else str(value or "")
    return normalized.lower()


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments:
            raise SystemExit("用法: python -m agentos_dev.coding.reporting.cli_v2")
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
