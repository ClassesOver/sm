"""Actual pinned pr80 declarations and an isolated backportable reader process."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.compat.fact_reader import (
    compatible_pr80_models,
    read_compatible_snapshot,
)
from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    DeterministicMetricFact,
)

from .fixtures.report_quality import pr80_fact_models as legacy
from .test_group_contribution_assertions import contribution_document


def models():
    return compatible_pr80_models(
        legacy.DeterministicMetricFact, legacy.DeterministicAnalysisBundle
    )


def read(document):
    raw = json.dumps(document, ensure_ascii=False, indent=2).encode()
    return read_compatible_snapshot(
        raw, models(), expected_size=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
    )


def cumulative_document():
    document = contribution_document()
    document["metrics"][0]["cumulativePolicy"] = {
        "version": "1",
        "reset": "calendar_year_zero",
        "observation": "closed_month_end",
        "changes": "signed_snapshot_delta",
    }
    return document


def test_cumulative_policy_is_read_without_reusing_new_semantics_or_changing_bytes():
    document = cumulative_document()
    DeterministicAnalysisBundle.model_validate(document)
    with pytest.raises(ValidationError):
        legacy.DeterministicAnalysisBundle.model_validate(document)
    snapshot = read(document)
    assert snapshot.document == document
    assert snapshot.raw == json.dumps(document, ensure_ascii=False, indent=2).encode()
    assert snapshot.required_features == (
        "complete_group_population",
        "cumulative_snapshot_policy",
        "period_aggregation_sum",
        "series_missing_count",
    )
    assert snapshot.semantic_status == "unknown"
    assert snapshot.semantic_support_reused is False
    assert snapshot.workflow_resume_supported is False


@pytest.mark.parametrize(
    "fault", ["unknown_field", "future_version", "unknown_reset", "missing_observation", "unknown_changes"]
)
def test_cumulative_policy_adapter_rejects_unknown_or_incomplete_declarations(fault):
    document = cumulative_document()
    policy = document["metrics"][0]["cumulativePolicy"]
    if fault == "unknown_field":
        policy["semanticVerified"] = True
    elif fault == "future_version":
        policy["version"] = "2"
    elif fault == "unknown_reset":
        policy["reset"] = "fiscal_year_zero"
    elif fault == "missing_observation":
        del policy["observation"]
    elif fault == "unknown_changes":
        policy["changes"] = "operating_flow"
    with pytest.raises(ValidationError):
        read(document)


@pytest.mark.parametrize("explicit_null", [True, False])
def test_absent_cumulative_policy_does_not_create_a_wire_field_or_a_required_feature(explicit_null):
    document = contribution_document()
    if explicit_null:
        document["metrics"][0]["cumulativePolicy"] = None
    snapshot = read(document)
    assert snapshot.document == document
    assert "cumulative_snapshot_policy" not in snapshot.required_features
    validated = models().bundle.model_validate(document)
    assert "cumulativePolicy" not in validated.model_dump(by_alias=True)["metrics"][0]


def test_actual_pr80_bundle_rejects_new_fields_but_read_adapter_preserves_every_byte_and_identity():
    document = contribution_document()
    with pytest.raises(ValidationError):
        legacy.DeterministicAnalysisBundle.model_validate(document)
    snapshot = read(document)
    assert snapshot.document == document
    assert snapshot.raw == json.dumps(document, ensure_ascii=False, indent=2).encode()
    assert snapshot.sha256 == hashlib.sha256(snapshot.raw).hexdigest()
    assert snapshot.required_features == (
        "complete_group_population",
        "period_aggregation_sum",
        "series_missing_count",
    )
    assert snapshot.semantic_status == "unknown"
    assert snapshot.semantic_support_reused is False
    assert snapshot.workflow_resume_supported is False
    assert [fact["factId"] for fact in snapshot.document["metrics"]] == [
        fact["factId"] for fact in document["metrics"]
    ]
    # Adaptation is local; it cannot turn the original reader permissive.
    with pytest.raises(ValidationError):
        legacy.DeterministicAnalysisBundle.model_validate(document)


def test_actual_legacy_snapshot_does_not_acquire_default_metadata_or_new_fact_ids():
    document = contribution_document()
    for metric in document["metrics"]:
        metric.pop("seriesMissingCount")
        metric.pop("groupPopulation")
        metric["periodAggregation"] = None
    legacy.DeterministicAnalysisBundle.model_validate(document)
    snapshot = read(document)
    assert snapshot.document == document and snapshot.required_features == ()
    assert "seriesMissingCount" not in snapshot.document["metrics"][0]
    assert "groupPopulation" not in snapshot.document["metrics"][0]
    assert snapshot.document["metrics"][0]["periodAggregation"] is None


def test_mutating_a_consumer_view_does_not_change_the_verified_snapshot():
    snapshot = read(contribution_document())
    view = snapshot.document
    view["metrics"][0]["total"] = -999
    view["metrics"].clear()
    assert snapshot.document == contribution_document()
    assert hashlib.sha256(snapshot.raw).hexdigest() == snapshot.sha256


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_field",
        "future_enum",
        "future_version",
        "negative_missing",
        "bad_group",
        "over_budget",
        "duplicate_fact",
        "invalid_source",
        "invalid_scope",
    ],
)
def test_bridge_does_not_accept_unrecognized_or_invalid_data(fault):
    doc = contribution_document()
    metric = doc["metrics"][0]
    if fault == "unknown_field":
        metric["futureProofPassed"] = True
    elif fault == "future_enum":
        metric["periodAggregation"] = "average"
    elif fault == "future_version":
        doc["version"] = "2"
    elif fault == "negative_missing":
        metric["seriesMissingCount"] = -1
    elif fault == "bad_group":
        metric["groupPopulation"][0]["unknownProof"] = True
    elif fault == "over_budget":
        metric["groupPopulation"] *= 1001
    elif fault == "duplicate_fact":
        doc["metrics"].append(metric)
    elif fault == "invalid_source":
        metric["datasetSha256"] = "invalid"
    elif fault == "invalid_scope":
        metric["scope"] = {"campus": ["北院", "南院"]}
    with pytest.raises((ValueError, ValidationError)):
        read(doc)


@pytest.mark.parametrize("kind", ["hash", "size", "size_bool", "large_size", "uppercase_hash"])
def test_expected_identity_must_match_authorized_original_bytes(kind):
    raw = json.dumps(contribution_document()).encode()
    size = len(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if kind == "hash":
        digest = "0" * 64
    elif kind == "size":
        size += 1
    elif kind == "size_bool":
        size = True
    elif kind == "large_size":
        size = 65 * 1024 * 1024
    elif kind == "uppercase_hash":
        digest = digest.upper()
    with pytest.raises(ValueError, match="snapshot_identity_mismatch"):
        read_compatible_snapshot(raw, models(), expected_size=size, expected_sha256=digest)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"analysisId":"analysis_001","analysisId":"analysis_002"}',
        b'{"metrics":[{"total":NaN}]}',
        b'{"metrics":[{"total":Infinity}]}',
        b'{"metrics":[{"total":1e999}]}',
    ],
)
def test_ambiguous_or_nonfinite_json_cannot_become_a_readable_snapshot(raw):
    with pytest.raises(ValueError):
        read_compatible_snapshot(
            raw, models(), expected_size=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
        )


def test_current_models_are_not_mistaken_for_a_supported_old_target():
    with pytest.raises(ValueError, match="unsupported_legacy_metric_model"):
        compatible_pr80_models(DeterministicMetricFact, DeterministicAnalysisBundle)


@pytest.mark.parametrize("valid_identity", [True, False])
@pytest.mark.parametrize("cumulative", [True, False])
def test_portable_probe_runs_in_a_separate_process_without_application_imports(
    tmp_path, valid_identity, cumulative
):
    import smart_reporting.reporting.compat.fact_reader as bridge

    # Copy only the adapter and exact old declarations into an empty directory.
    # The child must have no imports of the new app or of its generated proofs.
    shutil.copy(Path(bridge.__file__), tmp_path / "fact_reader.py")
    shutil.copy(Path(legacy.__file__), tmp_path / "pr80_fact_models.py")
    document = cumulative_document() if cumulative else contribution_document()
    raw = json.dumps(document, ensure_ascii=False).encode()
    target = tmp_path / "snapshot.json"
    target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest() if valid_identity else "0" * 64
    child = subprocess.run(
        [
            sys.executable,
            "fact_reader.py",
            "--legacy-module",
            "pr80_fact_models",
            "--fact-file",
            "snapshot.json",
            "--expected-sha256",
            digest,
            "--expected-size",
            str(len(raw)),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
        env={"PATH": str(Path(sys.executable).parent)},
    )
    assert child.returncode == (0 if valid_identity else 1), child.stderr
    result = json.loads(child.stdout)
    assert result["readCompatible"] is valid_identity
    assert result["rollbackReady"] is False
    if valid_identity:
        assert result["semanticStatus"] == "unknown"
        assert result["workflowResumeSupported"] is False
        assert ("cumulative_snapshot_policy" in result["requiredFeatures"]) is cumulative
    assert "科室" not in child.stdout and "北院" not in child.stdout
    assert target.read_bytes() == raw


@pytest.mark.parametrize("target", ["total", "group", "correlation"])
def test_string_nan_coercion_in_old_float_fields_is_not_accepted(target):
    doc = contribution_document()
    if target == "total":
        doc["metrics"][0]["total"] = "NaN"
    elif target == "group":
        doc["metrics"][0]["groupPopulation"][0]["value"] = "Infinity"
    else:
        doc["correlations"] = {"invalid": "NaN"}
    with pytest.raises(ValueError, match="snapshot_nonfinite_model_number"):
        read(doc)


def test_future_old_model_shape_is_not_silently_treated_as_pr80():
    from pydantic import create_model

    changed = create_model(
        "DifferentBundle", __base__=legacy.DeterministicAnalysisBundle, future_proof=(bool, False)
    )
    with pytest.raises(ValueError, match="unsupported_legacy_bundle_model"):
        compatible_pr80_models(legacy.DeterministicMetricFact, changed)


def test_known_optional_additions_preserve_the_same_schema_contract_as_the_current_metric():
    # Compare field constraints, aliases and nullability without comparing the
    # generated class title. New identity fields cannot be loosened by the bridge.
    adapted = models().metric.model_json_schema()
    current = DeterministicMetricFact.model_json_schema()
    for key in ("seriesMissingCount", "groupPopulation", "periodAggregation"):
        assert adapted["properties"][key] == current["properties"][key]
    old_policy = adapted["$defs"]["_CumulativeSnapshotPolicy"]
    current_policy = current["$defs"]["CumulativeSnapshotPolicy"]
    for key in ("properties", "required", "additionalProperties"):
        assert old_policy[key] == current_policy[key]


def test_compatible_read_does_not_erase_evidence_required_by_the_current_engine():
    from .test_group_contribution_assertions import compile_contribution

    document = contribution_document()
    before, _, _ = compile_contribution(document)
    after, _, _ = compile_contribution(read(document).document)
    assert before.status == "supported"
    assert after.model_dump() == before.model_dump()


def test_current_engine_does_not_infer_new_semantics_after_compatible_legacy_read():
    from .test_group_contribution_assertions import compile_contribution

    document = contribution_document()
    for metric in document["metrics"]:
        metric.pop("seriesMissingCount")
        metric.pop("groupPopulation")
        metric["periodAggregation"] = None
    result, _, _ = compile_contribution(read(document).document)
    assert result.status == "unknown" and result.value is None
