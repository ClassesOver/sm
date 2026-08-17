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


def domain_definitions() -> tuple[DomainDefinition, ...]:
    return (
        DomainDefinition(
            "income",
            "收入",
            ("actual_medical_income",),
            aliases=("收入", "营收", "营业收入", "医疗收入", "收入分析", "income"),
            core_questions=("收入规模与结构分析", "收入趋势及主要贡献对象识别"),
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
            core_questions=("业务规模与结构变化分析", "变化贡献组织及服务识别"),
            attribution_clues=("科室贡献", "资源供给", "排班", "季节性", "患者结构", "服务能力"),
            forbidden_inferences=("缺少可靠分母时推断人均或床位效率", "把单项业务量代表全部工作量"),
        ),
        DomainDefinition(
            "budget",
            "预算",
            ("budget_income",),
            aliases=("预算", "预算执行", "预算完成", "预算分析", "budget"),
            core_questions=("实际与预算差异测算", "偏差集中领域及持续性识别"),
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
            core_questions=("成本规模、结构与趋势分析", "成本与收入或业务量可比性验证"),
            attribution_clues=("业务量", "采购价格", "资源消耗", "成本归集", "分摊变化"),
            forbidden_inferences=("缺少可靠分母时不得计算单位成本", "把成本相关性写成确定原因"),
        ),
        DomainDefinition(
            "cost_control",
            "费控",
            ("average_cost",),
            aliases=("费控", "费用控制", "费用管控", "次均费用", "药耗", "cost control"),
            core_questions=("次均费用与药耗结构变化分析", "异常费用集中服务及对象识别"),
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
            core_questions=("资金余额及流入流出变化分析", "应收、回款和付款流动性压力识别"),
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


def resolve_domain_mentions(text: str) -> DomainResolution:
    """先用确定性别名识别领域；"成本"等重叠词明确返回歧义。"""
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
        "outline": "输入：已注册结构化发现、请求范围和数据覆盖。",
        "draft": "输入：批准提纲、详细分析计划、DatasetLineage、引用和审核意见。",
    }
    steps = {
        "request": (
            "执行：确定报告类型、领域和分析期间；综合报告默认以收入、工作量、预算、全成本、费控、资金六域为候选，"
            "再按用户明确范围和数据源实际覆盖收敛；专题报告的成本短词歧义才提出一个澄清问题。"
        ),
        "data_understanding": (
            "执行：只在冻结的用户范围内选择数据源实际支持的领域；综合报告可覆盖六域，"
            "缺少可靠数据的领域必须标记覆盖不足，不能虚构 requirement。"
        ),
        "analysis": (
            "执行：六域是条件规则，不是必须覆盖的主题清单；依次规划整体规模与结构、趋势与拐点、"
            "异常贡献、归因验证、经营影响。报告目标未涉及或无可靠数据时，不得创建对应 analysis 或 requirement。"
        ),
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
        "outline": "禁止：提交机器 code、固定十章模板、引用未存在的发现。",
        "draft": "禁止：改写 displayText、脱离绑定引用、生成空领域章节或未经证实的因果。",
    }
    examples = {
        "request": (
            "正例：‘生成2025年整体运营报告’→综合六域候选、期间 2025-01-01..2025-12-31；"
            "‘分析2025年收入’→收入专题；反例：把专题中的‘成本’静默解释为全成本或费控。"
        ),
        "data_understanding": "正例：收入专题只取收入表，工作量表仅在同期间同粒度验证量价时加入；反例：无目标地选择六域全部表。",
        "analysis": "正例：先比较规模，再定位十月拐点和贡献组织；反例：直接写‘因为政策导致下降’。",
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
            "；核心分析目标：" + "；".join(item.get("coreQuestions", ()))
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
    "build_domain_stage_guidance",
    "domain_definitions",
    "domain_guidance",
    "resolve_domain_mentions",
]
