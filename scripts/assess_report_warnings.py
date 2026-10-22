"""Export a lossless warning worklist from an already evaluated frozen report."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
from smart_reporting.reporting.trace.quality_bundle import QualityBundle
from smart_reporting.reporting.trace.warning_ledger import (
    build_warning_ledger,
    build_warning_review_packet,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-packet", action="store_true", help="Include an unadjudicated evidence case for every diagnostic")
    args = parser.parse_args()
    if any(args.output.resolve() == source.resolve() or (
        args.output.exists() and args.output.samefile(source)
    ) for source in (args.quality, args.index)):
        parser.error("Output must not overwrite a frozen input")
    inputs = {"quality": args.quality.read_bytes(), "index": args.index.read_bytes()}
    quality = QualityBundle.model_validate_json(inputs["quality"])
    index = RevisionTraceIndexV1.model_validate_json(inputs["index"])
    ledger = build_warning_ledger(quality, index)
    artifact = build_warning_review_packet(quality, index) if args.review_packet else ledger
    result = artifact.model_dump(mode="json", by_alias=True)
    result["inputFileHashes"] = {key: hashlib.sha256(raw).hexdigest() for key, raw in inputs.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Replacement avoids truncating another hard link even if the destination
    # changes after validation; failed serialization leaves the old output intact.
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"{ledger.original_issue_count} diagnostics, {ledger.group_count} groups; "
          f"not a business acceptance verdict: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
