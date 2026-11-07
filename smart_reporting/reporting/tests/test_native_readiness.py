"""原生编辑 readiness 只约束已启用能力，不干预既有下载。"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest


def settings(**changes):
    return SimpleNamespace(
        native_docx_enabled=False,
        native_pdf_enabled=False,
        native_pdf_text_enabled=False,
        native_ai_enabled=False,
        native_upload_enabled=False,
        **changes,
    )


def enabled(**changes):
    values = vars(settings())
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.fixture
def engines(tmp_path, monkeypatch):
    slides = tmp_path / "slides"
    pdf = tmp_path / "pdf"
    for root, script in ((slides, "edit-docx"), (pdf, "cli")):
        (root / "dist").mkdir(parents=True)
        (root / "dist" / f"{script}.mjs").write_text("// standalone bridge")
    (pdf / "wasm").mkdir()
    manifest = {}
    for name in ("pdfium.wasm", "hb-subset.wasm"):
        content = b"\x00asm" + name.encode()
        (pdf / "wasm" / name).write_bytes(content)
        manifest[name] = hashlib.sha256(content).hexdigest()
    (pdf / "WASM-SHA256.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("AGENT_REPORTING_SLIDES_ENGINE_DIR", str(slides))
    monkeypatch.setenv("AGENT_REPORTING_PDF_ENGINE_DIR", str(pdf))
    monkeypatch.delenv("AGENT_REPORTING_PDF_WASM_DIR", raising=False)
    from smart_reporting.report_editor import native_readiness as module

    monkeypatch.setattr(module, "_WASM_SHA256", manifest)
    monkeypatch.setattr(module.shutil, "which", lambda tool: "/usr/bin/" + tool)
    return slides, pdf


def test_disabled_features_do_not_require_any_native_resources(monkeypatch):
    from smart_reporting.report_editor.native_readiness import native_readiness_checks

    monkeypatch.setenv("AGENT_REPORTING_SLIDES_ENGINE_DIR", "/nonexistent")
    monkeypatch.setenv("AGENT_REPORTING_PDF_ENGINE_DIR", "/nonexistent")
    assert native_readiness_checks(settings()) == {}


def test_docx_enabled_requires_node_and_bridge_only(engines, monkeypatch):
    from smart_reporting.report_editor import native_readiness as module

    checks = module.native_readiness_checks(enabled(native_docx_enabled=True))
    assert checks and all(checks.values())
    assert not any("pdf" in key for key in checks)
    (engines[0] / "dist/edit-docx.mjs").unlink()
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    checks = module.native_readiness_checks(enabled(native_docx_enabled=True))
    assert checks["native_node"] is False
    assert checks["native_docx_bridge"] is False


def test_pdf_enabled_checks_fixed_wasm_identity_and_manifest(engines):
    from smart_reporting.report_editor.native_readiness import native_readiness_checks

    assert all(native_readiness_checks(enabled(native_pdf_enabled=True)).values())
    root = engines[1]
    (root / "wasm/pdfium.wasm").write_bytes(b"changed")
    manifest = json.loads((root / "WASM-SHA256.json").read_text())
    manifest["pdfium.wasm"] = hashlib.sha256(b"changed").hexdigest()
    (root / "WASM-SHA256.json").write_text(json.dumps(manifest))
    checks = native_readiness_checks(enabled(native_pdf_enabled=True))
    assert checks["native_pdf_pdfium_sha256"] is False
    assert checks["native_pdf_wasm_manifest"] is False
    assert checks["native_pdf_harfbuzz_sha256"] is True


@pytest.mark.parametrize("missing", ["dist/cli.mjs", "wasm/hb-subset.wasm", "WASM-SHA256.json"])
def test_pdf_missing_resource_is_not_ready(engines, missing):
    from smart_reporting.report_editor.native_readiness import native_readiness_checks

    (engines[1] / missing).unlink()
    assert not all(native_readiness_checks(enabled(native_pdf_enabled=True)).values())


def test_explicit_wasm_directory_is_checked_instead_of_bundled_copy(engines, monkeypatch, tmp_path):
    from smart_reporting.report_editor.native_readiness import native_readiness_checks

    configured = tmp_path / "configured"
    configured.mkdir()
    monkeypatch.setenv("AGENT_REPORTING_PDF_WASM_DIR", str(configured))
    checks = native_readiness_checks(enabled(native_pdf_enabled=True))
    assert checks["native_pdf_pdfium_sha256"] is False
    assert checks["native_pdf_harfbuzz_sha256"] is False


@pytest.mark.parametrize("probe", [True, False])
def test_pdf_text_uses_actual_engine_resource_probe(engines, monkeypatch, probe):
    from unittest.mock import Mock

    from smart_reporting.report_editor import native_readiness as module

    check = Mock(return_value=probe)
    monkeypatch.setattr(module, "_check_pdf_text_resources", check)
    checks = module.native_readiness_checks(
        enabled(native_pdf_enabled=True, native_pdf_text_enabled=True)
    )
    assert checks["native_pdf_text_resources"] is probe
    check.assert_called_once_with()


def test_pdf_text_probe_is_not_called_when_required_resources_are_missing(engines, monkeypatch):
    from unittest.mock import Mock

    from smart_reporting.report_editor import native_readiness as module

    (engines[1] / "wasm/pdfium.wasm").unlink()
    check = Mock(side_effect=AssertionError("must check assets before invoking bridge"))
    monkeypatch.setattr(module, "_check_pdf_text_resources", check)
    checks = module.native_readiness_checks(
        enabled(native_pdf_enabled=True, native_pdf_text_enabled=True)
    )
    assert checks["native_pdf_text_resources"] is False
    check.assert_not_called()


@pytest.mark.parametrize(
    "flags,dependency",
    [
        ({"native_ai_enabled": True}, "native_ai_editor_dependency"),
        ({"native_pdf_text_enabled": True}, "native_pdf_text_editor_dependency"),
    ],
)
def test_enabled_subfeature_requires_base_editor(engines, flags, dependency):
    from smart_reporting.report_editor.native_readiness import native_readiness_checks

    assert native_readiness_checks(enabled(**flags))[dependency] is False


@pytest.mark.parametrize("receipt", [{"ok": True}, {"ok": False}, {"ok": "true"}, {}, None])
def test_text_resource_probe_requires_explicit_success(monkeypatch, receipt):
    from smart_reporting.report_editor.native_readiness import _check_pdf_text_resources
    from smart_reporting.reporting.delivery import pdf_native

    monkeypatch.setattr(pdf_native, "check_text_resources", lambda: receipt)
    assert _check_pdf_text_resources() is (isinstance(receipt, dict) and receipt.get("ok") is True)


def test_text_resource_probe_failure_is_readiness_false(monkeypatch):
    from smart_reporting.report_editor.native_readiness import _check_pdf_text_resources
    from smart_reporting.reporting.delivery import pdf_native

    def unavailable():
        raise FileNotFoundError("missing bridge")

    monkeypatch.setattr(pdf_native, "check_text_resources", unavailable)
    assert _check_pdf_text_resources() is False


def test_upload_requires_all_four_import_and_edit_engines(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from smart_reporting.report_editor import native_readiness as module
    settings=SimpleNamespace(native_docx_enabled=False,native_pdf_enabled=False,native_pdf_text_enabled=False,native_ai_enabled=False,native_upload_enabled=True)
    monkeypatch.setattr(module,'engine_dir',lambda engine:tmp_path/engine)
    checks=module.native_readiness_checks(settings)
    for key in ('native_node','native_docx_bridge','native_pdf_bridge','native_workbook_bridge','native_slides_bridge'):
        assert key in checks
    assert checks['native_workbook_bridge'] is False
    assert checks['native_slides_bridge'] is False
