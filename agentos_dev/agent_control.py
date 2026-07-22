import re
from pathlib import PurePosixPath
from typing import Any

from agno.run import RunContext
from agno.tools import Toolkit

from .report_data_sources import ReportDataSourceToolkit
from .workspace import BaseToolkit, WorkspaceReportToolkit, WorkspaceService

AGENT_PLAN_STATE_KEY = "agentos_plan"
AGENT_CONTINUATION_STATE_KEY = "agentos_continuation"
AGENT_LOADED_TOOLKITS_STATE_KEY = "agentos_loaded_toolkits"
AGENT_CONTEXT_STATUS_DEPENDENCY = "AgentOS 上下文预算状态"
MAX_PLAN_STEPS = 20
MAX_PLAN_STEP_LENGTH = 300
MAX_PLAN_EXPLANATION_LENGTH = 1000
MAX_CONTINUATION_SUMMARY_LENGTH = 2000
MAX_CONTINUATION_STEPS = 20
MAX_CONTINUATION_ARTIFACTS = 50
PLAN_STATUSES = frozenset({"pending", "in_progress", "completed"})
_FORBIDDEN_PLAN_CONTENT = re.compile(
    r"snapshotId|hostRevision|modifiers|(?:authorization\s+token)|授权\s*token|"
    r"[\"']?token[\"']?\s*[:=]",
    re.IGNORECASE,
)

_TOOLKIT_CATALOG = {
    "base": {
        "name": "base",
        "description": "当前 thread 的工作区文件、Git、图片、PDF 和受管 Shell 进程工具。",
        "keywords": "文件 搜索 rg git shell 进程 图片 pdf workspace sandbox",
        "alwaysLoaded": True,
    },
    "report": {
        "name": "report",
        "description": "数据集准备、多轮分析、Markdown 写作和 PDF 渲染工具。",
        "keywords": "报表 报告 数据 分析 csv pandas markdown pdf report",
        "alwaysLoaded": False,
        "routeSkill": "workspace-smart-report",
    },
}


def build_agent_tools(
    workspace_service: WorkspaceService,
    *,
    run_context: RunContext,
    agent: Any | None = None,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> list[Toolkit]:
    """主助手工具工厂；报表能力只由独立 ReportAgent 暴露。"""
    state = run_context.session_state if isinstance(run_context.session_state, dict) else {}
    continuation = state.get(AGENT_CONTINUATION_STATE_KEY)
    return [
        AgentControlToolkit(
            workspace_service,
            model=getattr(agent, "model", None),
            context_token_budget=context_token_budget,
            output_token_reserve=output_token_reserve,
            continuation=continuation if isinstance(continuation, dict) else None,
        ),
        BaseToolkit(workspace_service),
    ]


def build_report_agent_tools(
    workspace_service: WorkspaceService,
    *,
    run_context: RunContext,
    agent: Any | None = None,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
    report_data_sources_file: str | None = None,
    database_url: str | None = None,
) -> list[Toolkit]:
    """ReportAgent 固定工具工厂；每个 run 重新解析当前引用和受控 session state。"""
    state = run_context.session_state if isinstance(run_context.session_state, dict) else {}
    continuation = state.get(AGENT_CONTINUATION_STATE_KEY)
    data_sources = ReportDataSourceToolkit(
        workspace_service,
        config_path=report_data_sources_file,
        excluded_database_url=database_url,
    )
    return [
        AgentControlToolkit(
            workspace_service,
            model=getattr(agent, "model", None),
            context_token_budget=context_token_budget,
            output_token_reserve=output_token_reserve,
            continuation=continuation if isinstance(continuation, dict) else None,
        ),
        BaseToolkit(workspace_service),
        data_sources,
        WorkspaceReportToolkit(workspace_service, data_sources=data_sources),
    ]


class AgentControlToolkit(Toolkit):
    def __init__(
        self,
        service: WorkspaceService,
        *,
        model: Any | None = None,
        context_token_budget: int = 262144,
        output_token_reserve: int = 32768,
        continuation: dict[str, Any] | None = None,
    ):
        self.service = service
        self.model = model
        self.context_token_budget = context_token_budget
        self.output_token_reserve = output_token_reserve
        continuation_instruction = ""
        if continuation:
            summary = continuation.get("summary")
            pending_steps = continuation.get("pendingSteps")
            artifact_paths = continuation.get("artifactPaths")
            safe_steps = bool(
                isinstance(pending_steps, list)
                and 1 <= len(pending_steps) <= MAX_CONTINUATION_STEPS
                and all(
                    isinstance(step, str)
                    and 0 < len(step) <= MAX_PLAN_STEP_LENGTH
                    and not _FORBIDDEN_PLAN_CONTENT.search(step)
                    for step in pending_steps
                )
            )
            path_values = artifact_paths if isinstance(artifact_paths, list) else []
            safe_paths = bool(
                isinstance(artifact_paths, list) and len(path_values) <= MAX_CONTINUATION_ARTIFACTS
            )
            normalized_paths = []
            if safe_paths:
                try:
                    normalized_paths = [
                        service.normalize_path(path, allow_root=False)[0]
                        for path in path_values
                        if isinstance(path, str)
                    ]
                except ValueError:
                    safe_paths = False
                else:
                    safe_paths = len(normalized_paths) == len(path_values)
            if (
                isinstance(summary, str)
                and 0 < len(summary) <= MAX_CONTINUATION_SUMMARY_LENGTH
                and not _FORBIDDEN_PLAN_CONTENT.search(summary)
                and safe_steps
                and safe_paths
            ):
                continuation_instruction = (
                    " 上一 run 已建立受控续跑交接："
                    f"摘要={summary}；待办={pending_steps}；产物={normalized_paths}。"
                    "先核验现有产物和当前用户目标，再继续执行。"
                )
        super().__init__(
            name="agent_control",
            tools=[
                self.agent_update_plan,
                self.agent_context_status,
                self.agent_prepare_continuation,
                self.agent_tool_search,
                self.agent_load_toolkit,
            ],
            instructions=(
                "复杂任务先用 agent_update_plan 维护简短计划；需要专业工具时先搜索。"
                "搜索结果包含 routeSkill 时必须选择对应 Skill，不能动态加载；其他可加载项再调用 agent_load_toolkit。"
                "工具加载在下一 run 生效，不代表用户确认，也不改变 Odoo 授权或工作区确认。"
                "上下文余量不足时用 agent_prepare_continuation 保存非业务交接；它不会自动启动新 run。"
                f"{continuation_instruction}"
            ),
            add_instructions=True,
        )
        for function in {**self.functions, **self.async_functions}.values():
            function.process_entrypoint()
            schema = dict(function.parameters)
            schema["additionalProperties"] = False
            function.parameters = schema
            function.skip_entrypoint_processing = True

    def agent_update_plan(
        self,
        plan: list[dict[str, str]],
        explanation: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """更新当前会话的非业务任务计划；最多 20 步且最多一个步骤进行中。

        Args:
            plan: 按顺序提供 step 和 pending、in_progress 或 completed 状态。
            explanation: 可选的简短计划变更说明。
        """
        if not isinstance(plan, list) or not 1 <= len(plan) <= MAX_PLAN_STEPS:
            raise ValueError(f"计划必须包含 1 至 {MAX_PLAN_STEPS} 个步骤。")
        normalized: list[dict[str, str]] = []
        active = 0
        for item in plan:
            if not isinstance(item, dict) or set(item) != {"step", "status"}:
                raise ValueError("每个计划步骤只能包含 step 和 status。")
            step = item.get("step")
            status = item.get("status")
            if not isinstance(step, str) or not step.strip() or len(step) > MAX_PLAN_STEP_LENGTH:
                raise ValueError(f"计划步骤必须是 1 至 {MAX_PLAN_STEP_LENGTH} 个字符。")
            if _FORBIDDEN_PLAN_CONTENT.search(step):
                raise ValueError("计划不得包含 Odoo 快照、授权或 modifiers 信息。")
            if status not in PLAN_STATUSES:
                raise ValueError("计划状态必须是 pending、in_progress 或 completed。")
            active += status == "in_progress"
            normalized.append({"step": step.strip(), "status": status})
        if active > 1:
            raise ValueError("计划最多只能有一个 in_progress 步骤。")
        if explanation is not None:
            if not isinstance(explanation, str) or len(explanation) > MAX_PLAN_EXPLANATION_LENGTH:
                raise ValueError(f"计划说明最多 {MAX_PLAN_EXPLANATION_LENGTH} 个字符。")
            if _FORBIDDEN_PLAN_CONTENT.search(explanation):
                raise ValueError("计划说明不得包含 Odoo 快照、授权或 modifiers 信息。")
        if run_context is None:
            raise ValueError("缺少当前运行上下文。")
        if run_context.session_state is None:
            run_context.session_state = {}
        value = {"plan": normalized, "explanation": (explanation or "").strip()}
        run_context.session_state[AGENT_PLAN_STATE_KEY] = value
        if normalized and all(item["status"] == "completed" for item in normalized):
            run_context.session_state.pop(AGENT_CONTINUATION_STATE_KEY, None)
        return {"ok": True, **value}

    def agent_context_status(self, run_context: RunContext | None = None) -> dict[str, Any]:
        """估算本轮完整模型上下文的已用和可用 token，并附带历史装配预算。"""
        dependencies = run_context.dependencies if run_context is not None else None
        value = (
            dependencies.get(AGENT_CONTEXT_STATUS_DEPENDENCY)
            if isinstance(dependencies, dict)
            else None
        )
        history = value if isinstance(value, dict) else {}
        allowed = {
            "configuredHistoryTokenBudget",
            "historyTokenBudget",
            "historyTokensUsed",
            "historyTokensRemaining",
            "mandatoryContextTokensEstimate",
            "summaryIncluded",
            "summaryVersion",
            "selectedRunCount",
        }
        result = {key: history[key] for key in allowed if key in history}
        if "tokenCountReliable" in history:
            result["historyTokenCountReliable"] = history["tokenCountReliable"]
        messages = run_context.messages if run_context is not None else None
        tools = self._model_tools(run_context.tools if run_context is not None else None)
        model = self.model
        reliable = model is not None and messages is not None
        try:
            if model is not None and messages is not None:
                used = model.count_tokens(
                    messages,
                    tools=tools,
                    output_schema=run_context.output_schema if run_context is not None else None,
                )
            else:
                used = 0
        except Exception:
            reliable = False
            used = sum(max(1, len(str(message.content)) // 4) for message in messages or [])
        result.update(
            {
                "available": messages is not None,
                "scope": "full_context_estimate",
                "contextTokenBudget": self.context_token_budget,
                "estimatedTokensUsed": min(self.context_token_budget, int(used)),
                "estimatedTokensRemaining": max(
                    0, self.context_token_budget - int(used) - self.output_token_reserve
                ),
                "outputReserveTokens": self.output_token_reserve,
                "tokenCountReliable": reliable,
            }
        )
        return result

    @staticmethod
    def _model_tools(tools: list[Any] | None) -> list[Any]:
        flattened: list[Any] = []
        for item in tools or []:
            if isinstance(item, Toolkit):
                flattened.extend(item.get_async_functions().values())
            else:
                flattened.append(item)
        return flattened

    def agent_prepare_continuation(
        self,
        summary: str,
        pending_steps: list[str],
        artifact_paths: list[str] | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """保存下一 run 可见的受控交接；仅包含工作摘要、待办和工作区产物路径。

        Args:
            summary: 已完成工作的简短摘要，不得包含 Odoo 快照或授权信息。
            pending_steps: 下一 run 继续处理的步骤。
            artifact_paths: 可选的工作区相对产物路径。
        """
        if (
            not isinstance(summary, str)
            or not summary.strip()
            or len(summary) > MAX_CONTINUATION_SUMMARY_LENGTH
            or _FORBIDDEN_PLAN_CONTENT.search(summary)
        ):
            raise ValueError("续跑交接摘要无效，且不得包含 Odoo 快照或授权信息。")
        if (
            not isinstance(pending_steps, list)
            or not 1 <= len(pending_steps) <= MAX_CONTINUATION_STEPS
        ):
            raise ValueError(f"续跑待办必须包含 1 至 {MAX_CONTINUATION_STEPS} 个步骤。")
        normalized_steps = []
        for step in pending_steps:
            if (
                not isinstance(step, str)
                or not step.strip()
                or len(step) > MAX_PLAN_STEP_LENGTH
                or _FORBIDDEN_PLAN_CONTENT.search(step)
            ):
                raise ValueError("续跑待办无效，且不得包含 Odoo 快照或授权信息。")
            normalized_steps.append(step.strip())
        paths = artifact_paths or []
        if not isinstance(paths, list) or len(paths) > MAX_CONTINUATION_ARTIFACTS:
            raise ValueError(f"续跑产物路径最多 {MAX_CONTINUATION_ARTIFACTS} 个。")
        normalized_paths = []
        for path in paths:
            value = PurePosixPath(path) if isinstance(path, str) else None
            if (
                value is None
                or value.is_absolute()
                or ".." in value.parts
                or any(part in ("", ".") for part in value.parts)
            ):
                raise ValueError("续跑产物必须是工作区相对路径。")
            normalized_paths.append(str(value))
        if run_context is None:
            raise ValueError("缺少当前运行上下文。")
        if run_context.session_state is None:
            run_context.session_state = {}
        handoff = {
            "summary": summary.strip(),
            "pendingSteps": normalized_steps,
            "artifactPaths": normalized_paths,
            "sourceRunId": run_context.run_id,
        }
        run_context.session_state[AGENT_CONTINUATION_STATE_KEY] = handoff
        return {"ok": True, "appliesFrom": "next_run", "handoff": handoff}

    def agent_tool_search(
        self, query: str, run_context: RunContext | None = None
    ) -> dict[str, Any]:
        """搜索服务端 Toolkit 类别；结果只描述能力，不执行工具。

        Args:
            query: 工具名称、用途或关键词。
        """
        if not isinstance(query, str) or not query.strip() or len(query) > 100:
            raise ValueError("工具搜索词必须是 1 至 100 个字符。")
        needle = query.strip().casefold()
        matches = [
            {key: value for key, value in item.items() if key != "keywords"}
            for item in _TOOLKIT_CATALOG.values()
            if needle in f"{item['name']} {item['description']} {item['keywords']}".casefold()
        ]
        return {"matches": matches, "loadAppliesFrom": "next_run"}

    def agent_load_toolkit(
        self, toolkit: str, run_context: RunContext | None = None
    ) -> dict[str, Any]:
        """为当前会话加载 Toolkit；Agno 将从下一 run 重新解析工具 schema。

        Args:
            toolkit: agent_tool_search 返回的 Toolkit 名称。
        """
        if toolkit not in _TOOLKIT_CATALOG:
            raise ValueError("未知 Toolkit，请先使用 agent_tool_search。")
        route_skill = _TOOLKIT_CATALOG[toolkit].get("routeSkill")
        if route_skill:
            raise ValueError(f"该能力必须通过 {route_skill} Skill 路由，不能动态加载。")
        if run_context is None:
            raise ValueError("缺少当前运行上下文。")
        if run_context.session_state is None:
            run_context.session_state = {}
        current = run_context.session_state.get(AGENT_LOADED_TOOLKITS_STATE_KEY, [])
        loaded = (
            [
                value
                for value in current
                if isinstance(value, str) and value in _TOOLKIT_CATALOG and value != "base"
            ]
            if isinstance(current, list)
            else []
        )
        if toolkit != "base" and toolkit not in loaded:
            loaded.append(toolkit)
        run_context.session_state[AGENT_LOADED_TOOLKITS_STATE_KEY] = sorted(set(loaded))
        return {"ok": True, "toolkit": toolkit, "appliesFrom": "next_run"}
