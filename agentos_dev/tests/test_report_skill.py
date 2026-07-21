import ast
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from agno.tools.function import Function

from agentos_dev.skills import SecureSkills, TrustedLocalSkills

SCRIPT = (
    Path(__file__).parents[2]
    / "deploy/agentos/skills/odoo-current-view-report/scripts/generate_reports.py"
)
DATASET_ID = "11111111-1111-4111-8111-111111111111"
REPORT_ID = "22222222-2222-4222-8222-222222222222"
SKILL_DIR = SCRIPT.parents[1]


class DeterministicReportSkillModel(OpenAIChat):
    def __init__(self, config_path):
        super().__init__(id="deterministic-report-skill-e2e", api_key="not-used")
        self.config_path = config_path
        self.invocation_count = 0

    @staticmethod
    def _tool_call(identifier, name, arguments):
        return {
            "id": identifier,
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        }

    def invoke(self, messages, **_kwargs):
        tool_messages = {
            message.tool_name: message
            for message in messages
            if message.role == "tool" and message.tool_name
        }
        self.invocation_count += 1
        if self.invocation_count == 1:
            return ModelResponse(
                tool_calls=[
                    self._tool_call(
                        "load-report-skill",
                        "get_skill_instructions",
                        {"skill_name": "odoo-current-view-report"},
                    )
                ]
            )
        if self.invocation_count == 2:
            instructions = json.loads(tool_messages["get_skill_instructions"].get_content_string())
            assert "Odoo 标准报表分析协议" in instructions["instructions"]
            return ModelResponse(
                tool_calls=[
                    self._tool_call(
                        "render-report",
                        "run_skill_script",
                        {
                            "skill_name": "odoo-current-view-report",
                            "script_path": "generate_reports.py",
                            "args": ["render", self.config_path],
                            "timeout": 60,
                        },
                    )
                ]
            )
        execution = ast.literal_eval(tool_messages["run_skill_script"].get_content_string())
        assert execution["exitCode"] == 0
        assert "分析报告.pdf" in execution["output"]
        return ModelResponse(content="企业分析报告已生成。")


def load_script():
    spec = importlib.util.spec_from_file_location("odoo_current_view_report_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report_workspace(tmp_path, sections=None, enterprise=False):
    fragment_path = tmp_path / f"报表/原始数据/{DATASET_ID}/分片/数据-0001.jsonl"
    fragment_path.parent.mkdir(parents=True)
    if enterprise:
        rows = [
            {"region": "华东大区", "amount": 314400.35},
            {"region": "华南大区", "amount": 248761.30},
            {"region": "华北大区", "amount": 230110.95},
            {"region": "海外业务", "amount": 209080.55},
            {"region": "西南大区", "amount": 191060.10},
            {"region": "华中大区", "amount": 174790.75},
            {"region": "东北大区", "amount": 136900.25},
            {"region": "西北大区", "amount": 108661.50},
        ]
        fragment = b"".join(
            (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            for row in rows
        )
    else:
        rows = [{"region": "=2+3", "amount": 10}, {"region": "华南", "amount": 20}]
        fragment = ('{"region":"=2+3","amount":10}\n{"region":"华南","amount":20}\n').encode()
    fragment_path.write_bytes(fragment)
    manifest = {
        "version": "agui.report.dataset.v1",
        "datasetId": DATASET_ID,
        "model": "res.partner",
        "fields": [
            {"name": "region", "label": "区域", "type": "char"},
            {"name": "amount", "label": "金额", "type": "float"},
        ],
        "rowCount": len(rows),
        "columnCount": 2,
        "fragments": [
            {
                "path": f"报表/原始数据/{DATASET_ID}/分片/数据-0001.jsonl",
                "size": len(fragment),
                "sha256": hashlib.sha256(fragment).hexdigest(),
            }
        ],
        "totalSize": len(fragment),
        "scope": "domain",
        "selectedCount": 0,
        "timezone": "Asia/Shanghai",
        "generatedAt": "2026-07-21 12:00:00",
        "scopeFingerprint": "a" * 64,
    }
    manifest_path = tmp_path / f"报表/原始数据/{DATASET_ID}/数据集.json"
    manifest_content = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_content)
    config = {
        "version": "agui.report.config.v1",
        "reportId": REPORT_ID,
        "manifestPath": f"报表/原始数据/{DATASET_ID}/数据集.json",
        "datasetHash": hashlib.sha256(manifest_content).hexdigest(),
        "title": "2026 年销售区域经营分析报告" if enterprise else "区域销售分析",
        "analysis": {
            "dimensions": ["region"],
            "metrics": [{"field": "amount", "aggregation": "sum", "label": "销售额"}],
            "notes": (
                [
                    "本报告基于当前 Odoo 列表完整筛选范围生成。",
                    "金额按原始业务口径汇总，不执行隐式汇率换算。",
                ]
                if enterprise
                else ["按当前列表范围统计。"]
            ),
        },
        "chart": {"type": "bar", "metric": "amount:sum", "title": "各区域销售额"},
        "presentation": {
            "purpose": (
                "比较各销售区域的收入规模，快速识别重点区域，并验证企业分析报告的中文布局与分页表现。"
                if enterprise
                else "比较区域销售表现并识别差异。"
            ),
            "sections": sections or ["overview", "notes", "chart", "analysis"],
        },
    }
    config_path = tmp_path / f"报表/配置/{REPORT_ID}/报表配置.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return f"报表/配置/{REPORT_ID}/报表配置.json", fragment_path


def test_report_skill_capabilities_use_versioned_pdf_protocol(capsys):
    module = load_script()

    assert module.main(["capabilities"]) == 0

    response = json.loads(capsys.readouterr().out)
    assert response["protocol"] == "agui.odoo.report.skill.v1"
    assert response["operation"] == "capabilities"
    assert response["ok"] is True
    assert response["operations"] == ["capabilities", "validate", "render"]
    assert response["inputVersions"] == {
        "config": "agui.report.config.v1",
        "dataset": "agui.report.dataset.v1",
    }
    assert response["artifacts"] == [
        {
            "kind": "pdf",
            "filename": "分析报告.pdf",
            "mimeType": "application/pdf",
        }
    ]
    assert response["sectionTypes"] == ["overview", "notes", "chart", "analysis"]
    assert not any(key.startswith("sample") for key in response["limits"])


def test_report_skill_validate_checks_complete_dataset_without_writing(tmp_path, monkeypatch):
    module = load_script()
    config_path, _fragment_path = report_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    response = module.validate(config_path)

    assert response == {
        "protocol": "agui.odoo.report.skill.v1",
        "operation": "validate",
        "ok": True,
        "reportId": REPORT_ID,
        "dataset": {"rowCount": 2, "columnCount": 2, "fragmentCount": 1},
        "artifact": {
            "kind": "pdf",
            "path": f"报表/生成结果/{REPORT_ID}/分析报告.pdf",
            "mimeType": "application/pdf",
        },
    }
    assert not (tmp_path / f"报表/生成结果/{REPORT_ID}").exists()


def test_report_skill_invalid_invocation_uses_protocol_error(capsys):
    module = load_script()

    assert module.main(["render"]) == 2

    response = json.loads(capsys.readouterr().err)
    assert response == {
        "protocol": "agui.odoo.report.skill.v1",
        "operation": "render",
        "ok": False,
        "error": {
            "code": "invalid_arguments",
            "message": "render 操作需要一个配置路径",
        },
    }


def test_report_skill_failure_leaves_no_partial_output(tmp_path, monkeypatch):
    module = load_script()
    config_path, _fragment_path = report_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    def fail_png(*_args):
        raise module.ReportFailure("图表生成失败")

    monkeypatch.setattr(module, "_write_png", fail_png)

    with pytest.raises(module.ReportFailure, match="图表生成失败"):
        module.render(config_path)

    output_parent = tmp_path / "报表/生成结果"
    assert not (output_parent / REPORT_ID).exists()
    if output_parent.exists():
        assert not list(output_parent.glob(f".{REPORT_ID}-*"))


def test_report_skill_rejects_changed_fragment_before_output(tmp_path, monkeypatch):
    module = load_script()
    config_path, fragment_path = report_workspace(tmp_path)
    fragment_path.write_bytes(fragment_path.read_bytes().replace("华南".encode(), "华北".encode()))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(module.ReportFailure, match="SHA-256"):
        module.render(config_path)

    assert not (tmp_path / f"报表/生成结果/{REPORT_ID}").exists()


def test_report_skill_context_sections_skip_unrequested_chart(tmp_path, monkeypatch):
    module = load_script()
    config_path, _fragment_path = report_workspace(tmp_path, ["overview", "analysis"])
    monkeypatch.chdir(tmp_path)

    def reject_chart(*_args):
        raise AssertionError("未请求图表章节时不应渲染图表")

    def write_pdf(path, png_path, config, *_args):
        assert png_path is None
        assert config["presentation"] == {
            "purpose": "比较区域销售表现并识别差异。",
            "sections": ["overview", "analysis"],
        }
        path.write_bytes(b"%PDF-context")

    monkeypatch.setattr(module, "_write_png", reject_chart)
    monkeypatch.setattr(module, "_write_pdf", write_pdf)

    response = module.render(config_path)

    assert response["ok"] is True
    assert (tmp_path / response["artifacts"][0]["path"]).read_bytes() == b"%PDF-context"


def test_report_skill_uses_business_labels_and_production_value_formats(tmp_path):
    module = load_script()
    config_path, _fragment_path = report_workspace(tmp_path)
    config = json.loads((tmp_path / config_path).read_text(encoding="utf-8"))
    manifest = json.loads(
        (tmp_path / f"报表/原始数据/{DATASET_ID}/数据集.json").read_text(encoding="utf-8")
    )
    document = module._report_document(
        Path("图表.png"),
        config,
        manifest,
        [{"_chart_category": "华东", "amount:sum": 123456.5}],
    )

    assert module._format_value(123456.5, "monetary") == "123,456.50"
    assert module._format_value(1200, "integer") == "1,200"
    assert module._format_value(False, "boolean") == "否"
    assert module._format_value([7, "重点客户"], "many2one") == "重点客户"
    assert "<th>区域</th>" in document
    assert "123,456.50" in document
    assert "当前列表完整范围" in document
    assert "有界样例" not in document
    assert 'content: "第 " counter(page)' in document
    assert '<meta name="author" content="Odoo">' in document


def test_report_skill_renders_only_pdf(tmp_path, monkeypatch):
    module = load_script()
    config_path, _fragment_path = report_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))

    response = module.render(config_path)

    expected_path = f"报表/生成结果/{REPORT_ID}/分析报告.pdf"
    assert response == {
        "protocol": "agui.odoo.report.skill.v1",
        "operation": "render",
        "ok": True,
        "reportId": REPORT_ID,
        "artifacts": [
            {
                "kind": "pdf",
                "path": expected_path,
                "mimeType": "application/pdf",
            }
        ],
    }
    output = tmp_path / f"报表/生成结果/{REPORT_ID}"
    assert [path.name for path in output.iterdir()] == ["分析报告.pdf"]
    assert (tmp_path / expected_path).read_bytes().startswith(b"%PDF-")


def test_agno_agent_discovers_confirms_and_runs_report_skill(tmp_path):
    trusted_root = tmp_path / "skills"
    trusted_skill = trusted_root / SKILL_DIR.name
    shutil.copytree(
        SKILL_DIR,
        trusted_skill,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for path in [trusted_root, *trusted_root.rglob("*")]:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    skills = SecureSkills(loaders=[TrustedLocalSkills(str(trusted_root))])

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path, _fragment_path = report_workspace(workspace, enterprise=True)
    executions = []

    def run_skill_script(
        skill_name: str,
        script_path: str,
        args: list[str] | None = None,
        timeout: int = 30,
    ):
        content = skills.script_bytes(skill_name, script_path)
        runtime_script = workspace / ".skill-runtime" / script_path
        runtime_script.parent.mkdir(parents=True, exist_ok=True)
        runtime_script.write_bytes(content)
        environment = dict(os.environ)
        environment["MPLCONFIGDIR"] = str(workspace / ".matplotlib")
        completed = subprocess.run(
            [sys.executable, str(runtime_script), *(args or [])],
            cwd=workspace,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        result = {
            "exitCode": completed.returncode,
            "output": completed.stdout or completed.stderr,
            "truncated": False,
        }
        executions.append(
            {
                "skillName": skill_name,
                "scriptPath": script_path,
                "args": args,
                "result": result,
            }
        )
        return result

    model = DeterministicReportSkillModel(config_path)
    agent = Agent(
        id="report-skill-e2e",
        model=model,
        skills=skills,
        tools=[
            Function(
                name="run_skill_script",
                description="执行可信技能声明的脚本；执行前需要确认。",
                entrypoint=run_skill_script,
                requires_confirmation=True,
            )
        ],
        db=SqliteDb(db_file=str(tmp_path / "agno.db")),
        instructions=["发现并使用适用的技能；执行可信脚本前等待确认。"],
    )

    run = agent.run("根据当前工作区配置生成企业分析 PDF。")

    assert run.is_paused
    assert not executions
    [requirement] = run.active_requirements
    assert requirement.needs_confirmation
    assert requirement.tool_execution.tool_name == "run_skill_script"
    requirement.confirm()

    completed = agent.continue_run(run_id=run.run_id, requirements=run.requirements)

    assert not completed.is_paused
    assert completed.content == "企业分析报告已生成。"
    assert model.invocation_count == 3
    assert executions == [
        {
            "skillName": "odoo-current-view-report",
            "scriptPath": "generate_reports.py",
            "args": ["render", config_path],
            "result": executions[0]["result"],
        }
    ]
    assert executions[0]["result"]["exitCode"] == 0
    result = json.loads(executions[0]["result"]["output"])
    assert result["protocol"] == "agui.odoo.report.skill.v1"
    assert result["ok"] is True
    assert (workspace / result["artifacts"][0]["path"]).read_bytes().startswith(b"%PDF-")
