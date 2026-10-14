"""Narrative planning durable phase transitions."""

from smart_reporting.reporting.workflow.state import (
    ReportingCommand,
    ReportingPhase,
    ReportingRunState,
    apply,
)


def test_analysis_freezing_enters_narrative_planning_before_sections():
    state = ReportingRunState.initial(
        report_run_id="run-1",
        external_run_id="external-1",
        thread_id="thread-1",
        owner_user_id="user-1",
    )
    running = apply(
        state,
        ReportingCommand(name="start_analysis", commandId="start-1"),
    ).state
    visualizing = apply(
        running,
        ReportingCommand(name="start_visualization", commandId="visual-1"),
    ).state
    freezing = apply(
        visualizing,
        ReportingCommand(name="freeze_analysis", commandId="freeze-1"),
    ).state
    planning = apply(
        freezing,
        ReportingCommand(name="start_narrative_planning", commandId="plan-1"),
    ).state
    sections = apply(
        planning,
        ReportingCommand(name="complete_narrative_planning", commandId="plan-2"),
    ).state

    assert freezing.phase is ReportingPhase.ANALYSIS_FREEZING
    assert planning.phase is ReportingPhase.NARRATIVE_PLANNING
    assert sections.phase is ReportingPhase.SECTIONS
