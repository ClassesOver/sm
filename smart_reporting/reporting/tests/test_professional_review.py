"""Professional annotations become bounded diagnostics, never verified amounts."""

import hashlib

import pytest

from smart_reporting.reporting.hospital_operation.professional_review import (
    PROFESSIONAL_CRITERIA,
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


def test_missing_branding_does_not_make_the_software_supplier_the_report_author():
    assert EffectiveDocumentBranding().organization_name == '编制单位待确认'
    configured = EffectiveDocumentBranding.model_validate({'organizationName': '示例医院财务部'})
    assert configured.organization_name == '示例医院财务部'
    # Explicitly frozen older branding is retained, never rewritten on read.
    historical = EffectiveDocumentBranding.model_validate({'organizationName': '原编制单位'})
    assert historical.organization_name == '原编制单位'


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
    ('开单收入增长，说明现金流充裕。', 'professional_billed_income_cashflow'),
    ('相关系数为0.9，说明效率提升。', 'professional_correlation_as_efficiency'),
    ('负成本为冲销。', 'professional_negative_value_as_adjustment'),
    ('集中记录表明是一次性入账。', 'professional_concentrated_record_as_oneoff'),
    ('成本占比高，因此管理异常。', 'professional_concentration_as_risk'),
    ('收入与成本口径不一致，但科室结余为20万元，仅供参考。', 'professional_incompatible_surplus'),
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
