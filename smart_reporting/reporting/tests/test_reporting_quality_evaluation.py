"""Synthetic evidence tests validate bookkeeping, never real report effectiveness."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.workflow.benchmark_bundle import BenchmarkFileIdentity
from smart_reporting.reporting.workflow.quality_evaluation import (
    StudyEvidence,
    StudyPlan,
    evaluate_study,
    main,
)


def _file(root, name, content):
    raw = content.encode() if isinstance(content, str) else json.dumps(content).encode()
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _evidence(root, *, complete=True, real=True, baseline_cost=2, candidate_cost=1,
              maximum_cost_ratio=1.2):
    tasks = []
    for i in range(42 if complete else 2):
        task = {
            "taskId": f"task-{i}",
            "partition": "pilot" if i < (12 if complete else 1) else "holdout",
            "sampleKind": "real" if real else "synthetic",
            "independenceGroup": f"family-{i}",
            "inputs": [_file(root, f"inputs/{i}.csv", f"metric,value\n{i},10\n")],
            "authorization": _file(root, f"authorizations/{i}.txt", f"TEST ONLY authorization {i}"),
            "requiredConditionIds": ["condition-1"],
        }
        tasks.append(task)
    plan = StudyPlan.model_validate(
        {
            "studyId": "test-study",
            "baseline": "old",
            "candidate": "new",
            "baselineConfiguration": _file(
                root, "config/baseline.json", {"commit": "baseline", "mode": "off"}
            ),
            "candidateConfiguration": _file(
                root, "config/candidate.json", {"commit": "candidate", "mode": "shadow"}
            ),
            "authorIds": ["author"],
            "domainReviewerIds": ["reviewer-1", "reviewer-2", "adjudicator"],
            "tasks": tasks,
            "thresholds": {
                "maximumUnsupportedRate": 0.05,
                "minimumAnswerCoverage": 0.9,
                "maximumCriticalErrors": 0,
                "maximumCostRatio": maximum_cost_ratio,
            },
        }
    )
    runs = []
    for task in tasks:
        task_id = task["taskId"]
        for variant in ("old", "new"):
            report = _file(
                root, f"reports/{task_id}-{variant}.md", f"TEST ONLY {task_id} {variant} claim1"
            )
            common = {"planSha256": plan.sha256, "reportSha256": report["sha256"], "taskId": task_id}
            metering = _file(
                root,
                f"metering/{task_id}-{variant}.json",
                {
                    **common,
                    "variant": variant,
                    "configurationSha256": (plan.baseline_configuration.sha256 if variant == "old"
                                            else plan.candidate_configuration.sha256),
                    "provenance": "provider_export",
                    "currency": "CNY",
                    "totalCost": baseline_cost if variant == "old" else candidate_cost,
                    "wallSeconds": 2,
                    "inputTokens": 10,
                    "outputTokens": 10,
                },
            )
            reviews = [
                _file(
                    root,
                    f"reviews/{task_id}-{variant}-{reviewer}.json",
                    {
                        **common,
                        "reviewerId": reviewer,
                        "role": "independent",
                        "blindReviewId": f"blind-{task_id}-{reviewer}-{variant}",
                        "claimInventoryComplete": True,
                        "blindedToVariant": True,
                        "unsupportedClaimIds": ["claim1"] if variant == "old" else [],
                        "answeredConditionIds": ["condition-1"],
                        "criticalErrorCount": 0,
                    },
                )
                for reviewer in ("reviewer-1", "reviewer-2")
            ]
            runs.append(
                {
                    "taskId": task_id,
                    "variant": variant,
                    "report": report,
                    "claimIds": ["claim1"],
                    "metering": metering,
                    "reviews": reviews,
                }
            )
    return StudyEvidence.model_validate({"plan": plan, "runs": runs})


def _mutate_file(root, identity, update):
    raw = json.loads((root / identity.path).read_bytes())
    raw.update(update)
    return BenchmarkFileIdentity.model_validate(_file(root, identity.path, raw))


def test_complete_paired_contract_reports_holdout_separately_without_authorizing_rollout(tmp_path):
    evidence = _evidence(tmp_path)
    report = evaluate_study(evidence, tmp_path)
    assert report["status"] == "evidence_evaluated"
    assert report["acceptanceMet"] is True
    assert report["rolloutAuthorized"] is False
    assert report["metrics"]["pilot"]["completePairs"] == 12
    assert report["metrics"]["holdout"]["completePairs"] == 30
    paired = report["metrics"]["holdout"]["pairedUnsupportedReduction"]
    assert paired["wins"] == 30 and paired["twoSidedSignP"] < 0.001
    assert report["costRatio"] == 0.5


def test_synthetic_or_small_study_cannot_establish_readiness(tmp_path):
    report = evaluate_study(_evidence(tmp_path, complete=False, real=False), tmp_path)
    assert report["status"] == "not_ready"
    assert report["acceptanceMet"] is None
    assert {issue["code"] for issue in report["issues"]} >= {
        "study_size_incomplete",
        "real_authorized_sample_missing",
        "independent_sample_size_incomplete",
    }


@pytest.mark.parametrize(
    "fault", ["family_leak", "input_leak", "duplicate_task", "author_review", "same_variant"]
)
def test_invalid_partition_or_reviewer_identity_rejected(tmp_path, fault):
    evidence = _evidence(tmp_path, complete=False)
    plan = evidence.plan.model_dump(mode="json", by_alias=True)
    if fault == "family_leak":
        plan["tasks"][1]["independenceGroup"] = plan["tasks"][0]["independenceGroup"]
    elif fault == "input_leak":
        plan["tasks"][1]["inputs"] = plan["tasks"][0]["inputs"]
    elif fault == "duplicate_task":
        plan["tasks"][1]["taskId"] = plan["tasks"][0]["taskId"]
    elif fault == "author_review":
        plan["domainReviewerIds"][0] = "author"
    else:
        plan["candidate"] = plan["baseline"]
    with pytest.raises(ValidationError):
        StudyPlan.model_validate(plan)


@pytest.mark.parametrize("partition", ["pilot", "holdout"])
def test_same_partition_cannot_count_duplicate_input_as_independent_tasks(tmp_path, partition):
    plan = _evidence(tmp_path, complete=False).plan.model_dump(mode="json", by_alias=True)
    for task in plan["tasks"]:
        task["partition"] = partition
    duplicate = dict(plan["tasks"][0]["inputs"][0])
    duplicate["path"] = "inputs/same-content-different-path.csv"
    plan["tasks"][1]["inputs"] = [duplicate]
    assert plan["tasks"][0]["independenceGroup"] != plan["tasks"][1]["independenceGroup"]
    with pytest.raises(ValidationError, match="不同评估任务不可复用相同输入内容"):
        StudyPlan.model_validate(plan)


@pytest.mark.parametrize("different_path", [False, True])
def test_variant_labels_cannot_disguise_identical_configuration_bytes(tmp_path, different_path):
    plan = _evidence(tmp_path, complete=False).plan.model_dump(mode="json", by_alias=True)
    plan["candidateConfiguration"] = dict(plan["baselineConfiguration"])
    if different_path:
        plan["candidateConfiguration"]["path"] = "config/renamed-baseline.json"
    with pytest.raises(ValidationError, match="基线与候选配置内容必须不同"):
        StudyPlan.model_validate(plan)


@pytest.mark.parametrize(
    "fault",
    [
        "no_runs",
        "missing_report",
        "changed_sample",
        "one_review",
        "same_reviewer",
        "incomplete_inventory",
        "wrong_plan",
        "wrong_report",
        "unknown_claim",
        "unknown_condition",
        "disagreement",
        "synthetic_cost",
        "currency",
        "zero_cost",
    ],
)
def test_incomplete_or_unbound_evidence_never_passes(tmp_path, fault):
    evidence = _evidence(tmp_path)
    run = evidence.runs[-1]
    if fault == "no_runs":
        evidence = evidence.model_copy(update={"runs": ()})
    elif fault == "missing_report":
        (tmp_path / run.report.path).unlink()
    elif fault == "changed_sample":
        (tmp_path / evidence.plan.tasks[-1].inputs[0].path).write_text("changed")
    elif fault == "one_review":
        run = run.model_copy(update={"reviews": run.reviews[:1]})
    elif fault == "same_reviewer":
        review = _mutate_file(tmp_path, run.reviews[1], {"reviewerId": "reviewer-1"})
        run = run.model_copy(update={"reviews": (run.reviews[0], review)})
    elif fault in {
        "incomplete_inventory",
        "wrong_plan",
        "wrong_report",
        "unknown_claim",
        "unknown_condition",
        "disagreement",
    }:
        updates = {
            "incomplete_inventory": {"claimInventoryComplete": False},
            "wrong_plan": {"planSha256": "a" * 64},
            "wrong_report": {"reportSha256": "a" * 64},
            "unknown_claim": {"unsupportedClaimIds": ["invented"]},
            "unknown_condition": {"answeredConditionIds": ["invented"]},
            "disagreement": {"unsupportedClaimIds": ["claim1"]},
        }[fault]
        review = _mutate_file(tmp_path, run.reviews[0], updates)
        run = run.model_copy(update={"reviews": (review, run.reviews[1])})
    else:
        if fault == "zero_cost":
            # All baseline measurements must be zero for the denominator to be unavailable.
            runs = tuple(
                item.model_copy(
                    update={"metering": _mutate_file(tmp_path, item.metering, {"totalCost": 0})}
                )
                if item.variant == "old"
                else item
                for item in evidence.runs
            )
            evidence = evidence.model_copy(update={"runs": runs})
        else:
            update = (
                {"provenance": "synthetic"} if fault == "synthetic_cost" else {"currency": "USD"}
            )
            run = run.model_copy(update={"metering": _mutate_file(tmp_path, run.metering, update)})
    if fault not in {"no_runs", "zero_cost"}:
        evidence = evidence.model_copy(update={"runs": (*evidence.runs[:-1], run)})
    result = evaluate_study(evidence, tmp_path)
    assert result["status"] == "not_ready"
    assert result["acceptanceMet"] is None
    assert result["issues"]


def test_acceptable_counts_do_not_hide_threshold_failure(tmp_path):
    evidence = _evidence(tmp_path)
    runs = []
    for run in evidence.runs:
        if run.variant == "new":
            reviews = tuple(
                _mutate_file(tmp_path, file, {"unsupportedClaimIds": ["claim1"]})
                for file in run.reviews
            )
            run = run.model_copy(update={"reviews": reviews})
        runs.append(run)
    report = evaluate_study(evidence.model_copy(update={"runs": tuple(runs)}), tmp_path)
    assert report["status"] == "evidence_evaluated"
    assert report["acceptanceMet"] is False


def test_cli_writes_unknown_when_no_real_execution_evidence_exists(tmp_path):
    evidence = _evidence(tmp_path, complete=False, real=False)
    study = tmp_path / "study.json"
    study.write_text(evidence.model_dump_json(by_alias=True))
    output = tmp_path / "output.json"
    assert main(["evaluate", str(study), "--output", str(output)]) == 2
    assert json.loads(output.read_bytes())["acceptanceMet"] is None


def test_input_evidence_cannot_escape_study_via_parent_symlink(tmp_path):
    from smart_reporting.reporting.workflow.quality_evaluation import _read

    outside = tmp_path / "outside"
    outside.mkdir()
    identity = BenchmarkFileIdentity.model_validate(_file(outside, "secret", "private"))
    root = tmp_path / "study"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="越界"):
        _read(root, identity.model_copy(update={"path": "link/secret"}))


def test_disagreement_requires_a_third_reviewer_bound_to_the_same_report(tmp_path):
    evidence = _evidence(tmp_path)
    run = evidence.runs[-1]
    disagreement = _mutate_file(tmp_path, run.reviews[0], {"unsupportedClaimIds": ["claim1"]})
    payload = json.loads((tmp_path / run.reviews[1].path).read_bytes())
    payload.update(reviewerId="adjudicator", role="adjudicator", blindReviewId="adjudication-1")
    adjudication = BenchmarkFileIdentity.model_validate(
        _file(tmp_path, "adjudication.json", payload)
    )
    run = run.model_copy(
        update={"reviews": (disagreement, run.reviews[1]), "adjudication": adjudication}
    )
    evidence = evidence.model_copy(update={"runs": (*evidence.runs[:-1], run)})
    assert evaluate_study(evidence, tmp_path)["acceptanceMet"] is True
    bad = _mutate_file(tmp_path, adjudication, {"reviewerId": "reviewer-1"})
    evidence = evidence.model_copy(
        update={"runs": (*evidence.runs[:-1], run.model_copy(update={"adjudication": bad}))}
    )
    assert evaluate_study(evidence, tmp_path)["acceptanceMet"] is None


def test_unblinded_review_or_changed_configuration_stays_unknown(tmp_path):
    evidence = _evidence(tmp_path)
    run = evidence.runs[-1]
    review = _mutate_file(tmp_path, run.reviews[0], {"blindedToVariant": False})
    run = run.model_copy(update={"reviews": (review, run.reviews[1])})
    report = evaluate_study(
        evidence.model_copy(update={"runs": (*evidence.runs[:-1], run)}), tmp_path
    )
    assert report["acceptanceMet"] is None
    (tmp_path / evidence.plan.candidate_configuration.path).write_text("changed configuration")
    report = evaluate_study(evidence, tmp_path, validate_only=True)
    assert any(issue["code"] == "variant_configuration_unavailable" for issue in report["issues"])


def test_thirty_tasks_from_one_family_are_not_thirty_independent_holdout_samples(tmp_path):
    evidence = _evidence(tmp_path)
    tasks = tuple(
        task.model_copy(update={"independence_group": "one-family"})
        if task.partition == "holdout"
        else task
        for task in evidence.plan.tasks
    )
    plan = evidence.plan.model_copy(update={"tasks": tasks})
    report = evaluate_study(
        evidence.model_copy(update={"plan": plan}), tmp_path, validate_only=True
    )
    assert any(issue["code"] == "independent_sample_size_incomplete" for issue in report["issues"])


def test_cli_cannot_overwrite_frozen_input_with_its_summary(tmp_path):
    evidence = _evidence(tmp_path, complete=False, real=False)
    study = tmp_path / "study.json"
    original = evidence.model_dump_json(by_alias=True)
    study.write_text(original)
    with pytest.raises(SystemExit):
        main(["evaluate", str(study), "--output", str(study)])
    assert study.read_text() == original


def test_large_finite_costs_cannot_overflow_mean_and_false_pass_ratio(tmp_path):
    evidence = _evidence(tmp_path, baseline_cost=1e308, candidate_cost=1e306,
                         maximum_cost_ratio=0.001)
    report = evaluate_study(evidence, tmp_path)
    assert report["status"] == "evidence_evaluated"
    assert report["costRatio"] == pytest.approx(0.01)
    assert report["acceptanceMet"] is False
    assert report["metrics"]["holdout"]["variants"]["old"]["cost"] == 1e308
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("replay", ["other_task", "other_variant"])
def test_valid_records_cannot_be_replayed_as_another_task_or_variant(tmp_path, replay):
    evidence = _evidence(tmp_path)
    runs = list(evidence.runs)
    if replay == "other_task":
        runs[-1] = runs[-3].model_copy(update={"task_id": runs[-1].task_id})
    else:
        runs[-2] = runs[-1].model_copy(update={"variant": "old"})
    result = evaluate_study(evidence.model_copy(update={"runs": tuple(runs)}), tmp_path)
    assert result["status"] == "not_ready" and result["acceptanceMet"] is None
    assert any(issue["code"] == "run_evidence_incomplete" for issue in result["issues"])


@pytest.mark.parametrize("kind,field,wrong", [
    ("review", "taskId", "other-task"),
    ("metering", "taskId", "other-task"),
    ("metering", "variant", "old"),
    ("metering", "configurationSha256", "a" * 64),
])
@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_wrong_record_binding_remains_unknown(tmp_path, kind, field, wrong, missing):
    evidence = _evidence(tmp_path)
    run = evidence.runs[-1]
    file = run.reviews[0] if kind == "review" else run.metering
    payload = json.loads((tmp_path / file.path).read_bytes())
    if missing:
        payload.pop(field)
    else:
        payload[field] = wrong
    changed = BenchmarkFileIdentity.model_validate(_file(tmp_path, file.path, payload))
    run = run.model_copy(update={"reviews": (changed, run.reviews[1])} if kind == "review"
                         else {"metering": changed})
    report = evaluate_study(evidence.model_copy(update={"runs": (*evidence.runs[:-1], run)}), tmp_path)
    assert report["status"] == "not_ready" and report["acceptanceMet"] is None
    assert any(issue["code"] == "run_evidence_incomplete" for issue in report["issues"])


@pytest.mark.parametrize("baseline_cost,candidate_cost", [(5e-324, 1e308), (1e308, 5e-324)])
def test_unrepresentable_cost_ratio_stays_unknown(tmp_path, baseline_cost, candidate_cost):
    report = evaluate_study(_evidence(tmp_path, baseline_cost=baseline_cost,
                                     candidate_cost=candidate_cost), tmp_path)
    assert report["status"] == "not_ready" and report["acceptanceMet"] is None
    assert any(issue["code"] == "cost_ratio_unrepresentable" for issue in report["issues"])
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("kind", ["configuration", "sample", "authorization", "report", "metering", "review"])
@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink"])
def test_cli_output_cannot_overwrite_any_registered_evidence(tmp_path, kind, alias):
    evidence = _evidence(tmp_path, complete=False, real=False)
    files = {
        "configuration": evidence.plan.baseline_configuration,
        "sample": evidence.plan.tasks[0].inputs[0],
        "authorization": evidence.plan.tasks[0].authorization,
        "report": evidence.runs[0].report,
        "metering": evidence.runs[0].metering,
        "review": evidence.runs[0].reviews[0],
    }
    registered = tmp_path / files[kind].path
    original = registered.read_bytes()
    output = registered
    if alias != "direct":
        output = tmp_path / "output-alias.json"
        if alias == "symlink":
            output.symlink_to(registered)
        else:
            output.hardlink_to(registered)
    study = tmp_path / "study.json"
    study.write_text(evidence.model_dump_json(by_alias=True))
    with pytest.raises(SystemExit):
        main(["evaluate", str(study), "--output", str(output)])
    assert registered.read_bytes() == original
