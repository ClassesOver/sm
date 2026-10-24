"""正文响应的数值引用关口：无法登记的引用交回模型在同一调用内纠正，有上限且不阻断。"""

import pytest
from agno.agent import Agent
from pydantic import ValidationError

from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
from smart_reporting.reporting.structured_output.execution import (
    _is_structural_validation_error,
    _validation_issues,
)
from smart_reporting.reporting.tests.test_number_selection import source
from smart_reporting.reporting.workflow.runtime import sections
from smart_reporting.reporting.workflow.runtime.phase_models import (
    SectionBlockContent,
    SectionContent,
)

BAD = '本期合计{{value:fact-bbbbbbbbbbbbbbbb:bogus:元}}。'
GOOD = '本期合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。'


def _validator(schema=SectionBlockContent):
    stage = sections._section_stage_agent(
        Agent(model=ReportingPhaseOpenAIChat(id='test', api_key='test')), schema, 'block-1',
        response_validator=sections._number_reference_validator(
            schema, number_contents=source(), field_definitions={}, assertions=None,
        ),
    )
    return getattr(stage.model, '_report_response_validator')


def test_registered_references_pass_unchanged():
    assert _validator()({'markdown': GOOD}) == SectionBlockContent(markdown=GOOD)


def test_unregistered_reference_is_returned_to_the_model_with_reason_and_alternatives():
    with pytest.raises(ValidationError) as caught:
        _validator()({'markdown': BAD})
    error = caught.value
    # 业务纠错：不触发结构化协议降级；模型原稿作为 previousOutput 回灌。
    assert not _is_structural_validation_error(error)
    assert error._report_candidate == {'markdown': BAD}
    [issue] = _validation_issues(error)
    assert issue['path'] == '$.markdown'
    assert '{{value:fact-bbbbbbbbbbbbbbbb:bogus:元}}' in issue['message']
    assert '{{value:fact-bbbbbbbbbbbbbbbb:total:元}}=100元' in issue['message']


def test_rejections_are_capped_so_generation_never_blocks():
    validate = _validator()
    for _ in range(sections._MAX_REFERENCE_REJECTIONS):
        with pytest.raises(ValidationError):
            validate({'markdown': BAD})
    assert validate({'markdown': BAD}).markdown == BAD


def test_whole_section_issue_points_at_the_failing_block():
    with pytest.raises(ValidationError) as caught:
        _validator(SectionContent)({'blocks': [{'blockId': 'block_001', 'markdown': GOOD},
                                              {'blockId': 'block_002', 'markdown': BAD}]})
    assert [issue['path'] for issue in _validation_issues(caught.value)] == ['$.blocks[1].markdown']


def test_structure_errors_still_carry_the_candidate():
    with pytest.raises(ValidationError) as caught:
        _validator()({'text': GOOD})
    assert caught.value._report_candidate == {'text': GOOD}


def test_handwritten_numbers_that_would_become_unverified_are_returned_with_their_sentence():
    with pytest.raises(ValidationError) as caught:
        _validator()({'markdown': '本期合计999元，另有888元，' + GOOD})
    first, second = _validation_issues(caught.value)
    # 语句按读者所见显示并还原模型原写法，当前数字以【】标出。
    assert '“999元”没有对应的登记值' in first['message']
    assert '本期合计【999元】，另有888元，本期合计100元' in first['message']
    assert '另有【888元】' in second['message'] and '不得写待核实' in second['message']


def test_registered_handwritten_numbers_pass():
    assert _validator()({'markdown': '本期合计100元。'}).markdown == '本期合计100元。'
