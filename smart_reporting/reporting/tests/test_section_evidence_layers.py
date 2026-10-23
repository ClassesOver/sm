"""补证文件身份进索引的登记契约：无计算记录也不得丢失 evidence 树。"""

from __future__ import annotations

from pathlib import Path

from smart_reporting.reporting.trace.contracts_v1 import (
    ComputationRecordV1,
    FactRefV1,
    derive_resource_id,
)
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    FileIdentity,
)
from smart_reporting.reporting.workflow.runtime.sections import (
    _evidence_and_computation_layers,
)


def _identity(path: str) -> FileIdentity:
    return FileIdentity(path=path, size=10, sha256="0" * 64)


def _record(record_id: str, inputs: tuple[str, ...], outputs: tuple[str, ...]):
    return ComputationRecordV1(
        computationId=record_id,
        method="contribution_decomposition",
        inputDatasetIds=("dataset-url-abc",),
        inputFactRefs=tuple(
            FactRefV1(
                analysisId=a,
                fileResourceId=derive_resource_id("facts.json"),
                jsonPointer="/derivedMetrics/0",
                factKind="derived",
            )
            for a in inputs
        ),
        outputFactRefs=tuple(
            FactRefV1(
                analysisId=a,
                fileResourceId=derive_resource_id("facts.json"),
                jsonPointer="/derivedMetrics/0",
                factKind="derived",
            )
            for a in outputs
        ),
    )


def _manifest(*items: AnalysisEvidence) -> AnalysisEvidenceManifest:
    from smart_reporting.reporting.workflow.checkpoint import AnalysisDatasetSemantics

    return AnalysisEvidenceManifest(
        evidence=tuple(items),
        datasetSemantics=(
            AnalysisDatasetSemantics(
                datasetId="dataset-1", rowGrain="record", duplicateResolution="not_applicable",
            ),
        ),
    )


def _evidence(
    analysis_id: str,
    record: dict | None,
    script: FileIdentity | None,
) -> AnalysisEvidence:
    return AnalysisEvidence(
        analysisId=analysis_id,
        summary="冻结证据",
        datasetIds=("dataset-1",),
        evidenceFiles=(
            _identity(f"run/evidence/{analysis_id}/attempt-1/supplement.json"),
        ),
        citationIds=("c1",),
        chartIds=(),
        computationRecord=record,
        computationScriptFile=script,
    )


def test_none_manifest_registers_nothing() -> None:
    assert _evidence_and_computation_layers(None) == ((), ())


def test_evidence_files_registered_without_computation_record() -> None:
    manifest = _manifest(_evidence("analysis_001", None, None))

    records, files = _evidence_and_computation_layers(manifest)

    assert records == ()
    assert [item.path for item in files] == [
        "run/evidence/analysis_001/attempt-1/supplement.json",
    ]


def test_invalid_computation_record_keeps_evidence_files_and_drops_script() -> None:
    manifest = _manifest(
        _evidence("analysis_001", {"computationId": "not-a-record"}, _identity("run/e.py")),
    )

    records, files = _evidence_and_computation_layers(manifest)

    assert records == ()
    assert [item.path for item in files] == [
        "run/evidence/analysis_001/attempt-1/supplement.json",
    ]


def test_valid_record_registers_script_then_evidence_files() -> None:
    record = _record("comp-" + "0" * 16, ("analysis_001",), ("analysis_002",))
    manifest = _manifest(
        _evidence(
            "analysis_001",
            record.model_dump(mode="json", by_alias=True),
            _identity("run/e.py"),
        ),
    )

    records, files = _evidence_and_computation_layers(manifest)

    assert [item.computation_id for item in records] == [record.computation_id]
    assert [item.path for item in files] == ["run/e.py", "run/evidence/analysis_001/attempt-1/supplement.json"]


def test_computation_cycle_drops_records_but_keeps_evidence_files() -> None:
    first = _record("comp-" + "0" * 15 + "1", ("analysis_002",), ("analysis_001",))
    second = _record("comp-" + "0" * 15 + "2", ("analysis_001",), ("analysis_002",))
    manifest = _manifest(
        _evidence(
            "analysis_001",
            first.model_dump(mode="json", by_alias=True),
            _identity("run/a.py"),
        ),
        _evidence("analysis_002", second.model_dump(mode="json", by_alias=True), None),
    )

    records, files = _evidence_and_computation_layers(manifest)

    assert records == ()
    assert [item.path for item in files] == [
        "run/evidence/analysis_001/attempt-1/supplement.json",
        "run/evidence/analysis_002/attempt-1/supplement.json",
    ]


def test_real_revision_bundle_shape_registers_supplement(tmp_path: Path) -> None:
    """真实回放发现的缺口回归：仅 facts/图表输入进索引时，补证必须仍然登记。"""

    manifest = _manifest(_evidence("analysis_001", None, None))
    records, files = _evidence_and_computation_layers(manifest)
    assert records == () and len(files) == 1
    assert files[0].path.endswith("/supplement.json")


def test_trace_index_falls_back_when_only_evidence_files_break_the_contract() -> None:
    # 审阅：补证文件在没有有效计算记录时也登记；只在有计算记录时回退，会让补证文件的
    # 问题拖垮整份溯源索引与产物清单。
    import pytest

    from smart_reporting.reporting.workflow.runtime.publication import (
        build_with_optional_computation_layer,
    )

    calls = []

    def build(files, computations):
        calls.append((files, computations))
        if files:
            raise ValueError("evidence registration rejected")
        return "index"

    evidence = (_identity("analysis/evidence.json"),)
    assert build_with_optional_computation_layer(build, evidence, ()) == "index"
    assert calls == [(evidence, ()), ((), ())]
    with pytest.raises(ValueError):
        build_with_optional_computation_layer(lambda *_: (_ for _ in ()).throw(ValueError("x")), (), ())


def test_trace_index_keeps_evidence_files_when_only_computation_records_are_rejected() -> None:
    # 回放：计算记录不被契约接受时整层回退，导出的修订包缺少图表输入声明来源的 evidence 文件。
    from smart_reporting.reporting.workflow.runtime.publication import (
        build_with_optional_computation_layer,
    )

    calls = []

    def build(files, computations):
        calls.append((files, computations))
        if computations:
            raise ValueError("computation record rejected")
        return files

    evidence = (_identity("analysis/evidence.json"),)
    assert build_with_optional_computation_layer(build, evidence, ("record",)) == evidence
    assert calls == [(evidence, ("record",)), (evidence, ())]
