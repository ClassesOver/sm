"""B4 计算记录服务测试（未决#8 + 依赖展开 + 循环检测）。"""

from __future__ import annotations

import sys

import pytest

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.computation_service import (
    build_standard_supplemental_computation_record,
    build_supplemental_computation_record,
    detect_computation_cycles,
    expand_computation_chain,
)
from smart_reporting.reporting.trace.contracts_v1 import FactRefV1, derive_resource_id

SCRIPT = {"path": "报表/智能分析/run1/evidence/analysis_001/attempt-1/supplement.py", "size": 10, "sha256": "a" * 64}
EVIDENCE = {"path": "报表/智能分析/run1/evidence/analysis_001/attempt-1/supplement.json", "size": 20, "sha256": "b" * 64}


def test_standard_record_has_no_script_and_keeps_input_output_identity() -> None:
    record = build_standard_supplemental_computation_record(
        analysis_id="analysis_001",
        dataset_ids=("dataset-url-abc0001",),
        input_files=(
            {"path": "data/income.csv", "size": 30, "sha256": "c" * 64},
        ),
        evidence_file=EVIDENCE,
        method="group_summary",
        method_version="standard-supplemental-v1",
        parameters={"outputName": "income_by_unit"},
        execution_id="execution-1",
        finding_count=1,
    )

    assert record.script_file_resource_id is None
    assert record.method == "group_summary"
    assert record.method_version == "standard-supplemental-v1"
    assert record.parameters["inputFiles"][0]["sha256"] == "c" * 64
    assert record.output_fact_refs[0].file_resource_id == derive_resource_id(EVIDENCE["path"])


def _record(analysis_id="analysis_001", finding_count=3, **overrides):
    params = dict(
        analysis_id=analysis_id,
        dataset_ids=("dataset-url-abc0001",),
        script_file=SCRIPT,
        evidence_file=EVIDENCE,
        execution={
            "runId": "exec-1",
            "environment": {"python": "3.12.0", "polars": "1.43.2"},
        },
        finding_count=finding_count,
    )
    params.update(overrides)
    return build_supplemental_computation_record(**params)


# ---------------------------------------------------------------------------
# ExecutionReceipt environment（未决#8）
# ---------------------------------------------------------------------------


def test_execution_receipt_carries_environment_snapshot() -> None:
    receipt = ExecutionReceipt(
        runId="r1",
        sourceFile={"path": "x.py", "size": 1, "sha256": "0" * 64},
        outputFiles=(),
        environment={"python": "3.12.0", "polars": "1.43.2"},
    )
    assert receipt.environment["python"] == "3.12.0"
    # 旧回执兼容：environment 缺省为 None。
    legacy = ExecutionReceipt(
        runId="r2",
        sourceFile={"path": "x.py", "size": 1, "sha256": "0" * 64},
        outputFiles=(),
    )
    assert legacy.environment is None


def test_environment_snapshot_helper_is_importable_and_tolerant() -> None:
    from smart_reporting.reporting.code_agent.toolkit import (
        _execution_environment_snapshot,
    )

    snapshot = _execution_environment_snapshot()
    assert "python" in snapshot and "platform" in snapshot
    assert all(isinstance(value, str) for value in snapshot.values())


# ---------------------------------------------------------------------------
# ComputationRecordV1 构造
# ---------------------------------------------------------------------------


def test_supplemental_record_outputs_and_reproducibility() -> None:
    record = _record()
    assert record.method == "supplemental_analysis"
    assert record.computation_id.startswith("comp-")
    assert record.script_file_resource_id is not None
    assert record.execution_id == "exec-1"
    assert record.reproducibility == "reproducible"
    assert record.verification == "not_checked"  # 运行成功≠数值复核通过
    assert len(record.output_fact_refs) == 3
    assert all(ref.fact_kind == "supplemental_finding" for ref in record.output_fact_refs)
    assert record.output_fact_refs[0].json_pointer == "/findings/rows/0"
    assert record.input_dataset_ids == ("dataset-url-abc0001",)


def test_supplemental_record_limited_without_environment() -> None:
    record = _record(execution={"runId": "exec-2"})
    assert record.reproducibility == "limited"  # 未决#8：无环境指纹不得声称可复算
    assert record.environment is None


def test_supplemental_record_empty_findings_anchors_to_findings_array() -> None:
    record = _record(finding_count=0)
    assert len(record.output_fact_refs) == 1
    assert record.output_fact_refs[0].json_pointer == "/findings"


# ---------------------------------------------------------------------------
# 依赖展开与循环检测
# ---------------------------------------------------------------------------


def _chain_records() -> tuple:
    """analysis_003 ← analysis_002 ← analysis_001 的三层链。"""

    base = _record(analysis_id="analysis_001", finding_count=1)
    base_input = FactRefV1(
        analysisId="analysis_001",
        fileResourceId=base.output_fact_refs[0].file_resource_id,
        jsonPointer="/findings/rows/0",
        factKind="supplemental_finding",
    )
    mid_input = FactRefV1(
        analysisId="analysis_002",
        fileResourceId=base.output_fact_refs[0].file_resource_id,
        jsonPointer="/findings/rows/0",
        factKind="supplemental_finding",
    )
    mid = build_supplemental_computation_record(
        analysis_id="analysis_002",
        dataset_ids=("dataset-url-abc0001",),
        script_file=SCRIPT,
        evidence_file=EVIDENCE,
        execution={"runId": "comp-mid", "environment": {"python": "3.12"}},
        finding_count=1,
        input_fact_refs=(base_input,),
    )
    top = build_supplemental_computation_record(
        analysis_id="analysis_003",
        dataset_ids=("dataset-url-abc0001",),
        script_file=SCRIPT,
        evidence_file=EVIDENCE,
        execution={"runId": "comp-top", "environment": {"python": "3.12"}},
        finding_count=1,
        input_fact_refs=(mid_input,),
    )
    return base, mid, top


def test_expand_computation_chain_follows_inputs() -> None:
    base, mid, top = _chain_records()
    tree = expand_computation_chain((base, mid, top), top.computation_id, depth=3)
    assert tree["computationId"] == top.computation_id
    assert tree["inputs"][0]["computationId"] == mid.computation_id
    assert tree["inputs"][0]["inputs"][0]["computationId"] == base.computation_id
    # 深度截断：depth=1 不展开输入。
    shallow = expand_computation_chain((base, mid, top), top.computation_id, depth=1)
    assert "inputs" not in shallow


def test_expand_rejects_unknown_entry_and_bad_depth() -> None:
    base, mid, top = _chain_records()
    with pytest.raises(ReportingError, match="不存在"):
        expand_computation_chain((base, mid, top), "comp-" + "f" * 16)
    with pytest.raises(ReportingError, match="展开深度"):
        expand_computation_chain((base, mid, top), top.computation_id, depth=99)


@pytest.mark.parametrize("identity_field", ["json_pointer", "file_resource_id", "fact_kind"])
@pytest.mark.parametrize("reverse", [False, True])
def test_chain_matches_exact_fact_identity(identity_field, reverse) -> None:
    first = _record(finding_count=1)
    ref = first.output_fact_refs[0]
    alternatives = {
        "json_pointer": "/findings/rows/1",
        "file_resource_id": "trf-" + "c" * 20,
        "fact_kind": "correlation",
    }
    target_ref = ref.model_copy(update={identity_field: alternatives[identity_field]})
    second = _record(execution={"runId": "second"}).model_copy(
        update={"output_fact_refs": (target_ref,)}
    )
    consumer = _record(
        analysis_id="analysis_002", execution={"runId": "consumer"},
        input_fact_refs=(target_ref,),
    )
    records = (second, first, consumer) if reverse else (first, second, consumer)
    tree = expand_computation_chain(records, consumer.computation_id)
    assert [node["computationId"] for node in tree["inputs"]] == [second.computation_id]
    # 同分析的另一个事实依赖消费者，不应凭分析 ID 误报环。
    first = first.model_copy(update={"input_fact_refs": consumer.output_fact_refs})
    assert detect_computation_cycles((first, second, consumer)) == []


def test_chain_does_not_link_unproduced_fact() -> None:
    provider = _record(finding_count=1)
    missing = provider.output_fact_refs[0].model_copy(
        update={"json_pointer": "/findings/rows/99"}
    )
    consumer = _record(analysis_id="analysis_002", input_fact_refs=(missing,))
    tree = expand_computation_chain((provider, consumer), consumer.computation_id)
    assert "inputs" not in tree


@pytest.mark.parametrize("reverse", [False, True])
def test_chain_warns_and_skips_ambiguous_providers_but_keeps_unique_inputs(reverse):
    first = _record(finding_count=1)
    duplicate = _record(finding_count=1, execution={"runId": "duplicate"})
    unique = _record(analysis_id="analysis_003", finding_count=1)
    consumer = _record(
        analysis_id="analysis_002",
        input_fact_refs=(*first.output_fact_refs, *unique.output_fact_refs),
    )
    # 其中一个候选依赖消费者，歧义边不能被当成确定的循环。
    first = first.model_copy(update={"input_fact_refs": consumer.output_fact_refs})
    records = (first, duplicate, unique, consumer)
    if reverse:
        records = tuple(reversed(records))
    tree = expand_computation_chain(records, consumer.computation_id)
    assert [node["computationId"] for node in tree["inputs"]] == [unique.computation_id]
    assert any("来源不唯一" in warning for warning in tree["warnings"])
    assert detect_computation_cycles(records) == []


def test_repeated_output_in_one_record_does_not_create_ambiguity():
    provider = _record(finding_count=1)
    provider = provider.model_copy(update={"output_fact_refs": provider.output_fact_refs * 2})
    consumer = _record(analysis_id="analysis_002", input_fact_refs=provider.output_fact_refs)
    tree = expand_computation_chain((provider, consumer), consumer.computation_id)
    assert [node["computationId"] for node in tree["inputs"]] == [provider.computation_id]
    assert not tree.get("warnings")


@pytest.mark.parametrize(("provider_key", "input_key", "matches"), [
    (None, None, True),
    (None, "fact-a", True),
    ("fact-a", None, True),
    ("fact-a", "fact-a", True),
    ("fact-a", "fact-b", False),
])
def test_chain_checks_known_fact_keys_and_preserves_keyless_records(provider_key, input_key, matches):
    provider = _record(finding_count=1)
    output = provider.output_fact_refs[0].model_copy(update={"fact_key": provider_key})
    provider = provider.model_copy(update={"output_fact_refs": (output,)})
    consumer = _record(
        analysis_id="analysis_002", input_fact_refs=(output.model_copy(update={"fact_key": input_key}),),
    )
    provider = provider.model_copy(update={"input_fact_refs": consumer.output_fact_refs})
    tree = expand_computation_chain((provider, consumer), consumer.computation_id)
    assert bool(tree.get("inputs")) == matches
    if not matches:
        assert any("核对键" in warning for warning in tree["warnings"])
    assert bool(detect_computation_cycles((provider, consumer))) == matches


@pytest.mark.parametrize("reverse", [False, True])
def test_matching_fact_key_disambiguates_conflicting_output_keys(reverse):
    first = _record(finding_count=1)
    first = first.model_copy(update={"output_fact_refs": (
        first.output_fact_refs[0].model_copy(update={"fact_key": "fact-a"}),
    )})
    second = _record(finding_count=1, execution={"runId": "other-key"})
    second = second.model_copy(update={"output_fact_refs": (
        second.output_fact_refs[0].model_copy(update={"fact_key": "fact-b"}),
    )})
    consumer = _record(analysis_id="analysis_002", input_fact_refs=second.output_fact_refs)
    records = (second, first, consumer) if reverse else (first, second, consumer)
    tree = expand_computation_chain(records, consumer.computation_id)
    assert [node["computationId"] for node in tree["inputs"]] == [second.computation_id]


def test_cycle_detection_does_not_enumerate_paths_in_a_shared_dag():
    from smart_reporting.reporting.trace import computation_service

    records = []
    previous = ()
    for level in range(24):
        layer = tuple(_record(
            analysis_id=f"analysis_{level * 2 + side + 1:03}", finding_count=1,
            input_fact_refs=previous,
        ) for side in range(2))
        records.extend(layer)
        previous = tuple(ref for record in layer for ref in record.output_fact_refs)

    # 固定工作量预算避免依赖 CI 墙钟速度：48 个合法节点不应触发十万次服务函数调用。
    calls = 0

    def bounded_work(frame, event, _arg):
        nonlocal calls
        if event == "call" and frame.f_code.co_filename == computation_service.__file__:
            calls += 1
            assert calls < 100_000, "合法无环依赖图被按共享路径反复遍历"

    previous_profile = sys.getprofile()
    try:
        sys.setprofile(bounded_work)
        assert detect_computation_cycles(tuple(records)) == []
    finally:
        sys.setprofile(previous_profile)


def test_self_cycle_is_detected_and_chain_stops() -> None:
    record = _record(finding_count=1)
    record = record.model_copy(update={"input_fact_refs": record.output_fact_refs})
    assert detect_computation_cycles((record,)) == [[record.computation_id]]
    tree = expand_computation_chain((record,), record.computation_id, depth=3)
    assert "inputs" not in tree


def test_chain_stops_at_two_record_cycle() -> None:
    first = _record(finding_count=1)
    second = _record(analysis_id="analysis_002", input_fact_refs=first.output_fact_refs)
    first = first.model_copy(update={"input_fact_refs": second.output_fact_refs})
    assert len(detect_computation_cycles((first, second))) == 1
    tree = expand_computation_chain((first, second), first.computation_id, depth=3)
    child = tree["inputs"][0]
    assert child["computationId"] == second.computation_id
    assert "inputs" not in child


def test_detect_computation_cycles_finds_loop() -> None:
    base, mid, top = _chain_records()
    assert detect_computation_cycles((base, mid, top)) == []
    # 制造环：base 的输入指向 analysis_002（mid 的输出）。
    looping_base = build_supplemental_computation_record(
        analysis_id="analysis_001",
        dataset_ids=("dataset-url-abc0001",),
        script_file=SCRIPT,
        evidence_file=EVIDENCE,
        execution={"runId": "loop", "environment": {"python": "3.12"}},
        finding_count=1,
        input_fact_refs=(
            FactRefV1(
                analysisId="analysis_002",
                fileResourceId=mid.output_fact_refs[0].file_resource_id,
                jsonPointer="/findings/rows/0",
                factKind="supplemental_finding",
            ),
        ),
    )
    cycles = detect_computation_cycles((looping_base, mid, top))
    assert cycles, "应检测到 analysis_001 ↔ analysis_002 依赖环"


# ---------------------------------------------------------------------------
# 链路接入：complete 工具构造 + finalize 提取入索引
# ---------------------------------------------------------------------------


def test_complete_tool_builds_computation_record_from_receipt() -> None:
    """_build_computation_record：有补充 evidence + 执行回执时构造记录。"""

    from types import SimpleNamespace

    from smart_reporting.reporting.code_agent.context import ExecutionReceipt
    from smart_reporting.reporting.tools.analysis_item import RuntimeAnalysisMixin

    receipt = ExecutionReceipt(
        runId="exec-9",
        sourceFile={"path": SCRIPT["path"], "size": 10, "sha256": "a" * 64},
        outputFiles=({"path": EVIDENCE["path"], "size": 20, "sha256": "b" * 64},),
        environment={"python": "3.12.0"},
    )
    binding = SimpleNamespace(execution_receipt=receipt)
    run_context = SimpleNamespace(dependencies={"AgentOS 任务执行": binding})
    identities = [dict(EVIDENCE)]
    record = RuntimeAnalysisMixin._build_computation_record(
        RuntimeAnalysisMixin.__new__(RuntimeAnalysisMixin),
        analysis_id="analysis_001",
        dataset_ids=["dataset-url-abc0001"],
        identities=identities,
        deterministic_paths=set(),  # 该 evidence 不在确定性事实路径内
        run_context=run_context,
        requirements={"codingRequirements": [{"datasetId": "d", "calculation": "分解"}]},
    )
    assert record is not None
    assert record["computationId"].startswith("comp-")
    assert record["executionId"] == "exec-9"
    assert record["environment"]["python"] == "3.12.0"
    assert record["reproducibility"] == "reproducible"
    assert record["parameters"]["requirements"][0]["calculation"] == "分解"
    # 单层补充分析无输入依赖；inputFactRefs 为空。
    assert record["inputFactRefs"] == []


def test_complete_tool_skips_without_receipt_or_supplement() -> None:
    from types import SimpleNamespace

    from smart_reporting.reporting.tools.analysis_item import RuntimeAnalysisMixin

    tools = RuntimeAnalysisMixin.__new__(RuntimeAnalysisMixin)
    # 无执行回执（依赖缺失）→ None，不伪造。
    assert (
        tools._build_computation_record(
            analysis_id="analysis_001",
            dataset_ids=["d"],
            identities=[dict(EVIDENCE)],
            deterministic_paths=set(),
            run_context=SimpleNamespace(dependencies={}),
            requirements={},
        )
        is None
    )
    # 回执不可用 + evidence 全部是确定性事实路径 → None。
    assert (
        tools._build_computation_record(
            analysis_id="analysis_001",
            dataset_ids=["d"],
            identities=[dict(EVIDENCE)],
            deterministic_paths={EVIDENCE["path"]},
            run_context=SimpleNamespace(dependencies={}),
            requirements={},
        )
        is None
    )


def test_finalize_extracts_computation_records_into_index() -> None:
    """索引登记计算记录：evidence/script 文件进 files、记录进 computations。"""

    from smart_reporting.reporting.trace.index_builder import build_csv_trace_index
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity

    from .test_trace_index_builder import MARKDOWN, _handle, _lineage

    record = _record(finding_count=2)
    index = build_csv_trace_index(
        handles=(_handle("dataset-url-abc0001"),),
        lineage=(_lineage("dataset-url-abc0001"),),
        report_id="run1",
        revision=1,
        workflow_run_id="run1",
        markdown_file=MARKDOWN,
        computation_files=(
            FileIdentity(path=SCRIPT["path"], size=10, sha256="a" * 64),
            FileIdentity(path=EVIDENCE["path"], size=20, sha256="b" * 64),
        ),
        computations=(record,),
    )
    assert index.computations[0].computation_id == record.computation_id
    paths = {item.path for item in index.files}
    assert SCRIPT["path"] in paths and EVIDENCE["path"] in paths
    # 补证 evidence 同时登记为 supplemental_evidence 事实条目。
    kinds = {entry.analysis_id: entry.content_kind for entry in index.fact_files}
    assert kinds.get("analysis_001") == "supplemental_evidence"


# ---------------------------------------------------------------------------
# correlations 元数据（B4-d）
# ---------------------------------------------------------------------------


def test_correlations_carry_metadata_and_fact_ids() -> None:
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        build_deterministic_analysis_bundle,
    )

    from .test_deterministic_analysis import analysis, context

    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits"), correlation=True),
        (
            (
                "current",
                b"month,department,amount,visits\n"
                b"2025-01,A,100,10\n2025-01,B,200,20\n2025-01,C,300,31\n",
                context(
                    "current",
                    fields=("month", "department", "amount", "visits"),
                    semantics=(
                        {
                            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.amount",
                            "aggregation": "sum",
                            "additiveAcross": ["month", "department"],
                            "exclusiveScope": {},
                            "unit": "元",
                        },
                        {
                            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.visits",
                            "aggregation": "sum",
                            "additiveAcross": ["month", "department"],
                            "exclusiveScope": {},
                            "unit": "人次",
                        },
                    ),
                ),
                ("current",),
            ),
        ),
        profile_metrics=(
            {
                "code": "income_total",
                "fieldRef": "dynamic_source.dynamic_db.dynamic_table.amount",
            },
            {
                "code": "visits_total",
                "fieldRef": "dynamic_source.dynamic_db.dynamic_table.visits",
            },
        ),
        profile_hash="c" * 64,
    )
    assert bundle.correlation_details, "两个数值字段应产生相关性元数据"
    detail = bundle.correlation_details[0]
    assert detail.method == "pearson"
    assert detail.sample_count == 3  # 样本量进入元数据
    assert detail.dataset_sha256 == "b" * 64
    assert {detail.left_field, detail.right_field} == {"amount", "visits"}
    assert detail.fact_id and detail.fact_id.startswith("fact-")
    # 旧键值投影保留（模型兼容）。
    assert len(bundle.correlations) == len(bundle.correlation_details)
    # factId → 指针可定位。
    from smart_reporting.reporting.trace.fact_index import fact_pointer

    assert fact_pointer(bundle, detail.fact_id) == "/correlationDetails/0"
