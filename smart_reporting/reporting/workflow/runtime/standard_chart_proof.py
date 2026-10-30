"""重编译服务端标准模板，绑定实际执行的源码、输入和图片身份。"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping
from functools import lru_cache
from pathlib import PurePosixPath

from loguru import logger

from ...code_agent.formatting import format_python_source_sync
from ...trace.contracts_v1 import StandardChartRenderProofV1
from ..checkpoint import FileIdentity
from .chart_inputs import ChartInputFile, ChartInputMaterialization
from .phase_models import VisualizationPlanDraft
from .standard_visualization import standard_visualization_preflight


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
            'proof': StandardChartRenderProofV1(
                runId=receipt.run_id, scriptSha256=script.sha256,
                imageSha256=outputs[chart.source_path].sha256,
                plan=frozen_plan.model_dump(mode='json', by_alias=True, exclude_unset=True), inputs=entries,
            ),
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
    compiled = recompile_standard_render_proof(proof, contents)
    if compiled is None or compiled != script_raw:
        raise ValueError('standard_render_source_changed')
    archived_script = await runtime._write_immutable_artifact(
        thread_id, str(PurePosixPath(image_path).with_suffix('.render.py')), script_raw,
    )
    return archived_script, (*dependencies, archived_script)
