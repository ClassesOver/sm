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
_REPAIR_WARNING_MARKER = re.compile(r"<!--\s*repair-warning:(period_claim_[a-f0-9]{16})\s*-->")
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


def _warning(details: dict[str, Any], value: dict[str, Any]) -> None:
    details.setdefault("warnings", []).append(value)


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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
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
    ambiguous: list[dict[str, Any]] = []
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
        all_periods = {
            str(period)
            for fact in selected_facts
            for key in ("periodCoverage", "missingPeriods")
            for period in fact.get(key, [])
            if isinstance(period, str)
        }
        claimed_periods = _claimed_periods(claim, all_periods)
        if not claimed_periods:
            continue
        if len(bindings) != 1:
            ambiguous.append(
                {
                    "claim": claim,
                    "citationIds": list(citation_ids),
                    "claimedPeriods": sorted(claimed_periods),
                    "reason": "multiple_citation_bindings",
                }
            )
            continue
        hard_periods: list[str] = []
        ambiguous_periods: list[str] = []
        observed_facts: list[dict[str, Any]] = []
        for period in sorted(claimed_periods):
            statuses: list[str] = []
            period_facts: list[dict[str, Any]] = []
            for fact in selected_facts:
                coverage = {
                    str(value) for value in fact.get("periodCoverage", []) if isinstance(value, str)
                }
                missing = {
                    str(value) for value in fact.get("missingPeriods", []) if isinstance(value, str)
                }
                if period in coverage and period not in missing:
                    statuses.append("observed")
                    period_facts.append(
                        {
                            "sourceId": fact.get("sourceId"),
                            "table": fact.get("table"),
                            "observedPeriods": [period],
                        }
                    )
                elif period in missing and period not in coverage:
                    statuses.append("missing")
                elif period in coverage or period in missing:
                    statuses.append("mixed")
                else:
                    statuses.append("unknown")
            if statuses and all(status == "observed" for status in statuses):
                hard_periods.append(period)
                observed_facts.extend(period_facts)
            elif "observed" in statuses or "mixed" in statuses:
                ambiguous_periods.append(period)
        if hard_periods:
            grouped_facts: dict[tuple[Any, Any], set[str]] = {}
            for fact in observed_facts:
                key = (fact.get("sourceId"), fact.get("table"))
                grouped_facts.setdefault(key, set()).update(fact["observedPeriods"])
            observed_facts = [
                {
                    "sourceId": source_id,
                    "table": table,
                    "observedPeriods": sorted(periods),
                }
                for (source_id, table), periods in grouped_facts.items()
            ]
            issue_payload = json.dumps(
                {
                    "claim": claim,
                    "citationIds": list(citation_ids),
                    "observedPeriods": hard_periods,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            issue: dict[str, Any] = {
                "issueId": "period_claim_"
                + hashlib.sha256(issue_payload.encode()).hexdigest()[:16],
                "claim": claim,
                "observedPeriods": hard_periods,
                "observedFacts": observed_facts,
                "suggestedAction": "改为有效观测描述",
            }
            if citation_ids:
                issue["citationIds"] = list(citation_ids)
            contradictions.append(issue)
        if ambiguous_periods:
            ambiguous.append(
                {
                    "claim": claim,
                    "citationIds": list(citation_ids),
                    "claimedPeriods": ambiguous_periods,
                    "reason": "mixed_table_coverage",
                }
            )
    return contradictions, unbound, ambiguous


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
    extended_keys = expected_keys | {"expectedCitations"}
    if (
        not isinstance(context, dict)
        or frozenset(context) not in {frozenset(expected_keys), frozenset(extended_keys)}
        or context.get("version") != 1
    ):
        return None, "content_invalid"
    return context, None


def _server_manifest(
    expected: dict[str, Any],
    validation_context: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    markdown: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    markdown_path = expected["markdownPath"]
    markdown_artifact = artifacts[markdown_path]
    citations = validation_context.get("expectedCitations") or [
        {
            "citationId": f"citation_{index:03d}",
            "datasetId": item["datasetId"],
            "requirementId": item["requirementId"],
        }
        for index, item in enumerate(
            validation_context.get("expectedCitationBindings", []), start=1
        )
    ]
    citation_datasets = {item["citationId"]: item["datasetId"] for item in citations}
    lines = markdown.splitlines()
    parent = PurePosixPath(markdown_path).parent
    bindings: dict[str, set[str]] = {}
    invalid_targets: list[str] = []
    unbound_paths: list[str] = []
    unknown_citations: set[str] = set()
    for token in MarkdownIt("commonmark").parse(markdown):
        images = [item for item in token.children or () if item.type == "image"]
        if not images:
            continue
        start, end = token.map or (0, len(lines))
        marker_ids = set(_CITATION_MARKER.findall("\n".join(lines[start:end])))
        unknown_citations.update(marker_ids - set(citation_datasets))
        for image in images:
            source = str(image.attrGet("src") or "")
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
            path = parent.joinpath(relative).as_posix()
            valid_ids = marker_ids & set(citation_datasets)
            if not valid_ids:
                unbound_paths.append(path)
                continue
            bindings.setdefault(path, set()).update(citation_datasets[item] for item in valid_ids)
    details: dict[str, Any] = {}
    _issue(details, "invalidMarkdownImageTargets", sorted(set(invalid_targets)))
    _issue(details, "unboundMarkdownChartPaths", sorted(set(unbound_paths)))
    _issue(details, "unknownChartCitationIds", sorted(unknown_citations))
    artifact_paths = set(artifacts) - {markdown_path}
    image_paths = {
        path
        for path in artifact_paths
        if PurePosixPath(path).suffix.lower() in {".png", ".jpg", ".jpeg"}
    }
    _issue(details, "missingArtifactPaths", sorted(set(bindings) - image_paths))
    _issue(details, "invalidChartArtifactPaths", sorted(artifact_paths - image_paths))
    media_types: dict[str, str] = {}
    for path in image_paths:
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".png":
            media_types[path] = "image/png"
        elif suffix in {".jpg", ".jpeg"}:
            media_types[path] = "image/jpeg"
    unused_paths = sorted(image_paths - set(bindings))
    if details:
        details.update(
            {
                "repairTarget": markdown_path,
                "repairInstructions": [
                    "只修改报告 Markdown：每个图表使用安全相对路径，并在同一段落放置至少一个 Workflow citation marker；不得创建或修改 manifest。"
                ],
            }
        )
        return None, details
    report_details: dict[str, Any] = {}
    if unused_paths:
        _warning(
            report_details,
            {
                "code": "unused_artifacts",
                "paths": unused_paths,
                "message": "未被 Markdown 引用的图表不会进入发布包。",
            },
        )
        report_details["autoFixes"] = [
            {
                "code": "unused_artifacts_excluded",
                "paths": unused_paths,
            }
        ]
    charts = [
        {
            "path": path,
            "mediaType": media_types[path],
            "size": artifacts[path]["size"],
            "sha256": artifacts[path]["sha256"],
            "chartId": f"chart_{index:03d}",
            "datasetIds": sorted(bindings[path]),
        }
        for index, path in enumerate(sorted(bindings), start=1)
    ]
    return (
        {
            "reportId": expected["reportId"],
            "revision": expected["revision"],
            "codingTaskKey": expected["codingTaskKey"],
            "datasetSnapshotHash": expected["datasetSnapshotHash"],
            "effectiveProfileHash": expected["effectiveProfileHash"],
            "markdown": {
                "path": markdown_path,
                "mediaType": "text/markdown",
                "size": markdown_artifact["size"],
                "sha256": markdown_artifact["sha256"],
            },
            "charts": charts,
            "citations": citations,
            "sections": validation_context["expectedSections"],
        },
        report_details,
    )


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
    server_generated = expected.get("manifestAuthority") == "server"

    validation_context, context_error = _load_validation_context(
        workspace_root, parameters.get("validationContextFile")
    )
    if validation_context is None:
        return {
            "id": requirement_id,
            "passed": False,
            "details": {"validationContextError": context_error or "content_invalid"},
        }

    markdown_artifact = by_path.get(markdown_path)
    manifest_artifact = by_path.get(manifest_path)
    if markdown_artifact is None or (not server_generated and manifest_artifact is None):
        required_artifacts = [(markdown_path, markdown_artifact)]
        if not server_generated:
            required_artifacts.append((manifest_path, manifest_artifact))
        missing_paths = [path for path, artifact in required_artifacts if artifact is None]
        return {
            "id": requirement_id,
            "passed": False,
            "details": {"missingArtifactPaths": missing_paths},
        }

    if server_generated:
        if manifest_artifact is not None:
            return {
                "id": requirement_id,
                "passed": False,
                "message": "manifest 只能由服务端生成。",
                "details": {
                    "unexpectedArtifactPaths": [manifest_path],
                    "repairInstructions": [
                        "从 verify 和 finish_task 的 artifact_paths 删除 manifest。"
                    ],
                },
            }
        try:
            markdown_for_manifest = Path(markdown_artifact["absolutePath"]).read_text(
                encoding="utf-8"
            )
        except (OSError, UnicodeError) as error:
            return {
                "id": requirement_id,
                "passed": False,
                "details": {"markdownError": type(error).__name__},
            }
        manifest, server_details = _server_manifest(
            expected, validation_context, by_path, markdown_for_manifest
        )
        if manifest is None:
            return {
                "id": requirement_id,
                "passed": False,
                "message": "报告 Markdown 与图表引用契约不一致，请只修复 Markdown。",
                "details": server_details,
            }
        details.update(server_details)
    else:
        assert manifest_artifact is not None
        try:
            manifest = json.loads(
                Path(manifest_artifact["absolutePath"]).read_text(encoding="utf-8")
            )
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
        **({"manifestAuthority": "server"} if server_generated else {}),
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
    expected_paths = declared_paths | (set() if server_generated else {manifest_path})
    submitted_paths = set(by_path)
    _issue(details, "missingArtifactPaths", sorted(expected_paths - submitted_paths))
    unexpected_paths = submitted_paths - expected_paths
    if server_generated:
        unexpected_paths = {
            path
            for path in unexpected_paths
            if PurePosixPath(path).suffix.lower() not in {".png", ".jpg", ".jpeg"}
        }
    _issue(details, "unexpectedArtifactPaths", sorted(unexpected_paths))

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
                        f"只在 {markdown_path} 中补齐上述协议标记，不得创建或修改 manifest。",
                        "标记应紧邻对应中文结论或章节标题；章节标题继续使用 effectiveProfile 中的中文 title。服务端会自动重算 Markdown 元数据。",
                    ],
                }
            )
        machine_terms = _visible_machine_terms(
            markdown,
            validation_context.get("forbiddenVisibleTerms", []),
        )
        if machine_terms:
            _warning(
                details,
                {
                    "code": "visible_machine_terms",
                    "items": machine_terms,
                    "message": "可见正文包含机器字段名；有中文 metadata 映射时应自动替换，否则进入发布审核。",
                },
            )
        derived_claims = (
            _forbidden_derived_claims(markdown)
            if validation_context.get("prohibitDerivedValues") is True
            else []
        )
        if derived_claims:
            _warning(
                details,
                {
                    "code": "derived_value_keywords",
                    "items": derived_claims,
                    "message": "正文包含估算或推算关键词；正则命中只进入发布审核，不单独阻断验收。",
                },
            )
        period_claims, unbound_period_claims, ambiguous_period_claims = _period_claim_issues(
            markdown,
            validation_context.get("observedDataFacts", []),
            manifest["citations"],
        )
        repair_warning_ids = set(_REPAIR_WARNING_MARKER.findall(markdown))
        unresolved_repair_claims = [
            item for item in period_claims if item.get("issueId") in repair_warning_ids
        ]
        period_claims = [
            item for item in period_claims if item.get("issueId") not in repair_warning_ids
        ]
        _issue(details, "contradictoryPeriodClaims", period_claims)
        if unresolved_repair_claims:
            _warning(
                details,
                {
                    "code": "unresolved_repair_issues",
                    "items": unresolved_repair_claims,
                    "message": "期间表述未能由受限修复工具自动改写，已写入报告发布审核提示。",
                },
            )
        if unbound_period_claims:
            _warning(
                details,
                {
                    "code": "unbound_period_claims",
                    "items": unbound_period_claims,
                    "message": "期间描述没有唯一 citation 绑定，交由发布审核判断。",
                },
            )
        if ambiguous_period_claims:
            _warning(
                details,
                {
                    "code": "period_binding_ambiguous",
                    "items": ambiguous_period_claims,
                    "message": "期间结论存在多 citation 或多表覆盖歧义，交由发布审核判断。",
                },
            )
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

    blocking_details = {
        key: value for key, value in details.items() if key not in {"warnings", "autoFixes"}
    }
    if server_generated and blocking_details.get("repairTarget") == markdown_path:
        details.pop("authorizedManifestMutationPaths", None)
        details["repairInstructions"] = [
            f"只修改 {markdown_path} 中 failedRequirements 明确列出的内容；不得创建或修改 manifest。",
            "修改后重新提交 Markdown 及其中实际引用的图表；服务端会自动重算 size、SHA-256 并生成 manifest。",
        ]
        blocking_details = {
            key: value for key, value in details.items() if key not in {"warnings", "autoFixes"}
        }
    if blocking_details:
        details["submittedArtifactPaths"] = sorted(submitted_paths)
    return {
        "id": requirement_id,
        "passed": not blocking_details,
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
            if "repairTarget" in blocking_details
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
