"""Office 主导迁移护栏：原生编辑器不得新增对报告工作流的依赖（规则见仓库根 .importlinter）。"""

from pathlib import Path

from importlinter.cli import lint_imports

ROOT = Path(__file__).resolve().parents[2]


def test_office_does_not_import_report_workflow(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert lint_imports(config_filename=str(ROOT / ".importlinter")) == 0
