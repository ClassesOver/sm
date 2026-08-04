from __future__ import annotations

from pathlib import Path
from typing import Any

from agno.skills import LocalSkills, Skills

from .artifacts_v1 import ReportArtifactManifest

REPORT_ARTIFACT_VALIDATOR_ID = "report-artifact:manifest"
REPORT_ARTIFACT_PATTERN = "报表/智能分析/*/*"
REPORTING_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "builtin_skills"
REPORT_ARTIFACT_VALIDATOR_SCRIPT = (
    REPORTING_BUILTIN_SKILLS_DIR / "report-artifact" / "scripts" / "validate_manifest.py"
)


def load_reporting_skills(base_skills: Skills | None) -> Skills:
    loaders = list(base_skills.loaders) if base_skills is not None else []
    loaders.append(LocalSkills(str(REPORTING_BUILTIN_SKILLS_DIR)))
    return Skills(loaders=loaders)


def build_report_artifact_acceptance_contract(
    expected_identity: dict[str, Any],
    *,
    validation_context_file: dict[str, Any],
    render_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "requirements": [
            {
                "id": "report-artifact",
                "validatorId": REPORT_ARTIFACT_VALIDATOR_ID,
                "parameters": {
                    "expectedIdentity": dict(expected_identity),
                    "validationContextFile": dict(validation_context_file),
                    **(
                        {"renderContract": dict(render_contract)}
                        if render_contract is not None
                        else {}
                    ),
                },
                "artifactPatterns": [REPORT_ARTIFACT_PATTERN],
            }
        ],
    }


def build_report_artifact_validation_context(
    *,
    forbidden_visible_terms: tuple[str, ...] = (),
    observed_data_facts: list[dict[str, Any]] | None = None,
    expected_sections: tuple[str, ...] = (),
    expected_citation_bindings: tuple[tuple[str, str], ...] = (),
    expected_citations: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, Any]:
    return {
        "version": 1,
        "forbiddenVisibleTerms": sorted(set(forbidden_visible_terms)),
        "observedDataFacts": list(observed_data_facts or []),
        "prohibitDerivedValues": True,
        "expectedSections": list(expected_sections),
        "expectedCitationBindings": [
            {"datasetId": dataset_id, "requirementId": requirement_id}
            for dataset_id, requirement_id in expected_citation_bindings
        ],
        "expectedCitations": [
            {
                "citationId": citation_id,
                "datasetId": dataset_id,
                "requirementId": requirement_id,
            }
            for citation_id, dataset_id, requirement_id in expected_citations
        ],
        "manifestSchema": ReportArtifactManifest.model_json_schema(by_alias=True),
    }
