from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from ast import literal_eval
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agno.models.openai import OpenAIChat
from agno.tools.code.types import CellResult
from pydantic import ValidationError

from smart_reporting.reporting.agent import create_reporting_code_agent_factory
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_mode import ScriptProcessResult
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    _batch_response,
    _custom_response,
    _function_response,
    _message_response,
    _run_context,
    _task_context,
    workspace,  # noqa: F401
)
from smart_reporting.reporting.workflow.runtime import code_generation
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisItemWorkflow,
    AnalysisSummaryDraft,
    supplemental_evidence_output_contract,
    supplemental_evidence_schema_error,
    validate_supplemental_evidence,
)

CURRENT_ANALYSIS = {"analysisId": "analysis_001", "datasetIds": ["dataset_1"]}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_output_contract_example_passes_real_validator_with_server_owned_identity():
    contract = supplemental_evidence_output_contract()
    example = contract["example"]
    evidence = validate_supplemental_evidence(json.dumps(example), CURRENT_ANALYSIS)
    assert evidence.analysis_id == "analysis_001"
    assert evidence.dataset_ids == ("dataset_1",)
    assert evidence.findings[0]["columns"]
    assert evidence.findings[0]["rows"]
    assert {"analysisId", "datasetIds"}.isdisjoint(example)
    assert set(contract["schema"]["properties"]) == {"findings", "reconciliations", "warnings"}
    assert contract["schema"]["properties"]["findings"]["minItems"] == 1


@pytest.mark.parametrize("invalid", ["row_width", "duplicate_columns", "object_rows", "nonfinite", "passed_string"])
def test_example_mutations_are_rejected_by_real_custom_validators(invalid):
    example = supplemental_evidence_output_contract()["example"]
    finding = example["findings"][0]
    if invalid == "row_width":
        finding["rows"][0].append("extra")
    elif invalid == "duplicate_columns":
        finding["columns"][1] = finding["columns"][0]
    elif invalid == "object_rows":
        finding["rows"] = [{"department": "A", "amount": 1}]
    elif invalid == "nonfinite":
        finding["rows"][0][1] = float("inf")
    else:
        example["reconciliations"][0]["passed"] = "false"
    with pytest.raises(ValidationError):
        validate_supplemental_evidence(json.dumps(example), CURRENT_ANALYSIS)


class _ResponsesClient:
    def __init__(self, responses):
        self.responses = self
        self.input_tokens = self
        self.pending = list(responses)
        self.requests = []

    def is_closed(self):
        return False

    async def count(self, **_kwargs):
        return SimpleNamespace(input_tokens=1)

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.pending.pop(0)


class _ScriptProcessRuntime:
    """执行固定测试源码；不启动交互 Kernel，保留真实进程和文件副作用。"""

    def __init__(self):
        self.executions = 0
        self.shutdowns = []

    async def execute_script_process(self, _session_id, task_workspace, path, **_kwargs):
        self.executions += 1
        process = await asyncio.create_subprocess_exec(
            sys.executable, path, cwd=task_workspace.identity.root,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return ScriptProcessResult(CellResult(
            status="ok" if process.returncode == 0 else "error",
            stdout=stdout.decode(), stderr=stderr.decode(),
        ), process.returncode)

    async def shutdown(self, session_id):
        self.shutdowns.append(session_id)


@pytest.mark.anyio
@pytest.mark.parametrize("scenario", ["repaired", "degraded", "last_slot", "exhausted"])
async def test_evidence_feedback_to_workflow_completion(workspace, monkeypatch, scenario):  # noqa: F811
    if scenario in {"last_slot", "exhausted"}:
        monkeypatch.setattr(code_generation, "ANALYSIS_TOOL_CALL_LIMIT", 3 if scenario == "last_slot" else 2)
    facts = json.dumps({
        "analysisId": "analysis_001", "metrics": [], "derivedMetrics": [],
        "comparisons": [], "reconciliations": [], "warnings": [],
    })
    root = "evidence/analysis_001"
    evidence_path = f"{root}/supplement.json"
    clients, completions, summaries, diagnostics = [], [], [], []
    runtime = _ScriptProcessRuntime()

    async def read_file(*, path, **_kwargs):
        content = facts if path == "facts.json" else await workspace.aread_text("task-1", path)
        raw = content.encode()
        return {"ok": True, "content": content, "sha256": hashlib.sha256(raw).hexdigest(),
                "totalBytes": len(raw), "nextOffset": len(raw)}

    async def run_code(*, script_path, task_facts, diagnostic, run_context):
        diagnostics.append(diagnostic)
        context = replace(
            _task_context(workspace), script_path=script_path,
            authorized_write_paths=(script_path, evidence_path), declared_output_paths=(evidence_path,),
        )
        source = f"from pathlib import Path\nPath({evidence_path!r}).write_text('{{}}')\n# attempt {len(clients)}\n"
        responses = [_batch_response(
            _custom_response("write_script", source, 1), _function_response(2, "run_script", {}),
        )]
        if scenario == "repaired":
            valid = json.dumps(task_facts["outputContract"]["example"], ensure_ascii=False)
            fixed = f"from pathlib import Path\nPath({evidence_path!r}).write_text({valid!r})\n"
            responses.append(_batch_response(
                _custom_response("write_script", fixed, 3), _function_response(4, "run_script", {}),
            ))
        responses.extend([_function_response(5, "submit_script", {}), _message_response("结束")])
        client = _ResponsesClient(responses)
        clients.append(client)
        base_factory = create_reporting_code_agent_factory(
            model=OpenAIChat(id="test", api_key="test", base_url="http://localhost"), name="trajectory",
        )

        def factory(tools):
            agent = base_factory(tools)
            agent.model.async_client = client
            return agent

        async def preflight(receipt):
            raw = await workspace.read_limited_regular_file("task-1", evidence_path, max_bytes=100_000)
            try:
                validate_supplemental_evidence(raw, task_facts["currentAnalysis"])
            except ValidationError as error:
                rejection = supplemental_evidence_schema_error(error)
                return {"code": rejection.code, "message": rejection.message, "details": rejection.details}
            return None

        return await code_generation.ReportingCodeGenerationRunner(
            factory, runtime, ReportingLspProcessManager(),
        ).run(context, workspace, task_facts, run_context=run_context,
              diagnostic=diagnostic, output_preflight=preflight)

    async def decide(_payload):
        return AnalysisEvidenceDecision(requiresSupplementalEvidence=True, reason="需要明细", missingFacts=("明细",))

    async def summarize(payload):
        summaries.append(payload)
        return AnalysisSummaryDraft(summary="完成")

    async def complete(**kwargs):
        completions.append(kwargs)
        return {"status": "accepted", "taskFinished": True}

    workflow = AnalysisItemWorkflow(
        decide_evidence=decide, run_code=run_code, read_file=read_file, summarize=summarize, complete=complete,
    )
    instruction = {
        "currentAnalysisId": "analysis_001", "currentAnalysis": CURRENT_ANALYSIS,
        "analysisOutputRoot": root, "datasets": [{"datasetId": "dataset_1"}],
        "deterministicFactFile": {"path": "facts.json", "size": len(facts.encode()),
                                  "sha256": hashlib.sha256(facts.encode()).hexdigest()},
        "deterministicFacts": json.loads(facts),
    }
    # C5（outputValidation 阻断 submit_script）让 schema 校验在 Coding Agent 循环
    # 内部就能捕获，不再需要 validate-evidence 阶段兜底；因此无论 tool_call_limit
    # 是否紧张（degraded/last_slot/exhausted 均如此），失败都在 execute-script
    # 阶段以 report_code_generation_no_submission 出现，按 generation_attempts
    # 重试到耗尽后统一软降级，而不是像 outputValidation 阻断之前那样区分
    # 「预算刚好够提交、稍后被 validate-evidence 拦下」与「预算太紧连提交都
    # 谈不上、在 execute-script 直接硬失败」两条路径。
    result = await workflow.run(instruction, _run_context())
    assert all(status == "completed" for _, status in result.stage_statuses)
    assert len(completions) == 1
    if scenario == "repaired":
        assert len(clients) == 1
        assert runtime.executions == 2
        assert completions[0]["evidencePaths"] == [evidence_path]
        assert summaries[0]["supplementalEvidence"]["analysisId"] == "analysis_001"
        assert any("report_analysis_evidence_reconciliation_warning" in item for item in completions[0]["warnings"])
    else:
        assert len(clients) == 3
        assert runtime.executions == 3
        assert all(
            item["code"] == "report_analysis_evidence_schema_invalid" for item in diagnostics[1:]
        )
        assert completions[0]["evidencePaths"] == []
        assert summaries[0]["supplementalEvidence"] is None
        assert any("report_analysis_supplement_abandoned" in item for item in completions[0]["warnings"])
    assert len(runtime.shutdowns) == len(clients)
    for client in clients:
        user_message = next(item for item in client.requests[0]["input"] if item.get("role") == "user")
        content = user_message["content"]
        prompt = json.loads(content if isinstance(content, str) else content[0]["text"])
        example = validate_supplemental_evidence(
            json.dumps(prompt["facts"]["outputContract"]["example"]), CURRENT_ANALYSIS,
        )
        assert example.findings[0]["rows"]
        outputs = [item for item in client.requests[1]["input"] if item.get("type") == "function_call_output"]
        assert len(outputs) == 1
        # Agno 原生 function 结果为文本，并会规范化 Responses 调用身份。
        feedback = literal_eval(outputs[0]["output"])
        assert feedback["outputValidation"]["code"] == "report_analysis_evidence_schema_invalid"
        assert "findings" in feedback["outputValidation"]["details"]["issueSummary"]
