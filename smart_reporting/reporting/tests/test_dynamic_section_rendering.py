"""章节 WorkItem 的发现边界契约。"""

import pytest

from smart_reporting.reporting.workflow.checkpoint import SectionWorkItem


def _item(**changes):
    payload = {
        "sectionCode": "section_001",
        "sectionNumber": "1",
        "title": "收入变化",
        "objective": "解释收入变化",
        "completionConditions": ["保留证据"],
        "analysisIds": ["analysis_001"],
        "findingIds": ["finding_0000000000000001"],
        "findingSummaries": [{"findingId": "finding_0000000000000001", "summary": "收入变化"}],
        "markdownRequirements": ["使用事实"],
        **changes,
    }
    return SectionWorkItem.model_validate(payload)


def test_section_work_item_keeps_assigned_finding_ids():
    item = _item()
    assert item.finding_ids == ("finding_0000000000000001",)


def test_section_work_item_rejects_summary_from_another_section():
    with pytest.raises(ValueError, match="当前章节"):
        _item(findingSummaries=[{"findingId": "finding_0000000000000002", "summary": "其他"}])
