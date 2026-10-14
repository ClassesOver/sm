"""动态章节生产步骤顺序契约。"""

from smart_reporting.reporting.workflow.orchestration import create_reporting_analysis_step


def test_analysis_step_factory_supports_evidence_and_draft_ids():
    evidence = create_reporting_analysis_step(
        lambda *_: None, step_id="run-analysis-evidence", name="完成原子分析与证据冻结"
    )
    draft = create_reporting_analysis_step(
        lambda *_: None, step_id="run-report-draft", name="按动态章节生成报告正文"
    )
    assert evidence.step_id == "run-analysis-evidence"
    assert draft.step_id == "run-report-draft"
    assert evidence.name != draft.name
