from smart_reporting.agent_control import (
    validated_agent_plan,
)


def test_validated_agent_plan_rejects_untrusted_or_invalid_state():
    assert validated_agent_plan(
        {
            "plan": [
                {"step": "读取数据", "status": "completed"},
                {"step": "生成报表", "status": "in_progress"},
            ],
            "explanation": "已完成准备",
        }
    ) == {
        "plan": [
            {"step": "读取数据", "status": "completed"},
            {"step": "生成报表", "status": "in_progress"},
        ],
        "explanation": "已完成准备",
    }
    assert validated_agent_plan({"plan": [], "explanation": ""}) is None
    assert (
        validated_agent_plan(
            {
                "plan": [{"step": "snapshotId=secret", "status": "in_progress"}],
                "explanation": "",
            }
        )
        is None
    )
