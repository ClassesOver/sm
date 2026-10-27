"""Validate a completed planner benchmark without running the reporting workflow."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def assess_results(results: dict[str, Any], *, expected_input_sha256: str) -> dict[str, Any]:
    """Return a machine-readable acceptance result for a planner benchmark."""

    errors: list[str] = []
    warnings: list[str] = []
    manifest = results.get("manifest")
    if not isinstance(manifest, dict):
        errors.append("缺少 manifest")
        manifest = {}
    if manifest.get("inputSha256") != expected_input_sha256:
        errors.append("manifest.inputSha256 与冻结输入不一致")
    repetitions = manifest.get("repetitions")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        errors.append("manifest.repetitions 无效")
        repetitions = 0

    summaries = results.get("summaries")
    summary_by_variant = {
        item.get("variant"): item
        for item in summaries
        if isinstance(item, dict) and isinstance(item.get("variant"), str)
    } if isinstance(summaries, list) else {}
    if "baseline" not in summary_by_variant:
        errors.append("缺少 baseline summary")
    elif summary_by_variant["baseline"].get("passRate") != 1.0:
        errors.append("baseline passRate 未达到 1.0")

    runs = results.get("runs")
    if not isinstance(runs, list):
        errors.append("缺少 runs")
        runs = []
    expected_run_count = repetitions * len(summary_by_variant) if repetitions else 0
    if expected_run_count and len(runs) != expected_run_count:
        errors.append(f"runs 数量为 {len(runs)}，期望 {expected_run_count}")
    baseline_runs = [item for item in runs if isinstance(item, dict) and item.get("variant") == "baseline"]
    if len(baseline_runs) != repetitions:
        errors.append(f"baseline runs 数量为 {len(baseline_runs)}，期望 {repetitions}")
    for item in baseline_runs:
        if item.get("error"):
            errors.append("baseline 存在模型调用错误")
        if not isinstance(item.get("validation"), dict) or item["validation"].get("valid") is not True:
            errors.append("baseline 存在结构/字段契约失败")

    reviews = results.get("reviews")
    if not isinstance(reviews, list) or len(reviews) != repetitions:
        errors.append("reviews 数量与 repetitions 不一致")
    for variant, summary in summary_by_variant.items():
        if variant != "baseline" and summary.get("passRate") != 1.0:
            warnings.append(f"候选 {variant} 存在契约失败，未作为 baseline 验收失败")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "runs": len(runs),
            "reviews": len(reviews) if isinstance(reviews, list) else 0,
            "variants": len(summary_by_variant),
            "repetitions": repetitions,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--input", type=Path, required=True, help="冻结输入 JSON")
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    frozen = json.loads(args.input.read_text(encoding="utf-8"))
    import hashlib

    expected = hashlib.sha256(
        json.dumps(frozen, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assessment = assess_results(results, expected_input_sha256=expected)
    print(json.dumps(assessment, ensure_ascii=False, indent=2))
    return 0 if assessment["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
