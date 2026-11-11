"""原生编辑资源 readiness；只供健康检查，不参与历史文件下载或签发。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from loguru import logger

from ..reporting.delivery.office_engine import engine_dir

# 与固定 PDF runtime packer 的资源身份一致，不能信任同目录可变清单自报的 hash。
_WASM_SHA256 = {
    "pdfium.wasm": "5e4cd023c3dad4a895b3571ca573d3fc51bac6de48360d95283134385b954eaa",
    "hb-subset.wasm": "3a5d246b0e4c0017084775e9f2c7fce96e45d09b1a354fd9e2e440c88fb9890d",
}


def _nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _has_identity(path: Path, expected: str) -> bool:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == expected
    except OSError:
        return False


def _check_pdf_text_resources() -> bool:
    try:
        from ..reporting.delivery.pdf_native import check_text_resources

        receipt = check_text_resources()
        return isinstance(receipt, dict) and receipt.get("ok") is True
    except Exception:
        # 真实引擎决定字体定位、TTC 单面抽取与中文数字 glyph 可写；不另造字体选择器。
        return False


def native_readiness_checks(settings: Any) -> dict[str, bool]:
    """返回可直接合入现有 /ready checks 的布尔值；关闭能力不要求其资源。"""
    docx = bool(settings.native_docx_enabled)
    pdf = bool(settings.native_pdf_enabled)
    pdf_text = bool(settings.native_pdf_text_enabled)
    ai = bool(settings.native_ai_enabled)
    upload = bool(getattr(settings, "native_upload_enabled", False))
    checks: dict[str, bool] = {}
    if docx or pdf or pdf_text or ai or upload:
        checks["native_node"] = shutil.which("node") is not None
    if docx or upload:
        checks["native_docx_bridge"] = _nonempty_file(engine_dir("doc") / "dist/edit-docx.mjs")
    if upload:
        checks["native_workbook_bridge"] = _nonempty_file(engine_dir("workbook") / "dist/cli.mjs")
        checks["native_slides_bridge"] = _nonempty_file(engine_dir("slides") / "dist/edit-pptx.mjs")
    if ai:
        checks["native_ai_editor_dependency"] = docx or pdf
    if pdf or pdf_text or upload:
        root = engine_dir("pdf")
        checks["native_pdf_bridge"] = _nonempty_file(root / "dist/cli.mjs")
        wasm = Path(os.getenv("AGENT_REPORTING_PDF_WASM_DIR") or root / "wasm")
        checks["native_pdf_pdfium_sha256"] = _has_identity(
            wasm / "pdfium.wasm", _WASM_SHA256["pdfium.wasm"]
        )
        checks["native_pdf_harfbuzz_sha256"] = _has_identity(
            wasm / "hb-subset.wasm", _WASM_SHA256["hb-subset.wasm"]
        )
        try:
            manifest = json.loads((root / "WASM-SHA256.json").read_text(encoding="utf-8"))
            checks["native_pdf_wasm_manifest"] = manifest == _WASM_SHA256
        except (OSError, ValueError):
            checks["native_pdf_wasm_manifest"] = False
    if pdf_text:
        checks["native_pdf_text_editor_dependency"] = pdf
        checks["native_pdf_text_resources"] = all(checks.values()) and _check_pdf_text_resources()
    for name, ok in checks.items():
        if not ok:
            logger.warning("native_readiness_failed check={}", name)
    return checks
