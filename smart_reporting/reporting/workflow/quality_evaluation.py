"""Offline paired evaluation of externally collected report quality evidence.

This module validates a study's evidence, never authorizes publication or rollout.
A file hash establishes identity, not that a reviewer or sample is genuine.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from ..contract import SHA256_PATTERN, StrictModel
from ..trace.contracts_v1 import canonical_sha256
from .benchmark_bundle import BenchmarkFileIdentity


class StudyThresholds(StrictModel):
    maximum_unsupported_rate: float = Field(
        alias="maximumUnsupportedRate", ge=0, le=1, allow_inf_nan=False
    )
    minimum_answer_coverage: float = Field(
        alias="minimumAnswerCoverage", ge=0, le=1, allow_inf_nan=False
    )
    maximum_critical_errors: int = Field(alias="maximumCriticalErrors", ge=0, strict=True)
    maximum_cost_ratio: float = Field(alias="maximumCostRatio", gt=0, allow_inf_nan=False)


class StudyTask(StrictModel):
    task_id: str = Field(alias="taskId", min_length=1, max_length=200)
    partition: Literal["pilot", "holdout"]
    sample_kind: Literal["real", "synthetic"] = Field(alias="sampleKind")
    independence_group: str = Field(alias="independenceGroup", min_length=1, max_length=200)
    inputs: tuple[BenchmarkFileIdentity, ...] = Field(min_length=1)
    authorization: BenchmarkFileIdentity | None = None
    required_condition_ids: tuple[str, ...] = Field(
        alias="requiredConditionIds", min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def unique_conditions(self) -> StudyTask:
        if any(not item.strip() for item in self.required_condition_ids):
            raise ValueError("完成条件身份不能为空")
        if len({file.path for file in self.inputs}) != len(self.inputs):
            raise ValueError("任务输入路径重复")
        if len(set(self.required_condition_ids)) != len(self.required_condition_ids):
            raise ValueError("完成条件身份重复")
        return self


class StudyPlan(StrictModel):
    version: Literal["1"] = "1"
    study_id: str = Field(alias="studyId", min_length=1, max_length=200)
    baseline: str = Field(min_length=1, max_length=200)
    candidate: str = Field(min_length=1, max_length=200)
    baseline_configuration: BenchmarkFileIdentity = Field(alias="baselineConfiguration")
    candidate_configuration: BenchmarkFileIdentity = Field(alias="candidateConfiguration")
    author_ids: tuple[str, ...] = Field(alias="authorIds", min_length=1)
    domain_reviewer_ids: tuple[str, ...] = Field(alias="domainReviewerIds", min_length=2)
    tasks: tuple[StudyTask, ...] = Field(default=(), max_length=1000)
    thresholds: StudyThresholds

    @model_validator(mode="after")
    def validate_partition(self) -> StudyPlan:
        if any(not item.strip() for item in (*self.author_ids, *self.domain_reviewer_ids)):
            raise ValueError("人员身份不能为空")
        if self.baseline == self.candidate:
            raise ValueError("基线与候选身份必须不同")
        if len(set(self.domain_reviewer_ids)) != len(self.domain_reviewer_ids):
            raise ValueError("审核人员身份重复")
        if set(self.author_ids) & set(self.domain_reviewer_ids):
            raise ValueError("独立审核人员不可是报告方案作者")
        if len({task.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("评估任务身份重复")
        groups: dict[str, str] = {}
        inputs: dict[str, str] = {}
        for task in self.tasks:
            previous = groups.setdefault(task.independence_group, task.partition)
            if previous != task.partition:
                raise ValueError("同源任务族不可横跨试点与保留集")
            for file in task.inputs:
                previous = inputs.setdefault(file.sha256, task.partition)
                if previous != task.partition:
                    raise ValueError("相同输入不可横跨试点与保留集")
        return self

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", by_alias=True))


class StudyRun(StrictModel):
    task_id: str = Field(alias="taskId", min_length=1)
    variant: str = Field(min_length=1)
    report: BenchmarkFileIdentity
    claim_ids: tuple[str, ...] = Field(alias="claimIds", min_length=1, max_length=10000)
    metering: BenchmarkFileIdentity
    reviews: tuple[BenchmarkFileIdentity, ...] = ()
    adjudication: BenchmarkFileIdentity | None = None

    @model_validator(mode="after")
    def unique_claims(self) -> StudyRun:
        if any(not item.strip() for item in self.claim_ids):
            raise ValueError("主张身份不能为空")
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("主张身份重复")
        return self


class StudyEvidence(StrictModel):
    plan: StudyPlan
    runs: tuple[StudyRun, ...] = Field(default=(), max_length=2000)

    @model_validator(mode="after")
    def unique_runs(self) -> StudyEvidence:
        keys = [(run.task_id, run.variant) for run in self.runs]
        if len(set(keys)) != len(keys):
            raise ValueError("任务/方案结果重复")
        if any(
            run.task_id not in {task.task_id for task in self.plan.tasks}
            or run.variant not in {self.plan.baseline, self.plan.candidate}
            for run in self.runs
        ):
            raise ValueError("结果引用未登记的任务或方案")
        return self


class DomainReview(StrictModel):
    plan_sha256: str = Field(alias="planSha256", pattern=SHA256_PATTERN)
    report_sha256: str = Field(alias="reportSha256", pattern=SHA256_PATTERN)
    reviewer_id: str = Field(alias="reviewerId", min_length=1)
    role: Literal["independent", "adjudicator"]
    blind_review_id: str = Field(alias="blindReviewId", min_length=1)
    claim_inventory_complete: bool = Field(alias="claimInventoryComplete", strict=True)
    blinded_to_variant: bool = Field(alias="blindedToVariant", strict=True)
    unsupported_claim_ids: tuple[str, ...] = Field(alias="unsupportedClaimIds")
    answered_condition_ids: tuple[str, ...] = Field(alias="answeredConditionIds")
    critical_error_count: int = Field(alias="criticalErrorCount", ge=0, strict=True)

    def verdict(self) -> tuple:
        return (
            frozenset(self.unsupported_claim_ids),
            frozenset(self.answered_condition_ids),
            self.critical_error_count,
        )


class StudyMetering(StrictModel):
    plan_sha256: str = Field(alias="planSha256", pattern=SHA256_PATTERN)
    report_sha256: str = Field(alias="reportSha256", pattern=SHA256_PATTERN)
    provenance: Literal["provider_export", "synthetic"]
    currency: str = Field(min_length=1, max_length=20)
    total_cost: float = Field(alias="totalCost", ge=0, allow_inf_nan=False)
    wall_seconds: float = Field(alias="wallSeconds", ge=0, allow_inf_nan=False)
    input_tokens: int = Field(alias="inputTokens", ge=0, strict=True)
    output_tokens: int = Field(alias="outputTokens", ge=0, strict=True)


def _read(root: Path, file: BenchmarkFileIdentity) -> bytes:
    path = root / file.path
    # Do not follow symlinks outside the study or accept a symlink as evidence.
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("证据路径越界或符号链接")
    if file.size > 64 * 1024 * 1024:
        raise ValueError("单个评估证据不得超过64 MiB")
    with path.open("rb") as stream:
        raw = stream.read(file.size + 1)
    if len(raw) != file.size or hashlib.sha256(raw).hexdigest() != file.sha256:
        raise ValueError("证据文件身份已改变")
    return raw


def _review(
    root: Path, file: BenchmarkFileIdentity, plan: StudyPlan, task: StudyTask, run: StudyRun
) -> DomainReview:
    review = DomainReview.model_validate_json(_read(root, file))
    if (
        review.plan_sha256 != plan.sha256
        or review.report_sha256 != run.report.sha256
        or review.reviewer_id not in plan.domain_reviewer_ids
        or not review.claim_inventory_complete
        or not review.blinded_to_variant
        or len(set(review.unsupported_claim_ids)) != len(review.unsupported_claim_ids)
        or len(set(review.answered_condition_ids)) != len(review.answered_condition_ids)
        or set(review.unsupported_claim_ids) - set(run.claim_ids)
        or set(review.answered_condition_ids) - set(task.required_condition_ids)
    ):
        raise ValueError("审核记录不匹配冻结方案、报告或全部主张清单")
    return review


def _paired(values: list[float]) -> dict:
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    n = wins + losses
    p = (
        min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n)
        if n
        else None
    )
    return {
        "pairs": len(values),
        "wins": wins,
        "losses": losses,
        "ties": len(values) - n,
        "meanDelta": sum(values) / len(values) if values else None,
        "twoSidedSignP": p,
    }


def evaluate_study(evidence: StudyEvidence, root: Path, *, validate_only: bool = False) -> dict:
    """Read identities and external attestations. Never fabricates missing reviews."""
    plan = evidence.plan
    issues: list[dict] = []
    counts = Counter(task.partition for task in plan.tasks)
    if counts["pilot"] < 12 or counts["holdout"] < 30:
        issues.append(
            {
                "code": "study_size_incomplete",
                "pilot": counts["pilot"],
                "holdout": counts["holdout"],
            }
        )
    for partition, minimum in (("pilot", 12), ("holdout", 30)):
        independent = len(
            {task.independence_group for task in plan.tasks if task.partition == partition}
        )
        if independent < minimum:
            issues.append(
                {
                    "code": "independent_sample_size_incomplete",
                    "partition": partition,
                    "groups": independent,
                }
            )
    for file in (plan.baseline_configuration, plan.candidate_configuration):
        try:
            _read(root, file)
        except (OSError, ValueError) as error:
            issues.append({"code": "variant_configuration_unavailable", "reason": str(error)})
    for task in plan.tasks:
        if task.sample_kind != "real" or task.authorization is None:
            issues.append({"code": "real_authorized_sample_missing", "taskId": task.task_id})
        for file in (*task.inputs, *((task.authorization,) if task.authorization else ())):
            try:
                _read(root, file)
            except (OSError, ValueError) as error:
                issues.append(
                    {
                        "code": "sample_identity_unavailable",
                        "taskId": task.task_id,
                        "reason": str(error),
                    }
                )
    result: dict[str, Any] = {
        "version": "1",
        "planSha256": plan.sha256,
        "status": "not_ready",
        "acceptanceMet": None,
        "rolloutAuthorized": False,
        "partitions": {"pilot": counts["pilot"], "holdout": counts["holdout"]},
        "issues": issues,
        "metrics": {},
    }
    if validate_only:
        result["status"] = "plan_validated" if not issues else "not_ready"
        return result
    runs = {(run.task_id, run.variant): run for run in evidence.runs}
    measurements: dict[tuple[str, str], dict] = {}
    for task in plan.tasks:
        for variant in (plan.baseline, plan.candidate):
            run = runs.get((task.task_id, variant))
            if run is None:
                issues.append(
                    {"code": "paired_run_missing", "taskId": task.task_id, "variant": variant}
                )
                continue
            try:
                _read(root, run.report)
                metering = StudyMetering.model_validate_json(_read(root, run.metering))
                if (
                    metering.plan_sha256 != plan.sha256
                    or metering.report_sha256 != run.report.sha256
                ):
                    raise ValueError("计量记录不匹配冻结方案或报告")
                if metering.provenance != "provider_export":
                    raise ValueError("真实成本必须来自提供方计量导出")
                reviews = [_review(root, file, plan, task, run) for file in run.reviews]
                if (
                    len(reviews) != 2
                    or len({item.reviewer_id for item in reviews}) != 2
                    or any(item.role != "independent" for item in reviews)
                    or len({item.blind_review_id for item in reviews}) != 2
                ):
                    raise ValueError("需要两位不同独立审核人员的完整盲审记录")
                verdict = reviews[0]
                if reviews[0].verdict() != reviews[1].verdict():
                    if run.adjudication is None:
                        raise ValueError("双人审核分歧尚未裁决")
                    verdict = _review(root, run.adjudication, plan, task, run)
                    if verdict.role != "adjudicator" or verdict.reviewer_id in {
                        item.reviewer_id for item in reviews
                    }:
                        raise ValueError("分歧裁决必须由第三位领域审核人员完成")
                measurements[(task.task_id, variant)] = {
                    "unsupportedRate": len(verdict.unsupported_claim_ids) / len(run.claim_ids),
                    "answerCoverage": len(verdict.answered_condition_ids)
                    / len(task.required_condition_ids),
                    "criticalErrors": verdict.critical_error_count,
                    "cost": metering.total_cost,
                    "currency": metering.currency,
                    "wallSeconds": metering.wall_seconds,
                    "inputTokens": metering.input_tokens,
                    "outputTokens": metering.output_tokens,
                }
            except (OSError, ValueError) as error:
                issues.append(
                    {
                        "code": "run_evidence_incomplete",
                        "taskId": task.task_id,
                        "variant": variant,
                        "reason": str(error),
                    }
                )
    for partition in ("pilot", "holdout"):
        tasks = [task for task in plan.tasks if task.partition == partition]
        pairs = [
            task
            for task in tasks
            if all(
                (task.task_id, variant) in measurements
                for variant in (plan.baseline, plan.candidate)
            )
        ]
        currencies = {
            measurements[(task.task_id, variant)]["currency"]
            for task in pairs
            for variant in (plan.baseline, plan.candidate)
        }
        if len(currencies) > 1:
            issues.append({"code": "cost_currency_conflict", "partition": partition})
        summary: dict[str, Any] = {
            "completePairs": len(pairs),
            "requiredPairs": len(tasks),
            "currency": next(iter(currencies)) if len(currencies) == 1 else None,
            "variants": {},
        }
        for variant in (plan.baseline, plan.candidate):
            rows = [measurements[(task.task_id, variant)] for task in pairs]
            summary["variants"][variant] = {
                key: sum(row[key] for row in rows) / len(rows) if rows else None
                for key in (
                    "unsupportedRate",
                    "answerCoverage",
                    "criticalErrors",
                    "cost",
                    "wallSeconds",
                    "inputTokens",
                    "outputTokens",
                )
            }
        summary["pairedUnsupportedReduction"] = _paired(
            [
                measurements[(task.task_id, plan.baseline)]["unsupportedRate"]
                - measurements[(task.task_id, plan.candidate)]["unsupportedRate"]
                for task in pairs
            ]
        )
        summary["pairedAnswerCoverageGain"] = _paired(
            [
                measurements[(task.task_id, plan.candidate)]["answerCoverage"]
                - measurements[(task.task_id, plan.baseline)]["answerCoverage"]
                for task in pairs
            ]
        )
        result["metrics"][partition] = summary
    if issues:
        return result
    held = result["metrics"]["holdout"]["variants"]
    baseline, candidate = held[plan.baseline], held[plan.candidate]
    cost_ratio = candidate["cost"] / baseline["cost"] if baseline["cost"] else None
    if cost_ratio is None:
        issues.append({"code": "baseline_cost_zero"})
        return result
    result["acceptanceMet"] = (
        candidate["unsupportedRate"] <= plan.thresholds.maximum_unsupported_rate
        and candidate["answerCoverage"] >= plan.thresholds.minimum_answer_coverage
        and sum(
            measurements[(task.task_id, plan.candidate)]["criticalErrors"]
            for task in plan.tasks
            if task.partition == "holdout"
        )
        <= plan.thresholds.maximum_critical_errors
        and cost_ratio <= plan.thresholds.maximum_cost_ratio
    )
    result["costRatio"] = cost_ratio
    result["status"] = "evidence_evaluated"
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "evaluate"))
    parser.add_argument(
        "study", type=Path, help="JSON plan and run evidence; relative files are rooted beside it"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.output is not None and args.output.resolve() == args.study.resolve():
        parser.error("输出文件不能覆盖冻结评估输入")
    try:
        evidence = StudyEvidence.model_validate_json(args.study.read_bytes())
        report = evaluate_study(
            evidence, args.study.parent, validate_only=args.command == "validate"
        )
        code = (
            0
            if report["status"] in {"plan_validated", "evidence_evaluated"}
            and report["acceptanceMet"] is not False
            else 2
        )
    except (OSError, ValueError) as error:
        report, code = (
            {
                "status": "invalid",
                "acceptanceMet": None,
                "rolloutAuthorized": False,
                "error": str(error),
            },
            2,
        )
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
