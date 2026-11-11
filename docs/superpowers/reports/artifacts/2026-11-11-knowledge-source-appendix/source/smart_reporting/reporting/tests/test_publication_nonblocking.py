from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime import publication


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["failed_receipt", "invalid_counts", "changed_hash", "overview_prepare"])
async def test_render_validation_failure_retains_actual_artifacts(monkeypatch, failure):
    manifest = {
        "reportId": "report-1", "revision": 1, "codingTaskKey": "task-1",
        "datasetSnapshotHash": "a" * 64, "reportBasisId": "b" * 64,
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
    runtime._scope = lambda _context: {"threadId": "thread", "externalRunId": "external-1", "userId": "user"}
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
    called = []
    if failure == "overview_prepare":
        from smart_reporting.reporting.workflow import overview_sources

        # 不依赖业务批准提供方，来源故障仍保留缺项投影并继续渲染。
        async def unavailable(*args):
            called.append(True)
            raise OSError("overview source unavailable")

        monkeypatch.setattr(overview_sources, "registered_management_overview", unavailable)

    result = await runtime._render_and_validate(RunContext(run_id="report-1", session_id="thread", session_state=state))

    assert result["status"] == "validation_failed"
    assert result["validation"]["ok"] is False
    assert result["validationIssues"]
    assert result["pdfSha256"] == "a" * 64
    if failure == "overview_prepare":
        assert called
        assert runtime.report_tools._render_report_pair.call_args.kwargs["management_overview"]["status"] == "unavailable"
        assert any(item["code"] == "management_overview_evidence_unavailable" and item["revision"] == 1
                   for item in state["report_quality_issues"])
    else:
        # 缺少总览来源时也不能回退到未经核验的章节摘录。
        assert runtime.report_tools._render_report_pair.call_args.kwargs["management_overview"]["status"] == "unavailable"
    assert result["wordSha256"] == "b" * 64
    assert result["pdfPath"] == "reports/report.pdf"
    assert result["wordPath"] == "reports/report.docx"
    runtime.report_tools.discard_report_revision.assert_not_awaited()
    assert state["report_workflow_result"] is result


@pytest.mark.anyio
async def test_source_index_failure_keeps_workflow_rendering_nonblocking(monkeypatch):
    manifest = {
        "reportId": "report-1", "revision": 1, "codingTaskKey": "task-1",
        "datasetSnapshotHash": "a" * 64, "reportBasisId": "b" * 64,
        "markdown": {"path": "reports/report.md", "mediaType": "text/markdown", "size": 1, "sha256": "c" * 64},
        "citations": [{"citationId": "citation_001", "datasetId": "dataset_001", "requirementId": "requirement_001", "snapshotHash": "a" * 64}],
        "sections": ["section_001"], "sectionNumbers": ["1"],
        "headingNumbers": [{"level": 2, "number": "1", "title": "运营分析", "sectionCode": "section_001", "anchor": "report-section-001"}],
    }
    state = {
        "report_artifacts": {"draft": manifest}, "report_dataset_lineage": [],
        "report_data_requirements": [], "report_analysis_plan": [],
        "report_workflow_result": {"jobId": "job-1", "revision": 0, "markdownPath": "reports/report.md"},
    }
    runtime = object.__new__(publication.RuntimePublicationMixin)
    runtime._state = lambda _context: state
    runtime._scope = lambda _context: {"threadId": "thread", "externalRunId": "external-1", "userId": "user"}
    runtime._workflow_result = lambda current: current["report_workflow_result"]
    runtime._envelope = lambda _context: SimpleNamespace(period=None)
    runtime._tool_context = lambda context: context
    runtime._data_shapes = lambda _context: []
    runtime._snapshots = lambda _context: []
    runtime._source_links_by_dataset = AsyncMock(side_effect=ReportingError(
        "snapshot_integrity_failed", "追溯索引解析失败",
    ))
    runtime.report_tools = SimpleNamespace(
        bind_citation_presentations=AsyncMock(),
        _render_report_pair=AsyncMock(return_value={"wordPath": "reports/report.docx", "validation": {"ok": False, "issues": [{"code": "layout_mismatch"}]}}),
        discard_report_revision=AsyncMock(),
    )

    async def hash_file(_thread, path):
        return {"path": path, "size": 3, "sha256": "a" * 64 if path.endswith(".pdf") else "b" * 64}

    runtime.workspace_service = SimpleNamespace(ahash_file=hash_file)
    monkeypatch.setattr(publication, "_frozen_outline", lambda _state: SimpleNamespace(title="运营分析"))
    monkeypatch.setattr(publication, "_report_pdf_path", lambda *_args: "reports/report.pdf")
    monkeypatch.setattr(publication, "_citation_presentations", lambda **_kwargs: [])
    monkeypatch.setattr(publication, "_reporting_observed_data_facts", lambda *_args: [])
    monkeypatch.setattr(publication, "_source_warnings_from_state", lambda _state: [])

    result = await runtime._render_and_validate(RunContext(run_id="report-1", session_id="thread", session_state=state))

    assert result["status"] == "validation_failed"
    assert any(issue["code"] == "report_source_appendix_unavailable" for issue in result["validationIssues"])
    assert runtime.report_tools._render_report_pair.await_count == 1


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
    "smart_reporting/reporting/trace/reader_formulas.py": ("reader_formula", "_formal_metric_formula"),
    "smart_reporting/reporting/workflow/claim_presentation.py": ("_registered_claim_support", "registered_claim_support_projection", "registered_native_claim_presentations"),
    "smart_reporting/reporting/trace/native_claims.py": ("native_claim_presentations", "present_native_summary"),
    "smart_reporting/reporting/trace/claim_presentation.py": ("claim_support_projection",),
    "smart_reporting/reporting/delivery/report_runtime/claim_support.py": ("insert_claim_support",),
    "smart_reporting/report_editor/recalculation.py": ("run_refresh_request", "read_refresh_delivery", "run_policy_adoption_request", "read_policy_adoption_delivery"),
    "smart_reporting/reporting/workflow/revision_execution.py": ("continue_revision_delivery",),
    "smart_reporting/reporting/workflow/policy_adoption_analysis.py": ("continue_policy_adoption_delivery",),
    "smart_reporting/reporting/trace/revision_impact.py": ("assess_revision_impact",),
    "smart_reporting/reporting/trace/narrative_claims.py": ("narrative_paragraphs",),
    "smart_reporting/reporting/trace/registered_claims.py": ("registered_claim_support", "registered_narrative_support"),
    "smart_reporting/reporting/business_knowledge/claims.py": ("knowledge_support", "knowledge_source_presentations", "knowledge_source_summary"),
    "smart_reporting/reporting/workflow/runtime/business_evidence.py": ("register_section_knowledge", "resolve_runtime_knowledge", "revalidate_section_knowledge", "withdraw_knowledge_blocks"),
    "smart_reporting/reporting/business_knowledge/dependencies.py": ("read_knowledge_dependencies", "resolve_knowledge_dependencies"),
    "smart_reporting/report_editor/render_preparation.py": ("prepare_editor_render",),
    "smart_reporting/reporting/workflow/runtime/publication.py": ("_native_claim_presentations", "_verify_claim_fact_bindings", "_render_and_validate", "_render_revision_document", "_render_pptx", "_render_xlsx", "publish_report", "_publish_revision_report", "_write_trace_index"),
    "smart_reporting/reporting/workflow/runtime/planning.py": ("issue_http_publication", "_issue_http_pptx_publication", "_issue_http_xlsx_publication", "_issue_http_office_publication"),
    "smart_reporting/reporting/workspace.py": ("_render_report_pair",),
    "smart_reporting/report_editor/service.py": (
        "recalculation_delivery",
        "_export_revision",
        "_retry_export_delivery",
        "_persist_delivery",
        "_issue_delivery_grants",
        "_record_delivery",
    ),
    "smart_reporting/report_editor/slides.py": ("save_revision",),
    "smart_reporting/report_editor/workbook.py": ("save_revision", "_mark_sources_unverified", "_drop_source_mapping"),
    "smart_reporting/report_editor/revision_notice.py": ("add_workbook_revision_notice", "add_slides_revision_notice"),
    "smart_reporting/report_editor/native_publication.py": (
        "save_revision", "_save_reserved", "_publish_artifacts", "_issue_links",
    ),
}
_GATE_CODE = r"validation|not_validated|gate|audit|quality"
# 门禁内部可以 raise，但其在签发链路上的每个调用点都必须被 except Exception 兜底。
_CALLER_GUARDED = {
    "smart_reporting/reporting/workflow/runtime/publication.py": (
        ("publish_report", "_dataset_publication_gate"),
        ("_render_and_validate", "registered_claim_support_projection"),
        ("_render_revision_document", "registered_claim_support_projection"),
        ("_render_pptx", "_native_claim_presentations"),
        ("_render_xlsx", "_native_claim_presentations"),
    ),
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


@pytest.mark.anyio
async def test_publication_gate_keeps_collected_issues_when_audit_write_fails(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agno.run import RunContext

    from smart_reporting.reporting.workflow.runtime import publication

    async def failing_audit(*_args, **_kwargs):
        raise RuntimeError("audit service down")

    monkeypatch.setattr(publication, "_record_publication_audit", failing_audit)
    state: dict = {}
    runtime = SimpleNamespace(
        _state=lambda _context: state,
        _workflow_result=lambda _state: {},
        _scope=lambda _context: {
            "threadId": "thread", "externalRunId": "external", "database": "db", "companyId": "c",
        },
        workspace_service=SimpleNamespace(ahash_file=AsyncMock(return_value={"missing": True})),
        quality_warning_service=None,
    )

    gate = await publication.RuntimePublicationMixin._dataset_publication_gate(
        runtime, RunContext(run_id="run", session_id="thread", session_state=state), {"revision": 0}
    )

    codes = [item["code"] for item in gate["issues"]]
    assert gate["formalReleaseAllowed"] is False
    # 审计失败只追加一条问题，之前收集的门禁问题不被替换。
    assert codes[-1] == "report_quality_audit_failed"
    assert len(codes) > 1


@pytest.mark.anyio
async def test_pptx_publication_gate_checks_pptx_identity_without_document_exports():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agno.run import RunContext

    from smart_reporting.reporting.workflow.runtime import publication

    state: dict = {}
    hash_file = AsyncMock(
        side_effect=lambda _thread, path: {
            "missing": False,
            "size": {"reports/report.md": 1, "reports/report.pptx": 2}.get(path),
            "sha256": {"reports/report.md": "a" * 64, "reports/report.pptx": "b" * 64}.get(path),
        }
    )
    runtime = SimpleNamespace(
        _state=lambda _context: state,
        _workflow_result=lambda _state: {},
        _scope=lambda _context: {
            "threadId": "thread", "externalRunId": "external", "database": "db", "companyId": "c",
        },
        workspace_service=SimpleNamespace(ahash_file=hash_file),
        quality_warning_service=None,
    )
    result = {
        "status": "validation_failed",
        "deliveryFormat": "pptx",
        "revision": 1,
        "markdownPath": "reports/report.md",
        "markdownSize": 1,
        "markdownSha256": "a" * 64,
        "pptxPath": "reports/report.pptx",
        "pptxSize": 2,
        "pptxSha256": "b" * 64,
        "validationIssues": [{"code": "pptx_text_overflow"}],
    }

    gate = await publication.RuntimePublicationMixin._dataset_publication_gate(
        runtime,
        RunContext(run_id="run", session_id="thread", session_state=state),
        result,
    )

    paths = [call.args[1] for call in hash_file.await_args_list]
    assert "reports/report.md" in paths
    assert "reports/report.pptx" in paths
    assert "reports/report.pdf" not in paths
    assert "reports/report.docx" not in paths
    assert any(
        item["code"] == "artifact_not_validated"
        and item["details"]["validationIssues"] == result["validationIssues"]
        for item in gate["issues"]
    )


@pytest.mark.anyio
@pytest.mark.parametrize("knowledge_fault", [None, "revoked", "unavailable"])
async def test_publication_gate_preserves_caption_review_from_checkpoint(monkeypatch, knowledge_fault):
    from smart_reporting.reporting.workflow.checkpoint import ReportingCheckpoint

    caption_warning = {
        "code": "chart_caption_numeric_review",
        "chartId": "chart_001",
        "message": "图注部分数值缺少依据，已移除相关分句。",
    }
    checkpoint = ReportingCheckpoint.model_validate({
        "revision": 1, "phase": "analysis", "outlineHash": "a" * 64,
        "profileCoverage": {
            "authorizedDatasetCount": 1, "coveredDatasetCount": 1,
            "datasets": [{
                "datasetId": "dataset-1", "datasetPath": "datasets/source.csv",
                "datasetSize": 1, "datasetSnapshotHash": "b" * 64,
                "profileFile": {"path": "profiles/source.json", "size": 1, "sha256": "c" * 64},
                "rowCount": 1, "fieldCount": 1, "fields": ["amount"],
            }],
        },
        "evidenceManifest": {
            "evidence": [{
                "analysisId": "analysis_001", "summary": "收入比较",
                "datasetIds": ["dataset-1"], "citationIds": ["citation_001"],
                "evidenceFiles": [{"path": "evidence/source.json", "size": 1, "sha256": "d" * 64}],
            }],
            "datasetSemantics": [{
                "datasetId": "dataset-1", "rowGrain": "收入类型",
                "duplicateResolution": "not_applicable",
            }],
        },
        "warnings": [caption_warning, {"code": "unrelated_checkpoint_warning"}],
    })
    from smart_reporting.reporting.workflow.checkpoint import CompletedSection, SectionArtifact
    from smart_reporting.reporting.workflow.runtime import business_evidence

    artifact = SectionArtifact(sectionCode='section_001', blocks=[{
        'blockId': 'block_001', 'markdown': '旧业务解释', 'claimIds': ['c']}],
        claims=[{'claimId': 'c', 'metricCode': 'budget', 'value': 1, 'periodBasis': '本期',
                 'managementQuestion': '预算变化', 'currentPeriod': '本期', 'citationIds': ['citation_001']}],
        knowledgeReceiptIds=('knowledge-rules',))
    checkpoint = checkpoint.model_copy(update={'completed_sections': (CompletedSection(
        sectionCode='section_001', workItemHash='a' * 64,
        artifactFile={'path': 'section.json', 'size': 1, 'sha256': 'b' * 64}),)})
    async def revalidate(_runtime, _context, value, *, report_revision):
        assert report_revision == '1'
        assert value == artifact
        if knowledge_fault == 'unavailable':
            raise OSError('knowledge backend unavailable')
        if knowledge_fault == 'revoked':
            return artifact.model_copy(update={'knowledge_status': 'unavailable', 'claims': (),
                'blocks': (artifact.blocks[0].model_copy(update={'claim_ids': (), 'markdown': '知识依据不可用'}),),
                'warnings': ({
                'code': 'report_section_knowledge_unavailable', 'message': '知识已撤销'},)})
        return value
    checked = AsyncMock(side_effect=revalidate)
    monkeypatch.setattr(business_evidence, 'revalidate_section_knowledge', checked)
    state: dict = {}
    runtime = SimpleNamespace(
        _state=lambda _context: state,
        _workflow_result=lambda _state: {},
        _scope=lambda _context: {
            "threadId": "thread", "externalRunId": "external", "database": "db", "companyId": "c",
        },
        state_repository=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
            payload={"workflowCheckpoint": checkpoint.model_dump(mode="json", by_alias=True)},
        ))),
        _verify_claim_fact_bindings=AsyncMock(return_value=([], [])),
        _read_identity_model=AsyncMock(return_value=artifact),
        quality_warning_service=None,
    )

    gate = await publication.RuntimePublicationMixin._dataset_publication_gate(
        runtime, RunContext(run_id="run", session_id="thread", session_state=state), {"revision": 1}
    )

    checked.assert_awaited_once()
    if knowledge_fault:
        assert any(item['code'] == 'report_section_knowledge_unavailable' for item in gate['warnings'])
        assert any(item['code'] == 'report_section_knowledge_unavailable' for item in gate['issues'])
        assert not gate['formalReleaseAllowed']
    else:
        assert not any(item['code'] == 'report_section_knowledge_unavailable' for item in gate['issues'])
    assert caption_warning in gate["warnings"]
    assert not any(item.get("code") == "unrelated_checkpoint_warning" for item in gate["warnings"])
    assert not any(item["code"] == "chart_caption_numeric_review" for item in gate["issues"])
