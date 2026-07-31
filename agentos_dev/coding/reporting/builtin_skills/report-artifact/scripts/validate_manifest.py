from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator
from markdown_it import MarkdownIt

_PROTOCOL_MARKER = re.compile(r"\[\[(?:citation|section):[^\]\r\n]+\]\]")
_CITATION_MARKER = re.compile(r"\[\[citation:([^\]\r\n]+)\]\]")
_MARKDOWN_LINK_TARGET = re.compile(r"\]\([^\)\r\n]*\)")
_FORBIDDEN_DERIVATION = re.compile(
    r"(?:拟合|估算|估计|推算|插值|外推|年化|平滑|填补|补齐|视为(?:未发生|零|0))"
)
_DERIVATION_NEGATION = re.compile(
    r"(?:(?:不得|禁止|避免|拒绝|无需|无须|不应|不可).{0,24}|"
    r"不(?:进行|采用|使用|予以|做|作).{0,8})$"
)
_MISSING_CLAIM = re.compile(r"(?:无记录|没有记录|缺失|未提供|未出数|无数据|没有数据|数据为空)")
_MISSING_NEGATION = re.compile(r"(?:不|并非|并无|不存在|未发现).{0,12}$")
_CLAIM = re.compile(r"[^。！？；;\r\n]+[。！？；;]?")
_YEAR_MONTH = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月")
_ISO_MONTH = re.compile(r"(?<!\d)((?:19|20)\d{2})[-/](\d{1,2})(?!\d)")
_YEAR_MONTH_RANGE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月?\s*[-至到~～—]\s*"
    r"(?:((?:19|20)\d{2})\s*年\s*)?(\d{1,2})\s*月"
)
_MONTH_RANGE = re.compile(r"(?<!\d)(\d{1,2})\s*月?\s*[-至到~～—]\s*(\d{1,2})\s*月")


def _issue(details: dict[str, Any], key: str, value: Any) -> None:
    if value:
        details[key] = value


def _schema_issue(error: Any) -> dict[str, Any]:
    issue = {
        "path": ".".join(str(item) for item in error.absolute_path) or "$",
        "message": error.message[:512],
    }
    contains = error.schema.get("contains") if isinstance(error.schema, dict) else None
    if isinstance(contains, dict) and isinstance(contains.get("const"), str):
        issue["expectedContains"] = contains["const"]
    return issue


def _schema_mutation_paths(error: Any) -> list[str]:
    base = ".".join(str(item) for item in error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        required = error.validator_value
        if isinstance(required, list):
            return [
                ".".join(filter(None, (base, str(item))))
                for item in required
                if isinstance(item, str) and item not in error.instance
            ]
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        properties = error.schema.get("properties", {})
        if isinstance(properties, dict):
            return [
                ".".join(filter(None, (base, str(item))))
                for item in error.instance
                if item not in properties
            ]
    return [base] if base else []


def _visible_machine_terms(markdown: str, terms: list[str]) -> list[str]:
    visible = _PROTOCOL_MARKER.sub("", markdown)
    visible = _MARKDOWN_LINK_TARGET.sub("]", visible)
    matches = []
    for term in sorted(set(terms)):
        if not term or re.search(r"[^A-Za-z0-9_.-]", term):
            continue
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
        if re.search(pattern, visible, flags=re.IGNORECASE):
            matches.append(term)
    return matches


def _visible_claims(markdown: str) -> list[str]:
    return [claim for claim, _citation_ids in _visible_claim_records(markdown)]


def _visible_claim_records(markdown: str) -> list[tuple[str, tuple[str, ...]]]:
    records: list[tuple[str, tuple[str, ...]]] = []
    for line in markdown.splitlines():
        citation_ids = tuple(dict.fromkeys(_CITATION_MARKER.findall(line)))
        visible = _PROTOCOL_MARKER.sub("", line)
        visible = _MARKDOWN_LINK_TARGET.sub("]", visible)
        for match in _CLAIM.finditer(visible):
            claim = match.group(0).strip().lstrip("#>- ")
            if claim:
                records.append((claim, citation_ids))
    return records


def _forbidden_derived_claims(markdown: str) -> list[str]:
    claims: list[str] = []
    for claim in _visible_claims(markdown):
        if any(
            not _DERIVATION_NEGATION.search(claim[: match.start()])
            for match in _FORBIDDEN_DERIVATION.finditer(claim)
        ):
            claims.append(claim)
    return claims


def _claimed_periods(claim: str, observed_periods: set[str]) -> set[str]:
    periods = {
        f"{int(year):04d}-{int(month):02d}"
        for pattern in (_YEAR_MONTH, _ISO_MONTH)
        for year, month in pattern.findall(claim)
        if 1 <= int(month) <= 12
    }
    for start_year, start_month, end_year, end_month in _YEAR_MONTH_RANGE.findall(claim):
        first_year = int(start_year)
        first_month = int(start_month)
        last_year = int(end_year or start_year)
        last_month = int(end_month)
        if not (1 <= first_month <= 12 and 1 <= last_month <= 12):
            continue
        first = first_year * 12 + first_month - 1
        last = last_year * 12 + last_month - 1
        if first <= last and last - first < 120:
            periods.update(
                f"{value // 12:04d}-{value % 12 + 1:02d}" for value in range(first, last + 1)
            )
    years = {period[:4] for period in observed_periods if re.fullmatch(r"\d{4}-\d{2}", period)}
    if len(years) == 1:
        year = next(iter(years))
        for start, end in _MONTH_RANGE.findall(claim):
            first, last = int(start), int(end)
            if 1 <= first <= last <= 12:
                periods.update(f"{year}-{month:02d}" for month in range(first, last + 1))
    return periods


def _period_claim_issues(
    markdown: str,
    observed_data_facts: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts_by_binding: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fact in observed_data_facts:
        if not isinstance(fact, dict):
            continue
        dataset_id = fact.get("datasetId")
        requirement_id = fact.get("requirementId")
        if isinstance(dataset_id, str) and isinstance(requirement_id, str):
            facts_by_binding.setdefault((dataset_id, requirement_id), []).append(fact)
    citation_bindings = {
        item["citationId"]: (item["datasetId"], item["requirementId"])
        for item in citations
        if isinstance(item, dict)
    }
    contradictions: list[dict[str, Any]] = []
    unbound: list[dict[str, Any]] = []
    for claim, citation_ids in _visible_claim_records(markdown):
        missing_matches = list(_MISSING_CLAIM.finditer(claim))
        if not missing_matches or all(
            _MISSING_NEGATION.search(claim[: match.start()]) for match in missing_matches
        ):
            continue
        bindings = {
            citation_bindings[citation_id]
            for citation_id in citation_ids
            if citation_id in citation_bindings
        }
        if not bindings and len(facts_by_binding) == 1:
            bindings = set(facts_by_binding)
        if not bindings:
            unbound.append({"claim": claim, "citationIds": list(citation_ids)})
            continue
        selected_facts = [
            fact for binding in bindings for fact in facts_by_binding.get(binding, [])
        ]
        observed_facts: list[dict[str, Any]] = []
        for fact in selected_facts:
            observed_periods = {
                str(period) for period in fact.get("periodCoverage", []) if isinstance(period, str)
            }
            missing_periods = {
                str(period) for period in fact.get("missingPeriods", []) if isinstance(period, str)
            }
            contradicted = sorted(
                _claimed_periods(claim, observed_periods | missing_periods)
                & (observed_periods - missing_periods)
            )
            if contradicted:
                observed_facts.append(
                    {
                        "sourceId": fact.get("sourceId"),
                        "table": fact.get("table"),
                        "observedPeriods": contradicted,
                    }
                )
        if observed_facts:
            issue: dict[str, Any] = {
                "claim": claim,
                "observedPeriods": sorted(
                    {period for fact in observed_facts for period in fact["observedPeriods"]}
                ),
                "observedFacts": observed_facts,
            }
            if citation_ids:
                issue["citationIds"] = list(citation_ids)
            contradictions.append(issue)
    return contradictions, unbound


def _load_validation_context(
    workspace_root: str, identity: Any
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(identity, dict) or set(identity) != {"path", "size", "sha256"}:
        return None, "identity_invalid"
    raw_path = identity.get("path")
    relative = PurePosixPath(raw_path) if isinstance(raw_path, str) else PurePosixPath(".")
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or "\\" in raw_path
        or relative.is_absolute()
        or ".." in relative.parts
        or not isinstance(identity.get("size"), int)
        or not 0 < identity["size"] <= 200 * 1024 * 1024
        or not isinstance(identity.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", identity["sha256"])
    ):
        return None, "identity_invalid"
    try:
        content = Path(workspace_root, relative.as_posix()).read_bytes()
    except OSError:
        return None, "file_unavailable"
    if (
        len(content) != identity["size"]
        or hashlib.sha256(content).hexdigest() != identity["sha256"]
    ):
        return None, "file_changed"
    try:
        context = json.loads(content)
    except (UnicodeError, ValueError):
        return None, "content_invalid"
    expected_keys = {
        "version",
        "forbiddenVisibleTerms",
        "observedDataFacts",
        "prohibitDerivedValues",
        "expectedSections",
        "expectedCitationBindings",
        "manifestSchema",
    }
    if (
        not isinstance(context, dict)
        or set(context) != expected_keys
        or context.get("version") != 1
    ):
        return None, "content_invalid"
    return context, None


def _manifest_invariant_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    charts = manifest["charts"]
    citations = manifest["citations"]
    sections = manifest["sections"]
    chart_ids = [item["chartId"] for item in charts]
    citation_ids = [item["citationId"] for item in citations]
    paths = [manifest["markdown"]["path"], *(item["path"] for item in charts)]
    if manifest["markdown"]["mediaType"] != "text/markdown":
        errors.append("正文产物必须是 Markdown")
    if any(not item["mediaType"].startswith("image/") for item in charts):
        errors.append("图表产物必须是图片")
    if any(len(item["datasetIds"]) != len(set(item["datasetIds"])) for item in charts):
        errors.append("图表数据集引用不能重复")
    for values, message in (
        (chart_ids, "chartId 不能重复"),
        (citation_ids, "citationId 不能重复"),
        (paths, "产物路径不能重复"),
        (sections, "报告章节不能重复"),
    ):
        if len(values) != len(set(values)):
            errors.append(message)
    return errors


def _markdown_image_paths(markdown: str, markdown_path: str) -> tuple[set[str], list[str]]:
    paths: set[str] = set()
    invalid_targets: list[str] = []
    parent = PurePosixPath(markdown_path).parent
    for token in MarkdownIt("commonmark").parse(markdown):
        for child in token.children or []:
            if child.type != "image":
                continue
            source_value = child.attrGet("src")
            source = source_value if isinstance(source_value, str) else ""
            parsed = urlsplit(source)
            decoded = unquote(parsed.path)
            relative = PurePosixPath(decoded)
            if (
                parsed.scheme
                or parsed.netloc
                or parsed.query
                or parsed.fragment
                or not decoded
                or "\\" in decoded
                or relative.is_absolute()
                or ".." in relative.parts
            ):
                invalid_targets.append(source)
                continue
            paths.add(parent.joinpath(relative).as_posix())
    return paths, invalid_targets


def _validate(requirement: dict[str, Any], *, workspace_root: str) -> dict[str, Any]:
    requirement_id = requirement["id"]
    parameters = requirement["parameters"]
    expected = parameters["expectedIdentity"]
    artifacts = requirement["artifacts"]
    by_path = {item["path"]: item for item in artifacts}
    manifest_path = expected["artifactManifestPath"]
    markdown_path = expected["markdownPath"]
    details: dict[str, Any] = {}

    validation_context, context_error = _load_validation_context(
        workspace_root, parameters.get("validationContextFile")
    )
    if validation_context is None:
        return {
            "id": requirement_id,
            "passed": False,
            "details": {"validationContextError": context_error or "content_invalid"},
        }

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
        Draft202012Validator(validation_context["manifestSchema"]).iter_errors(manifest),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    _issue(
        details,
        "schemaErrors",
        [_schema_issue(error) for error in schema_errors[:20]],
    )
    if schema_errors:
        authorized_paths = sorted(
            {path for error in schema_errors[:20] for path in _schema_mutation_paths(error) if path}
        )
        details.update(
            {
                "repairTarget": manifest_path,
                "authorizedManifestMutationPaths": authorized_paths,
                "repairInstructions": [
                    "只修改 schemaErrors 对应的 authorizedManifestMutationPaths；不得整份覆盖 manifest，"
                    "不得修改未授权的身份、章节、citation、数据集或图表声明。"
                ],
            }
        )
        return {
            "id": requirement_id,
            "passed": False,
            "message": "报告 manifest 不符合 JSON Schema，请只修复指定字段。",
            "details": details,
        }

    invariant_errors = _manifest_invariant_errors(manifest)
    if invariant_errors:
        return {
            "id": requirement_id,
            "passed": False,
            "message": "报告 manifest 不满足正式模型不变量，请按指定路径修复。",
            "details": {
                "manifestInvariantErrors": invariant_errors,
                "repairTarget": manifest_path,
                "relatedRepairTarget": markdown_path,
                "authorizedManifestMutationPaths": ["charts", "citations", "sections"],
                "repairInstructions": [
                    "只修复 manifestInvariantErrors 指定的不变量；变更 citationId 时同步修改 Markdown 中对应 marker，"
                    "随后重新计算 Markdown 的 size 和 SHA-256。"
                ],
            },
        }

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
    expected_sections = validation_context.get("expectedSections", [])
    if expected_sections:
        received_sections = manifest["sections"]
        if received_sections != expected_sections:
            details["manifestSectionMismatch"] = {
                "expected": expected_sections,
                "received": received_sections,
            }
    expected_bindings = validation_context.get("expectedCitationBindings", [])
    if expected_bindings:
        received_bindings = [
            {
                "datasetId": item["datasetId"],
                "requirementId": item["requirementId"],
            }
            for item in manifest["citations"]
        ]
        expected_binding_keys = {
            (item["datasetId"], item["requirementId"]) for item in expected_bindings
        }
        received_binding_keys = {
            (item["datasetId"], item["requirementId"]) for item in received_bindings
        }
        duplicate_binding_count = len(received_bindings) - len(received_binding_keys)
        if expected_binding_keys != received_binding_keys or duplicate_binding_count:
            details["manifestCitationBindingMismatch"] = {
                "missing": [
                    {"datasetId": dataset_id, "requirementId": requirement_id}
                    for dataset_id, requirement_id in sorted(
                        expected_binding_keys - received_binding_keys
                    )
                ],
                "unexpected": [
                    {"datasetId": dataset_id, "requirementId": requirement_id}
                    for dataset_id, requirement_id in sorted(
                        received_binding_keys - expected_binding_keys
                    )
                ],
                "duplicateBindingCount": duplicate_binding_count,
            }
    if details.get("manifestSectionMismatch") or details.get("manifestCitationBindingMismatch"):
        details["repairTarget"] = manifest_path
        details["authorizedManifestMutationPaths"] = ["sections", "citations"]
        details.setdefault("repairInstructions", []).append(
            "manifest 的 sections 必须逐项复制 expectedSections；citations 必须与 Workflow "
            "声明的数据集和需求绑定一一对应。不得删除、替换或伪造绑定来绕过 Markdown 验收。"
        )
        return {
            "id": requirement_id,
            "passed": False,
            "message": "报告 manifest 偏离 Workflow 固定事实，请恢复受保护字段。",
            "details": details,
        }

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
        missing_citation_ids = [
            item["citationId"]
            for item in manifest["citations"]
            if f"[[citation:{item['citationId']}]]" not in markdown
        ]
        missing_section_ids = [
            section for section in manifest["sections"] if f"[[section:{section}]]" not in markdown
        ]
        _issue(
            details,
            "missingCitationIds",
            missing_citation_ids,
        )
        _issue(
            details,
            "missingSectionIds",
            missing_section_ids,
        )
        if missing_citation_ids or missing_section_ids:
            details.update(
                {
                    "repairTarget": markdown_path,
                    "missingCitationMarkers": [
                        f"[[citation:{item}]]" for item in missing_citation_ids
                    ],
                    "missingSectionMarkers": [
                        f"[[section:{item}]]" for item in missing_section_ids
                    ],
                    "repairInstructions": [
                        f"只在 {markdown_path} 中补齐上述协议标记，不要改写 manifest 的 citations 或 sections 清单。",
                        "标记应紧邻对应中文结论或章节标题；章节标题继续使用 effectiveProfile 中的中文 title。",
                        "修改后重新计算 Markdown 的 size 和 SHA-256，并更新 manifest 的 markdown 元数据。",
                    ],
                    "authorizedManifestMutationPaths": ["markdown.size", "markdown.sha256"],
                }
            )
        machine_terms = _visible_machine_terms(
            markdown,
            validation_context.get("forbiddenVisibleTerms", []),
        )
        _issue(details, "visibleMachineTerms", machine_terms)
        if machine_terms:
            details["repairTarget"] = markdown_path
            instructions = details.setdefault("repairInstructions", [])
            instructions.append(
                "将 visibleMachineTerms 对应的可见文字改为中文业务名称；不要修改协议标记、"
                "citations 或 sections 清单。修改后重新计算 Markdown 的 size 和 SHA-256，"
                "并仅更新 manifest 的 markdown 元数据。"
            )
            details["authorizedManifestMutationPaths"] = ["markdown.size", "markdown.sha256"]
        derived_claims = (
            _forbidden_derived_claims(markdown)
            if validation_context.get("prohibitDerivedValues") is True
            else []
        )
        _issue(details, "forbiddenDerivedClaims", derived_claims)
        if derived_claims:
            details["repairTarget"] = markdown_path
            instructions = details.setdefault("repairInstructions", [])
            instructions.append(
                "删除 forbiddenDerivedClaims 中的拟合、估算、推算、插值、外推、年化、"
                "平滑或补齐结果，只保留不可变数据集中的观测值；不要修改数据集、citations、"
                "sections 或 charts 清单。修改后重新计算 Markdown 的 size 和 SHA-256，"
                "并仅更新 manifest 的 markdown 元数据。"
            )
            details["authorizedManifestMutationPaths"] = ["markdown.size", "markdown.sha256"]
        period_claims, unbound_period_claims = _period_claim_issues(
            markdown,
            validation_context.get("observedDataFacts", []),
            manifest["citations"],
        )
        _issue(details, "contradictoryPeriodClaims", period_claims)
        _issue(details, "unboundPeriodClaims", unbound_period_claims)
        if period_claims:
            details["repairTarget"] = markdown_path
            instructions = details.setdefault("repairInstructions", [])
            instructions.append(
                "将 contradictoryPeriodClaims 改为与 observedPeriods 一致的中文观测描述；"
                "已覆盖期间不得写成无记录、缺失、未提供或未出数，零值也必须按有效观测披露。"
                "不要修改数据集或 manifest 清单；修改后重新计算 Markdown 的 size 和 SHA-256，"
                "并仅更新 manifest 的 markdown 元数据。"
            )
            details["authorizedManifestMutationPaths"] = ["markdown.size", "markdown.sha256"]
        if unbound_period_claims:
            details["repairTarget"] = markdown_path
            instructions = details.setdefault("repairInstructions", [])
            instructions.append(
                "为 unboundPeriodClaims 中的期间结论在同一行补充唯一 citation marker；"
                "不得使用其他数据集的缺失期间解释当前结论。修改后重新计算 Markdown 的 size 和 "
                "SHA-256，并仅更新 manifest 的 markdown 元数据。"
            )
            details["authorizedManifestMutationPaths"] = ["markdown.size", "markdown.sha256"]
        markdown_chart_paths, invalid_image_targets = _markdown_image_paths(
            markdown,
            markdown_path,
        )
        manifest_chart_paths = {item["path"] for item in manifest.get("charts", [])}
        missing_markdown_chart_paths = sorted(manifest_chart_paths - markdown_chart_paths)
        unexpected_markdown_image_paths = sorted(markdown_chart_paths - manifest_chart_paths)
        _issue(details, "missingMarkdownChartPaths", missing_markdown_chart_paths)
        _issue(details, "unexpectedMarkdownImagePaths", unexpected_markdown_image_paths)
        _issue(details, "invalidMarkdownImageTargets", invalid_image_targets)
        if missing_markdown_chart_paths and not (
            unexpected_markdown_image_paths or invalid_image_targets
        ):
            details["repairTarget"] = markdown_path
            instructions = details.setdefault("repairInstructions", [])
            instructions.append(
                "在 Markdown 中使用相对路径和中文替代文字引用 missingMarkdownChartPaths "
                "列出的全部图表；不要修改 manifest 的 charts 清单。修改后重新计算 Markdown "
                "的 size 和 SHA-256，并仅更新 manifest 的 markdown 元数据。"
            )
            details["authorizedManifestMutationPaths"] = ["markdown.size", "markdown.sha256"]

    if details:
        details["submittedArtifactPaths"] = sorted(submitted_paths)
    return {
        "id": requirement_id,
        "passed": not details,
        **(
            {
                "message": (
                    "报告 Markdown 的期间结论与固定事实或 citation 绑定不一致，请只修复 Markdown。"
                    if details.get("contradictoryPeriodClaims")
                    or details.get("unboundPeriodClaims")
                    else (
                        "报告 Markdown 包含禁止的数据派生，请只修复 Markdown。"
                        if details.get("forbiddenDerivedClaims")
                        else (
                            "报告 Markdown 缺少协议标记，请只修复 Markdown。"
                            if details.get("missingCitationIds") or details.get("missingSectionIds")
                            else (
                                "报告 Markdown 与图表清单不一致，请只修复 Markdown。"
                                if details.get("missingMarkdownChartPaths")
                                else "报告 Markdown 暴露机器标识，请只修复 Markdown。"
                            )
                        )
                    )
                )
            }
            if "repairTarget" in details
            else {}
        ),
        **({"details": details} if details else {}),
    }


def main() -> None:
    request = json.loads(Path(sys.argv[-1]).read_text(encoding="utf-8"))
    result = {
        "version": 1,
        "requirements": [
            _validate(item, workspace_root=request["workspaceRoot"])
            for item in request["requirements"]
        ],
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
