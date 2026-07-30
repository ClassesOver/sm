from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def _issue(details: dict[str, Any], key: str, value: Any) -> None:
    if value:
        details[key] = value


def _validate(requirement: dict[str, Any]) -> dict[str, Any]:
    requirement_id = requirement["id"]
    parameters = requirement["parameters"]
    expected = parameters["expectedIdentity"]
    artifacts = requirement["artifacts"]
    by_path = {item["path"]: item for item in artifacts}
    manifest_path = expected["artifactManifestPath"]
    markdown_path = expected["markdownPath"]
    details: dict[str, Any] = {}

    manifest_artifact = by_path.get(manifest_path)
    markdown_artifact = by_path.get(markdown_path)
    if manifest_artifact is None or markdown_artifact is None:
        missing_paths = [
            path
            for path, artifact in (
                (manifest_path, manifest_artifact),
                (markdown_path, markdown_artifact),
            )
            if artifact is None
        ]
        return {
            "id": requirement_id,
            "passed": False,
            "details": {"missingArtifactPaths": missing_paths},
        }

    try:
        manifest = json.loads(Path(manifest_artifact["absolutePath"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        return {
            "id": requirement_id,
            "passed": False,
            "details": {"manifestError": type(error).__name__},
        }

    schema_errors = sorted(
        Draft202012Validator(parameters["manifestSchema"]).iter_errors(manifest),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    _issue(
        details,
        "schemaErrors",
        [
            {
                "path": ".".join(str(item) for item in error.absolute_path) or "$",
                "message": error.message[:512],
            }
            for error in schema_errors[:20]
        ],
    )
    if schema_errors:
        return {"id": requirement_id, "passed": False, "details": details}

    received_identity = {
        "reportId": manifest["reportId"],
        "revision": manifest["revision"],
        "codingTaskKey": manifest["codingTaskKey"],
        "datasetSnapshotHash": manifest["datasetSnapshotHash"],
        "effectiveProfileHash": manifest["effectiveProfileHash"],
        "markdownPath": manifest["markdown"]["path"],
        "artifactManifestPath": manifest_path,
    }
    _issue(
        details,
        "mismatchedIdentityFields",
        [key for key, value in expected.items() if received_identity.get(key) != value],
    )

    declared = [manifest["markdown"], *manifest.get("charts", [])]
    declared_paths = {item["path"] for item in declared}
    expected_paths = declared_paths | {manifest_path}
    submitted_paths = set(by_path)
    _issue(details, "missingArtifactPaths", sorted(expected_paths - submitted_paths))
    _issue(details, "unexpectedArtifactPaths", sorted(submitted_paths - expected_paths))

    changed_paths = []
    for item in declared:
        actual = by_path.get(item["path"])
        if (
            actual is None
            or actual.get("size") != item["size"]
            or actual.get("sha256") != item["sha256"]
        ):
            changed_paths.append(item["path"])
    _issue(details, "changedArtifactPaths", changed_paths)

    try:
        markdown = Path(markdown_artifact["absolutePath"]).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        details["markdownError"] = type(error).__name__
    else:
        _issue(
            details,
            "missingCitationIds",
            [
                item["citationId"]
                for item in manifest["citations"]
                if f"[[citation:{item['citationId']}]]" not in markdown
            ],
        )
        _issue(
            details,
            "missingSectionIds",
            [
                section
                for section in manifest["sections"]
                if f"[[section:{section}]]" not in markdown
            ],
        )

    if details:
        details["submittedArtifactPaths"] = sorted(submitted_paths)
    return {
        "id": requirement_id,
        "passed": not details,
        **({"details": details} if details else {}),
    }


def main() -> None:
    request = json.loads(Path(sys.argv[-1]).read_text(encoding="utf-8"))
    result = {
        "version": 1,
        "requirements": [_validate(item) for item in request["requirements"]],
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
