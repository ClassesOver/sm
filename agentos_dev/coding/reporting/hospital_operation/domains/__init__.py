from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

DOMAIN_CODES = (
    "income",
    "workload",
    "budget",
    "full_cost",
    "cost_control",
    "funds",
)
DomainCode = Literal["income", "workload", "budget", "full_cost", "cost_control", "funds"]


@dataclass(frozen=True)
class DomainDefinition:
    code: str
    title: str
    required_metrics: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    core_questions: tuple[str, ...] = ()
    attribution_clues: tuple[str, ...] = ()
    forbidden_inferences: tuple[str, ...] = ()

    def prompt_dict(self) -> dict[str, object]:
        """以中文业务语义导出提示词上下文，不暴露物理表或连接信息。"""
        return {
            "code": self.code,
            "title": self.title,
            "aliases": list(self.aliases),
            "coreQuestions": list(self.core_questions),
            "attributionClues": list(self.attribution_clues),
            "forbiddenInferences": list(self.forbidden_inferences),
        }


@dataclass(frozen=True)
class DomainResolution:
    """请求范围的确定性解析结果；歧义时不替模型猜测。"""

    selected: tuple[str, ...] = ()
    primary: str | None = None
    matched_aliases: tuple[str, ...] = ()
    ambiguous_aliases: tuple[str, ...] = ()

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous_aliases)

    @property
    def is_unspecified(self) -> bool:
        return not self.selected and not self.ambiguous_aliases


class HospitalOperationCore:
    """六域静态装配；域之间只共享事实契约，不互相导入。"""

    def __init__(self, definitions: tuple[DomainDefinition, ...] | None = None):
        self._definitions = definitions or domain_definitions()
        codes = [item.code for item in self._definitions]
        if tuple(codes) != DOMAIN_CODES:
            raise ValueError("医院运营六域必须使用稳定顺序")

    @property
    def domains(self) -> tuple[DomainDefinition, ...]:
        return self._definitions

    def definition(self, code: str) -> DomainDefinition:
        for item in self._definitions:
            if item.code == code:
                return item
        raise KeyError(code)


def domain_definitions() -> tuple[DomainDefinition, ...]:
    return (
        DomainDefinition(
            "income",
            "收入",
            ("actual_medical_income",),
            aliases=("收入", "营收", "营业收入", "医疗收入", "收入分析", "income"),
            core_questions=("收入规模和结构是什么？", "收入趋势和主要贡献对象在哪里？"),
            attribution_clues=(
                "工作量",
                "服务结构",
                "价格或政策",
                "结算进度",
                "统计范围",
                "日历因素",
            ),
            forbidden_inferences=("仅凭收入相关性断言确定因果", "缺少工作量或口径时推断量价原因"),
        ),
        DomainDefinition(
            "workload",
            "工作量",
            ("outpatient_visits", "discharges"),
            aliases=("工作量", "业务量", "工作量分析", "门急诊量", "出院量", "workload"),
            core_questions=("业务规模和结构如何变化？", "哪些组织或服务贡献了变化？"),
            attribution_clues=("科室贡献", "资源供给", "排班", "季节性", "患者结构", "服务能力"),
            forbidden_inferences=("缺少可靠分母时推断人均或床位效率", "把单项业务量代表全部工作量"),
        ),
        DomainDefinition(
            "budget",
            "预算",
            ("budget_income",),
            aliases=("预算", "预算执行", "预算完成", "预算分析", "budget"),
            core_questions=("实际与预算差异多大？", "偏差集中在哪里且是否持续？"),
            attribution_clues=("序时进度", "项目结构", "收入或支出类别", "组织执行", "预算版本"),
            forbidden_inferences=(
                "不得把当前进度外推为全年结果",
                "没有版本字段时自动去重或累计项目预算",
            ),
        ),
        DomainDefinition(
            "full_cost",
            "全成本",
            ("total_cost",),
            aliases=("全成本", "总成本", "成本核算", "成本分析", "full cost"),
            core_questions=("成本规模、结构和趋势怎样？", "成本与收入或业务量是否可比？"),
            attribution_clues=("业务量", "采购价格", "资源消耗", "成本归集", "分摊变化"),
            forbidden_inferences=("缺少可靠分母时不得计算单位成本", "把成本相关性写成确定原因"),
        ),
        DomainDefinition(
            "cost_control",
            "费控",
            ("average_cost",),
            aliases=("费控", "费用控制", "费用管控", "次均费用", "药耗", "cost control"),
            core_questions=("次均费用和药耗结构有何变化？", "异常费用集中于哪些服务或对象？"),
            attribution_clues=("业务结构", "高值耗材", "用药", "编码", "支付政策"),
            forbidden_inferences=(
                "缺少对应数据时不得推断医保、DRG或DIP结论",
                "不得把次均费用替代全成本",
            ),
        ),
        DomainDefinition(
            "funds",
            "资金",
            ("cash_balance", "receivables"),
            aliases=("资金", "现金流", "现金", "资金分析", "回款", "funds"),
            core_questions=("资金余额及流入流出如何变化？", "应收、回款和付款是否造成流动性压力？"),
            attribution_clues=("回款", "医保结算", "付款安排", "季节性", "重大支出"),
            forbidden_inferences=(
                "没有现金或应收事实时不得判断流动性",
                "不得把应收变化直接等同现金变化",
            ),
        ),
    )


_NORMALIZE_RE = re.compile(r"[\s、，,：:；;|/\\_\-]+")


def _normalized_alias(value: str) -> str:
    return _NORMALIZE_RE.sub("", value.strip().casefold())


def normalize_domain_code(value: str) -> str:
    normalized = _normalized_alias(value)
    for definition in domain_definitions():
        if normalized in {
            _normalized_alias(definition.code),
            *(_normalized_alias(item) for item in definition.aliases),
        }:
            return definition.code
    raise ValueError(f"未知医院运营领域: {value}")


def resolve_domain_mentions(text: str) -> DomainResolution:
    """先用确定性别名识别领域；"成本"等重叠词明确返回歧义。"""
    if not isinstance(text, str):
        return DomainResolution()
    normalized_text = _normalized_alias(text)
    candidates: list[tuple[str, str]] = []
    for definition in domain_definitions():
        for alias in definition.aliases:
            token = _normalized_alias(alias)
            if token and token in normalized_text:
                candidates.append((token, definition.code))
    # “成本”同时可能表示全成本或费控，不能仅凭一个短词选择其一。
    cost_token = _normalized_alias("成本")
    has_specific_cost_alias = any(
        code in {"full_cost", "cost_control"} and token != cost_token for token, code in candidates
    )
    if cost_token in normalized_text and not has_specific_cost_alias:
        return DomainResolution(ambiguous_aliases=("成本",))
    by_alias: dict[str, set[str]] = {}
    for token, code in candidates:
        by_alias.setdefault(token, set()).add(code)
    ambiguous = tuple(sorted(token for token, codes in by_alias.items() if len(codes) > 1))
    if ambiguous:
        return DomainResolution(ambiguous_aliases=ambiguous)
    # 长别名优先，避免“收入”从“医疗收入”中产生无意义重复命中。
    ordered = sorted(candidates, key=lambda item: (-len(item[0]), DOMAIN_CODES.index(item[1])))
    selected = tuple(
        code
        for code in DOMAIN_CODES
        if any(candidate_code == code for _token, candidate_code in ordered)
    )
    matched = tuple(dict.fromkeys(token for token, _code in ordered))
    return DomainResolution(
        selected=selected, primary=selected[0] if selected else None, matched_aliases=matched
    )


def domain_guidance(stage: str | None = None) -> tuple[dict[str, Any], ...]:
    """返回所有阶段共用的结构化六域指引；stage 只筛选职责，不改变事实内容。"""
    definitions = [definition.prompt_dict() for definition in domain_definitions()]
    if stage is None:
        return tuple(definitions)
    allowed = {
        "request": {"aliases", "title"},
        "data_understanding": {"title", "coreQuestions", "attributionClues", "forbiddenInferences"},
        "analysis": {"title", "coreQuestions", "attributionClues", "forbiddenInferences"},
        "findings": {"title", "coreQuestions", "attributionClues", "forbiddenInferences"},
        "outline": {"title", "coreQuestions"},
        "draft": {"title", "forbiddenInferences"},
    }.get(stage)
    if allowed is None:
        raise ValueError(f"未知医院运营提示阶段: {stage}")
    return tuple(
        {"code": item["code"], **{key: item[key] for key in allowed if key in item}}
        for item in definitions
    )


def build_domain_stage_guidance(stage: str) -> tuple[str, ...]:
    """生成每阶段单一职责的中文规则，供所有 planner/worker 复用。"""
    input_labels = {
        "request": "输入：用户原始目标、可选领域代码和期间文本。",
        "data_understanding": "输入：已冻结请求范围、Schema/DataShape 和可用领域事实。",
        "analysis": "输入：已批准取数需求、期间角色数据和领域事实。",
        "findings": "输入：FactSet、MetricFact、引用和期间覆盖。",
        "outline": "输入：已注册结构化发现、请求范围和数据覆盖。",
        "draft": "输入：批准提纲、FactSet、发现、引用和审核意见。",
    }
    steps = {
        "request": "执行：确定主领域和分析期间；未指定领域保留为空，歧义只提出一个澄清问题。",
        "data_understanding": "执行：只选择主领域数据；仅在期间、粒度、组织和口径可比且确有必要时选择跨域证据。",
        "analysis": (
            "执行：六域是条件规则，不是必须覆盖的主题清单；依次规划整体规模与结构、趋势与拐点、"
            "异常贡献、归因验证、经营影响。报告目标未涉及或无可靠数据时，不得创建对应 analysis 或 requirement。"
        ),
        "findings": "执行：从已注册 factId 生成整体、趋势、异常线索、归因或数据质量发现。",
        "outline": (
            "执行：按真实发现的重要性自由组织中文经营章节；未涉及或无数据领域不建空章，"
            "可用简短章节或段落说明分析依据与分析方法，但不单列数据来源、技术实现或审计信息。"
        ),
        "draft": (
            "执行：以管理结论、证据、异常、原因、影响和行动建议成稿；不新增事实，"
            "说明业务分析依据和方法，不展示取数、系统实现或审计过程。"
        ),
    }
    prohibitions = {
        "request": "禁止：生成表名、字段、SQL、章节、指标值或强制询问 reportType。",
        "data_understanding": "禁止：虚构表字段、为覆盖六域而全选表、用不可比跨域数据归因。",
        "analysis": "禁止：补齐/外推/年化；相关性不得表述为确定因果，也不得把待验证原因写成事实。",
        "findings": "禁止：引用未注册 factId、提交自造数值、把相关性写成因果。",
        "outline": "禁止：提交机器 code、固定十章模板、引用未存在的发现。",
        "draft": "禁止：改写 displayText、脱离绑定引用、生成空领域章节或未经证实的因果。",
    }
    examples = {
        "request": "正例：‘分析2025年收入’→主领域 income、期间 2025-01-01..2025-12-31；反例：‘分析成本’→澄清全成本/费控。",
        "data_understanding": "正例：收入专题只取收入表，工作量表仅在同期间同粒度验证量价时加入；反例：无目标地选择六域全部表。",
        "analysis": "正例：先比较规模，再定位十月拐点和贡献组织；反例：直接写‘因为政策导致下降’。",
        "findings": "正例：finding 引用 metric-001 并标记 hypothesis；反例：引用不存在的 fact-999。",
        "outline": "正例：发现只有收入趋势和数据质量时组织两到三节；反例：固定生成六个空领域章节。",
        "draft": "正例：‘收入为 1.20亿元（metric-001）’；反例：模型自行把 12000万元换算并改精度。",
    }
    definitions = domain_guidance(stage)
    domain_lines = tuple(
        "领域条件："
        + str(item["title"])
        + "（"
        + str(item["code"])
        + "）"
        + ("；别名：" + "、".join(item.get("aliases", ())) if item.get("aliases") else "")
        + (
            "；核心问题：" + " ".join(item.get("coreQuestions", ()))
            if item.get("coreQuestions")
            else ""
        )
        + (
            "；可验证线索：" + "、".join(item.get("attributionClues", ()))
            if item.get("attributionClues")
            else ""
        )
        + (
            "；禁止推断：" + "、".join(item.get("forbiddenInferences", ()))
            if item.get("forbiddenInferences")
            else ""
        )
        for item in definitions
    )
    return (
        input_labels[stage],
        steps[stage],
        *domain_lines,
        prohibitions[stage],
        examples[stage],
    )


__all__ = [
    "DOMAIN_CODES",
    "DomainCode",
    "DomainDefinition",
    "DomainResolution",
    "HospitalOperationCore",
    "build_domain_stage_guidance",
    "domain_definitions",
    "domain_guidance",
    "normalize_domain_code",
    "resolve_domain_mentions",
]
