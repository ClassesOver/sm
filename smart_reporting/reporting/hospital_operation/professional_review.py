"""Professional review criteria and finite warning checks for hospital reports.

Criteria are distilled from the supplied 39-page annotated report. Its examples
are editorial guidance, never verified business data. Detectors flag unresolved
premises; absence of a flag does not certify an arbitrary business statement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ReviewStage = Literal["analysis", "outline", "draft"]
PROFESSIONAL_REVIEW_VERSION = "3"


@dataclass(frozen=True)
class ProfessionalCriterion:
    code: str
    review_ids: tuple[str, ...]
    stages: tuple[ReviewStage, ...]
    guidance: str
    required_evidence: tuple[str, ...]


PROFESSIONAL_CRITERIA = (
    ProfessionalCriterion("structure", tuple(f"R{n:03d}" for n in (
        1, 17, 22, 29, 31, 47, 59, 62, 63, 65, 66, 69, 72, 73, 74, 77,
    )), ("outline", "draft"),
        "按管理问题合并同主题发现，图解紧随结论，不为图解、通用建议或相关性另设重复小节；"
        "收入和支出预算共同评价，收支结余独立回答；附表保留支撑任务的维度，章节数按内容决定。",
        ("冻结管理问题与完成条件", "发现的唯一主章节归属")),
    ProfessionalCriterion("period", tuple(f"R{n:03d}" for n in (
        2, 6, 8, 35, 44, 64, 67, 76, 79,
    )), ("analysis", "outline", "draft"),
        "主结论、摘要、表格、图注使用请求期间及同范围上年同期；请求年份、统计期间、数据截至日与"
        "编制日期分别记录。月标签不是某一天的日窗口；不得改年份复用往年示例，不以全年实际替代本期实际。",
        ("请求期间", "实际覆盖期间及同期窗口", "数据截至日与编制日期")),
    ProfessionalCriterion("answer", tuple(f"R{n:03d}" for n in (
        3, 7, 20, 23, 27, 45, 46, 48, 57,
    )), ("analysis", "outline", "draft"),
        "摘要回答总体收入、成本、统一口径收支结余及预算偏差；按用户实际要求列本期、同期、增减额、"
        "增幅和主要贡献。规模与占比不能替代同比；支出七大类不能由成本七大类冒充，缺项明确披露。",
        ("冻结问题完成条件", "同期与本期事实", "指标分类字典")),
    ProfessionalCriterion("budget_policy", ("R009", "R018", "R037", "R070"),
        ("analysis", "draft"),
        "先确认年度预算、月度下达预算、累计预算或年度预算重复挂载及版本；相同月值不证明可求和或"
        "应取期末。区分年度预算完成率和同期预算执行率；未下达月预算不得按年预算除以12生成正式预算。",
        ("预算时间属性及版本", "下达与汇总规则", "同期预算或年度预算分母")),
    ProfessionalCriterion("consistent_values", tuple(f"R{n:03d}" for n in (
        4, 5, 11, 19, 21, 26, 32, 60, 75,
    )), ("analysis", "draft"),
        "摘要、正文、图形、图注和附表必须使用同一核实后的指标与窗口；累计与月均分别计算。"
        "执行率按实际/预算时，低于100%不能称超预算。对平须有完整且互斥的同范围分项证据，金额对平不证明归属正确。",
        ("同一冻结事实选择器", "完整同范围分项", "图文表共同来源")),
    ProfessionalCriterion("missing_zero", ("R014", "R016", "R068", "R071"),
        ("analysis", "draft"),
        "分别处理真实零、未采集、未映射和未知状态；无预算有实际、有预算无实际不得一概剔除。"
        "预算为零时执行率不计算；缺项不补零，不把未知零展示为完整构成的0.00%，不宣称重大缺失不影响结论。",
        ("采集与映射状态", "零预算异常分类", "原始缺失计数")),
    ProfessionalCriterion("recommendation", ("R010", "R012", "R025", "R028", "R049"),
        ("analysis", "draft"),
        "建议依赖已核实的偏差或风险；不能从占比高、规模大直接认定不合理依赖或浪费。"
        "结合目标、同期、工作量和病种结构再评价，责任人、目标及期限缺失时由管理确认，不得补造。",
        ("已核实偏差", "目标或同期基准", "对应业务量与结构")),
    ProfessionalCriterion("metric_identity", tuple(f"R{n:03d}" for n in (
        13, 24, 39, 41, 42, 58, 61,
    )), ("analysis", "draft"),
        "明细行数不是去重科室数；预算归口部门不是实际费用消耗科室，支出性质不是收入业务条线。"
        "药品采购与药品费用先核对确认基础；出院患者床日不是本期实际占用床日，相关系数不能替代效率指标。",
        ("组织唯一键与归属", "分类及确认基础", "业务指标定义")),
    ProfessionalCriterion("cross_metric", tuple(f"R{n:03d}" for n in (
        30, 33, 34, 43, 52, 53, 54, 55,
    )), ("analysis", "draft"),
        "金额与人次单位不同不自动排除次均分析，须先匹配期间、业务范围和分子分母归属。"
        "开单收入不证明现金流；收入与成本未完成归属/分摊匹配时不计算或排名正式结余、盈利、亏损，"
        "也不能仅加“仅供参考”后继续归因。",
        ("共同业务范围与期间", "认可的收入归属和成本分摊阶段", "回款/应收/现金证据")),
    ProfessionalCriterion("anomaly", ("R036", "R038", "R040", "R051", "R056"),
        ("analysis", "draft"),
        "大额极值、负值和集中记录先列原始事实并核查唯一键、单位、累计/期初与确认基础；"
        "不能直接认定一次性入账、冲销或科目错配。未经确认的异常不升格为图题或摘要中的经营结论。",
        ("原始凭证或业务说明", "唯一键及单位", "异常性质确认")),
    ProfessionalCriterion("contribution", ("R015", "R050"), ("analysis", "draft"),
        "最大短缺或最大贡献须使用完整同维度对照及统一有符号差额分母；1月与9月的端点差额不能替代"
        "1—9月累计同比贡献。科室与业务条线不交叉重复加总，贡献不能升格为因果。",
        ("完整同期分项", "统一净差额分母", "互斥分析维度")),
    ProfessionalCriterion("formal_identity", ("R078",), ("draft",),
        "医院正式报告的编制单位、编制部门、审核角色及日期采用已确认配置，缺失时保持待确认；"
        "软件供应商不自动成为医院编制或签发主体。",
        ("已确认医院署名与审核配置",)),
)


def professional_stage_guidance(stage: ReviewStage) -> tuple[str, ...]:
    return tuple("专业审阅要求：" + item.guidance for item in PROFESSIONAL_CRITERIA if stage in item.stages)


@dataclass(frozen=True)
class ProfessionalExpressionPattern:
    code: str
    review_ids: tuple[str, ...]
    guidance: str


# Distilled from all 37 blue examples in the native Word review. These are
# conditional writing patterns, not example amounts or a mandatory chapter list.
PROFESSIONAL_EXPRESSION_PATTERNS = (
    ProfessionalExpressionPattern("structure", ("R001", "R074"),
        "围绕管理问题合并同主题结论，收入和支出预算并列评价，支出与成本注明各自口径。"
        "正文突出重要变化，完整维度表放附表；图解紧随结论，不反复重述。示例目录不固定为七章。"),
    ProfessionalExpressionPattern("period", ("R002",),
        "编制说明分别列统计期间、同比期间、数据截至、预算版本和核算口径；"
        "历史回溯与当前年度任务明确区分，不能通过改标题年份沿用旧事实。"),
    ProfessionalExpressionPattern("overview", ("R003", "R020", "R057"),
        "摘要先回答本期累计、同期变化和主要偏差，再补重要月度观察；收入范围、分类字典、"
        "门诊是否含急诊或体检使用已确认名称。缺少同期时说明该同比暂不可评价，不用月度高低替代。"),
    ProfessionalExpressionPattern("budget", tuple(f"R{number:03d}" for number in (
        9, 11, 13, 14, 15, 17, 35, 39, 41, 43, 70,
    )),
        "预算先写分母属性，再列实际、差额和相应执行率：年度预算对应年度完成率，正式同期下达预算"
        "对应同期执行率。未下达分期预算不生成同期执行率或月度执行曲线，时间进度只作参考。"
        "偏差按金额影响与执行率共同说明；完整同维度对照才支持最大贡献。归口部门不称使用科室，"
        "支出性质不称业务条线；未知零说明采集/映射缺口，不能写成真实无预算。"),
    ProfessionalExpressionPattern("income", tuple(f"R{number:03d}" for number in (21, 23, 24, 27, 29, 31)),
        "累计与月均分别列示；分项及院区用规模、占比、同期增减和统一分母的贡献解释变化。"
        "两个收费分类反向变化不证明分类调整或需求下降；月度环比不证明持续改善。"
        "未证实的分类、政策和业务原因只列核查方向，科室规模排名不替代同比贡献。"),
    ProfessionalExpressionPattern("cost", tuple(f"R{number:03d}" for number in (36, 46, 48, 49, 50)),
        "成本先写同期间累计、同期和增减，再按类别、院区及匹配工作量解释；"
        "首尾两月差额仅是两个单月观察，不能写成本期累计同比下降。"
        "极值先写原始记录及性质待核实，不推导超预算或趋势；规模大不直接写成本过高、要求压降。"),
    ProfessionalExpressionPattern("surplus", ("R052", "R055", "R063"),
        "科室结余先交代已确认收入归属、成本分摊阶段和共同期间。未匹配单元标明暂不可评价，"
        "分别列收入与成本，不补零或直接相减排名。临床、医技、行政后勤按职能评价，"
        "内部结算汇总避免重复；仅在可比分解成立时说明收入与成本对结余变化的贡献。"),
    ProfessionalExpressionPattern("efficiency", ("R033", "R058", "R059", "R061"),
        "先匹配共同期间、组织和业务范围，再使用正式次均、平均住院日或床位使用率。"
        "金额和人次单位不同不排除次均分析，但全院收入不能直接除以出院人次；"
        "出院者床日不替代本期实际占用床日。无匹配指标时只报告服务量，不用相关系数评价效率。"),
    ProfessionalExpressionPattern("actions", ("R069", "R078"),
        "末段按已核实问题、金额或业务影响、核查/改进动作衔接。证据缺口只安排核查方向，"
        "责任部门、目标和时限由医院确认；不代医院下达整改。署名采用已确认医院及部门，"
        "系统提供方说明不代替编制或签发主体。"),
)


def professional_expression_guidance() -> tuple[str, ...]:
    return (
        "人工建议表述示例仅指导表达组织：仅在当前冻结证据满足适用条件时参考，不复制示例数字、"
        "空白占位符或无关口径限制；不得为凑齐句式补造同比、原因和建议。",
        *("人工示例表达要求：" + pattern.guidance for pattern in PROFESSIONAL_EXPRESSION_PATTERNS),
    )


@dataclass(frozen=True)
class ProfessionalReviewIssue:
    code: str
    criterion: str
    review_ids: tuple[str, ...]
    message: str


_BY_CODE = {item.code: item for item in PROFESSIONAL_CRITERIA}
_CLAUSE = re.compile(r"[。！？；;\n]")
_NEGATED = re.compile(
    r"(?:不能|不得|不可|并非|不是|不代表|尚不能|无法|不宜|尚未|待核实|待确认)"
    r"(?:据此)?(?:判断|认定|计算|作|作为|评价)?(?:正式)?\s*$"
)


def _affirmed(pattern: str, text: str) -> bool:
    return any(not _NEGATED.search(text[:match.start()]) for match in re.finditer(pattern, text))


def _unqualified_inference(pattern: str, text: str, qualifications: str) -> bool:
    """Unrelated limitations must not suppress a separate unsupported inference."""
    governing_negation = re.compile(
        r"(?:不能|不得|不可|不宜|无法|不足以|不应|不支持)"
        r"(?:仅|只|单独)?(?:据此|根据|基于|凭借|通过|利用|使用|用|以|凭|把|将|从)?\s*$"
    )
    return any(
        not re.search(qualifications, match[0])
        and not governing_negation.search(text[:match.start()])
        for match in re.finditer(pattern, text)
    )


def review_professional_content(markdown: str) -> tuple[ProfessionalReviewIssue, ...]:
    """Finite diagnostics only: never rewrites values, certifies truth or gates downloads."""
    from ..trace.markdown_body import trace_body

    text = trace_body(markdown, mask_inline_code=False)
    text = re.sub(r"\[\[[^\]\n]+\]\]|\*\*", "", text)
    issues: dict[str, ProfessionalReviewIssue] = {}

    def warn(code: str, criterion: str, message: str) -> None:
        rule = _BY_CODE[criterion]
        issues.setdefault(code, ProfessionalReviewIssue(code, criterion, rule.review_ids, message))

    for clause in _CLAUSE.split(text):
        # Only an explicitly percentage-valued execution/completion rate has
        # this denominator. A bare 0.89 is not silently converted to 89%.
        rates = list(re.finditer(r"(?:执行率|完成率)(?:约为|为|约)?\s*([+-]?\d+(?:\.\d+)?)\s*[%％]", clause))
        if (re.search(r"(?:预算|实际|执行率|差额).{0,12}(?:待核实|待确认|尚未核实)", clause)
                and _affirmed(r"接近预算|略低于预算|超预算|低于预算|预算合理|主要缺口", clause)
                and not re.search(r"不能判断|无法判断|尚不能判断|不宜判断", clause)):
            warn("professional_unverified_budget_conclusion", "budget_policy",
                 "专业口径需复核：预算、实际或差额尚未核实，不能提前判断接近预算、超预算或主要缺口。")
        if len(rates) == 1 and "待核实" not in clause and "待确认" not in clause:
            rate = Decimal(rates[0][1])
            after = clause[rates[0].end():]
            judgment = re.sub(r"^[\s，,:：]*(?:(?:实际支出|实际收入|实际|明显|因此|说明|表明|整体|均|已|仍|却|但|且)\s*)*", "", after)
            if ((rate < 100 and re.match(r"超预算|高于预算|超过预算", judgment))
                    or (rate > 100 and re.match(r"低于预算|未达到预算|不足预算", judgment))):
                warn("professional_budget_direction_conflict", "consistent_values",
                     "专业口径需复核：实际/预算执行率与超预算或低于预算的判断相反，须同步核对正文和图注。")
        if (re.search(r"预算(?:金额)?(?:为|是)\s*(?:0|零)(?![\d.])", clause)
                and re.search(r"(?:执行率|完成率)(?:为|约为)?\s*\d+(?:\.\d+)?\s*[%％]", clause)):
            warn("professional_zero_budget_rate", "missing_zero",
                 "专业口径需复核：预算为零时不能计算执行率，须单列无预算有实际等异常状态。")
        if (re.search(r"(?:预算|实际).{0,12}(?:为零|为0|零值)", clause)
                and _affirmed(r"(?:剔除|排除|不纳入)(?:全部|所有|该类|零值|这些|上述)?", clause)
                and not re.search(r"不能.{0,8}(?:剔除|排除)|不得.{0,8}(?:剔除|排除)", clause)):
            warn("professional_zero_records_excluded", "missing_zero",
                 "专业口径需复核：预算或实际为零的记录不能一概剔除，需区分异常零、真实零和缺失。")
        if (re.search(r"(?:月值|各月|每月).{0,10}(?:相同|相等|一致|重复)", clause)
                and (_affirmed(r"(?:因此|所以|据此|说明|表明).{0,15}(?:期末余额|存量|取(?:最新|期末))", clause)
                     or _affirmed(r"(?:属于|为|是|即)(?:按)?(?:整年|全年|年度)?(?:等额|均摊|平均分摊|分摊)", clause))):
            warn("professional_constant_budget_as_stock", "budget_policy",
                 "专业口径需复核：相同月值不能证明预算属于期末余额，须由预算时间属性和汇总规则确认。")
        if _unqualified_inference(
            r"开单收入.{0,90}(?:说明|表明|支持|用于|据此|因此).{0,20}(?:现金流|现金安排|资金安排)",
            clause, r"不能|不足以|不代表|无法|不支持|另需|还需",
        ):
            warn("professional_billed_income_cashflow", "cross_metric",
                 "专业口径需复核：开单收入不证明现金流或资金安排，须另有回款、应收及现金收支证据。")
        if _unqualified_inference(
            r"(?:相关系数|相关性).{0,90}(?:说明|表明|证明|反映).{0,12}(?:效率提升|效率改善|预算准确|预算合理|资源利用率提高)",
            clause, r"不能|不代表|不足以|无法",
        ):
            warn("professional_correlation_as_efficiency", "metric_identity",
                 "专业口径需复核：相关系数不能替代正式效率指标或证明预算准确性。")
        if (re.search(r"(?:负成本|负值|负数).{0,16}(?:为|是|属于|表明|反映)(?:冲销|调整|冲减)", clause)
                and not re.search(r"可能|待核|待确认|不能|无法|尚未确认", clause)):
            warn("professional_negative_value_as_adjustment", "anomaly",
                 "专业口径需复核：负数不能直接认定为冲销或调整，须核对凭证、映射和计算。")
        if (re.search(r"集中记录.{0,30}(?:说明|表明|属于|是).{0,10}一次性入账", clause)
                and not re.search(r"可能|待核|不能|尚未确认", clause)):
            warn("professional_concentrated_record_as_oneoff", "anomaly",
                 "专业口径需复核：集中记录不证明一次性入账性质，须有凭证或业务说明。")
        if _unqualified_inference(
            r"(?:成本|收入|支出)?(?:占比|规模|集中度).{0,10}(?:高|大).{0,90}(?:说明|表明|因此|据此|可见).{0,15}(?:浪费|不合理依赖|管理异常|成本管控不力)",
            clause, r"不能|不足以|不代表|无法",
        ):
            warn("professional_concentration_as_risk", "recommendation",
                 "专业口径需复核：规模或占比不能单独证明浪费或不合理依赖，须结合业务量、结构及比较基准。")
        if (re.search(r"(?:1月与9月|1月和9月|期初月|期末月|首尾两?月).{0,20}(?:计算|差额|相减)", clause)
                and re.search(r"变动|变化|增减|增长|下降", clause)
                and not re.search(r"不能|不代表|不等于|仅为两个单月|只是两个单月|不替代", clause)):
            warn("professional_endpoint_change_as_period_change", "contribution",
                 "专业口径需复核：首尾两个月的差额不能替代本期累计同比变化或贡献。")
    if "下半年" in text and re.search(r"1\s*[-—–~至到]\s*9\s*月|前三季度", text) and not re.search(
        r"1[0-2]\s*月", text
    ):
        warn("professional_half_year_beyond_window", "period",
             "专业口径需复核：本期只覆盖到9月，“下半年”会被理解为7—12月，应写明7—9月。")
    if re.search(r"^#{2,6}[^\n]*(?:统计关联|相关性分析|相关系数)", markdown, re.MULTILINE):
        warn("professional_correlation_section", "structure",
             "专业口径需复核：相关系数不回答预算执行或效率问题，不宜单列统计关联章节。")
    captions = [
        *re.findall(r"!\[([^\]]*)\]\([^)\s]*(?:\s+\"([^\"]*)\")?\)", markdown),
        *((caption, "") for caption in re.findall(r"^\*图表[:：]([^*\n]+)\*", markdown, re.MULTILINE)),
    ]
    if any("待核实" in part for caption in captions for part in caption):
        warn("professional_caption_placeholder", "consistent_values",
             "专业口径需复核：图题、图注或替代文本含“待核实”占位，图表结论未完成核对。")
    # Scope incompatibility can precede a claimed conclusion in the same paragraph.
    for paragraph in re.split(r"\n\s*\n", text):
        # 强弱描述常在系数之后的下一句；只看到下一个系数之前的描述。
        coefficients = list(re.finditer(r"相关系数(?:为|约为|是)?\s*([+-]?(?:0?\.\d+|1(?:\.0+)?))", paragraph))
        for index, coefficient in enumerate(coefficients):
            end = coefficients[index + 1].start() if index + 1 < len(coefficients) else len(paragraph)
            label = re.search(r"(弱|中等(?:强度)?|较强|强)(?:正|负)?相关", paragraph[coefficient.end():end])
            strength = abs(Decimal(coefficient[1]))
            if label and ((label[1] == "弱" and strength >= Decimal("0.7"))
                          or (label[1] in {"强", "较强"} and strength < Decimal("0.4"))):
                warn("professional_correlation_strength_mislabeled", "metric_identity",
                     "专业口径需复核：相关系数强弱描述与数值不符（如0.97写成弱相关）。")
        if (re.search(r"(?:收入与成本|收支).{0,25}(?:口径不一致|不同统计口径|口径未匹配|未完成分摊)", paragraph)
                and _affirmed(r"(?:结余|亏损|盈利|缺口)(?:最大|主要来源|排名|为[+-]?\d)|(?:最大|主要)(?:亏损|结余|缺口)", paragraph)):
            warn("professional_incompatible_surplus", "cross_metric",
                 "专业口径需复核：收入归属或成本分摊未匹配，不能据此计算或排名正式收支结余，参考声明不能补足前提。")
    return tuple(issues.values())
