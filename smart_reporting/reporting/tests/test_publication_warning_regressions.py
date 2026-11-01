"""发布中真实出现的告警必须进入台账，未知规则仍不得静默放行。"""

import pytest

from smart_reporting.quality_warnings.audit import QualityAuditCollector
from smart_reporting.reporting.workflow.runtime.publication import _record_publication_audit


@pytest.mark.anyio
async def test_caption_numeric_review_is_recorded_instead_of_dropped():
    audit = QualityAuditCollector(report_run_id='report-run-test', revision=1)
    skipped = await _record_publication_audit(audit, [{
        'code': 'chart_caption_numeric_review', 'chartId': 'section_001_chart_02',
        'message': '图注数值无法对应登记依据，图表及证据保留。',
    }], service=None, tenant=None, complete=True)
    assert skipped == 0
    result = audit.build()
    assert result.total == 1
    finding, = result.findings
    assert finding.rule_code == 'chart_caption_numeric_review'
    assert finding.subject_type == 'analysis_chart'
    assert finding.subject_id == 'section_001_chart_02'
    assert finding.disposition == 'quality_warning'
