"""交付外观独立于统计口径和旧业务配置。"""

from types import SimpleNamespace

import pytest
from agno.run import RunContext
from pydantic import ValidationError

from smart_reporting.reporting.contract import ReportRequestEnvelope
from smart_reporting.reporting.delivery.settings import ReportDeliverySettings
from smart_reporting.reporting.hospital_operation.outline import ReportOutline
from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin


def test_deployment_settings_validate_layout_and_branding():
    settings = ReportDeliverySettings.from_env({
        "AGENT_REPORT_ORGANIZATION_NAME": "  示例医院财务部  ",
        "AGENT_REPORT_GENERATED_BY_LABEL": "财务分析系统",
        "AGENT_REPORT_WATERMARK_TEXT": "内部资料",
        "AGENT_REPORT_HEADER_LEFT": "{organization} / {title}",
        "AGENT_REPORT_FOOTER_RIGHT": "{page} / {pages}",
    })
    assert settings.branding.organization_name == "示例医院财务部"
    assert settings.branding.generated_by_label == "财务分析系统"
    assert settings.branding.watermark_text == "内部资料"
    assert settings.page_layout.header_left == "{organization} / {title}"
    assert settings.page_layout.footer_right == "{page} / {pages}"


@pytest.mark.parametrize("values", [
    {"AGENT_REPORT_HEADER_LEFT": "{organization.__class__}"},
    {"AGENT_REPORT_HEADER_LEFT": "{title!r}"},
    {"AGENT_REPORT_HEADER_LEFT": "{title:>20}"},
    {"AGENT_REPORT_HEADER_LEFT": "{title"},
    {"AGENT_REPORT_FOOTER_RIGHT": "无页码"},
    {"AGENT_REPORT_FOOTER_RIGHT": "{{page}} / {{pages}}"},
    {"AGENT_REPORT_WATERMARK_TEXT": "内部\n资料"},
    {"AGENT_REPORT_GENERATED_BY_LABEL": "   "},
])
def test_invalid_delivery_configuration_is_rejected(values):
    with pytest.raises(ValidationError):
        ReportDeliverySettings.from_env(values)


@pytest.mark.anyio
async def test_document_context_uses_delivery_settings_without_business_profile():
    bound = {}

    async def bind_document_context(job_id, document_context, *, run_context):
        bound[job_id] = document_context

    envelope = ReportRequestEnvelope.model_validate({
        "reportGoal": "预算执行分析",
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
    })
    runtime = SimpleNamespace(
        delivery_settings=ReportDeliverySettings.from_env({
            "AGENT_REPORT_ORGANIZATION_NAME": "试点医院",
            "AGENT_REPORT_GENERATED_BY_LABEL": "预算分析平台",
            "AGENT_REPORT_WATERMARK_TEXT": "已授权资料",
        }),
        report_tools=SimpleNamespace(bind_document_context=bind_document_context),
        _state=lambda context: context.session_state,
        _envelope=lambda context: envelope,
        _tool_context=lambda context: context,
    )
    outline = ReportOutline.model_validate({
        "reportType": "topic", "title": "预算执行专题",
        "sections": [{"code": "section_001", "sectionNumber": "1", "title": "执行情况",
                      "analysisIds": ["analysis_001"]}],
    })
    context = RunContext(run_id="run", session_id="thread", session_state={})
    await RuntimeAnalysisMixin._bind_report_document_context(
        runtime, context, outline=outline, job_id="job",
    )
    assert bound["job"]["organizationName"] == "试点医院"
    assert bound["job"]["generatedByLabel"] == "预算分析平台"
    assert bound["job"]["watermarkText"] == "已授权资料"
    assert bound["job"]["periodLabel"] == "2026年11月1日至11月30日"
    first_date = bound["job"]["generatedDate"]
    await RuntimeAnalysisMixin._bind_report_document_context(
        runtime, context, outline=outline, job_id="job",
    )
    assert bound["job"]["generatedDate"] == first_date
