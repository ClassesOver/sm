"""在冻结 CSV 上验收服务端标准补证计算，不启动完整报告工作流。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (  # noqa: E402
    validate_supplemental_evidence,
)
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (  # noqa: E402
    StandardSupplementalRequest,
    run_standard_supplemental,
)
from smart_reporting.runtime.settings import AgentSettings  # noqa: E402


def summarize_timings(seconds: list[float]) -> dict[str, Any]:
    if not seconds:
        raise ValueError("至少需要一次基准运行")
    values = sorted(seconds)
    p50 = values[(len(values) - 1) // 2] if len(values) % 2 else statistics.mean(values[len(values) // 2 - 1:len(values) // 2 + 1])
    p95 = values[min(len(values) - 1, max(0, math.ceil(len(values) * 0.95) - 1))]
    return {
        "count": len(values),
        "meanSeconds": round(statistics.mean(values), 6),
        "p50Seconds": round(p50, 6),
        "p95Seconds": round(p95, 6),
    }


def run_benchmark(*, csv_path: Path, request_path: Path, output: Path, repetitions: int, env_file: Path) -> dict[str, Any]:
    raw = csv_path.read_bytes()
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    authorization = request_payload.pop("authorization", None)
    if not isinstance(authorization, dict):
        raise ValueError("benchmark request 缺少冻结授权快照")
    request = StandardSupplementalRequest.model_validate(request_payload)
    authorized_dataset_ids = authorization.get("datasetIds")
    authorized_fields = authorization.get("fields")
    if not isinstance(authorized_dataset_ids, list) or not isinstance(authorized_fields, list):
        raise ValueError("冻结授权快照结构无效")
    if request.dataset_id not in authorized_dataset_ids:
        raise ValueError("计算请求 dataset 不在冻结授权快照中")
    if not set((request.period_field, request.dimension_field, request.measure_field)) <= set(authorized_fields):
        raise ValueError("计算请求字段不在冻结授权快照中")
    os.environ["AGENT_ENV_FILE"] = str(env_file)
    settings = AgentSettings.from_environment()
    env = dotenv_values(env_file)
    timings: list[float] = []
    runs: list[dict[str, Any]] = []
    for index in range(repetitions):
        started = perf_counter()
        payload = run_standard_supplemental(
            analysis_id="analysis_001",
            dataset_ids=authorized_dataset_ids,
            authorized_fields=authorized_fields,
            csv_content=raw,
            request=request,
        )
        evidence = validate_supplemental_evidence(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
            {"analysisId": "analysis_001", "datasetIds": [request.dataset_id]},
        )
        elapsed = perf_counter() - started
        timings.append(elapsed)
        runs.append({
            "repetition": index + 1,
            "seconds": round(elapsed, 6),
            "findingCount": len(evidence.findings),
            "warningCount": len(evidence.warnings),
            "reconciliationCount": len(evidence.reconciliations),
            "reconciliationsPassed": sum(1 for item in evidence.reconciliations if item["passed"]),
            "evidenceBytes": len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()),
        })
    result = {
        "manifest": {
            "kind": "standard_supplemental_baseline",
            "envFile": str(env_file),
            "model": settings.model_standard_id,
            "baseUrlConfigured": bool(env.get("OPENAI_BASE_URL")),
            "inputSha256": hashlib.sha256(raw).hexdigest(),
            "request": request.model_dump(mode="json", by_alias=True),
            "repetitions": repetitions,
            "workflowStarted": False,
            "sqlExecuted": False,
        },
        "timings": summarize_timings(timings),
        "runs": runs,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("repetitions 必须大于 0")
    result = run_benchmark(
        csv_path=args.csv, request_path=args.request, output=args.output,
        repetitions=args.repetitions, env_file=args.env_file,
    )
    print(json.dumps({"timings": result["timings"], "output": str(args.output / "results.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
