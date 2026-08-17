from __future__ import annotations

from pathlib import Path
from typing import Any

from agno.skills import LocalSkills, Skills

from .artifacts_v1 import ReportArtifactManifest

REPORT_PHASE_CONTRACT_ID = "reporting-phase:contract"
REPORTING_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "builtin_skills"


def load_reporting_skills(base_skills: Skills | None) -> Skills:
    loaders = list(base_skills.loaders) if base_skills is not None else []
    loaders.append(LocalSkills(str(REPORTING_BUILTIN_SKILLS_DIR)))
    return Skills(loaders=loaders)


def build_report_phase_acceptance_contract(
    *,
    phase: str,
    validation_context_file: dict[str, Any],
    phase_contract: dict[str, Any],
    analysis_output_path: str | None = None,
    section_output_path: str | None = None,
    rework_request_path: str | None = None,
) -> dict[str, Any]:
    """把内部 phase 身份放入首个 requirement，供 Reporting 工具可信读取。"""

    trusted_phase_contract = dict(phase_contract)
    if phase == "analysis":
        task_kind = trusted_phase_contract.get("taskKind")
        # citationRegistry 只用于模型指令展示，工具校验只消费 citationIds；visualization
        # 也不需要单项计划映射。避免把重复的大型投影塞进 16 KiB acceptance 参数。
        trusted_phase_contract.pop("citationRegistry", None)
        if task_kind == "visualization":
            trusted_phase_contract.pop("analysisPlans", None)
            trusted_phase_contract.pop("analysisDatasetIds", None)
        if task_kind == "analysis_item":
            if analysis_output_path or section_output_path or rework_request_path:
                raise ValueError("analysis item 不得声明阶段输出路径")
            analysis_ids = trusted_phase_contract.get("analysisIds")
            output_root = trusted_phase_contract.get("analysisOutputRoot")
            if (
                not isinstance(analysis_ids, list)
                or len(analysis_ids) != 1
                or not isinstance(analysis_ids[0], str)
                or not analysis_ids[0]
                or not isinstance(output_root, str)
                or not output_root
            ):
                raise ValueError("analysis item 必须绑定唯一 analysisId 和专属输出目录")
            paths = []
            output_parameters = {}
        else:
            if not analysis_output_path or section_output_path or rework_request_path:
                raise ValueError("analysis phase 输出路径无效")
            paths = [analysis_output_path]
            output_parameters = {"analysisOutputPath": analysis_output_path}
    elif phase == "section":
        if not section_output_path or not rework_request_path or analysis_output_path:
            raise ValueError("section phase 输出路径无效")
        paths = [section_output_path, rework_request_path]
        output_parameters = {
            "sectionOutputPath": section_output_path,
            "reworkRequestPath": rework_request_path,
        }
    else:
        raise ValueError("Reporting phase 无效")
    return {
        "version": 1,
        "requirements": [
            {
                "id": f"report-{phase}-phase",
                # Report Worker 已关闭通用 acceptance validator；requirement 仅作为
                # 不可变 phase 参数载体，由阶段工具自行核验产物哈希。
                "validatorId": REPORT_PHASE_CONTRACT_ID,
                "parameters": {
                    "phase": phase,
                    "validationContextFile": dict(validation_context_file),
                    "phaseContract": trusted_phase_contract,
                    **output_parameters,
                },
                "artifactPatterns": paths,
            }
        ],
    }


def build_report_artifact_validation_context(
    *,
    forbidden_visible_terms: tuple[str, ...] = (),
    observed_data_facts: list[dict[str, Any]] | None = None,
    expected_sections: tuple[str, ...] = (),
    expected_citation_bindings: tuple[tuple[str, str], ...] = (),
    expected_citations: tuple[tuple[str, ...], ...] = (),
    analysis_context_file: dict[str, Any] | None = None,
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
                "citationId": item[0],
                "datasetId": item[1],
                "requirementId": item[2],
                **({"snapshotHash": item[3]} if len(item) > 3 else {}),
            }
            for item in expected_citations
            if len(item) >= 3
        ],
        **(
            {"analysisContextFile": dict(analysis_context_file)}
            if analysis_context_file is not None
            else {}
        ),
        "manifestSchema": ReportArtifactManifest.model_json_schema(by_alias=True),
    }
