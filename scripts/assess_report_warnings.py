"""Export a lossless warning worklist from an already evaluated frozen report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
from smart_reporting.reporting.trace.quality_bundle import QualityBundle
from smart_reporting.reporting.trace.warning_ledger import build_warning_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in {args.quality.resolve(), args.index.resolve()}:
        parser.error("Output must not overwrite a frozen input")
    inputs = {"quality": args.quality.read_bytes(), "index": args.index.read_bytes()}
    quality = QualityBundle.model_validate_json(inputs["quality"])
    index = RevisionTraceIndexV1.model_validate_json(inputs["index"])
    ledger = build_warning_ledger(quality, index)
    result = ledger.model_dump(mode="json", by_alias=True)
    result["inputFileHashes"] = {key: hashlib.sha256(raw).hexdigest() for key, raw in inputs.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"{ledger.original_issue_count} diagnostics, {ledger.group_count} groups; "
          f"not a business acceptance verdict: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
