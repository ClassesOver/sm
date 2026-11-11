"""固定源表单设计控件的严格身份桥接；不覆盖输入 PDF。"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from .pdf_native import _invoke


def inspect_pdf_design_widgets(content: bytes) -> dict[str, Any]:
    """读取真实控件身份及保守删除能力。"""
    with tempfile.TemporaryDirectory(prefix="inspect-pdf-form-design-") as temporary:
        root = Path(temporary)
        source = root / "input.pdf"
        source.write_bytes(content)
        receipt = _invoke({"kind": "inspectDesignWidgets", "input": str(source)}, root)
        if receipt.get("sourceSha256") != hashlib.sha256(content).hexdigest():
            raise ValueError("pdf_form_design_source_identity_invalid")
        return receipt


def remove_pdf_design_widget(content: bytes, target: dict[str, Any]) -> dict[str, Any]:
    """按来源绑定控件身份删除，返回新字节和实际文件身份。"""
    if not isinstance(target, dict):
        raise ValueError("pdf_form_design_widget_invalid")
    keys = ("fieldName", "widgetId", "widgetIdentity", "expectedWidgetSha256")
    if any(key not in target for key in keys):
        raise ValueError("pdf_form_design_widget_invalid")
    with tempfile.TemporaryDirectory(prefix="remove-pdf-form-widget-") as temporary:
        root = Path(temporary)
        source, output = root / "input.pdf", root / "output.pdf"
        source.write_bytes(content)
        receipt = _invoke({
            "kind": "removeDesignWidget",
            "input": str(source),
            "output": str(output),
            "sourceSha256": hashlib.sha256(content).hexdigest(),
            "target": {key: target[key] for key in keys},
        }, root)
        result = output.read_bytes()
        if (
            not result
            or receipt.get("sourceSha256") != hashlib.sha256(content).hexdigest()
            or receipt.get("sha256") != hashlib.sha256(result).hexdigest()
            or receipt.get("size") != len(result)
        ):
            raise ValueError("pdf_form_design_output_identity_invalid")
        return {**receipt, "content": result}
