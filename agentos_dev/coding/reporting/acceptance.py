from __future__ import annotations

from pathlib import Path
from typing import Any

from agno.skills import LocalSkills, Skills

from .artifacts_v1 import ReportArtifactManifest

REPORT_ARTIFACT_VALIDATOR_ID = "report-artifact:manifest"
REPORT_ARTIFACT_PATTERN = "报表/智能分析/*/*"
REPORTING_BUILTIN_SKILLS_DIR = Path(__file__).with_name("builtin_skills")
REPORT_ARTIFACT_VALIDATOR_SCRIPT = (
    REPORTING_BUILTIN_SKILLS_DIR / "report-artifact" / "scripts" / "validate_manifest.py"
)


def load_reporting_skills(base_skills: Skills | None) -> Skills:
    loaders = list(base_skills.loaders) if base_skills is not None else []
    loaders.append(LocalSkills(str(REPORTING_BUILTIN_SKILLS_DIR)))
    return Skills(loaders=loaders)


def build_report_artifact_acceptance_contract(
    expected_identity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": 1,
        "requirements": [
            {
                "id": "report-artifact",
                "validatorId": REPORT_ARTIFACT_VALIDATOR_ID,
                "parameters": {
                    "expectedIdentity": dict(expected_identity),
                    "manifestSchema": ReportArtifactManifest.model_json_schema(by_alias=True),
                },
                "artifactPatterns": [REPORT_ARTIFACT_PATTERN],
            }
        ],
    }
