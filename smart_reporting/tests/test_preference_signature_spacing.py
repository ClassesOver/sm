"""落款间距的维护契约与正式文档设计保持一致。"""

import pytest

from smart_reporting.preferences.document_adapter import document_design
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.report_runtime.design import design_css


@pytest.mark.parametrize('format', ['word', 'pdf'])
def test_signature_spacing_keeps_full_preference_range_in_document_design(format):
    prefs = FormatPreferences.model_validate({'common': {'signer': '测试署名'}, format: {
        'signature': {'lineHeight': 1.8, 'spaceBefore': 144, 'spaceAfter': 7, 'dateGap': 9},
    }})
    design = document_design(resolve_format_preferences(prefs, format))
    assert design.signature.line_height == 1.8
    assert design.signature.space_before == 144
    assert design.signature.space_after == 7
    assert design.signature.date_gap == 9
    css = design_css(design)
    assert 'margin-top:144pt' in css
    assert 'margin-bottom:7pt' in css
    assert '.report-signature p+p{margin-top:9pt}' in css
