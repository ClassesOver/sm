"""用同一冻结 CSV 和结构化请求对比服务端与 Python 补证路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
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


def _percentiles(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("至少需要一次基准运行")
    middle = len(ordered) // 2
    p50 = ordered[middle] if len(ordered) % 2 else statistics.mean(ordered[middle - 1:middle + 1])
    p95 = ordered[min(len(ordered) - 1, max(0, (95 * len(ordered) + 99) // 100 - 1))]
    return {
        "count": len(ordered),
        "meanSeconds": round(statistics.mean(ordered), 6),
        "p50Seconds": round(p50, 6),
        "p95Seconds": round(p95, 6),
    }


def _validate_payload(payload: dict[str, Any], request: StandardSupplementalRequest) -> dict[str, Any]:
    evidence = validate_supplemental_evidence(
        json.dumps(
            {"analysisId": "analysis_001", "datasetIds": [request.dataset_id], **payload},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode(),
        {"analysisId": "analysis_001", "datasetIds": [request.dataset_id]},
    )
    return {
        "findingCount": len(evidence.findings),
        "rowCount": sum(len(item.get("rows", ())) for item in evidence.findings),
        "warningCount": len(evidence.warnings),
        "reconciliationCount": len(evidence.reconciliations),
        "reconciliationsPassed": sum(item["passed"] is True for item in evidence.reconciliations),
    }


def run_comparison(
    *, csv_path: Path, request_path: Path, output: Path, repetitions: int, env_file: Path
) -> dict[str, Any]:
    raw = csv_path.read_bytes()
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    authorization = request_payload.pop("authorization", None)
    if not isinstance(authorization, dict):
        raise ValueError("benchmark request 缺少冻结授权快照")
    request = StandardSupplementalRequest.model_validate(request_payload)
    dataset_ids = authorization.get("datasetIds")
    fields = authorization.get("fields")
    if not isinstance(dataset_ids, list) or not isinstance(fields, list):
        raise ValueError("冻结授权快照结构无效")
    if request.dataset_id not in dataset_ids:
        raise ValueError("计算请求 dataset 不在冻结授权快照中")
    if not set((request.period_field, request.dimension_field, request.measure_field)) <= set(fields):
        raise ValueError("计算请求字段不在冻结授权快照中")
    os.environ["AGENT_ENV_FILE"] = str(env_file)
    settings = AgentSettings.from_environment()
    env = dotenv_values(env_file)
    script = ROOT / "scripts/fixtures/standard_supplemental_python.py"
    request_for_script = output / "request.json"
    request_for_script.parent.mkdir(parents=True, exist_ok=True)
    request_for_script.write_text(
        json.dumps(request.model_dump(mode="json", by_alias=True), ensure_ascii=False), encoding="utf-8"
    )
    service_seconds: list[float] = []
    script_seconds: list[float] = []
    service_payload: dict[str, Any] | None = None
    script_payload: dict[str, Any] | None = None
    run_details: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        started = perf_counter()
        service_payload = run_standard_supplemental(
            analysis_id="analysis_001", dataset_ids=dataset_ids, authorized_fields=fields,
            csv_content=raw, request=request,
        )
        service_validation = _validate_payload(service_payload, request)
        service_seconds.append(perf_counter() - started)

        script_output = output / f"python-evidence-{repetition}.json"
        started = perf_counter()
        subprocess.run(
            [sys.executable, str(script), str(csv_path), str(request_for_script), str(script_output)],
            check=True, capture_output=True, text=True,
        )
        script_payload = json.loads(script_output.read_text(encoding="utf-8"))
        script_validation = _validate_payload(script_payload, request)
        script_seconds.append(perf_counter() - started)
        if service_payload != script_payload:
            raise ValueError(f"第 {repetition} 次服务端与 Python 结果不一致")
        run_details.append({
            "repetition": repetition,
            "service": {
                "seconds": round(service_seconds[-1], 6),
                **service_validation,
                "evidenceSha256": hashlib.sha256(
                    json.dumps(service_payload, ensure_ascii=False, separators=(",", ":")).encode()
                ).hexdigest(),
            },
            "python": {
                "seconds": round(script_seconds[-1], 6),
                **script_validation,
                "evidenceSha256": hashlib.sha256(script_output.read_bytes()).hexdigest(),
            },
            "evidenceBytes": len(script_output.read_bytes()),
        })
    assert service_payload is not None and script_payload is not None
    result = {
        "manifest": {
            "kind": "standard_supplemental_path_comparison",
            "pythonBaseline": "fixed local script; excludes model generation and CodeMode tool orchestration",
            "envFile": str(env_file),
            "model": settings.model_standard_id,
            "baseUrlConfigured": bool(env.get("OPENAI_BASE_URL")),
            "inputSha256": hashlib.sha256(raw).hexdigest(),
            "request": request.model_dump(mode="json", by_alias=True),
            "authorization": {"datasetIds": dataset_ids, "fields": fields},
            "repetitions": repetitions,
            "workflowStarted": False,
            "sqlExecuted": False,
            "modelCalls": 0,
            "resultEqualityChecked": True,
        },
        "service": _percentiles(service_seconds),
        "python": _percentiles(script_seconds),
        "runs": run_details,
    }
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
    result = run_comparison(
        csv_path=args.csv, request_path=args.request, output=args.output,
        repetitions=args.repetitions, env_file=args.env_file,
    )
    print(json.dumps({"service": result["service"], "python": result["python"], "output": str(args.output / "results.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
