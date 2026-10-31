"""重编译服务端标准模板，绑定实际执行的源码、输入和图片身份。"""

from __future__ import annotations

import hashlib
import hmac
import subprocess
from collections.abc import Mapping
from functools import lru_cache
from pathlib import PurePosixPath

from loguru import logger

from ...code_agent.formatting import format_python_source_sync
from ...trace.contracts_v1 import StandardChartRenderProofV1, canonical_json_bytes
from ..checkpoint import FileIdentity
from .chart_inputs import ChartInputFile, ChartInputMaterialization
from .phase_models import VisualizationPlanDraft
from .standard_visualization import standard_visualization_preflight

_PROOF_SIGNING_DOMAIN = b"standard-render-proof/v1"
_proof_signing_key: bytes | None = None


def configure_render_proof_signing(secret: str) -> None:
    """复用工作区HMAC密钥并按用途派生子密钥；不足32字节时不签名，核验只依赖重编译。"""
    global _proof_signing_key
    raw = secret.encode("utf-8")
    _proof_signing_key = (hmac.new(raw, _PROOF_SIGNING_DOMAIN, hashlib.sha256).digest()
                          if len(raw) >= 32 else None)


def _proof_digest(proof: StandardChartRenderProofV1, key: bytes) -> str:
    payload = canonical_json_bytes(proof.model_dump(mode="json", by_alias=True, exclude={"signature"}))
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def sign_standard_render_proof(proof: StandardChartRenderProofV1) -> StandardChartRenderProofV1:
    key = _proof_signing_key
    return proof if key is None else proof.model_copy(update={"signature": _proof_digest(proof, key)})


def standard_render_proof_signed(proof: StandardChartRenderProofV1) -> bool:
    key = _proof_signing_key
    return (key is not None and proof.signature is not None
            and hmac.compare_digest(proof.signature, _proof_digest(proof, key)))


def verify_standard_render_source(
    proof: StandardChartRenderProofV1, contents: Mapping[str, bytes], script_raw: bytes,
) -> str | None:
    """返回核验依据：当前模板重编译一致为recompiled；模板已演进时依签发签名为signed。

    contents按已核验hash索引；签名路径仍要求脚本字节与证明登记的hash一致。
    """
    compiled = recompile_standard_render_proof(proof, contents)
    if compiled is not None and compiled == script_raw:
        return "recompiled"
    if hashlib.sha256(script_raw).hexdigest() == proof.script_sha256 and standard_render_proof_signed(proof):
        return "signed"
    return None


@lru_cache(maxsize=32)
def _executed_source(source: str, expected_sha256: str) -> bytes | None:
    raw = source.encode()
    if hashlib.sha256(raw).hexdigest() == expected_sha256:
        return raw
    try:
        formatted = format_python_source_sync(source).encode()
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return formatted if hashlib.sha256(formatted).hexdigest() == expected_sha256 else None


def recompile_standard_render_proof(
    proof: StandardChartRenderProofV1, contents: Mapping[str, bytes],
) -> bytes | None:
    """contents 按已核验的 hash 索引；只编译受控模板，不执行归档脚本。"""
    try:
        plan = VisualizationPlanDraft.model_validate(proof.plan)
        files = []
        for entry in proof.inputs:
            raw = contents[entry['sha256']]
            if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                return None
            files.append(ChartInputFile(path=entry['path'], content=raw))
        inputs = ChartInputMaterialization(files=tuple(files), entries=proof.inputs)
        source = standard_visualization_preflight(plan, inputs).source
        return _executed_source(source, proof.script_sha256) if source is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def create_standard_render_proofs(result, plan, inputs) -> tuple[dict, ...]:
    """只接受与编译源码完全一致、输出身份齐全的真实执行回执。"""
    try:
        receipt = getattr(result, 'execution_receipt', None)
        script = getattr(result, 'script_file', None)
        if receipt is None or script is None or receipt.source_file != script:
            return ()
        frozen_plan = VisualizationPlanDraft.model_validate(
            plan.model_dump(mode='json', by_alias=True, exclude_unset=True)
        )
        compiled = standard_visualization_preflight(frozen_plan, inputs).source
        if compiled is None or _executed_source(compiled, script.sha256) is None:
            return ()
        outputs = {file.path: file for file in receipt.output_files}
        if len(outputs) != len(receipt.output_files):
            return ()
        entries = tuple(dict(entry) for entry in inputs.entries)
        if not entries:
            return ()
        return tuple({
            'chartId': chart.chart_id,
            'scriptFile': script,
            'proof': sign_standard_render_proof(StandardChartRenderProofV1(
                runId=receipt.run_id, scriptSha256=script.sha256,
                imageSha256=outputs[chart.source_path].sha256,
                plan=frozen_plan.model_dump(mode='json', by_alias=True, exclude_unset=True), inputs=entries,
            )),
        } for chart in frozen_plan.charts)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        logger.warning('report_standard_chart_proof_unavailable error={}', type(error).__name__)
        return ()


async def archive_standard_render_proof(runtime, thread_id, chart, image_path):
    """把完整输入依赖和执行源码归档；调用者把异常降为图表质量告警。"""
    proof = chart.standard_render_proof
    script = chart.render_script_file
    if proof is None or script is None or proof.image_sha256 != chart.source_file.sha256:
        raise ValueError('standard_render_identity_unavailable')
    script_raw = await runtime._read_identity_bytes(thread_id, script, max_bytes=1024 * 1024)
    contents = {}
    dependencies = []
    parent = PurePosixPath(image_path).parent
    for entry in proof.inputs:
        identity = FileIdentity(path=entry['path'], size=entry['size'], sha256=entry['sha256'])
        raw = await runtime._read_identity_bytes(thread_id, identity, max_bytes=8 * 1024 * 1024)
        contents[identity.sha256] = raw
        dependencies.append(await runtime._write_immutable_artifact(
            thread_id, str(parent / f'render-input-{identity.sha256}.json'), raw,
        ))
    if verify_standard_render_source(proof, contents, script_raw) is None:
        raise ValueError('standard_render_source_changed')
    archived_script = await runtime._write_immutable_artifact(
        thread_id, str(PurePosixPath(image_path).with_suffix('.render.py')), script_raw,
    )
    return archived_script, (*dependencies, archived_script)
