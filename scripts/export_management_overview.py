"""Export the current evidence matrix from a caller-verified quality record."""

from __future__ import annotations

import argparse
from pathlib import Path

from smart_reporting.reporting.trace.quality_bundle import QualityBundle
from smart_reporting.reporting.workflow.management_overview import (
    build_management_overview,
    render_management_overview,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.quality.resolve():
        parser.error("Output must not overwrite the quality input")
    quality = QualityBundle.model_validate_json(args.quality.read_bytes())
    # Rebuild instead of trusting a serialized prior passing matrix.
    overview = build_management_overview(quality)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_management_overview(overview))
    print(f"{overview.status}: {len(overview.rows)} conditions; {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
