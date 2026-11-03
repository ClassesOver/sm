from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from loguru import logger

_MAX_PPTX_BYTES = 64 * 1024 * 1024
_MAX_REQUEST_BYTES = 8 * 1024 * 1024
_MAX_RECEIPT_BYTES = 128 * 1024 * 1024
_BRIDGE_TIMEOUT = 120


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise RuntimeError("pptx_engine_output_too_large")
    return content


def _run_bridge(content: bytes, operations: list[dict] | None) -> tuple[dict, bytes | None]:
    if not isinstance(content, bytes) or not content or len(content) > _MAX_PPTX_BYTES:
        raise ValueError("pptx_input_invalid")
    if operations is not None and (
        not isinstance(operations, list)
        or len(operations) > 1000
        or any(not isinstance(operation, dict) for operation in operations)
    ):
        raise ValueError("pptx_operations_invalid")
    engine = Path(os.environ.get(
        "AGENT_REPORTING_SLIDES_ENGINE_DIR",
        Path(__file__).parents[1] / "slides_engine",
    )).resolve()
    with tempfile.TemporaryDirectory(prefix="report-slides-edit-") as temporary:
        directory = Path(temporary)
        input_path = directory / "input.pptx"
        output_path = directory / "edited.pptx"
        receipt_path = directory / "receipt.json"
        request_path = directory / "request.json"
        request = {
            "mode": "inspect" if operations is None else "edit",
            "input": str(input_path),
            "output": str(output_path),
            "receipt": str(receipt_path),
            "operations": operations,
        }
        try:
            encoded = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError("pptx_operations_invalid") from error
        if len(encoded) > _MAX_REQUEST_BYTES:
            raise ValueError("pptx_operations_too_large")
        input_path.write_bytes(content)
        request_path.write_bytes(encoded)
        # 输出写入本次调用的临时文件，避免子进程输出无限占用 Python 内存。
        with (directory / "stderr.log").open("w+b") as stderr:
            try:
                process = subprocess.run(
                    [str(engine / "node_modules" / ".bin" / "tsx"),
                     str(engine / "bridge" / "edit-pptx.ts"), str(request_path)],
                    cwd=engine,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr,
                    timeout=_BRIDGE_TIMEOUT,
                )
            except subprocess.TimeoutExpired as error:
                logger.warning("PPTX 编辑引擎超时")
                raise RuntimeError("pptx_engine_timeout") from error
            except OSError as error:
                raise RuntimeError("pptx_engine_unavailable") from error
            if process.returncode:
                stderr.seek(0, 2)
                stderr.seek(max(0, stderr.tell() - 2000))
                detail = stderr.read(2000).decode("utf-8", errors="replace")
                logger.warning("PPTX 编辑引擎失败: {}", detail)
                raise RuntimeError("pptx_engine_failed")
        try:
            receipt = json.loads(_read_bounded(receipt_path, _MAX_RECEIPT_BYTES))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("pptx_engine_receipt_invalid") from error
        if not isinstance(receipt, dict):
            raise RuntimeError("pptx_engine_receipt_invalid")
        if receipt.get("error"):
            raise ValueError(str(receipt["error"]))
        edited = None
        if operations is not None:
            try:
                edited = _read_bounded(output_path, _MAX_PPTX_BYTES)
            except OSError as error:
                raise RuntimeError("pptx_engine_artifact_missing") from error
            if not edited:
                raise RuntimeError("pptx_engine_artifact_missing")
        return receipt, edited


def inspect_pptx(content: bytes) -> dict:
    """读取可编辑元素；未支持的原生对象保留在 PPTX 中。"""
    receipt, _ = _run_bridge(content, None)
    return receipt


def edit_pptx(content: bytes, operations: list[dict]) -> tuple[bytes, dict]:
    """返回新的 PPTX 与软告警，不覆盖原稿。"""
    if not isinstance(operations, list):
        raise ValueError("pptx_operations_invalid")
    receipt, edited = _run_bridge(content, operations)
    if edited is None:
        raise RuntimeError("pptx_engine_artifact_missing")
    return edited, receipt
