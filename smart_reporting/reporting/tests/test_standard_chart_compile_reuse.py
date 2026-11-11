"""首次预检只编译一次；布局候选和产物证明仍各自核验。"""

import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_standard_chart_proof import proof_case
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime import standard_chart_proof as proofs
from smart_reporting.reporting.workflow.runtime import standard_chart_routing as routing


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("deterministic", [False, True])
@pytest.mark.parametrize("layout_retry", [False, True])
async def test_single_route_compiles_each_candidate_once_and_independently_proves_output(
    tmp_path, monkeypatch, deterministic, layout_retry,
):
    plan, inputs, _, _ = proof_case()
    monkeypatch.chdir(tmp_path)
    for file in inputs.files:
        (tmp_path / file.path).write_bytes(file.content)
    compiled_widths, proof_compilations, executed = [], [], []
    real_preflight = routing.standard_visualization_preflight

    def route_preflight(candidate, frozen):
        compiled_widths.append(candidate.charts[0].standard_canvas.width)
        return real_preflight(candidate, frozen)

    def proof_preflight(candidate, frozen):
        proof_compilations.append(candidate.charts[0].standard_canvas.width)
        return real_preflight(candidate, frozen)

    monkeypatch.setattr(routing, "standard_visualization_preflight", route_preflight)
    monkeypatch.setattr(proofs, "standard_visualization_preflight", proof_preflight)

    async def standard(context, workspace, source, facts, **kwargs):
        assert kwargs == ({"deterministic": True} if deterministic else {})
        executed.append(source)
        if layout_retry and len(executed) == 1:
            # 替代外部视觉审查的布局失败；源码编译、重绘与证明均走真实实现。
            raise ReportingError("review_failed", "布局失败", details={
                "standardDiagnostic": {"code": "standard_chart_layout_unresolved"},
            })
        exec(compile(source, "chart.py", "exec"), {})
        image = (tmp_path / "chart.png").read_bytes()
        script = FileIdentity(path="chart.py", size=len(source.encode()),
                              sha256=hashlib.sha256(source.encode()).hexdigest())
        return SimpleNamespace(script_file=script, execution_receipt=ExecutionReceipt(
            runId="current-run", sourceFile=script,
            outputFiles=(FileIdentity(path="chart.png", size=len(image),
                                      sha256=hashlib.sha256(image).hexdigest()),),
        ))

    async def coding(*args, **kwargs):
        raise AssertionError("标准成功或可修复布局不调用模型回退")

    result = await routing.run_standard_chart_routes(
        SimpleNamespace(run_standard_visualization=standard, run=coding),
        object(), object(), plan, inputs, {}, object(), deterministic=deterministic,
    )
    assert len(compiled_widths) == (2 if layout_retry else 1)
    assert len(executed) == len(compiled_widths)
    if layout_retry:
        assert compiled_widths[1] > compiled_widths[0]
        assert executed[1] != executed[0]
    assert proof_compilations == [compiled_widths[-1]]
    assert result.standard_chart_routes[0]["route"] == "standard"
    assert len(result.standard_render_proofs) == 1
    proof = result.standard_render_proofs[0]["proof"]
    image = (tmp_path / "chart.png").read_bytes()
    assert image.startswith(b"\x89PNG")
    assert proof.image_sha256 == hashlib.sha256(image).hexdigest()
    assert proofs.recompile_standard_render_proof(
        proof, {file.sha256: file.content for file in inputs.files},
    ) == executed[-1].encode()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("deterministic", [False, True])
async def test_reused_preflight_still_rejects_input_replaced_before_execution(
    tmp_path, monkeypatch, deterministic,
):
    plan, inputs, _, _ = proof_case()
    monkeypatch.chdir(tmp_path)
    executions = []

    async def standard(context, workspace, source, facts, **kwargs):
        executions.append(source)
        (tmp_path / inputs.files[0].path).write_bytes(b'{"rows": []}')
        exec(compile(source, "chart.py", "exec"), {})
        raise AssertionError("输入被替换后不能交付图片")

    async def coding(*args, **kwargs):
        raise AssertionError("身份失败不能调用模型重试")

    with pytest.raises(ValueError, match="chart input identity changed"):
        await routing.run_standard_chart_routes(
            SimpleNamespace(run_standard_visualization=standard, run=coding),
            object(), object(), plan, inputs, {}, object(), deterministic=deterministic,
        )
    assert len(executions) == 1
    assert not (tmp_path / "chart.png").exists()
