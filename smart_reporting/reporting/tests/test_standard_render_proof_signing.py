"""签发签名让模板演进后的旧证明仍可核验，且不放宽身份校验。"""
import hashlib
import hmac
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_standard_chart_proof import proof_case
from smart_reporting.reporting.trace.contracts_v1 import canonical_json_bytes
from smart_reporting.reporting.workflow.runtime import standard_chart_proof as module

SECRET = "s" * 32


@pytest.fixture(autouse=True)
def reset_signing(monkeypatch):
    monkeypatch.setattr(module, "_proof_signing_key", None)


def signed_case(secret=SECRET):
    module.configure_render_proof_signing(secret)
    plan, inputs, result, source = proof_case()
    proof = module.create_standard_render_proofs(result, plan, inputs)[0]["proof"]
    return proof, {file.sha256: file.content for file in inputs.files}, source


def evolve_templates(monkeypatch):
    original = module.standard_visualization_preflight

    def evolved(plan, inputs):
        result = original(plan, inputs)
        return SimpleNamespace(source=result.source + "\n# template evolved\n", diagnostic=None)

    monkeypatch.setattr(module, "standard_visualization_preflight", evolved)


def test_signed_proof_verifies_by_recompile_then_by_signature_after_template_change(monkeypatch):
    proof, contents, source = signed_case()
    assert proof.signature is not None
    assert module.verify_standard_render_source(proof, contents, source) == "recompiled"
    evolve_templates(monkeypatch)
    assert module.verify_standard_render_source(proof, contents, source) == "signed"


@pytest.mark.parametrize("fault", ["plan", "inputs", "image", "script_bytes", "signature"])
def test_signature_does_not_cover_tampered_proof_or_script(monkeypatch, fault):
    proof, contents, source = signed_case()
    evolve_templates(monkeypatch)
    if fault == "plan":
        proof = proof.model_copy(update={"plan": {**proof.plan, "warnings": ["改动"]}})
    elif fault == "inputs":
        proof = proof.model_copy(update={"inputs": ({**proof.inputs[0], "chartId": "other"},)})
    elif fault == "image":
        proof = proof.model_copy(update={"image_sha256": "0" * 64})
    elif fault == "script_bytes":
        source += b" "
    else:
        proof = proof.model_copy(update={"signature": "0" * 64})
    assert module.verify_standard_render_source(proof, contents, source) is None


@pytest.mark.parametrize("secret", ["", "short-secret"])
def test_weak_or_missing_secret_never_signs(monkeypatch, secret):
    proof, contents, source = signed_case(secret)
    assert proof.signature is None
    evolve_templates(monkeypatch)
    assert module.verify_standard_render_source(proof, contents, source) is None


def test_rotated_key_rejects_old_signature_and_raw_secret_is_not_the_key(monkeypatch):
    proof, contents, source = signed_case()
    payload = canonical_json_bytes(proof.model_dump(mode="json", by_alias=True, exclude={"signature"}))
    # 按用途派生子密钥：不能直接用工作区原始密钥伪造证明签名。
    assert proof.signature != hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    module.configure_render_proof_signing("t" * 32)
    evolve_templates(monkeypatch)
    assert module.verify_standard_render_source(proof, contents, source) is None
