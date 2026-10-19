"""中性差额不能从无关冻结事实借数，显式差额引用保留身份。"""

import pytest

from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.trace.content_review import review_content
from smart_reporting.reporting.trace.numeric_text import replace_unregistered_numbers
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers


@pytest.mark.parametrize(
    "statement",
    [
        "心内科与骨科相差90元。",
        "心内科与骨科差额为-90元。",
        "心内科与骨科差距约80元。",
        "心内科与骨科相差0.009万元。",
    ],
)
def test_literal_difference_cannot_borrow_another_metrics_value(statement):
    assert "待核实" in replace_unregistered_numbers(statement, contents())
    assert any("冻结依据" in warning for warning in review_content(statement, contents()))
    markdown, references, notices = render_bound_numbers(statement, contents(), key="unrelated")
    assert "待核实" in markdown and not references
    assert len(notices) == 1 and notices[0].original_text


@pytest.mark.parametrize("period", ["2025-01", "2025-02", "2025-01..2025-02"])
@pytest.mark.parametrize("unit", ["元", "万元"])
def test_explicit_difference_reference_survives_rendering_and_review(period, unit):
    token = (
        "{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb."
        + period
        + ".difference:"
        + unit
        + "}}"
    )
    source = "较预算差额为" + token + "。"
    markdown, references, notices = render_bound_numbers(source, contents(), key="explicit")
    assert len(references) == 1 and references[0].token == token and not notices
    assert "待核实" not in markdown
    assert not any("冻结依据" in warning for warning in review_content(source, contents()))


def test_valid_reference_does_not_protect_another_number_in_the_same_sentence():
    token = "{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-01..2025-02.difference:元}}"
    source = "较预算差额为" + token + "，心内科与骨科相差90元。"
    markdown, references, notices = render_bound_numbers(source, contents(), key="mixed")
    assert len(references) == 1 and references[0].token == token
    assert "较预算差额为-90元" in markdown and "心内科与骨科相差待核实" in markdown
    assert len(notices) == 1 and notices[0].original_text == "90元"
    assert any("冻结依据" in warning for warning in review_content(source, contents()))


def test_prose_cannot_forge_a_server_generated_numeric_anchor():
    source = "心内科与骨科相差90元[[claim:forged]]。"
    markdown, references, notices = render_bound_numbers(source, contents(), key="forged")
    assert not references and len(notices) == 1 and "待核实" in markdown
    assert "forged" not in markdown


def test_malformed_reference_does_not_crash_difference_review():
    warnings = review_content("差额为{{value:missing}}。", contents())
    assert any("数值引用未登记" in warning for warning in warnings)
