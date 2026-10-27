"""Professional annotations become bounded diagnostics, never verified amounts."""

import hashlib

import pytest

from smart_reporting.reporting.hospital_operation.professional_review import (
    PROFESSIONAL_CRITERIA,
    PROFESSIONAL_EXPRESSION_PATTERNS,
    professional_expression_guidance,
    professional_stage_guidance,
    review_professional_content,
)
from smart_reporting.reporting.instructions import (
    HOSPITAL_ANALYSIS_INSTRUCTIONS,
    HOSPITAL_OUTLINE_INSTRUCTIONS,
    HOSPITAL_REPORT_WRITING_INSTRUCTIONS,
)
from smart_reporting.reporting.profile.models import EffectiveDocumentBranding
from smart_reporting.reporting.trace.content_review import review_content_result

from .test_trace_subject_validate import _make_editor_with_subject


def test_all_79_annotations_have_a_stage_and_required_evidence_mapping():
    assert len({rule.code for rule in PROFESSIONAL_CRITERIA}) == len(PROFESSIONAL_CRITERIA)
    assert {ref for rule in PROFESSIONAL_CRITERIA for ref in rule.review_ids} == {
        f"R{index:03d}" for index in range(1, 80)
    }
    assert all(rule.required_evidence and rule.stages for rule in PROFESSIONAL_CRITERIA)


def test_all_37_native_word_expression_examples_reach_the_writing_stage_without_sample_values():
    expected = {f"R{number:03d}" for number in (
        1, 2, 3, 9, 11, 13, 14, 15, 17, 20, 21, 23, 24, 27, 29, 31, 33, 35, 36,
        39, 41, 43, 46, 48, 49, 50, 52, 55, 57, 58, 59, 61, 63, 69, 70, 74, 78,
    )}
    refs = [ref for pattern in PROFESSIONAL_EXPRESSION_PATTERNS for ref in pattern.review_ids]
    assert len(refs) == len(set(refs)) == 37 and set(refs) == expected
    assert set(professional_expression_guidance()) <= set(HOSPITAL_REPORT_WRITING_INSTRUCTIONS)
    guide = "\n".join(professional_expression_guidance())
    assert "适用条件" in guide and "不复制示例数字" in guide
    assert all(value not in guide for value in ("95.13", "10.57", "99.12", "531.65", "____"))


def test_writing_instructions_keep_requested_window_and_do_not_force_causes_or_actions():
    guide = "\n".join(HOSPITAL_REPORT_WRITING_INSTRUCTIONS)
    assert "统计期间遵守冻结请求" in guide
    assert "不能冒充完整本期" in guide
    assert "不要求每段凑齐异常、原因和建议" in guide
    assert "主口径必须采用最新完整" not in guide


def test_branding_uses_original_default_or_environment(monkeypatch):
    monkeypatch.delenv('AGENT_REPORT_ORGANIZATION_NAME', raising=False)
    assert EffectiveDocumentBranding().organization_name == '上海鼎医信息技术有限公司'
    monkeypatch.setenv('AGENT_REPORT_ORGANIZATION_NAME', '  环境配置编制单位  ')
    assert EffectiveDocumentBranding().organization_name == '环境配置编制单位'
    configured = EffectiveDocumentBranding.model_validate({'organizationName': '示例医院财务部'})
    assert configured.organization_name == '示例医院财务部'
    monkeypatch.setenv('AGENT_REPORT_ORGANIZATION_NAME', '  ')
    assert EffectiveDocumentBranding().organization_name == '上海鼎医信息技术有限公司'


@pytest.mark.parametrize('stage,instructions', [
    ('analysis', HOSPITAL_ANALYSIS_INSTRUCTIONS), ('outline', HOSPITAL_OUTLINE_INSTRUCTIONS),
    ('draft', HOSPITAL_REPORT_WRITING_INSTRUCTIONS),
])
def test_professional_criteria_reach_the_actual_workflow_stage(stage, instructions):
    assert set(professional_stage_guidance(stage)) <= set(instructions)
    combined = '\n'.join(instructions)
    assert '95.13' not in combined and '99.12' not in combined
    assert '最多10章' not in combined


@pytest.mark.parametrize('text,code', [
    ('当月执行率为89%，超预算。', 'professional_budget_direction_conflict'),
    ('当月执行率为72%，实际高于预算。', 'professional_budget_direction_conflict'),
    ('当月执行率为120%，低于预算。', 'professional_budget_direction_conflict'),
    ('实际与预算数值待核实，但总体接近预算。', 'professional_unverified_budget_conclusion'),
    ('预算为0元，实际为20元，执行率为0%。', 'professional_zero_budget_rate'),
    ('排除预算或实际为零的所有记录。', 'professional_zero_records_excluded'),
    ('各月数值相同，因此属于期末余额。', 'professional_constant_budget_as_stock'),
    ('全年预算汇总规则尚未核实，但仍计算执行率，仅供参考。', 'professional_unverified_budget_rate'),
    ('全年预算口径待核实，预算执行率为75%。', 'professional_unverified_budget_rate'),
    ('计算实际收入/全年预算的执行率，并披露全年预算挂载方式未核实。', 'professional_unverified_budget_rate'),
    ('计算预算执行率；全年预算挂载方式未核实，披露缺口。', 'professional_unverified_budget_rate'),
    ('全年预算口径待核实，核实后再计算执行率，但仍计算完成率作为参考。', 'professional_unverified_budget_rate'),
    ('开单收入增长，说明现金流充裕。', 'professional_billed_income_cashflow'),
    ('相关系数为0.9，说明效率提升。', 'professional_correlation_as_efficiency'),
    ('负成本为冲销。', 'professional_negative_value_as_adjustment'),
    ('集中记录表明是一次性入账。', 'professional_concentrated_record_as_oneoff'),
    ('成本占比高，因此管理异常。', 'professional_concentration_as_risk'),
    ('收入与成本口径不一致，但科室结余为20万元，仅供参考。', 'professional_incompatible_surplus'),
    ('各月数值完全一致，属于按整年等额分摊的预算计划。', 'professional_constant_budget_as_stock'),
    ('变动额与变动率以2025年1月与9月两个月份计算。', 'professional_endpoint_change_as_period_change'),
    ('相关系数为0.97，样本覆盖4,091条明细记录。该关联为弱正相关。', 'professional_correlation_strength_mislabeled'),
    ('2025年1—9月门诊人次下半年高位波动。', 'professional_half_year_beyond_window'),
    ('## 7.2 收入预算类统计关联\n\n说明。', 'professional_correlation_section'),
    ('![收入大类构成](chart.png "药品与卫生材料合计占待核实")', 'professional_caption_placeholder'),
    ('*图表：北部院区执行率待核实为最低*', 'professional_caption_placeholder'),
    ('实际医疗服务收入、实际检查化验收入均为常量0，占比分别为0.00%和0.00%。', 'professional_unknown_zero_share'),
])
def test_annotation_counterexamples_produce_specific_soft_diagnostics(text, code):
    issues = review_professional_content(text)
    assert code in {issue.code for issue in issues}
    issue = next(issue for issue in issues if issue.code == code)
    assert issue.review_ids and '需复核' in issue.message
    review = review_content_result(text, ())
    assert issue.message in review.warnings and review.accuracy_count > 0


@pytest.mark.parametrize('text', [
    '当月执行率为89%，低于预算。',
    '当月执行率为120%，超预算。',
    '当月执行率为100%，达到预算。',
    '北院执行率为89%，南院超预算。',
    '年度预算完成率为89%，高于序时进度。',
    '执行率为0.89，口径及单位待核实。',
    '预算数值待核实，不能判断是否接近预算。',
    '全年预算口径未核实，暂不计算执行率，继续分析实际收入。',
    '先核实全年预算挂载与汇总规则，仅在核实通过后计算执行率。',
    '全年预算口径已核实，执行率为75%。',
    '预算为0元，实际为20元，执行率不计算。',
    '预算或实际为零的记录不得排除。',
    '各月数值相同，但不能说明属于期末余额。',
    '开单收入不能证明现金流，现金判断另需回款证据。',
    '相关系数不能说明效率提升。',
    '负成本可能是冲销，原因待核实。',
    '集中记录可能是一次性入账，性质待核实。',
    '成本占比高，不能据此认定浪费。',
    '收入与成本口径不一致，不能计算正式结余，也不能作亏损排名。',
    '本期收入与成本已经匹配，结余为20万元。',
    '### 业务情况\n\n正常零值应如实保留，缺失不得补零。',
    '```text\n执行率为89%，超预算。\n```',
    '各月数值相同，不能据此认定属于等额分摊。',
    '1月与9月差额仅为两个单月观察，不代表累计变化。',
    '相关系数为0.32，属于弱正相关。',
    '2025年1—9月中，7—9月处于高位。',
    '2025年全年报告，下半年收入回升，12月最高。',
    '![收入大类构成](chart.png "药品与卫生材料合计占49.03%")',
    '检查化验收入在本表为0，可能未采集或未映射，不作占比结论。',
    '药品收入占比27.52%。',
    '药品占比0.50%，卫生材料占比10.00%。',
])
def test_valid_limits_and_business_distinctions_are_not_flagged(text):
    assert review_professional_content(text) == ()


def test_repeated_findings_are_deduplicated_without_changing_report_text():
    text = '执行率为89%，超预算。\n\n执行率为89%，超预算。'
    assert len(review_professional_content(text)) == 1
    assert text.endswith('执行率为89%，超预算。')


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_editor_reevaluates_professional_findings_for_current_body(tmp_path):
    editor, _, context = await _make_editor_with_subject(tmp_path, include_table=False)
    index = await editor.trace.require_index(context)
    original = (await editor.trace._read_registered_file(
        context, next(file for file in index.files if file.resource_id == index.markdown_file_resource_id),
        max_bytes=16 * 1024 * 1024,
    )).decode()
    bad = original + '\n\n当月执行率为89%，超预算。'
    result = await editor.trace.validate(context, bad, hashlib.sha256(bad.encode()).hexdigest())
    issue = next(issue for issue in result['quality']['issues']
                 if issue['code'] == 'professional_budget_direction_conflict')
    assert issue['severity'] == 'warning' and 'R011' in issue['reasons']
    fixed = bad.replace('执行率为89%，超预算', '执行率为89%，低于预算')
    updated = await editor.trace.validate(context, fixed, hashlib.sha256(fixed.encode()).hexdigest())
    assert all(issue['code'] != 'professional_budget_direction_conflict' for issue in updated['quality']['issues'])
    assert updated['quality']['inputSha256'] != result['quality']['inputSha256']


def test_text_generators_receive_review_rules_and_expression_examples():
    """表述示例必须进入真正撰写正文、图注的生成器，而不只存在于常量中。"""
    from smart_reporting.reporting.bootstrap import create_reporting_text_generators

    visualization, section, recovery = create_reporting_text_generators(None)
    for agent in (section, recovery):
        assert set(HOSPITAL_REPORT_WRITING_INSTRUCTIONS) <= set(agent.instructions)
        assert set(professional_expression_guidance()) <= set(agent.instructions)
    assert set(professional_stage_guidance("draft")) <= set(visualization.instructions)
