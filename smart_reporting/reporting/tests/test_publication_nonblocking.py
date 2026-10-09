from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.workflow.runtime import publication


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["failed_receipt", "invalid_counts", "changed_hash"])
async def test_render_validation_failure_retains_actual_artifacts(monkeypatch, failure):
    manifest = {
        "reportId": "report-1", "revision": 1, "codingTaskKey": "task-1",
        "datasetSnapshotHash": "a" * 64, "effectiveProfileHash": "b" * 64,
        "markdown": {"path": "reports/report.md", "mediaType": "text/markdown",
                     "size": 1, "sha256": "c" * 64},
        "citations": [{"citationId": "citation_001", "datasetId": "dataset_001",
                       "requirementId": "requirement_001", "snapshotHash": "a" * 64}],
        "sections": ["section_001"], "sectionNumbers": ["1"],
        "headingNumbers": [{"level": 2, "number": "1", "title": "运营分析",
                           "sectionCode": "section_001", "anchor": "report-section-001"}],
    }
    validation = {
        "ok": failure != "failed_receipt", "pdfSha256": "a" * 64,
        "wordSha256": "b" * 64, "issues": [{"code": "layout_mismatch"}],
    }
    if failure == "changed_hash":
        validation["pdfSha256"] = "c" * 64
    state = {
        "report_artifacts": {"draft": manifest}, "report_dataset_lineage": [],
        "report_data_requirements": [], "report_analysis_plan": [],
        "report_workflow_result": {"jobId": "job-1", "revision": 0, "markdownPath": "reports/report.md"},
    }
    runtime = object.__new__(publication.RuntimePublicationMixin)
    runtime._state = lambda _context: state
    runtime._scope = lambda _context: {"threadId": "thread", "externalRunId": "external-1"}
    runtime._workflow_result = lambda current: current["report_workflow_result"]
    runtime._envelope = lambda _context: SimpleNamespace(period=None)
    runtime._tool_context = lambda context: context
    runtime._data_shapes = lambda _context: []
    runtime._snapshots = lambda _context: []
    runtime._source_links_by_dataset = AsyncMock(return_value={})
    runtime.report_tools = SimpleNamespace(
        bind_citation_presentations=AsyncMock(),
        _render_report_pair=AsyncMock(return_value={"wordPath": "reports/report.docx", "validation": validation}),
        discard_report_revision=AsyncMock(),
    )

    async def hash_file(_thread, path):
        return {"path": path, "size": 3, "sha256": ("a" if path.endswith("pdf") else "b") * 64}

    runtime.workspace_service = SimpleNamespace(ahash_file=hash_file)
    monkeypatch.setattr(publication, "_frozen_outline", lambda _state: SimpleNamespace(title="运营分析"))
    monkeypatch.setattr(publication, "_report_pdf_path", lambda *_args: "reports/report.pdf")
    monkeypatch.setattr(publication, "_citation_presentations", lambda **_kwargs: [])
    monkeypatch.setattr(publication, "_reporting_observed_data_facts", lambda *_args: [])
    monkeypatch.setattr(publication, "_source_warnings_from_state", lambda _state: [])

    result = await runtime._render_and_validate(RunContext(run_id="report-1", session_id="thread", session_state=state))

    assert result["status"] == "validation_failed"
    assert result["validation"]["ok"] is False
    assert result["validationIssues"]
    assert result["pdfSha256"] == "a" * 64
    assert result["wordSha256"] == "b" * 64
    assert result["pdfPath"] == "reports/report.pdf"
    assert result["wordPath"] == "reports/report.docx"
    runtime.report_tools.discard_report_revision.assert_not_awaited()
    assert state["report_workflow_result"] is result


def test_agents_nonblocking_contract_registry_points_at_existing_tests():
    """AGENTS.md 登记的非阻断契约用例必须真实存在，重命名或删除即失败。"""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    entries = re.findall(r"`(smart_reporting/reporting/tests/[\w/]+\.py)::(test_\w+)`", agents)
    assert len(entries) >= 6
    for path, name in entries:
        source = (root / path).read_text(encoding="utf-8")
        assert re.search(rf"^(?:async )?def {name}\(", source, re.MULTILINE), f"{path}::{name}"


# 静态守卫：签发链路上，表达“验收/门禁/审计未通过”的 ReportingError 不得直接终止签发。
# 这类 raise 必须位于 try 体内且有 except Exception（或裸 except）兜底，把原因转为
# validation.issues / publicationGate.issues 后继续。新增此类 raise 未兜底即失败。
_SIGNING_CHAIN = {
    "smart_reporting/reporting/workflow/runtime/publication.py": ("_render_and_validate", "publish_report"),
    "smart_reporting/reporting/workflow/runtime/planning.py": ("issue_http_publication",),
    "smart_reporting/reporting/workspace.py": ("_render_report_pair",),
    "smart_reporting/report_editor/service.py": ("_export_revision",),
}
_GATE_CODE = r"validation|not_validated|gate|audit|quality"
# 门禁内部可以 raise，但其在签发链路上的每个调用点都必须被 except Exception 兜底。
_CALLER_GUARDED = {
    "smart_reporting/reporting/workflow/runtime/publication.py": (("publish_report", "_dataset_publication_gate"),),
}


def _blocking_gate_raises(
    source: str, functions: tuple[str, ...], *, calls: tuple[str, str] | None = None,
) -> list[str]:
    import ast
    import re

    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def guarded(node: ast.AST) -> bool:
        child = node
        while child in parents:
            parent = parents[child]
            # 兜底处理器须捕获 Exception 且不再 raise；清理后重新抛出的处理器不算兜底。
            if isinstance(parent, ast.Try) and child in parent.body and any(
                (handler.type is None
                 or (isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}))
                and not any(isinstance(item, ast.Raise) for item in ast.walk(handler))
                for handler in parent.handlers
            ):
                return True
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) and parent.name in functions:
                return False
            child = parent
        return False

    if calls is not None:
        caller, callee = calls
        owners = [node for node in ast.walk(tree)
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == caller]
        assert len(owners) == 1, f"签发链路函数缺失或改名：{caller}"
        sites = [node for node in ast.walk(owners[0]) if isinstance(node, ast.Call)
                 and getattr(node.func, "attr", getattr(node.func, "id", None)) == callee]
        assert sites, f"{caller} 中未找到对 {callee} 的调用"
        return [f"{caller}:{node.lineno} 调用 {callee} 未兜底" for node in sites if not guarded(node)]
    found = {node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions}
    assert found == set(functions), f"签发链路函数缺失或改名：{set(functions) - found}"
    violations = []
    for function in (node for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions):
        for node in ast.walk(function):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            callee = node.exc.func
            name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
            args = node.exc.args
            if (name == "ReportingError" and args and isinstance(args[0], ast.Constant)
                    and isinstance(args[0].value, str) and re.search(_GATE_CODE, args[0].value)
                    and not guarded(node)):
                violations.append(f"{function.name}:{node.lineno} {args[0].value}")
    return violations


def test_signing_chain_never_raises_gate_failures_without_fallback():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    violations = [
        f"{path} {item}"
        for path, functions in _SIGNING_CHAIN.items()
        for item in _blocking_gate_raises((root / path).read_text(encoding="utf-8"), functions)
    ]
    violations.extend(
        f"{path} {item}"
        for path, pairs in _CALLER_GUARDED.items()
        for caller, callee in pairs
        for item in _blocking_gate_raises(
            (root / path).read_text(encoding="utf-8"), (caller,), calls=(caller, callee),
        )
    )
    assert not violations, "验收/门禁失败不得终止签发（见 AGENTS.md）：" + "；".join(violations)


def test_signing_chain_guard_detects_an_unguarded_gate_raise():
    # 守卫自检：违规写法必须被识别，兜底写法必须放行。
    source = '''
async def sign():
    raise ReportingError("report_artifact_validation_failed", "x")

async def guarded():
    try:
        raise ReportingError("report_artifact_validation_failed", "x")
    except Exception:
        pass

async def cleanup_then_reraise():
    try:
        raise ReportingError("report_artifact_validation_failed", "x")
    except BaseException:
        cleanup()
        raise
'''
    assert _blocking_gate_raises(source, ("sign",)) == ["sign:3 report_artifact_validation_failed"]
    assert _blocking_gate_raises(source, ("guarded",)) == []
    assert _blocking_gate_raises(source, ("cleanup_then_reraise",)) == [
        "cleanup_then_reraise:13 report_artifact_validation_failed"
    ]
    calls = '''
async def publish():
    gate = await self._gate()

async def safe():
    try:
        gate = await self._gate()
    except Exception:
        gate = {}
'''
    assert _blocking_gate_raises(calls, ("publish",), calls=("publish", "_gate")) == ["publish:3 调用 _gate 未兜底"]
    assert _blocking_gate_raises(calls, ("safe",), calls=("safe", "_gate")) == []
