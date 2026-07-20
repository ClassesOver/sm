import copy
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import time
from uuid import uuid4

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunStartedEvent,
    StateSnapshotEvent,
)
from agno.agent import Agent
from agno.os.interfaces.agui.input import extract_context, parse_client_tools, validate_state
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events
from agno.run.base import RunContext, RunStatus
from agno.session.agent import AgentSession

from .async_utils import complete_cleanup
from .security import CapabilityClaims
from .workspace import WorkspaceService

logger = logging.getLogger(__name__)


class BranchError(ValueError):
    pass


@dataclass(frozen=True)
class BranchSpec:
    source_thread_id: str
    source_run_id: str
    target_message_id: str


def parse_forwarded_props(payload: dict) -> BranchSpec | None:
    forwarded = payload.get("forwardedProps", {})
    if forwarded in (None, {}):
        return None
    if not isinstance(forwarded, dict) or set(forwarded) != {"branch"}:
        raise BranchError("forwarded_props_invalid")
    branch = forwarded.get("branch")
    required = {"sourceThreadId", "sourceRunId", "targetMessageId"}
    if not isinstance(branch, dict) or set(branch) != required:
        raise BranchError("branch_payload_invalid")
    values = [branch.get(key) for key in required]
    if not all(isinstance(value, str) and 0 < len(value) <= 256 for value in values):
        raise BranchError("branch_payload_invalid")
    return BranchSpec(
        source_thread_id=branch["sourceThreadId"],
        source_run_id=branch["sourceRunId"],
        target_message_id=branch["targetMessageId"],
    )


def validate_branch_identity(target: CapabilityClaims, source: CapabilityClaims) -> None:
    target_identity = (
        target.database,
        target.user,
        target.company,
        target.odoo_session,
    )
    source_identity = (
        source.database,
        source.user,
        source.company,
        source.odoo_session,
    )
    if target_identity != source_identity:
        raise BranchError("branch_identity_mismatch")


def capability_user_id(claims: CapabilityClaims) -> str:
    payload = json.dumps(
        [claims.database, claims.user, claims.company, claims.odoo_session],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return "odoo:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _copy_session_through_run(
    source: AgentSession,
    target_thread_id: str,
    source_run_id: str,
    user_id: str,
) -> tuple[AgentSession, dict[str, str], str]:
    runs = source.runs or []
    target_index = next(
        (
            index
            for index, run in enumerate(runs)
            if run.run_id == source_run_id and run.parent_run_id is None
        ),
        -1,
    )
    if target_index < 0:
        raise BranchError("branch_source_run_not_found")
    target_run = runs[target_index]
    if target_run.status != RunStatus.completed:
        raise BranchError("branch_source_run_not_completed")

    copied_runs = copy.deepcopy(runs[: target_index + 1])
    source_run_ids = [str(run.run_id or "") for run in copied_runs]
    if any(not run_id for run_id in source_run_ids) or len(set(source_run_ids)) != len(
        source_run_ids
    ):
        raise BranchError("branch_source_runs_invalid")
    run_id_map = {run_id: str(uuid4()) for run_id in source_run_ids}
    for run in copied_runs:
        source_id = str(run.run_id or "")
        run.run_id = run_id_map[source_id]
        run.session_id = target_thread_id
        if run.parent_run_id:
            run.parent_run_id = run_id_map.get(str(run.parent_run_id), run.parent_run_id)
        if run.forked_from_run_id:
            run.forked_from_run_id = run_id_map.get(
                str(run.forked_from_run_id),
                run.forked_from_run_id,
            )
        if run.regenerated_from:
            run.regenerated_from = run_id_map.get(
                str(run.regenerated_from),
                run.regenerated_from,
            )
        if not run.forked_from_session_id:
            run.forked_from_session_id = source.session_id

    now = int(time())
    session = AgentSession(
        session_id=target_thread_id,
        agent_id=source.agent_id,
        user_id=user_id,
        agent_data=copy.deepcopy(source.agent_data),
        session_data={"forked_from_session_id": source.session_id},
        metadata={
            **copy.deepcopy(source.metadata or {}),
            "forked_from_session_id": source.session_id,
            "forked_from_run_id": source_run_id,
        },
        runs=copied_runs,
        summary=None,
        created_at=now,
        updated_at=now,
    )
    return session, run_id_map, run_id_map[source_run_id]


async def prepare_branch(
    agent: Agent,
    workspace: WorkspaceService,
    spec: BranchSpec,
    target_thread_id: str,
    user_id: str,
) -> tuple[dict[str, str], str, dict[str, int]]:
    if target_thread_id == spec.source_thread_id:
        raise BranchError("branch_thread_reused")
    source = await agent.aget_session(
        session_id=spec.source_thread_id,
        user_id=user_id,
    )
    if not isinstance(source, AgentSession):
        raise BranchError("branch_source_session_not_found")
    existing = await agent.aget_session(session_id=target_thread_id)
    if existing is not None:
        raise BranchError("branch_target_session_exists")

    target, run_id_map, copied_target_run_id = _copy_session_through_run(
        source,
        target_thread_id,
        spec.source_run_id,
        user_id,
    )
    workspace_result = await workspace.acopy_branch(spec.source_thread_id, target_thread_id)
    try:
        await agent.asave_session(target)
    except BaseException:
        try:
            await complete_cleanup(cleanup_branch(agent, workspace, target_thread_id, user_id))
        except Exception as error:
            logger.error("branch_prepare_cleanup_failed error_type=%s", type(error).__name__)
        raise
    return run_id_map, copied_target_run_id, workspace_result


async def cleanup_branch(
    agent: Agent,
    workspace: WorkspaceService,
    target_thread_id: str,
    user_id: str,
) -> None:
    try:
        if agent.db:
            await agent.adelete_session(target_thread_id, user_id=user_id)
    finally:
        await workspace.adestroy(target_thread_id)


async def run_branch(
    agent: Agent,
    workspace: WorkspaceService,
    run_input: RunAgentInput,
    spec: BranchSpec,
    user_id: str,
) -> AsyncIterator[BaseEvent]:
    started = False
    prepared = False
    try:
        run_id_map, copied_target_run_id, workspace_result = await prepare_branch(
            agent,
            workspace,
            spec,
            run_input.thread_id,
            user_id,
        )
        prepared = True
        session_state = validate_state(run_input.state, run_input.thread_id)
        state_snapshot = copy.deepcopy(session_state)
        ui_dependencies = extract_context(run_input.context)
        run_context = RunContext(
            run_id=copied_target_run_id,
            session_id=run_input.thread_id,
            user_id=user_id,
            client_tools=parse_client_tools(run_input.tools) or None,
            dependencies=ui_dependencies,
            session_state=session_state,
        )
        run_kwargs = {"add_dependencies_to_context": True} if ui_dependencies else {}
        response_stream = agent.acontinue_run(  # type: ignore[call-overload]
            run_id=copied_target_run_id,
            session_id=run_input.thread_id,
            user_id=user_id,
            regenerate=True,
            replace_original=True,
            stream=True,
            stream_events=True,
            run_context=run_context,
            **run_kwargs,
        )
        first = await anext(response_stream)
        generated_run_id = str(getattr(first, "run_id", "") or "")
        if not generated_run_id or generated_run_id == copied_target_run_id:
            raise BranchError("branch_regenerated_run_invalid")
        run_context.run_id = generated_run_id
        if run_context.session_state is not None:
            run_context.session_state["current_run_id"] = generated_run_id

        async def with_first():
            yield first
            async for event in response_stream:
                yield event

        yield CustomEvent(
            type=EventType.CUSTOM,
            name="AGUI_BRANCH_PREPARED",
            value={
                "sourceThreadId": spec.source_thread_id,
                "targetThreadId": run_input.thread_id,
                "targetMessageId": spec.target_message_id,
                "runIdMap": run_id_map,
                "runId": generated_run_id,
                "workspace": workspace_result,
            },
        )
        started = True
        yield RunStartedEvent(
            type=EventType.RUN_STARTED,
            thread_id=run_input.thread_id,
            run_id=generated_run_id,
        )
        if state_snapshot is not None:
            yield StateSnapshotEvent(
                type=EventType.STATE_SNAPSHOT,
                snapshot=state_snapshot,
            )
        async for event in async_stream_agno_response_as_agui_events(
            response_stream=with_first(),
            thread_id=run_input.thread_id,
            run_id=generated_run_id,
            run_state=state_snapshot,
        ):
            yield event
    except BranchError as error:
        if prepared and not started:
            try:
                await cleanup_branch(agent, workspace, run_input.thread_id, user_id)
            except Exception:
                pass
        yield RunErrorEvent(
            type=EventType.RUN_ERROR,
            message="无法基于所选消息创建分支。",
            code=str(error),
        )
    except Exception as error:
        logger.error("branch_failed error_type=%s", type(error).__name__)
        if prepared and not started:
            try:
                await cleanup_branch(agent, workspace, run_input.thread_id, user_id)
            except Exception:
                pass
        yield RunErrorEvent(
            type=EventType.RUN_ERROR,
            message="分支创建失败，请稍后重试。",
            code="branch_failed",
        )
    except BaseException:
        if prepared and not started:
            try:
                await complete_cleanup(
                    cleanup_branch(agent, workspace, run_input.thread_id, user_id)
                )
            except Exception:
                pass
        raise
