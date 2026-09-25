"""离线运行补证覆盖率与输出契约软校验（A1/A2），只读、不调用 provider。

用法：
    .venv/bin/python scripts/analysis_coverage_check.py \
        --evidence path/to/supplement.json \
        --requirements path/to/coding-requirements.json \
        --dataset dataset_a=path/to/a.csv --dataset dataset_b=path/to/b.csv

--requirements 可以是 codingRequirements 数组、含 codingRequirements 的 planner 输出，
或含 facts.codingRequirements 的 Coding payload。结果以 JSON 输出到 stdout，
与 recompute-report.txt 对照评估召回与误报。
"""

# ruff: noqa: E402 - 直接运行脚本时先把仓库根目录加入模块搜索路径。

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smart_reporting.reporting.workflow.runtime.analysis_coverage import (
    dimension_coverage_gaps,
    one_sided_gap_warnings,
    parse_csv_columns,
    requirement_output_gaps,
)


def _requirements(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for candidate in (payload, payload.get("facts")):
            if isinstance(candidate, dict) and isinstance(
                candidate.get("codingRequirements"), list
            ):
                return _requirements(candidate["codingRequirements"])
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--dataset", action="append", default=[], metavar="ID=CSV")
    args = parser.parse_args(argv)

    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    requirements = _requirements(json.loads(args.requirements.read_text(encoding="utf-8")))
    findings = [item for item in evidence.get("findings") or () if isinstance(item, dict)]
    fields_by_dataset: dict[str, set[str]] = {}
    for requirement in requirements:
        fields_by_dataset.setdefault(str(requirement.get("datasetId")), set()).update(
            str(field) for field in requirement.get("fields") or ()
        )
    dataset_columns: dict[str, dict[str, list[str]]] = {}
    for item in args.dataset:
        dataset_id, _, path = item.partition("=")
        if not path:
            parser.error(f"--dataset 需要 ID=CSV：{item}")
        dataset_columns[dataset_id] = parse_csv_columns(
            Path(path).read_text(encoding="utf-8"), fields_by_dataset.get(dataset_id, set())
        )
    warnings = [
        *requirement_output_gaps(requirements, findings),
        *dimension_coverage_gaps(requirements, dataset_columns, findings),
        *one_sided_gap_warnings(findings, [str(item) for item in evidence.get("warnings") or ()]),
    ]
    print(json.dumps({"warnings": warnings}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
