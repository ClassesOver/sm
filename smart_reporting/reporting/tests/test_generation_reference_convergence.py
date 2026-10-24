"""纠错评分、最终正文与编辑器引用必须使用同一份规范化候选。"""

import hashlib
import json

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.model_policy import ThinkingRequest
from smart_reporting.reporting.structured_output.execution import _validation_issues
from smart_reporting.reporting.tests.test_content_review import _metric
from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _context,
    _plan_claim,
    _revenue_work_item,
)
from smart_reporting.reporting.trace import semantic_bindings
from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime import sections
from smart_reporting.reporting.workflow.runtime.phase_models import (
    RenderSectionPlan,
    SectionBlockContent,
    SectionContent,
    SectionEvidenceBundle,
    SectionEvidenceFile,
    SectionPlanOutput,
)
from smart_reporting.task_execution import TaskExecutionScope

RAW_RETARGETABLE = '2025年2月收入{{value:fact-aaaaaaaaaaaaaaaa:total:人次}}。'
EXPECTED_REFERENCE = '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:人次}}'


def _source_file(content, *, path='evidence/table.json', **overrides):
    raw = content.encode('utf-8')
    identity = FileIdentity(
        path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
    ).model_copy(update=overrides)
    return SectionEvidenceFile(identity=identity, content=content)


async def _generate(monkeypatch, mode, outputs, *, project=False, corrections=None):
    work_item = _revenue_work_item()
    metric = {**_metric(values=(10, 20)), 'displayName': '收入'}
    controlled = outputs in (['USE_ASSERTION'], ['USE_COMPARISON'], ['USE_MONTH_CHANGE'],
                              ['USE_MONTH_AVERAGE'], ['USE_MULTI_COMPARISON'], ['USE_GROUP_SHARE'], ['USE_GROUP_RANK'], ['USE_MONTH_TREND'])
    comparison = outputs == ['USE_COMPARISON']
    monthly_change = outputs == ['USE_MONTH_CHANGE']
    monthly_average = outputs == ['USE_MONTH_AVERAGE']
    multi_comparison = outputs == ['USE_MULTI_COMPARISON']
    group_share = outputs == ['USE_GROUP_SHARE']
    group_rank = outputs == ['USE_GROUP_RANK']
    monthly_trend = outputs == ['USE_MONTH_TREND']
    if controlled:
        metric['scope'] = {'院区': '北院'}
    if monthly_change:
        metric.update(profileHash='a' * 64, periodMissingCount=0)
    document = {'analysisId': 'analysis_001', 'metrics': [metric]}
    if comparison:
        from smart_reporting.reporting.tests.test_assertion_compiler import comparison_document
        document = comparison_document()
    selected_fact_id = 'fact-cccccccccccccccc' if comparison else 'fact-aaaaaaaaaaaaaaaa'
    if monthly_average or multi_comparison:
        from smart_reporting.reporting.tests.test_frozen_time_aggregation import frozen_bundle
        document = json.loads(frozen_bundle(comparison=multi_comparison).model_dump_json(by_alias=True))
        selected_fact_id = (document['comparisons'][0] if multi_comparison else document['metrics'][0])['factId']
    if group_share or group_rank:
        from smart_reporting.reporting.tests.test_group_share_assertions import group_bundle
        document = json.loads(group_bundle().model_dump_json(by_alias=True))
        selected_fact_id = document['metrics'][0]['factId']
    if monthly_trend:
        from smart_reporting.reporting.tests.test_monthly_trend_assertions import trend_bundle
        document = json.loads(trend_bundle().model_dump_json(by_alias=True))
        selected_fact_id = document['metrics'][0]['factId']
    source = json.dumps(document, ensure_ascii=False)
    evidence_file = _source_file(source, path=work_item.evidence[0].evidence_files[0].path)
    evidence = SectionEvidenceBundle(
        sectionCode='section_001', factSummaries=(), files=(evidence_file,),
    )
    if project:
        work_item = work_item.model_copy(update={'finding_ids': ('finding-test',)})

        def project_evidence(files, _work_item):
            # Projection deliberately changes bytes without changing the frozen identity.
            return (files[0].model_copy(update={'content': source + ' '}),), {
                'fact-aaaaaaaaaaaaaaaa',
            }, ()

        monkeypatch.setattr(sections, 'finding_evidence_view', project_evidence)
    plan_payload = {
        'sectionCode': 'section_001',
        'blocks': [{'blockId': 'block_001', 'objective': '收入', 'claimIds': ['claim_001']}],
        'claims': [_plan_claim('claim_001', factIds=[selected_fact_id])],
    }
    calls = []
    bound_source_maps = []
    render_bound_numbers = semantic_bindings.render_bound_numbers

    def capture_bound_numbers(*args, **kwargs):
        bound_source_maps.append(kwargs.get('table_sources'))
        return render_bound_numbers(*args, **kwargs)

    monkeypatch.setattr(semantic_bindings, 'render_bound_numbers', capture_bound_numbers)

    async def fake_stage(_agent, _schema, stage, payload, **_kwargs):
        if stage == 'plan':
            return SectionPlanOutput.model_validate({'kind': 'render', **plan_payload})
        while True:
            text = outputs[min(len(calls), len(outputs) - 1)]
            if controlled:
                text = next(item['placeholder'] for item in payload['assertionCatalog']
                            if item['status'] == 'supported' and item['operation'] == ('monthly_trend' if monthly_trend else 'group_rank' if group_rank else 'share' if group_share else 'monthly_average' if monthly_average else 'difference' if comparison or monthly_change or multi_comparison else 'value')
                            and (not comparison or item['unit'] == '万元'))
            calls.append(payload)
            candidate = ({'blocks': [{'blockId': 'block_001', 'markdown': text}]}
                         if mode in {'whole', 'whole_entry'} else {'markdown': text})
            if corrections is None:
                return (SectionContent if mode in {'whole', 'whole_entry'} else SectionBlockContent).model_validate(candidate)
            # 模拟结构化执行器：响应校验失败时把 issues 回灌给同一模型，再取下一份输出。
            try:
                return _kwargs['response_validator'](candidate)
            except ValidationError as error:
                corrections.append(_validation_issues(error))

    monkeypatch.setattr(sections, '_run_section_stage', fake_stage)
    notices = {}
    options = {
        'scope': TaskExecutionScope('task-1', 'user-1', 'thread-1', 'sandbox-1', 'section'),
        'run_context': _context(),
        'thinking_request': ThinkingRequest(operation='section_generation', complexity='standard'),
        'review_notices': notices,
    }
    instruction = {'assertionPolicy': {'mode': 'enabled', 'profileHash': 'a' * 64,
                                     'authorizationScopeHash': 'b' * 64,
                                     'trustedFactSha256': [hashlib.sha256(source.encode()).hexdigest()]}} if controlled else {}
    if mode == 'whole':
        result = await sections._generate_whole_section_content(
            object(), instruction, evidence, work_item, RenderSectionPlan.model_validate(plan_payload), **options,
        )
    else:
        result = await sections._generate_section_in_blocks(
            object(), instruction, evidence, work_item, whole_section=mode == 'whole_entry', **options,
        )
    return result.blocks[0], notices.get('block_001', []), calls, source, bound_source_maps


def _assert_original_source_maps(source_maps, source):
    path = _revenue_work_item().evidence[0].evidence_files[0].path
    assert source_maps
    assert all(mapping == {derive_resource_id(path): source.encode('utf-8')} for mapping in source_maps)


def _assert_editor_binding_is_current(block, source):
    assert block.markdown == '2025年2月收入20人次。'
    assert not block.review_notices
    assert len(block.number_references) == 1
    reference = block.number_references[0]
    assert reference.token == EXPECTED_REFERENCE
    selected = resolve_number_reference(reference.token, [source])
    assert selected is not None
    markdown = anchor_bound_numbers(block.markdown, block.number_references)
    assert claim_status(
        markdown, reference.claim_id, selected['value'],
        expected_unit=selected['unit'], expected_periods=selected['periods'],
        expected_period_roles=selected['period_roles'], expected_scope=selected['scope'],
        expected_reference=selected,
    ) == {'status': 'valid', 'warnings': []}


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks'])
async def test_unique_reference_alignment_converges_without_an_extra_model_call(monkeypatch, mode):
    block, notices, calls, source, source_maps = await _generate(monkeypatch, mode, [RAW_RETARGETABLE])
    _assert_original_source_maps(source_maps, source)
    _assert_editor_binding_is_current(block, source)
    assert len(calls) == 1
    assert notices == []


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks'])
async def test_correction_is_scored_after_alignment_and_does_not_restore_unknown_number(monkeypatch, mode):
    block, notices, calls, source, source_maps = await _generate(monkeypatch, mode, ['收入999人次。', RAW_RETARGETABLE])
    _assert_original_source_maps(source_maps, source)
    _assert_editor_binding_is_current(block, source)
    assert len(calls) == 2
    assert notices == []


BAD_REFERENCE = '本期合计{{value:fact-aaaaaaaaaaaaaaaa:bogus:人次}}。'


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks'])
async def test_invalid_reference_is_corrected_by_the_model_inside_the_same_stage(monkeypatch, mode):
    corrections = []
    block, notices, calls, source, _ = await _generate(
        monkeypatch, mode, [BAD_REFERENCE, RAW_RETARGETABLE], corrections=corrections,
    )
    _assert_editor_binding_is_current(block, source)
    # 引用问题在产出关口就交回模型改正，后续内容复核不再为它多开一轮。
    assert len(calls) == 2 and notices == []
    [[issue]] = corrections
    assert '{{value:fact-aaaaaaaaaaaaaaaa:total:人次}}=30人次' in issue['message']


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks'])
async def test_uncorrected_reference_degrades_to_notice_with_reason(monkeypatch, mode):
    corrections = []
    block, notices, calls, _source, _ = await _generate(monkeypatch, mode, [BAD_REFERENCE], corrections=corrections)
    # 每个 stage 最多退回两次后放行；内容复核纠错轮同样受限，生成不被阻断。
    assert len(calls) == 2 * (sections._MAX_REFERENCE_REJECTIONS + 1)
    assert len(corrections) == 2 * sections._MAX_REFERENCE_REJECTIONS
    assert '待核实' in block.markdown and not block.number_references
    [notice] = block.review_notices
    assert notice.kind == 'numeric_unverified' and '取值方式' in notice.reason
    assert any(item['code'] == 'report_section_block_unverified_numbers' for item in notices)


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole_entry', 'blocks'])
async def test_projection_keeps_original_verified_bytes_for_number_rendering(monkeypatch, mode):
    block, notices, calls, source, source_maps = await _generate(
        monkeypatch, mode, [RAW_RETARGETABLE], project=True,
    )
    _assert_original_source_maps(source_maps, source)
    _assert_editor_binding_is_current(block, source)
    assert len(calls) == 1
    assert notices == []


@pytest.mark.parametrize('fault', ['size', 'hash', 'unicode', 'conflict'])
@pytest.mark.parametrize('reverse', [False, True])
def test_verified_table_sources_rejects_entire_conflicting_group(fault, reverse):
    good = _source_file('{"收入": 20}')
    other = _source_file('{"收入": 40}', path='evidence/other.json')
    if fault == 'size':
        bad = good.model_copy(update={'identity': good.identity.model_copy(update={'size': 1})})
    elif fault == 'hash':
        bad = good.model_copy(update={'identity': good.identity.model_copy(update={'sha256': 'b' * 64})})
    elif fault == 'unicode':
        bad = good.model_copy(update={'content': '\ud800'})
    else:
        bad = _source_file('{"收入": 30}')
    files = (good, bad, good, other)
    if reverse:
        files = tuple(reversed(files))
    assert sections._verified_table_sources(files) == {
        derive_resource_id(other.identity.path): other.content.encode('utf-8'),
    }


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks', 'whole_entry'])
async def test_controlled_fact_is_expanded_before_review_and_uses_original_selector(monkeypatch, mode):
    block, notices, calls, source, _ = await _generate(monkeypatch, mode, ['USE_ASSERTION'])
    assert '北院' in block.markdown
    assert '{{assert:' not in block.markdown and 'assert-' not in block.markdown
    assert len(block.number_references) == 1 and not notices
    assert resolve_number_reference(block.number_references[0].token, [source]) is not None
    assert calls[0]['assertionCatalog']


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks', 'whole_entry'])
async def test_controlled_comparison_is_identical_before_review_and_final_binding(monkeypatch, mode):
    block, notices, calls, source, _ = await _generate(monkeypatch, mode, ['USE_COMPARISON'])
    assert all(label in block.markdown for label in ('本期2025-01', '基期2024-01', '北院', '同比差额'))
    assert '{{assert:' not in block.markdown
    assert len(block.number_references) == 1 and not notices
    reference = block.number_references[0]
    assert reference.token == '{{value:fact-cccccccccccccccc:change:万元}}'
    assert resolve_number_reference(reference.token, [source])['value'] == -60
    assert any(item['operation'] == 'difference' and item['status'] == 'supported'
               for item in calls[0]['assertionCatalog'])


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks', 'whole_entry'])
async def test_controlled_monthly_change_is_exposed_as_assertion_without_raw_server_token(monkeypatch, mode):
    block, notices, calls, source, _ = await _generate(monkeypatch, mode, ['USE_MONTH_CHANGE'])
    assert all(label in block.markdown for label in ('本期2025-02', '基期2025-01', '环比差额'))
    assert len(block.number_references) == 1 and not notices
    reference = block.number_references[0]
    assert reference.token == '{{value:fact-aaaaaaaaaaaaaaaa:periodChanges.1:人次}}'
    assert resolve_number_reference(reference.token, [source])['value'] == 10
    assert not any('periodChanges.' in token for token in calls[0]['frozenNumbers'])


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks', 'whole_entry'])
@pytest.mark.parametrize('choice,operation,value', [('USE_MONTH_AVERAGE', 'monthly_average', 150),
                                                  ('USE_MULTI_COMPARISON', 'difference', 150)])
async def test_generation_consumes_frozen_time_contract_without_model_capability_claims(monkeypatch, mode, choice, operation, value):
    block, notices, calls, source, _ = await _generate(monkeypatch, mode, [choice])
    assert '2025-01至2025-02' in block.markdown
    if operation == 'difference':
        assert '基期2024-01至2024-02' in block.markdown
    else:
        assert '月均值' in block.markdown
    assert len(block.number_references) == 1 and not notices
    selected = resolve_number_reference(block.number_references[0].token, [source])
    assert selected['value'] == value
    assert any(item['status'] == 'supported' and item['operation'] == operation
               for item in calls[0]['assertionCatalog'])


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks', 'whole_entry'])
async def test_group_share_generation_keeps_the_frozen_population_and_scope(monkeypatch, mode):
    block, notices, calls, source, _ = await _generate(monkeypatch, mode, ['USE_GROUP_SHARE'])
    assert all(label in block.markdown for label in ('2025-01至2025-02', '分组范围', '内科', '总体范围', '北院', '收入登记合计'))
    assert '全院' not in block.markdown and '南院' not in block.markdown
    assert len(block.number_references) == 1 and not notices
    reference = block.number_references[0]
    assert ':groupShares.topGroups.0:%}}' in reference.token
    selected = resolve_number_reference(reference.token, [source])
    assert selected['value'] == 60 and selected['scope'] == {'campus': '北院', 'department': '内科'}
    assert not any('groupShares.' in token for token in calls[0]['frozenNumbers'])
    assert any(item['status'] == 'supported' and item['operation'] == 'share' for item in calls[0]['assertionCatalog'])


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks', 'whole_entry'])
async def test_group_rank_generation_keeps_scope_direction_and_competition_rule(monkeypatch, mode):
    block, notices, calls, source, source_maps = await _generate(monkeypatch, mode, ['USE_GROUP_RANK'])
    _assert_original_source_maps(source_maps, source)
    assert '总体范围（campus=北院）' in block.markdown
    assert '降序' in block.markdown and '同值同名次' in block.markdown and '第1名' in block.markdown
    assert 'department=内科' in block.markdown and '120元' in block.markdown
    assert len(block.number_references) == 1 and not notices and len(calls) == 1
    assert ':topGroups.0:元}}' in block.number_references[0].token
    assert not block.review_notices


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks', 'whole_entry'])
async def test_monthly_trend_generation_uses_complete_window_before_review(monkeypatch, mode):
    block, notices, calls, source, source_maps = await _generate(monkeypatch, mode, ['USE_MONTH_TREND'])
    _assert_original_source_maps(source_maps, source)
    assert '2025-01至2025-03' in block.markdown and 'department=A' in block.markdown
    assert '逐月严格上升' in block.markdown and '全部相邻月份' in block.markdown
    assert len(block.number_references) == 1 and len(calls) == 1 and not notices and not block.review_notices
    assert ':monthlyTrend:元}}' in block.number_references[0].token
    assert not any('monthlyTrend' in token for token in calls[0]['frozenNumbers'])
