"""解释状态进入展示投影，不修改冻结正文或依赖来源附录开关。"""

import copy
import hashlib

import pytest

from smart_reporting.reporting.delivery.report_runtime.projection import (
    build_render_projection,
    verify_render_projection,
)

SOURCE = '# 报告\n\n[[section:budget]]\n## 1. 预算\n\n采购延后影响执行。[[claim:cause]]\n'
SECTIONS = [{'code': 'budget', 'title': '预算'}]


def payload(status='unverified', kind='inference'):
    return {'version': 'claim-support-render/1', 'sourceSha256': hashlib.sha256(SOURCE.encode()).hexdigest(),
        'claims': [{'sectionId': 'budget', 'claimId': 'cause', 'kind': kind, 'supportStatus': status}]}


@pytest.mark.parametrize('sources', [False, True])
@pytest.mark.parametrize('status,label', [('supported', '推断'), ('unverified', '推断，待核实'), ('conflicted', '推断，存在反证')])
def test_explanation_label_is_visible_without_source_appendix_and_bound_to_projection(sources, status, label):
    support = payload(status)
    result = build_render_projection(SOURCE, SECTIONS, claim_support=support, include_sources=sources)
    assert '采购延后影响执行。（' + label + '）' in result.markdown
    assert result.receipt['sourceSha256'] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert SOURCE.endswith('。[[claim:cause]]\n')
    assert verify_render_projection(result.receipt, SOURCE, SECTIONS,
        claim_support=support, include_sources=sources)['status'] == 'verified'
    changed = copy.deepcopy(support)
    changed['claims'][0]['supportStatus'] = 'supported' if status != 'supported' else 'unverified'
    assert verify_render_projection(result.receipt, SOURCE, SECTIONS,
        claim_support=changed, include_sources=sources)['status'] == 'unknown'


@pytest.mark.parametrize('fault', ['source', 'status', 'duplicate', 'version'])
def test_invalid_explanation_projection_discloses_uncertainty_without_blocking_render(fault):
    support = payload('supported')
    if fault == 'source':
        support['sourceSha256'] = '0' * 64
    elif fault == 'status':
        support['claims'][0]['supportStatus'] = 'approved'
    elif fault == 'duplicate':
        support['claims'].append(support['claims'][0].copy())
    else:
        support['version'] = 'unknown'
    result = build_render_projection(SOURCE, SECTIONS, claim_support=support)
    assert '解释与建议的支持状态未能核验' in result.markdown
    assert result.claim_support_check['status'] == 'unknown'
    assert '采购延后影响执行。' in result.markdown


def test_recommendation_label_and_section_identity_do_not_certify_another_claim():
    support = payload('supported', 'recommendation')
    result = build_render_projection(SOURCE, SECTIONS, claim_support=support)
    assert '（建议）' in result.markdown
    support['claims'][0]['sectionId'] = 'foreign'
    result = build_render_projection(SOURCE, SECTIONS, claim_support=support)
    assert '（建议）' not in result.markdown
    assert result.claim_support_check['status'] == 'unknown'
