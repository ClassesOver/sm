"""共同统计范围应来自全部引用的交集，并在正文可见，不能由复核模型猜补。"""
import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.model_policy import ThinkingRequest
from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
from smart_reporting.reporting.workflow.runtime import sections


def scope_case(*, other_company=False, missing_scope=False):
    document = json.loads(contents()[0])
    for index, metric in enumerate(document['metrics']):
        metric['scope'] = {'company': '甲医院' if not other_company or index == 0 else '乙医院',
                           'income_nature': '开单收入', 'area': '院区甲' if index == 0 else '院区乙'}
    if missing_scope:
        document['metrics'][1]['scope'] = {}
    frozen = [json.dumps(document, ensure_ascii=False)]
    markdown, refs, notices = render_bound_numbers(
        '收入{{value:fact-aaaaaaaaaaaaaaaa:total:元}}，预算{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。',
        frozen, key='common-scope',
    )
    return (ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs, reviewNotices=notices),), frozen


def test_common_scope_is_visible_without_borrowing_different_areas_or_changing_numbers():
    blocks, frozen = scope_case()
    result = sections._with_section_scope_disclosure(blocks, frozen,
        {'company': '医院名称', 'income_nature': '收入性质', 'area': '院区'}, {})
    assert len(result) == 2
    assert '医院名称：甲医院' in result[0].markdown
    assert '收入性质：开单收入' in result[0].markdown
    assert '院区甲' not in result[0].markdown and '院区乙' not in result[0].markdown
    assert result[1] == blocks[0]
    assert sections._with_section_scope_disclosure(result, frozen,
        {'company': '医院名称', 'income_nature': '收入性质', 'area': '院区'}, {}) == result


@pytest.mark.parametrize('fault', ['different_company', 'missing_scope', 'no_label', 'unbound'])
def test_common_scope_never_invents_a_hospital_or_exposes_internal_field_names(fault):
    blocks, frozen = scope_case(other_company=fault == 'different_company', missing_scope=fault == 'missing_scope')
    labels = {} if fault == 'no_label' else {'company': '医院名称'}
    if fault == 'unbound':
        frozen = []
    result = sections._with_section_scope_disclosure(blocks, frozen, labels, {})
    assert result == blocks


@pytest.mark.anyio
async def test_scope_disclosure_is_passed_to_semantic_review_and_survives_review_failure(monkeypatch):
    blocks, frozen = scope_case()
    seen = []

    async def unavailable(agent, current, *_args, **_kwargs):
        seen.append(current)
        raise RuntimeError('semantic review unavailable')

    monkeypatch.setattr(sections, '_interpret_section_claims', unavailable)
    result = await sections._disambiguate_section_claims(
        object(), blocks, frozen, section_code='section_001', scope=SimpleNamespace(),
        run_context=SimpleNamespace(), thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'),
        field_definitions={'company': '医院名称'},
    )
    assert '医院名称：甲医院' in seen[0][0].markdown
    assert result == seen[0]
    assert result[1] == blocks[0]
