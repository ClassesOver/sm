"""全局格式偏好的继承、落款与格式边界；不调用模型或外部服务。"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.delivery.settings import ReportDeliverySettings


def preferences(payload=None):
    from smart_reporting.preferences.models import FormatPreferences

    return FormatPreferences.model_validate(payload or {"common": {"signer": "报告编制人"}})


def resolve(payload=None, format="word"):
    from smart_reporting.preferences.models import resolve_format_preferences

    return resolve_format_preferences(preferences(payload), format)


def test_initialization_uses_effective_delivery_identity_and_page_text():
    from smart_reporting.preferences.models import FormatPreferences

    delivery = ReportDeliverySettings.model_validate({
        "branding": {"organizationName": "既有报告署名", "generatedByLabel": "既有生成说明"},
        "pageLayout": {"headerLeft": "部署标题", "headerRight": "{title}"},
    })
    initial = FormatPreferences.from_delivery(delivery)
    assert initial.common.signer == "既有报告署名"
    assert initial.word.header_footer.header.left == "部署标题"
    assert initial.pdf.header_footer.footer.right == "第 {page} / {pages} 页"
    assert initial.word.watermark.text == delivery.branding.watermark_text
    assert initial.common.generated_by_label == "既有生成说明"
    assert initial.common.date_format == "iso"
    assert initial.word.page.margins.model_dump() == {"top": 20, "right": 18, "bottom": 22, "left": 18}
    assert initial.word.header_footer.header_distance == 8


def test_format_override_is_per_field_and_other_formats_keep_common_defaults():
    payload = {"common": {"signer": "报告编制人", "accentColor": "#174a66", "font": "serif"},
        "word": {"common": {"accentColor": "#123456"}}}
    assert resolve(payload)["common"] == {
        "signer": "报告编制人", "dateFormat": "chinese", "font": "serif", "accentColor": "#123456",
        "generatedByLabel": "",
    }
    assert resolve(payload, "xlsx")["common"]["accentColor"] == "#174a66"
    payload["word"]["common"]["accentColor"] = None
    assert resolve(payload)["common"]["accentColor"] == "#174a66"


def test_resolved_documents_are_independent_and_have_no_ambient_date():
    from smart_reporting.preferences.models import resolve_format_preferences

    prefs = preferences()
    before = deepcopy(prefs.model_dump(mode="json", by_alias=True))
    first = resolve_format_preferences(prefs, "word")
    first["common"]["signer"] = "外部修改"
    first["page"]["margins"]["top"] = 70
    assert prefs.model_dump(mode="json", by_alias=True) == before
    assert "generatedDate" not in str(before)
    assert resolve_format_preferences(prefs, "word")["common"]["signer"] == "报告编制人"


@pytest.mark.parametrize("format", ["md", "xlsx", "pptx", "pdf", "word"])
def test_signature_is_present_and_cannot_be_switched_off(format):
    assert "signature" in resolve(format=format)
    with pytest.raises(ValidationError):
        preferences({"common": {"signer": "报告编制人"}, format: {"signature": {"enabled": False}}})


@pytest.mark.parametrize("signer", ["", "  ", "姓名\n其他", "姓名\x00"])
def test_signer_cannot_be_empty_or_contain_control_characters(signer):
    with pytest.raises(ValidationError):
        preferences({"common": {"signer": signer}})


def test_signer_is_normalized_without_inventing_identity():
    assert preferences({"common": {"signer": "  自填署名  "}}).common.signer == "自填署名"
    with pytest.raises(ValidationError):
        preferences({"common": {}})


@pytest.mark.parametrize("format,field", [("md", "page"), ("md", "headerFooter"),
    ("pptx", "page"), ("pptx", "firstPageDifferent"), ("xlsx", "typography")])
def test_inapplicable_fields_are_rejected(format, field):
    with pytest.raises(ValidationError):
        preferences({"common": {"signer": "报告编制人"}, format: {field: {}}})


@pytest.mark.parametrize("content", ["{password}", "{title.__class__}", "{title!r}", "{page:04d}", "{", "line\nline"])
def test_header_footer_only_accepts_supported_plain_fields(content):
    with pytest.raises(ValidationError):
        preferences({"common": {"signer": "报告编制人"},
            "word": {"headerFooter": {"header": {"left": content}}}})


def test_format_appropriate_dynamic_fields_and_native_page_number_settings():
    prefs = preferences({"common": {"signer": "报告编制人"},
        "word": {"headerFooter": {"header": {"center": "{title} · {period}"},
            "footer": {"right": "{page}/{pages}"}, "firstPageDifferent": True,
            "oddEvenDifferent": True, "pageNumberStart": 3}},
        "pptx": {"footer": {"left": "{date}", "right": "{slide}/{slides}"}}})
    assert prefs.word.header_footer.page_number_start == 3
    with pytest.raises(ValidationError):
        preferences({"common": {"signer": "报告编制人"},
            "pptx": {"footer": {"left": "{page}"}}})


@pytest.mark.parametrize("page", [
    {"margins": {"left": 100, "right": 100}},
    {"paper": "Letter", "orientation": "landscape", "margins": {"top": 100, "bottom": 100}},
    {"margins": {"top": -1}},
])
def test_page_settings_leave_printable_space(page):
    with pytest.raises(ValidationError):
        preferences({"common": {"signer": "报告编制人"}, "word": {"page": page}})


def test_landscape_page_uses_swapped_dimensions():
    prefs = preferences({"common": {"signer": "报告编制人"}, "word": {
        "page": {"orientation": "landscape", "margins": {"left": 100, "right": 100}}}})
    assert prefs.word.page.orientation == "landscape"


@pytest.mark.parametrize("payload", [
    {"common": {"signer": "报告编制人", "font": "missing-font"}},
    {"common": {"signer": "报告编制人", "accentColor": "red"}},
    {"common": {"signer": "报告编制人"}, "pdf": {"signature": {"size": float("nan")}}},
    {"common": {"signer": "报告编制人"}, "xlsx": {"numbers": {"decimalPlaces": 21}}},
    {"common": {"signer": "报告编制人"}, "xlsx": {"print": {"scalePercent": 9}}},
    {"common": {"signer": "报告编制人"}, "word": {"headerFooter": {"pageNumberStart": True}}},
])
def test_invalid_font_color_units_and_numeric_types_are_rejected(payload):
    with pytest.raises(ValidationError):
        preferences(payload)


def test_word_and_pdf_overrides_remain_independent():
    payload = {"common": {"signer": "报告编制人"}, "word": {"page": {"paper": "A3"}},
        "pdf": {"page": {"paper": "Letter"}}}
    assert resolve(payload)["page"]["paper"] == "A3"
    assert resolve(payload, "pdf")["page"]["paper"] == "Letter"


def test_format_resolution_rejects_unknown_format():
    with pytest.raises(ValueError, match="format"):
        resolve(format="html")


def test_inherited_font_and_accent_resolve_to_renderable_style_values():
    payload = {"common": {"signer": "报告编制人", "font": "serif", "accentColor": "#123456"},
        "word": {"typography": {"h2": {"font": "sans", "color": "#445566"}}}}
    resolved = resolve(payload)
    assert resolved["signature"]["font"] == "serif"
    assert resolved["signature"]["color"] == "#172033"
    assert resolved["typography"]["h1"]["color"] == "#123456"
    assert resolved["typography"]["h2"]["font"] == "sans"
    assert resolved["typography"]["h2"]["color"] == "#445566"


def test_setting_common_font_changes_previously_inherited_deployment_title_font():
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences

    payload = FormatPreferences.from_delivery(ReportDeliverySettings()).model_dump(mode="json", by_alias=True)
    payload["common"]["font"] = "serif"
    assert resolve_format_preferences(FormatPreferences.model_validate(payload), "word")["typography"]["h1"]["font"] == "serif"
