from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from .models import (
    PROFILE_DIRECTORY_NAME,
    EffectiveDimension,
    EffectiveMetric,
    EffectivePageLayout,
    EffectiveReconciliation,
    EffectiveReportingProfile,
    EffectiveScopeFilter,
    EffectiveSection,
    ReportingProfileDocument,
    ReportingProfileRegistry,
    effective_profile_hash,
)

MAX_PROFILE_BYTES = 1024 * 1024
MAX_PROFILES = 500
_REQUIRED_SECTION_CODES = frozenset(
    {
        "executive_summary",
        "scope_and_methodology",
        "key_findings",
        "limitations",
        "recommendations",
    }
)
_FORBIDDEN_KEYS = frozenset(
    {
        "connection",
        "connectionstring",
        "databaseurl",
        "dsn",
        "dsnenv",
        "host",
        "hostname",
        "password",
        "port",
        "pwd",
        "url",
        "user",
        "username",
    }
)


def load_configured_reporting_profiles(
    configured_dir: str | Path | None,
    *,
    current_dir: str | Path | None = None,
) -> ReportingProfileRegistry:
    boundary = Path(configured_dir or Path.cwd()).resolve(strict=True)
    start = Path(current_dir or boundary).resolve(strict=True)
    try:
        relative = start.relative_to(boundary)
    except ValueError:
        start = boundary
        relative = Path()
    directories = [boundary]
    current = boundary
    for part in relative.parts:
        current /= part
        directories.append(current)
    documents: dict[str, ReportingProfileDocument] = {}
    paths: list[Path] = []
    for directory in directories:
        root = directory / PROFILE_DIRECTORY_NAME
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"Profile 根目录必须是普通目录: {root}")
        layer_ids: set[str] = set()
        for path in _profile_files(root):
            document = _load_profile(path)
            if document.profile_id in layer_ids:
                raise ValueError(f"同一配置层的 profileId 重复: {document.profile_id}")
            layer_ids.add(document.profile_id)
            documents[document.profile_id] = document
            paths.append(path)
    if len(documents) > MAX_PROFILES:
        raise ValueError(f"生效 Profile 不能超过 {MAX_PROFILES} 个。")
    return ReportingProfileRegistry(documents=documents, config_paths=tuple(paths))


def resolve_reporting_profile(
    registry: ReportingProfileRegistry,
    profile_id: str | None,
) -> EffectiveReportingProfile:
    if profile_id is None:
        return _builtin_profile()
    ordered: list[ReportingProfileDocument] = []
    visited: set[str] = set()
    active: set[str] = set()

    def visit(current_id: str) -> None:
        if current_id in visited:
            return
        if current_id in active:
            raise ValueError("Profile extends 存在循环依赖。")
        document = registry.documents.get(current_id)
        if document is None:
            raise ValueError(f"Profile 不存在: {current_id}")
        active.add(current_id)
        for parent_id in document.extends:
            visit(parent_id)
        active.remove(current_id)
        visited.add(current_id)
        ordered.append(document)

    visit(profile_id)
    dimensions = _merge_items(ordered, "dimensions")
    metrics = _merge_items(ordered, "metrics")
    reconciliations = _merge_items(ordered, "reconciliations")
    scope_filters = _merge_items(ordered, "scope_filters")
    measure_semantics = _merge_measure_semantics(ordered)
    sections = _merge_items(ordered, "sections")
    section_order = next(
        (
            document.section_order
            for document in reversed(ordered)
            if document.section_order is not None
        ),
        None,
    )
    if section_order is not None:
        sections_by_code = {item["code"]: item for item in sections}
        if set(section_order) != set(sections_by_code):
            raise ValueError("sectionOrder 必须且只能包含全部生效章节 code。")
        sections = tuple(sections_by_code[code] for code in section_order)
    effective_dimensions = tuple(EffectiveDimension.model_validate(item) for item in dimensions)
    effective_metrics = tuple(EffectiveMetric.model_validate(item) for item in metrics)
    effective_reconciliations = tuple(
        EffectiveReconciliation.model_validate(item) for item in reconciliations
    )
    effective_scope_filters = tuple(
        EffectiveScopeFilter.model_validate(item) for item in scope_filters
    )
    effective_sections = tuple(EffectiveSection.model_validate(item) for item in sections)
    layout: dict[str, Any] = {}
    for document in ordered:
        if document.page_layout is not None:
            layout.update(
                document.page_layout.model_dump(
                    mode="json", by_alias=True, exclude_none=True, exclude_unset=True
                )
            )
    effective_layout = EffectivePageLayout.model_validate(layout)
    if not effective_sections:
        raise ValueError("有效 Profile 至少需要一个报告章节。")
    _validate_references(
        effective_dimensions,
        effective_metrics,
        effective_reconciliations,
        effective_sections,
    )
    payload: dict[str, object] = {
        "profileId": profile_id,
        "revision": ordered[-1].revision,
        "layers": [{"profileId": item.profile_id, "revision": item.revision} for item in ordered],
        "dimensions": [
            item.model_dump(mode="json", by_alias=True) for item in effective_dimensions
        ],
        "metrics": [item.model_dump(mode="json", by_alias=True) for item in effective_metrics],
        "reconciliations": [
            item.model_dump(mode="json", by_alias=True) for item in effective_reconciliations
        ],
        "scopeFilters": [
            item.model_dump(mode="json", by_alias=True) for item in effective_scope_filters
        ],
        "measureSemantics": [
            item.model_dump(mode="json", by_alias=True) for item in measure_semantics
        ],
        "sections": [item.model_dump(mode="json", by_alias=True) for item in effective_sections],
        "pageLayout": effective_layout.model_dump(mode="json", by_alias=True),
    }
    return EffectiveReportingProfile.model_validate(
        {**payload, "effectiveProfileHash": effective_profile_hash(payload)}
    )


def _profile_files(root: Path) -> tuple[Path, ...]:
    result: list[Path] = []
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in names:
            if (base / name).is_symlink():
                raise ValueError("Profile 目录不得包含符号链接。")
        for name in files:
            path = base / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Profile 必须是普通文件。")
            if path.suffix.lower() == ".json":
                result.append(path)
    return tuple(sorted(result))


def _load_profile(path: Path) -> ReportingProfileDocument:
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise ValueError(f"Profile 超过 1 MiB: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Profile 无法读取: {path}") from error
    if _contains_forbidden_key(payload):
        raise ValueError(f"Profile 包含连接字段: {path}")
    try:
        return ReportingProfileDocument.model_validate(payload)
    except Exception as error:
        raise ValueError(f"Profile 不符合 v1 契约: {path}") from error


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized in _FORBIDDEN_KEYS or _contains_forbidden_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _merge_items(
    documents: list[ReportingProfileDocument],
    field: str,
) -> tuple[dict[str, Any], ...]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for document in documents:
        values = getattr(document, field)
        for item in values:
            raw = item.model_dump(mode="json", by_alias=True, exclude_unset=True)
            code = item.code
            if item.enabled is False:
                merged.pop(code, None)
                if code in order:
                    order.remove(code)
                continue
            raw.pop("enabled", None)
            if code not in merged:
                order.append(code)
                merged[code] = {"code": code}
            merged[code].update(raw)
    return tuple(merged[code] for code in order)


def _merge_measure_semantics(
    documents: list[ReportingProfileDocument],
) -> tuple[Any, ...]:
    merged: dict[str, Any] = {}
    order: list[str] = []
    for document in documents:
        for item in document.measure_semantics:
            field_ref = item.field_ref.lower()
            if field_ref not in merged:
                order.append(field_ref)
            merged[field_ref] = item
    return tuple(merged[field_ref] for field_ref in order)


def _validate_references(
    dimensions: tuple[EffectiveDimension, ...],
    metrics: tuple[EffectiveMetric, ...],
    reconciliations: tuple[EffectiveReconciliation, ...],
    sections: tuple[EffectiveSection, ...],
) -> None:
    dimension_codes = {item.code for item in dimensions}
    metric_map = {item.code: item for item in metrics}
    capability_codes = dimension_codes | set(metric_map) | {item.code for item in reconciliations}
    if not _REQUIRED_SECTION_CODES.issubset({item.code for item in sections}):
        raise ValueError("Profile 缺少领域无关的基础章节。")
    for metric in metrics:
        if metric.aggregation == "ratio" and {
            metric.numerator_metric,
            metric.denominator_metric,
        } - set(metric_map):
            raise ValueError("ratio 指标依赖不存在。")
    for item in reconciliations:
        if {item.left_metric, item.right_metric} - set(metric_map) or set(
            item.grain
        ) - dimension_codes:
            raise ValueError("对账规则引用了未知指标或维度。")
        if any(
            metric_map[code].aggregation not in {"sum", "count"}
            for code in (item.left_metric, item.right_metric)
        ):
            raise ValueError("对账规则当前只支持 sum 和 count 基础指标。")
    for section in sections:
        if set(section.required_capabilities) - capability_codes:
            raise ValueError("章节引用了未知 capability。")


def _builtin_profile() -> EffectiveReportingProfile:
    sections = tuple(
        EffectiveSection(code=code, title=title, required=True)
        for code, title in (
            ("executive_summary", "执行摘要"),
            ("scope_and_methodology", "分析范围与方法"),
            ("key_findings", "关键发现"),
            ("limitations", "局限性"),
            ("recommendations", "建议"),
        )
    )
    payload: dict[str, object] = {
        "profileId": "builtin-generic",
        "revision": "1",
        "layers": [{"profileId": "builtin-generic", "revision": "1"}],
        "dimensions": [],
        "metrics": [],
        "reconciliations": [],
        "scopeFilters": [],
        "measureSemantics": [],
        "sections": [item.model_dump(mode="json", by_alias=True) for item in sections],
        "pageLayout": EffectivePageLayout().model_dump(mode="json", by_alias=True),
    }
    return EffectiveReportingProfile.model_validate(
        {**payload, "effectiveProfileHash": effective_profile_hash(payload)}
    )
