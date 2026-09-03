from __future__ import annotations

import pytest

from smart_reporting.reporting.workflow.checkpoint import reporting_phase_task_key


@pytest.mark.parametrize(
    ("task_kind", "identity"),
    (
        ("analysis_item", {"analysis_id": "analysis_001"}),
        ("visualization_section", {"section_code": "section_001"}),
    ),
)
def test_analysis_task_identity_accepts_current_coding_task_kinds(
    task_kind: str, identity: dict[str, str]
) -> None:
    task_key = reporting_phase_task_key("run-1", 1, "analysis", task_kind=task_kind, **identity)
    assert task_key
    assert task_key == reporting_phase_task_key(
        "run-1", 1, "analysis", task_kind=task_kind, **identity
    )


@pytest.mark.parametrize(
    ("task_kind", "identity"),
    (
        ("analysis_item", {"section_code": "section_001"}),
        ("visualization_section", {"analysis_id": "analysis_001"}),
    ),
)
def test_analysis_task_identity_rejects_mismatched_current_task_kind(
    task_kind: str, identity: dict[str, str]
) -> None:
    with pytest.raises(ValueError):
        reporting_phase_task_key("run-1", 1, "analysis", task_kind=task_kind, **identity)


def test_section_task_identity_is_reserved_for_section_phase() -> None:
    assert reporting_phase_task_key("run-1", 1, "section", section_code="section_001")
