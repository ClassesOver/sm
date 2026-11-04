"""报告展示设计独立于业务事实，并可安全复用到另一份报告。"""
import pytest
from pydantic import ValidationError

from smart_reporting.reporting.delivery.report_design import (
    ReportDesign,
    cover_text,
    resolve_design,
    template_design,
)


def test_design_resolves_old_export_flags_without_mutating_facts():
    state = {"_editorExportSettings": {"cover": False, "toc": False}}
    design = resolve_design(state)
    assert design.options.cover is False
    assert design.options.toc is False
    assert design.typography.body.size == 11
    assert resolve_design({}).options.cover is True


def test_template_rebinds_cover_text_but_preserves_watermark_and_positions():
    design = ReportDesign()
    design.cover.title.text = "旧报告"
    design.cover.period.text = "旧期间"
    design.cover.signature.text = "旧机构"
    design.cover.title.x = 24
    design.watermark.text = "内部资料"
    template = template_design(design)
    context = {"title": "新报告", "periodLabel": "2026年", "organizationName": "新机构", "generatedByLabel": "报告平台", "generatedDate": "2026-11-03"}
    assert cover_text(template, context) == {"title": "新报告", "period": "分析期间：2026年", "signature": "新机构\n报告平台\n2026-11-03"}
    assert template.cover.title.x == 24
    assert template.watermark.text == "内部资料"
    assert design.cover.title.text == "旧报告"


@pytest.mark.parametrize("change", [
    {"cover": {"title": {"x": -1}}},
    {"cover": {"title": {"x": 150, "width": 100}}},
    {"watermark": {"opacity": 1.1}},
    {"cover": {"background": "url(https://example.com)"}},
    {"typography": {"body": {"size": float('nan')}}},
])
def test_design_rejects_invalid_geometry_and_non_style_values(change):
    with pytest.raises(ValidationError):
        ReportDesign.model_validate(change)
