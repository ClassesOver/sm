"""补证决策的确定性前置：固定事实明确覆盖问题时不请求模型；不确定时照常交给模型。"""

from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisItemWorkflow,
    _AnalysisItemState,
)
from smart_reporting.reporting.workflow.runtime.evidence_coverage import facts_cover_analysis

from .test_dimension_breakdowns import FIELDS, _bundle

THREE_MONTHS = (
    "month,department,income_type,amount\n"
    "2025-01,A,住院,60\n2025-01,A,门诊,40\n2025-02,A,住院,90\n"
    "2025-02,B,门诊,70\n2025-03,B,住院,80\n2025-03,A,门诊,30\n"
)


def _analysis(step, actions=("汇总",)):
    return {"analysisId": "analysis_001", "step": step, "actions": list(actions)}


@pytest.mark.parametrize(("step", "covered"), [
    # 2025-10-19 真实运行的管理问题：规模、结构占比与月度走势由固定事实覆盖。
    ("2025年医院医疗收入的总体规模及按收入类型和门诊住院划分的结构占比如何？", "规模、维度构成"),
    ("2025年各月医疗收入的变化走势如何，拐点出现在哪些月份？", "趋势"),
    # 贡献、同步/可比等超出固定事实的意图交给模型判断。
    ("2025年收入月度波动主要由哪些收入类型贡献？", None),
    ("2025年成本与收入的月度变化是否同步，口径上是否可比？", None),
    # 点名了未拆分的维度（院区）不能视为覆盖；已拆分的科室可以。
    ("2025年按院区划分的收入结构如何？", None),
    ("2025年按科室划分的收入结构如何？", "维度构成"),
    # 没有同比事实时同比问题不能视为覆盖。
    ("2025年收入同比变化如何？", None),
    # 只说“比重”而点名的项目未登记分组时不能视为覆盖；点名已登记的组值可以。
    ("2025年药品收入占医疗收入的比重如何？", None),
    ("2025年住院收入占医疗收入的比重如何？", "维度构成"),
    # 多出限定词的维度（开单科室）不是已拆分的“科室”。
    ("2025年按开单科室划分的收入结构如何？", None),
])
def test_standard_questions_are_covered_only_by_matching_facts(step, covered):
    reason = facts_cover_analysis(_bundle(THREE_MONTHS), _analysis(step), {})
    assert (reason is None) is (covered is None)
    if covered:
        assert reason.endswith(covered)


@pytest.mark.parametrize("instruction", [
    {"analysisReworkRequest": {"analysisIds": ["analysis_001"]}},
    {"reviewFeedback": "补充科室构成"},
    {"thinkingFailureKind": "evidence_incomplete"},
])
def test_rework_feedback_and_retries_always_ask_the_model(instruction):
    assert facts_cover_analysis(_bundle(THREE_MONTHS), _analysis("2025年收入总体规模如何？"), instruction) is None


def test_structure_needs_shareable_groups_for_every_current_metric():
    from .test_deterministic_analysis import semantic

    measures = (
        {**semantic("amount", unit="元"), "additiveAcross": ["department", "income_type"]},
        # 成本未确认可加维度，没有分组：构成问题可能问的是成本，交给模型。
        {**semantic("cost", unit="元")},
    )
    csv = ("month,department,income_type,amount,cost\n2025-01,A,住院,60,1\n"
           "2025-02,B,门诊,40,2\n2025-03,A,门诊,30,3\n")
    bundle = _bundle(csv, fields=(*FIELDS, "cost"), measures=measures)
    assert facts_cover_analysis(bundle, _analysis("2025年按科室划分的结构占比如何？"), {}) is None
    # 净额有负组时不登记占比，构成不算已覆盖。
    negative = "month,department,income_type,amount\n2025-01,A,住院,60\n2025-02,B,门诊,-10\n2025-03,A,门诊,30\n"
    assert facts_cover_analysis(_bundle(negative), _analysis("2025年按科室划分的结构占比如何？"), {}) is None


def test_named_group_must_be_registered_for_a_current_fact():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        build_deterministic_analysis_bundle,
    )

    from .test_deterministic_analysis import analysis, context, semantic
    from .test_dimension_breakdowns import DIMENSIONS

    declaration = {
        **semantic("amount", unit="元"),
        "additiveAcross": ["month", "department", "income_type"],
    }

    def dataset(dataset_id):
        return context(
            dataset_id,
            fields=FIELDS,
            semantics=(declaration,),
        ).model_copy(update={"period_granularities": {"month": "month"}})

    bundle = build_deterministic_analysis_bundle(
        analysis().model_copy(update={"series_granularity": "month"}),
        (
            (
                "current",
                "month,department,income_type,amount\n"
                "2025-01,A,住院,60\n2025-01,B,门诊,40\n".encode(),
                dataset("current"),
                ("current",),
            ),
            (
                "baseline",
                "month,department,income_type,amount\n"
                "2024-01,C,药品,70\n2024-01,D,检查,30\n".encode(),
                dataset("baseline"),
                ("yoy",),
            ),
        ),
        profile_dimensions=DIMENSIONS,
    )

    assert facts_cover_analysis(
        bundle, _analysis("2025年药品收入占医疗收入的比重如何？"), {},
    ) is None
    assert facts_cover_analysis(
        bundle, _analysis("2025年住院收入占医疗收入的比重如何？"), {},
    ).endswith("维度构成")


def test_level_and_cumulative_snapshots_do_not_prove_a_flow_trend():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )

    from .test_cumulative_changes import cumulative_document
    from .test_frozen_time_aggregation import frozen_bundle

    stock = frozen_bundle(additive=("department",), months=(1, 2, 3), comparison=False)
    cumulative = DeterministicAnalysisBundle.model_validate(cumulative_document())

    for facts in (stock, cumulative):
        assert facts_cover_analysis(
            facts, _analysis("2025年收入月度走势如何？", ()), {},
        ) is None


def test_actions_beyond_fixed_facts_ask_the_model():
    facts = _bundle(THREE_MONTHS)
    assert facts_cover_analysis(facts, _analysis("2025年收入总体规模如何？", ("汇总", "异常识别")), {}) is None
    assert facts_cover_analysis(facts, _analysis("2025年收入总体规模如何？", ("汇总", "科室排名")), {}) is None
    # 无法识别任何标准意图时不猜测覆盖。
    assert facts_cover_analysis(facts, {"analysisId": "analysis_001", "step": "收入情况", "actions": []}, {}) is None


@pytest.mark.anyio
async def test_covered_question_completes_planning_without_a_model_decision():
    decide = AsyncMock(side_effect=AssertionError("固定事实已覆盖时不应请求补证决策"))
    workflow = AnalysisItemWorkflow(decide_evidence=decide, run_code=AsyncMock(), summarize=AsyncMock(),
                                    read_file=AsyncMock(), complete=AsyncMock())
    state = _AnalysisItemState(instruction={
        "currentAnalysisId": "analysis_001",
        "currentAnalysis": _analysis("2025年医院医疗收入的总体规模及按收入类型划分的结构占比如何？"),
    })
    state.facts = _bundle(THREE_MONTHS)
    await workflow._decide_evidence(state)
    decide.assert_not_awaited()
    assert state.decision.requires_supplemental_evidence is False
    assert state.decision.reason.startswith("固定事实已覆盖")
    assert state.statuses["plan-evidence"] == "completed"
