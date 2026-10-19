"""待核实原始写法只作为核对信息，不恢复成可信正文。"""

import pytest

from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.trace.contracts_v1 import ReviewNoticeV1
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
)


@pytest.mark.parametrize(
    "text,original",
    [
        ("租赁999999元。", "999999元"),
        ("门诊量98.7654万人次。", "98.7654万人次"),
        ("租赁98.7654亿。", "98.7654亿"),
        ("租赁是预算的99999倍。", "99999倍"),
        ("租赁-999,999.1234元。", "-999,999.1234元"),
        ("| 指标 | 金额（万元） |\n| --- | ---: |\n| 租赁 | 98.7654 |", "98.7654万元"),
    ],
)
def test_original_numeric_text_survives_without_returning_to_body(text, original):
    markdown, references, notices = render_bound_numbers(text, contents(), key="original")
    numeric = [notice for notice in notices if notice.kind == "numeric_unverified"]
    assert len(numeric) == 1 and numeric[0].original_text == original
    assert not references and "待核实" in markdown and original not in markdown
    restored = ReviewNoticeV1.model_validate_json(numeric[0].model_dump_json(by_alias=True))
    assert restored.original_text == original
    assembled = anchor_bound_numbers(markdown, references, notices)
    assert original not in assembled and "[[claim:" + restored.claim_id + "]]" in assembled


def test_two_unverified_values_keep_their_own_original_text_and_offsets():
    markdown, references, notices = render_bound_numbers(
        "租赁999999元，门诊量888888人次。", contents(), key="two"
    )
    assert [notice.original_text for notice in notices] == ["999999元", "888888人次"]
    assert len({notice.claim_id for notice in notices}) == 2
    assert [notice.offset for notice in notices] == [
        markdown.index("待核实") + 3,
        markdown.rindex("待核实") + 3,
    ]
    assert not references


def test_old_and_source_review_notices_do_not_invent_original_values():
    old = ReviewNoticeV1.model_validate({"claimId": "old", "kind": "numeric_unverified"})
    assert old.original_text is None
    _, _, notices = render_bound_numbers(
        "供应商答复待核实。无效引用{{value:fact-cccccccccccccccc:total:元}}。",
        contents(),
        key="unknown",
    )
    assert len(notices) == 2 and all(notice.original_text is None for notice in notices)


def test_oversized_original_text_does_not_block_report_generation():
    raw = '0' * 4096 + '999999元'
    markdown, references, notices = render_bound_numbers('租赁' + raw + '。', contents(), key='oversized')
    assert markdown == '租赁待核实。' and not references
    assert len(notices) == 1 and notices[0].original_text is None
