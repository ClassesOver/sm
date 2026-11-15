from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field

from ..office.contract import StrictModel
from ..reporting.structured_output.execution import (
    ReportingStructuredOutputExecutor,
    StructuredOutputCallBudget,
)


# 图表缓存只能由 applyChartSource 从真实工作表读取，不能由模型填入。
WorkbookAIOperationKind = Literal[
    "applyCellEdits", "applySheetMerges", "applySheetEdits", "applyRowColumnOps", "applyCellShift",
    "applyDvRules", "applyDataValidationSource", "applyCfRules", "appendSheetConditionalFormats",
    "replaceSheetConditionalFormats", "applySheetNotes", "applySheetFilter", "protectSheet", "addPivot",
    "applyColumnWidths", "applyRowHeights", "applyPageSetups", "applySheetOutline",
    "applyTableAdditions", "applyTableEdits", "refreshPivotCaches", "applyPivotLayoutExpansions",
    "expandPivotOutputs", "applyDefinedNames", "sortRange", "applyChartEdits", "applyChartDeletions", "applyChartSource",
    "appendSheetSparklines", "clearCellRange", "replaceRangeText", "applyTableSource", "applyHyperlinkSource", "applyNoteSource",
]


class WorkbookAIOperation(StrictModel):
    kind: WorkbookAIOperationKind
    arguments: dict[str, Any] = Field(default_factory=dict)


class WorkbookAIProposal(StrictModel):
    """工作簿 AI 候选的结构化输出；操作参数仍由真实引擎预览核验。"""

    summary: str = Field(min_length=1, max_length=2_000)
    operations: tuple[WorkbookAIOperation, ...] = Field(min_length=1, max_length=100)

    def engine_operations(self) -> list[dict[str, Any]]:
        """还原为引擎原生协议 {kind, ...参数}。"""
        if any("kind" in item.arguments for item in self.operations):
            raise ValueError("workbook_ai_operation_arguments_invalid")
        return [{"kind": item.kind, **item.arguments} for item in self.operations]


@dataclass(frozen=True)
class WorkbookAINativePlan:
    """Trusted native planner outcome; never part of a model output schema."""

    proposal: WorkbookAIProposal | None
    navigation: dict[str, Any] | None


class AgnoWorkbookProposalPlanner:
    """经 Reporting 结构化输出执行器调用 Agno，返回已通过 Schema 校验的候选。"""

    def __init__(self, agent: Any) -> None:
        self.agent = agent

    async def __call__(self, prompt: str, *, session_id: str, user_id: str) -> WorkbookAIProposal:
        output = await ReportingStructuredOutputExecutor(self.agent).execute(
            prompt,
            routing_context=None,
            session_id=session_id,
            user_id=user_id,
            call_budget=StructuredOutputCallBudget(max_model_calls=2),
        )
        content = getattr(output, "content", None)
        if isinstance(content, WorkbookAIProposal):
            return content
        if isinstance(content, Mapping):
            return WorkbookAIProposal.model_validate(dict(content))
        raise ValueError("workbook_ai_proposal_not_structured")

    async def plan_native_workbook(self, *args, **kwargs) -> WorkbookAINativePlan:
        return await self.plan_workbook(*args, **kwargs, navigation_enabled=True)

    async def plan_workbook(self, prompt: str, *, model: dict[str, Any], scope: str,
                            selection: dict[str, Any], preview: Any,
                            session_id: str, user_id: str, navigation_enabled: bool = False) -> WorkbookAIProposal | WorkbookAINativePlan:
        """使用原生 Agno 工具循环读取工作簿，并通过提案工具运行真实引擎预览。"""
        from .workbook_ai_tools import WorkbookAIToolkit

        toolkit = WorkbookAIToolkit(model=model, scope=scope, selection=selection, preview=preview,
                                   navigation_enabled=navigation_enabled)
        agent = self.agent.deep_copy(update={
            "output_schema": None, "parse_response": False, "structured_outputs": False,
            "use_json_mode": False, "tools": [toolkit], "tool_choice": "auto",
            "retries": 0, "exponential_backoff": False, "markdown": False,
        })
        from ..reporting.agent_events import run_owned_agent_with_events

        tool_protocol = (
            "工具调用协议：propose_operations 的 operations 每项可以直接使用指南的源 DSL 对象。"
            "源 DSL 的操作名放 op，不放 kind；kind 只用于引擎原生操作且参数放 arguments。不要混合这两种包装。"
            "propose_operations成功后候选即冻结，必须在提交前把用户要求的全部修改放入同一候选，"
            "不能先提交部分修改再补交；成功后直接结束并等待用户采纳，不重复调用。"
            '图表新增的完整工具参数示例：{"operations":[{"op":"add_chart","sheetId":"Sheet",'
            '"chartType":"line","dataRange":"A1:B3","title":"季度收入（万元）","anchorCell":"E20"}],'
            '"summary":"按实际单元格新增收入图表"}。示例的表名与范围必须换为已读取的真实身份。'
            '图表换绑并改标题示例：{"operations":[{"op":"edit_chart","chartPath":"xl/charts/chart1.xml","title":"修订收入",'
            '"seriesData":[{"index":0,"valuesRange":"B2:B3","categoriesRange":"A2:A3"}]}],'
            '"summary":"按真实范围换绑系列"}。不要将源DSL字段直接放到kind=applyChartSource的arguments中。\n'
        )
        if navigation_enabled:
            tool_protocol += ("仅用户要求移动视图时使用select_range。回执navigation_requested仅表示请求，不能声称浏览器已定位。"
                "仅定位时无需propose_operations；若还需编辑，先请求定位，再一次性提交完整候选。最终正文或JSON不能发起导航。")
        from ..office.settings import configure_office_agent
        await configure_office_agent(agent, update_model=True)
        await run_owned_agent_with_events(agent, tool_protocol + prompt, session_id=session_id, user_id=user_id)
        if navigation_enabled and (toolkit.proposal is not None or toolkit.navigation is not None):
            return WorkbookAINativePlan(toolkit.proposal, toolkit.navigation)
        if toolkit.proposal is None:
            raise ValueError("workbook_ai_proposal_not_submitted")
        return toolkit.proposal


