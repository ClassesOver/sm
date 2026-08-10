from pathlib import Path

from agentos_dev.coding.reporting.delivery.acceptance import load_reporting_skills
from agentos_dev.skills import load_sandbox_execution_skills


def test_reporting_worker加载可视化skill且纯coding保持通用skill() -> None:
    coding_skills = load_sandbox_execution_skills()
    reporting_skills = load_reporting_skills(coding_skills)

    assert [skill.name for skill in coding_skills.get_all_skills()] == ["sandbox-tooling"]
    assert {skill.name for skill in reporting_skills.get_all_skills()} == {
        "sandbox-tooling",
        "report-artifact",
        "report-visualization",
    }
    visualization = reporting_skills.get_skill("report-visualization")
    assert visualization is not None
    assert visualization.references == ["chart-cookbook.md"]
    assert "固定图表数量" in visualization.instructions
    assert "不是模板、白名单或验收条件" in visualization.instructions
    assert "联系表" in visualization.instructions
    assert "不进入 Manifest、PDF 或 Word" in visualization.instructions


def test_chart_cookbook只提供开放示例而不设置数量和类型门禁() -> None:
    cookbook = (
        Path(__file__).parent.parent
        / "builtin_skills"
        / "report-visualization"
        / "references"
        / "chart-cookbook.md"
    ).read_text(encoding="utf-8")

    for example in ("趋势", "Pareto", "箱线图", "热力图", "气泡图", "子弹图", "瀑布图", "漏斗图"):
        assert example in cookbook
    for gate in ("必须生成", "至少生成", "仅允许", "固定数量", "白名单", "强制模板"):
        assert gate not in cookbook
    assert "也可以使用这里未列出的图形" in cookbook
