from smart_reporting.report_editor.trace_sources import narrative_section_projection


def test_editor_projection_exposes_dynamic_finding_ids_and_grouping_reason():
    manifest = {
        "sections": ["section_001"],
        "sectionFindingIds": {"section_001": ["finding_0000000000000001"]},
        "sectionGroupingReasons": {"section_001": "共享收入与工作量管理问题"},
    }

    assert narrative_section_projection(manifest) == [
        {
            "sectionCode": "section_001",
            "findingIds": ["finding_0000000000000001"],
            "groupingReason": "共享收入与工作量管理问题",
        }
    ]


def test_editor_projection_keeps_old_manifest_compatible():
    assert narrative_section_projection({"sections": ["section_001"]}) == [
        {"sectionCode": "section_001", "findingIds": [], "groupingReason": None}
    ]
