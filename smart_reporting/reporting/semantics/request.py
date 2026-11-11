"""将公开请求转为可信组织内的依据摘要；不登记身份、不猜测业务场景。"""

from datetime import timedelta

from ..contract import ReportRequestEnvelope
from ..models import ReportingError
from .models import Period, ReportQuestion, ReportRequestSummary, RequestAssumption


def summarize_report_request(request: ReportRequestEnvelope, *, organization: str) -> ReportRequestSummary:
    if request.scenario is None:
        raise ReportingError("report_scenario_missing", "请明确报告场景后选择统计口径。")
    comparison = request.comparison_period
    if comparison is None and request.comparison_roles:
        windows = [item.period for item in request.period_windows().windows if item.role != "current"]
        if len(windows) > 1:
            raise ReportingError("report_comparison_ambiguous", "本次支持一个比较基期，请明确选用期间。")
        comparison = windows[0] if windows else None
    try:
        period = Period(start=request.period.start, end=request.period.end + timedelta(days=1))
        baseline = Period(start=comparison.start, end=comparison.end + timedelta(days=1)) if comparison else None
    except (OverflowError, ValueError) as error:
        raise ReportingError("report_period_invalid", "报告期间无法转换为有效计算窗口。") from error
    outputs = {"document": ("pdf", "docx"), "pptx": ("pptx",), "xlsx": ("xlsx",)}[request.delivery_format]
    assumptions = [
        RequestAssumption(field="knowledgeAsOf", value=request.knowledge_as_of.isoformat() if request.knowledge_as_of else "报告创建时的知识截止时间",
            source="explicit" if request.knowledge_as_of else "default"),
        RequestAssumption(field="scenario", value=request.scenario, source="explicit"),
        RequestAssumption(field="requestedOutputs", value=",".join(outputs),
            source="explicit" if "delivery_format" in request.model_fields_set else "default"),
        RequestAssumption(field="displayUnit", value=request.display_unit or "指标原始单位",
            source="explicit" if request.display_unit else "default"),
        RequestAssumption(field="questions", value="采用明确问题" if request.questions else "以报告目标作为待回答问题",
            source="explicit" if request.questions else "default"),
        RequestAssumption(field="domains", value=",".join(request.domains) if request.domains else "未限定业务范围",
            source="explicit" if request.domains is not None else "default"),
    ]
    if baseline is not None:
        assumptions.append(RequestAssumption(field="comparisonPeriod",
            value=f"{baseline.start.isoformat()}/{baseline.end.isoformat()} [start,end)",
            source="explicit" if comparison is request.comparison_period or "comparison_roles" in request.model_fields_set else "default"))
    return ReportRequestSummary(goal=request.report_goal, scenario=request.scenario, organization=organization,
        period=period, comparison_period=baseline, display_unit=request.display_unit or "指标原始单位",
        domains=request.domains, requested_outputs=outputs,
        questions=request.questions or (ReportQuestion(id="goal", text=request.report_goal),),
        assumptions=tuple(assumptions))
