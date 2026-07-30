from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol


class ReviewableWorkflow(Protocol):
    def arun(self, *args: Any, **kwargs: Any) -> Any: ...

    def acontinue_run(self, *args: Any, **kwargs: Any) -> Any: ...

    def acancel_run(self, run_id: str) -> Any: ...


class AguiWorkflowAdapter:
    """将现有 AG-UI 请求语义映射到 Agno Workflow 原生流。"""

    def __init__(self, workflow: ReviewableWorkflow):
        self.workflow = workflow

    async def start_events(
        self,
        report_input: Any,
        *,
        run_id: str,
        session_id: str,
        user_id: str,
    ) -> AsyncIterator[Any]:
        source = await self.workflow.arun(
            report_input,
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=True,
        )
        async for event in source:
            yield event

    async def continue_events(
        self,
        *,
        run_id: str,
        session_id: str,
        requirements: list[Any],
    ) -> AsyncIterator[Any]:
        source = await self.workflow.acontinue_run(
            run_id=run_id,
            session_id=session_id,
            step_requirements=requirements,
            stream=True,
            stream_events=True,
        )
        async for event in source:
            yield event

    async def cancel(self, run_id: str) -> bool:
        return bool(await self.workflow.acancel_run(run_id))


class CliReviewAdapter:
    def __init__(
        self,
        *,
        read: Callable[[str], str] = input,
        write: Callable[[str], None] = print,
    ):
        self._read = read
        self._write = write

    def review_action(self, snapshot: dict[str, Any]) -> tuple[str, str | None]:
        self._write(str(snapshot))
        if snapshot.get("stage") == "agent":
            agents = (snapshot.get("preview") or {}).get("agents")
            allowed = (
                {
                    item.get("code")
                    for item in agents
                    if isinstance(item, dict) and isinstance(item.get("code"), str)
                }
                if isinstance(agents, list)
                else set()
            )
            agent_id = self._read("选择 Agent code: ").strip()
            if agent_id not in allowed:
                raise ValueError("所选报表 Agent 不在候选列表中。")
            return "select_agent", agent_id
        action = self._read("批准 [a] / 拒绝 [r] / 取消 [c]: ").strip().lower()
        if action == "a":
            return "approve", None
        if action == "r":
            feedback = self._read("修改意见: ").strip()
            if not feedback:
                raise ValueError("拒绝时必须提供修改意见。")
            return "reject", feedback
        if action == "c":
            return "cancel", None
        raise ValueError("未知审核操作。")

    def resolve_output_reviews(self, run_output: Any) -> Any:
        for requirement in getattr(run_output, "steps_requiring_output_review", ()) or ():
            content = getattr(getattr(requirement, "step_output", None), "content", "")
            self._write(str(content))
            action = self._read("批准 [a] / 拒绝 [r] / 取消 [c]: ").strip().lower()
            if action == "a":
                requirement.confirm()
            elif action == "r":
                feedback = self._read("修改意见: ").strip()
                if not feedback:
                    raise ValueError("拒绝时必须提供修改意见。")
                requirement.reject(feedback=feedback)
            elif action == "c":
                requirement.reject()
            else:
                raise ValueError("未知审核操作。")
        return run_output
