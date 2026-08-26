"""Analysis-plan structural and semantic validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import ValidationError

from .base import (
    AnalysisBundle,
    AnalysisItem,
    DataUnderstandingPlan,
    ModelColumn,
    ModelTable,
    QueryRequirement,
    ReportingError,
    ReportRequestEnvelope,
    SequenceMatcher,
    SourceSchemaSnapshot,
)
from .models import _NUMERIC_MEASURE_TYPE_PATTERN


def _validate_requirements_match_understanding(
    requirements: tuple[QueryRequirement, ...],
    plan: DataUnderstandingPlan,
) -> None:
    selected = {(item.source_id, item.table): item for item in plan.tables}
    for requirement in requirements:
        for table in requirement.tables:
            matches = [
                item
                for (source_id, qualified), item in selected.items()
                if source_id == requirement.source_id
                and (qualified == table.table or qualified.endswith(f".{table.table}"))
            ]
            if len(matches) != 1:
                raise ReportingError(
                    "report_analysis_plan_invalid",
                    "分析计划引用了数据理解计划外的数据表。",
                )
            understood = matches[0]
            if (
                understood.period_column.lower() != table.period_column.lower()
                or understood.period_granularity != table.period_granularity
            ):
                raise ReportingError(
                    "report_analysis_plan_invalid",
                    "分析计划的期间语义与数据理解计划不一致。",
                )


def _analysis_bundle_semantic_issues(
    bundle: AnalysisBundle,
    plan: DataUnderstandingPlan,
    snapshots: tuple[SourceSchemaSnapshot, ...],
    envelope: ReportRequestEnvelope | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        _validate_requirements_match_understanding(bundle.requirements, plan)
    except ReportingError as error:
        issues.append(
            {
                "path": "requirements",
                "rejectedValue": [
                    item.model_dump(mode="json", by_alias=True) for item in bundle.requirements
                ],
                "reason": error.message,
                "requiredAction": (
                    "只引用 dataUnderstanding 中已选择的 sourceId、table、periodColumn "
                    "和 periodGranularity"
                ),
            }
        )
    for index, requirement in enumerate(bundle.requirements):
        if envelope is not None:
            _, comparison_issue = _resolve_requirement_comparison_roles(
                requirement,
                index,
                envelope,
            )
            if comparison_issue is not None:
                issues.append(comparison_issue)
        issues.extend(_requirement_column_issues(requirement, index, snapshots))
        issues.extend(_measure_column_issues(requirement, index, snapshots))
        issues.extend(_measure_semantic_issues(requirement, index, snapshots))
        issues.extend(_multi_table_requirement_issues(requirement, index, snapshots))
    requirement_ids = {item.requirement_id for item in bundle.requirements}
    for index, analysis in enumerate(bundle.analyses):
        unknown = sorted(set(analysis.requirement_ids) - requirement_ids)
        if unknown:
            allowed_values = sorted(requirement_ids)
            issue = {
                "path": f"analyses[{index}].requirementIds",
                "rejectedValue": unknown,
                "reason": "分析计划引用了 requirements 中不存在的 requirementId",
                "allowedValues": allowed_values,
                "requiredAction": "从 allowedValues 选择正确引用或在 requirements 中补齐完整需求",
            }
            suggested = _suggested_replacement(unknown, allowed_values)
            if suggested is not None:
                issue["suggestedReplacement"] = suggested
            issues.append(issue)
    return issues


def _requirement_column_issues(
    requirement: QueryRequirement,
    requirement_index: int,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    available_tables = _available_tables(snapshots)
    table_columns: list[set[str]] = []
    issues: list[dict[str, Any]] = []
    for table_index, table in enumerate(requirement.tables):
        matches = [
            model
            for (source_id, qualified), model in available_tables.items()
            if source_id == requirement.source_id
            and (qualified == table.table or qualified.endswith(f".{table.table}"))
        ]
        if len(matches) != 1:
            continue
        model = matches[0]
        columns = {column.name.lower() for column in model.columns}
        table_columns.append(columns)
        unknown_measures = sorted(set(table.measure_columns) - columns)
        if unknown_measures:
            allowed = sorted(
                column.name
                for column in model.columns
                if _NUMERIC_MEASURE_TYPE_PATTERN.match(column.data_type) is not None
                and column.name.lower() != table.period_column
            )
            issues.append(
                {
                    "path": (
                        f"requirements[{requirement_index}].tables[{table_index}].measureColumns"
                    ),
                    "rejectedValue": unknown_measures,
                    "reason": "measureColumns 引用了当前表结构快照中不存在的字段",
                    "allowedValues": allowed,
                    "requiredAction": "删除 rejectedValue，或从 allowedValues 选择真实数值指标字段",
                }
            )

    if not table_columns:
        return issues
    dimension_columns = set().union(*table_columns)
    unknown_dimensions = sorted(set(requirement.dimension_columns) - dimension_columns)
    if unknown_dimensions:
        issues.append(
            {
                "path": f"requirements[{requirement_index}].dimensionColumns",
                "rejectedValue": unknown_dimensions,
                "reason": "dimensionColumns 引用了 requirement 数据表结构快照中不存在的字段",
                "allowedValues": sorted(dimension_columns),
                "requiredAction": "删除或替换 rejectedValue，保留其他有效维度",
            }
        )

    if len(requirement.tables) == 1:
        grain_columns = table_columns[0]
        unknown_grain = sorted(set(requirement.grain_columns) - grain_columns)
        if unknown_grain:
            issues.append(
                {
                    "path": f"requirements[{requirement_index}].grainColumns",
                    "rejectedValue": unknown_grain,
                    "reason": "grainColumns 引用了当前表结构快照中不存在的字段",
                    "allowedValues": sorted(grain_columns),
                    "requiredAction": "删除或替换 rejectedValue，保留其他有效粒度",
                }
            )
    return issues


def _measure_column_issues(
    requirement: QueryRequirement,
    requirement_index: int,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    available_tables = _available_tables(snapshots)
    dimensions = set(requirement.dimension_columns)
    overlapping_dimensions: set[str] = set()
    measure_issues: list[dict[str, Any]] = []
    for table_index, table in enumerate(requirement.tables):
        matches = [
            model
            for (source_id, qualified), model in available_tables.items()
            if source_id == requirement.source_id
            and (qualified == table.table or qualified.endswith(f".{table.table}"))
        ]
        if len(matches) != 1:
            continue
        model = matches[0]
        columns = {column.name.lower(): column for column in model.columns}
        overlapping_dimensions.update(
            name
            for name in table.measure_columns
            if name in dimensions
            and name in columns
            and _NUMERIC_MEASURE_TYPE_PATTERN.match(columns[name].data_type) is not None
            and name != table.period_column
        )
        invalid = [
            columns[name]
            for name in table.measure_columns
            if name in columns
            and (
                _NUMERIC_MEASURE_TYPE_PATTERN.match(columns[name].data_type) is None
                or name == table.period_column
            )
        ]
        if not invalid:
            continue
        allowed = sorted(
            column.name
            for column in model.columns
            if _NUMERIC_MEASURE_TYPE_PATTERN.match(column.data_type) is not None
            and column.name.lower() != table.period_column
            and column.name.lower() not in dimensions
        )
        measure_issues.append(
            {
                "path": (f"requirements[{requirement_index}].tables[{table_index}].measureColumns"),
                "rejectedValue": [
                    {"column": column.name, "dataType": column.data_type} for column in invalid
                ],
                "reason": (
                    "measureColumns 只能声明需要聚合的数值指标；期间、分类和文本字段不是可聚合指标"
                ),
                "allowedValues": allowed,
                "requiredAction": (
                    "从 allowedValues 选择可聚合数值字段；需要分组展示的分类字段"
                    "放入 dimensionColumns 和适用的 grainColumns"
                ),
            }
        )
    issues: list[dict[str, Any]] = []
    if overlapping_dimensions:
        rejected = [
            column for column in requirement.dimension_columns if column in overlapping_dimensions
        ]
        issues.append(
            {
                "path": f"requirements[{requirement_index}].dimensionColumns",
                "rejectedValue": rejected,
                "reason": "数值指标不能同时声明为 measureColumns 和 dimensionColumns",
                "allowedValues": [
                    column
                    for column in requirement.dimension_columns
                    if column not in overlapping_dimensions
                ],
                "requiredAction": "从 dimensionColumns 删除 rejectedValue，保留原有其他维度",
            }
        )
        overlapping_grain = [
            column for column in requirement.grain_columns if column in overlapping_dimensions
        ]
        if overlapping_grain:
            issues.append(
                {
                    "path": f"requirements[{requirement_index}].grainColumns",
                    "rejectedValue": overlapping_grain,
                    "reason": "聚合数值指标不能作为分组粒度",
                    "allowedValues": [
                        column
                        for column in requirement.grain_columns
                        if column not in overlapping_dimensions
                    ],
                    "requiredAction": "从 grainColumns 删除 rejectedValue，保留原有其他粒度",
                }
            )
    return [*issues, *measure_issues]


def _measure_semantic_issues(
    requirement: QueryRequirement,
    requirement_index: int,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    semantics = {
        item.field_ref.lower(): item
        for snapshot in snapshots
        for item in snapshot.measure_semantics
    }
    issues: list[dict[str, Any]] = []
    missing_grain_columns: set[str] = set()
    ordered_table_columns: list[str] = []
    for table_index, table in enumerate(requirement.tables):
        qualified = table.table if "." in table.table else ""
        if not qualified:
            matches = [
                model
                for snapshot in snapshots
                for model in snapshot.tables
                if model.source_id == requirement.source_id and model.name.lower() == table.table
            ]
            if len(matches) != 1:
                continue
            qualified = f"{matches[0].database}.{matches[0].name}".lower()
        table_models = [
            model
            for snapshot in snapshots
            for model in snapshot.tables
            if model.source_id == requirement.source_id
            and f"{model.database}.{model.name}".lower() == qualified
        ]
        if len(table_models) != 1:
            continue
        columns = {column.name.lower(): column for column in table_models[0].columns}
        table_columns = set(columns)
        ordered_table_columns.extend(
            column.name.lower()
            for column in table_models[0].columns
            if column.name.lower() not in ordered_table_columns
        )
        # periodColumn 不只是 SQL WHERE 边界，也是 CSV 分析的期间事实来源。
        # 即使指标声明可跨该列相加，也必须保留在 SELECT/GROUP BY 和不可变数据集中；
        # 否则 Coding 无法判断每行属于哪个月，不能用查询窗口代替行事实。
        if table.period_column not in requirement.grain_columns:
            missing_grain_columns.add(table.period_column)
        table_prefix = f"{requirement.source_id}.{qualified}.".lower()
        declared_measure_columns = {
            field_ref.rsplit(".", 1)[-1]
            for field_ref in semantics
            if field_ref.startswith(table_prefix)
        }
        for measure in table.measure_columns:
            column = columns.get(measure)
            if (
                column is None
                or _NUMERIC_MEASURE_TYPE_PATTERN.match(column.data_type) is None
                or measure in requirement.dimension_columns
            ):
                continue
            field_ref = f"{requirement.source_id}.{qualified}.{measure}".lower()
            semantic = semantics.get(field_ref)
            path = f"requirements[{requirement_index}].tables[{table_index}].measureColumns"
            if semantic is None:
                allowed = sorted(
                    item.field_ref.rsplit(".", 1)[-1]
                    for item in semantics.values()
                    if item.field_ref.lower().startswith(
                        f"{requirement.source_id}.{qualified}.".lower()
                    )
                )
                issues.append(
                    {
                        "path": path,
                        "rejectedValue": measure,
                        "reason": "字段未获服务端结构快照批准为可聚合指标，禁止猜测聚合口径",
                        "allowedValues": allowed,
                        "requiredAction": (
                            "只保留 allowedValues 中已批准的指标；为空时删除整个 requirement，"
                            "并删除仅引用它的 analysis 或从混合引用中移除该 requirementId；"
                            "不得改用无关指标或把 rejectedValue 移入维度伪装通过"
                        ),
                    }
                )
                continue
            forbidden = sorted(
                table_columns
                - declared_measure_columns
                - set(requirement.grain_columns)
                - set(semantic.additive_across)
                - set(semantic.exclusive_scope)
            )
            missing_grain_columns.update(forbidden)
    if missing_grain_columns:
        missing = [name for name in ordered_table_columns if name in missing_grain_columns]
        target_dimensions = list(dict.fromkeys((*requirement.dimension_columns, *missing)))
        target_grain = list(dict.fromkeys((*requirement.grain_columns, *missing)))
        issue: dict[str, Any] = {
            "path": f"requirements[{requirement_index}].grainColumns",
            "missingValues": missing,
            "reason": "指标表存在未保留、未固定且未声明为可加的维度",
            "repairTargets": [
                f"requirements[{requirement_index}].dimensionColumns",
                f"requirements[{requirement_index}].grainColumns",
            ],
            "requiredAction": (
                "将 missingValues 同时追加到 dimensionColumns 和 grainColumns；"
                "不得删除原有字段或修改表、指标及分析引用"
            ),
        }
        if len(target_dimensions) <= 30 and len(target_grain) <= 30:
            issue["targetValues"] = {
                "dimensionColumns": target_dimensions,
                "grainColumns": target_grain,
            }
        else:
            issue["requiredColumnCount"] = max(len(target_dimensions), len(target_grain))
            issue["maxColumnCount"] = 30
            issue["requiredAction"] = (
                "完整安全粒度超过契约上限；减少当前 requirement 的 measureColumns，"
                "或通过已审核 Profile/metadata 补充可加维度或固定范围后重新规划"
            )
        issues.append(issue)
    return issues


def _normalize_analysis_bundle_grain(
    bundle: AnalysisBundle,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[AnalysisBundle, list[dict[str, Any]]]:
    """只追加服务端可证明的安全粒度，不替模型改写分析意图。"""

    normalized_requirements: list[QueryRequirement] = []
    repairs: list[dict[str, Any]] = []
    for index, requirement in enumerate(bundle.requirements):
        if len(requirement.tables) != 1:
            normalized_requirements.append(requirement)
            continue
        semantic_issues = _measure_semantic_issues(requirement, index, snapshots)
        if any(str(issue.get("path", "")).endswith(".measureColumns") for issue in semantic_issues):
            normalized_requirements.append(requirement)
            continue
        grain_issue = next(
            (
                issue
                for issue in semantic_issues
                if issue.get("path") == f"requirements[{index}].grainColumns"
                and isinstance(issue.get("targetValues"), Mapping)
            ),
            None,
        )
        if grain_issue is None:
            normalized_requirements.append(requirement)
            continue
        target_values = grain_issue["targetValues"]
        payload = requirement.model_dump(mode="json", by_alias=True)
        payload["dimensionColumns"] = target_values["dimensionColumns"]
        payload["grainColumns"] = target_values["grainColumns"]
        try:
            normalized = QueryRequirement.model_validate(payload)
        except ValidationError:
            normalized_requirements.append(requirement)
            continue
        normalized_requirements.append(normalized)
        repairs.append(
            {
                "requirementId": requirement.requirement_id,
                "addedColumns": grain_issue["missingValues"],
                "repairTargets": grain_issue["repairTargets"],
            }
        )
    if not repairs:
        return bundle, []
    normalized_bundle = AnalysisBundle.model_validate(
        {
            "analyses": [item.model_dump(mode="json", by_alias=True) for item in bundle.analyses],
            "requirements": [
                item.model_dump(mode="json", by_alias=True) for item in normalized_requirements
            ],
        }
    )
    return normalized_bundle, repairs


def _normalize_requirement_columns(
    bundle: AnalysisBundle,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[AnalysisBundle, list[dict[str, Any]]]:
    """删除结构快照外的维度/粒度字段，不猜测语义别名或补充新字段。"""

    normalized_requirements: list[QueryRequirement] = []
    repairs: list[dict[str, Any]] = []
    for requirement in bundle.requirements:
        normalized, repair = _normalize_requirement_column_values(requirement, snapshots)
        normalized_requirements.append(normalized)
        if repair is not None:
            repairs.append(repair)
    if not repairs:
        return bundle, []
    return (
        AnalysisBundle.model_validate(
            {
                "analyses": [
                    item.model_dump(mode="json", by_alias=True) for item in bundle.analyses
                ],
                "requirements": [
                    item.model_dump(mode="json", by_alias=True) for item in normalized_requirements
                ],
            }
        ),
        repairs,
    )


def _normalize_requirement_periods(
    bundle: AnalysisBundle,
    plan: DataUnderstandingPlan,
) -> tuple[AnalysisBundle, list[dict[str, Any]]]:
    """把取数期间恢复为已冻结的数据理解事实，不让规划模型重新解释字段语义。

    DataUnderstandingPlan 已依据真实 Schema 和字段值完成审批，是期间字段与粒度的
    唯一事实来源。这里只处理 sourceId/table 能唯一命中的表；未知或多义引用仍交给
    后续语义校验失败关闭，不能通过相似名称猜测替换。
    """

    selected = {(item.source_id, item.table): item for item in plan.tables}
    normalized_requirements: list[QueryRequirement] = []
    repairs: list[dict[str, Any]] = []
    for requirement in bundle.requirements:
        normalized_tables = []
        for table_index, table in enumerate(requirement.tables):
            matches = [
                item
                for (source_id, qualified), item in selected.items()
                if source_id == requirement.source_id
                and (qualified == table.table or qualified.endswith(f".{table.table}"))
            ]
            if len(matches) != 1:
                normalized_tables.append(table)
                continue
            understood = matches[0]
            if (
                understood.period_column.lower() == table.period_column.lower()
                and understood.period_granularity == table.period_granularity
            ):
                normalized_tables.append(table)
                continue
            normalized_tables.append(
                table.model_copy(
                    update={
                        "period_column": understood.period_column,
                        "period_granularity": understood.period_granularity,
                    }
                )
            )
            repairs.append(
                {
                    "requirementId": requirement.requirement_id,
                    "tableIndex": table_index,
                    "table": table.table,
                    "periodColumn": understood.period_column,
                    "periodGranularity": understood.period_granularity,
                }
            )
        normalized_requirements.append(
            requirement.model_copy(update={"tables": tuple(normalized_tables)})
        )
    if not repairs:
        return bundle, []
    return (
        AnalysisBundle.model_validate(
            {
                "analyses": [
                    item.model_dump(mode="json", by_alias=True) for item in bundle.analyses
                ],
                "requirements": [
                    item.model_dump(mode="json", by_alias=True) for item in normalized_requirements
                ],
            }
        ),
        repairs,
    )


def _normalize_requirement_column_values(
    requirement: QueryRequirement,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[QueryRequirement, dict[str, Any] | None]:
    column_sets = [
        {
            column.name
            for column in _analysis_table_columns(requirement.source_id, table.table, snapshots)
        }
        for table in requirement.tables
    ]
    if not column_sets or any(not columns for columns in column_sets):
        return requirement, None
    dimension_allowed = set.union(*column_sets)
    grain_allowed = set.intersection(*column_sets)
    dimensions = tuple(
        value for value in requirement.dimension_columns if value in dimension_allowed
    )
    grain = tuple(
        value
        for value in requirement.grain_columns
        if value in grain_allowed and value in dimensions
    )
    if (
        not dimensions
        or not grain
        or (dimensions == requirement.dimension_columns and grain == requirement.grain_columns)
    ):
        return requirement, None
    return (
        requirement.model_copy(update={"dimension_columns": dimensions, "grain_columns": grain}),
        {
            "requirementId": requirement.requirement_id,
            "removedDimensionColumns": [
                value for value in requirement.dimension_columns if value not in dimensions
            ],
            "removedGrainColumns": [
                value for value in requirement.grain_columns if value not in grain
            ],
        },
    )


def _normalize_requirement_columns_in_payload(
    payload: dict[str, Any],
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> dict[str, Any]:
    requirements = payload.get("requirements")
    if not isinstance(requirements, list):
        return payload
    normalized_payload = dict(payload)
    normalized_requirements = list(requirements)
    changed = False
    for index, candidate in enumerate(requirements):
        try:
            requirement = QueryRequirement.model_validate(candidate)
        except ValidationError:
            continue
        normalized, repair = _normalize_requirement_column_values(requirement, snapshots)
        if repair is None:
            continue
        normalized_requirements[index] = normalized.model_dump(mode="json", by_alias=True)
        changed = True
    if not changed:
        return payload
    normalized_payload["requirements"] = normalized_requirements
    return normalized_payload


def _normalize_comparison_roles(
    bundle: AnalysisBundle,
    requested_roles: tuple[Literal["yoy", "mom"], ...],
) -> tuple[AnalysisBundle, list[dict[str, Any]]]:
    """把需求比较窗口收敛到用户已授权集合，分析层环比计算不因此受限。"""

    requested = tuple(role for role in ("yoy", "mom") if role in requested_roles)
    repairs: list[dict[str, Any]] = []
    normalized_requirements: list[QueryRequirement] = []
    for requirement in bundle.requirements:
        selected = requirement.comparison_roles
        if selected is None:
            normalized_requirements.append(requirement)
            continue
        normalized = tuple(role for role in requested if role in selected)
        stored = None if normalized == requested else normalized
        if stored == selected:
            normalized_requirements.append(requirement)
            continue
        normalized_requirements.append(requirement.model_copy(update={"comparison_roles": stored}))
        repairs.append(
            {
                "requirementId": requirement.requirement_id,
                "removedRoles": [role for role in selected if role not in requested],
                "comparisonRoles": list(normalized),
            }
        )
    if not repairs:
        return bundle, []
    return (
        AnalysisBundle.model_validate(
            {
                "analyses": [
                    item.model_dump(mode="json", by_alias=True) for item in bundle.analyses
                ],
                "requirements": [
                    item.model_dump(mode="json", by_alias=True) for item in normalized_requirements
                ],
            }
        ),
        repairs,
    )


def _normalize_duplicate_requirements(
    bundle: AnalysisBundle,
) -> tuple[AnalysisBundle, list[dict[str, Any]]]:
    """合并同一物理窗口的重复取数需求，避免物化后把同一事实当成多来源冲突。

    同一张表的不同分析视角只需要一次包含完整指标和安全粒度的查询；Coding 会按
    详细计划从不可变 CSV 复算。合并只扩展字段集合并改写引用，不对数值
    做加法，也不吞掉真实的跨数据集冲突。
    """

    canonical_by_key: dict[tuple[Any, ...], int] = {}
    merged: list[QueryRequirement] = []
    replacement: dict[str, str] = {}
    repairs: list[dict[str, Any]] = []
    for requirement in bundle.requirements:
        if len(requirement.tables) != 1:
            merged.append(requirement)
            continue
        table = requirement.tables[0]
        key = (
            requirement.source_id.lower(),
            table.table.lower(),
            table.period_column.lower(),
            table.period_granularity,
            requirement.comparison_roles,
        )
        canonical_index = canonical_by_key.get(key)
        if canonical_index is None:
            canonical_by_key[key] = len(merged)
            merged.append(requirement)
            continue
        canonical = merged[canonical_index]
        canonical_table = canonical.tables[0]
        merged_table = canonical_table.model_copy(
            update={
                "measure_columns": tuple(
                    dict.fromkeys((*canonical_table.measure_columns, *table.measure_columns))
                ),
            }
        )
        merged_requirement = canonical.model_copy(
            update={
                "tables": (merged_table,),
                "dimension_columns": tuple(
                    dict.fromkeys((*canonical.dimension_columns, *requirement.dimension_columns))
                ),
                "grain_columns": tuple(
                    dict.fromkeys((*canonical.grain_columns, *requirement.grain_columns))
                ),
            }
        )
        try:
            merged[canonical_index] = QueryRequirement.model_validate(
                merged_requirement.model_dump(mode="json", by_alias=True)
            )
        except ValidationError:
            # 只有合并后的字段集合超过协议上限时才保留原需求，让语义校验给出
            # 精确的可修复路径；不能静默丢字段。
            merged.append(requirement)
            continue
        replacement[requirement.requirement_id] = canonical.requirement_id
        repairs.append(
            {
                "removedRequirementId": requirement.requirement_id,
                "canonicalRequirementId": canonical.requirement_id,
                "table": table.table,
            }
        )

    if not repairs:
        return bundle, []
    analyses: list[AnalysisItem] = []
    for analysis in bundle.analyses:
        analyses.append(
            analysis.model_copy(
                update={
                    "requirement_ids": tuple(
                        dict.fromkeys(
                            replacement.get(item, item) for item in analysis.requirement_ids
                        )
                    )
                }
            )
        )
    normalized = AnalysisBundle.model_validate(
        {
            "analyses": [item.model_dump(mode="json", by_alias=True) for item in analyses],
            "requirements": [item.model_dump(mode="json", by_alias=True) for item in merged],
        }
    )
    return normalized, repairs


def _multi_table_requirement_issues(
    requirement: QueryRequirement,
    requirement_index: int,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    if len(requirement.tables) <= 1:
        return []

    path = f"requirements[{requirement_index}]"
    issues: list[dict[str, Any]] = []
    granularities = sorted({table.period_granularity for table in requirement.tables})
    if len(granularities) > 1:
        issues.append(
            {
                "path": f"{path}.tables",
                "rejectedValue": [
                    {
                        "table": table.table,
                        "periodColumn": table.period_column,
                        "periodGranularity": table.period_granularity,
                    }
                    for table in requirement.tables
                ],
                "reason": "多表 requirement 的 periodGranularity 不一致，不能在同一 SQL 中强行拼接",
                "allowedValues": granularities,
                "requiredAction": (
                    "拆分为单表 requirements，并让 analyses.requirementIds 同时引用它们"
                ),
            }
        )

    available_columns = _available_table_columns(snapshots)
    grain_columns = set(requirement.grain_columns)
    for table_index, table in enumerate(requirement.tables):
        matches = [
            columns
            for (source_id, qualified), columns in available_columns.items()
            if source_id == requirement.source_id
            and (qualified == table.table or qualified.endswith(f".{table.table}"))
        ]
        if len(matches) != 1:
            continue
        columns = {column.lower() for column in matches[0]}
        missing = sorted(grain_columns - columns)
        if missing:
            issues.append(
                {
                    "path": f"{path}.grainColumns",
                    "rejectedValue": {"table": table.table, "missingColumns": missing},
                    "reason": (
                        "多表 requirement 的全部 grainColumns 必须真实存在于每张表；"
                        f"{table.table} 缺少 {', '.join(missing)}"
                    ),
                    "allowedValues": sorted(columns),
                    "requiredAction": (
                        "拆分为单表 requirements；只有确实存在完整共同粒度时才保留多表 requirement"
                    ),
                }
            )

    for relation_index, relation in enumerate(requirement.relations):
        if set(relation.join_columns) != grain_columns:
            issues.append(
                {
                    "path": f"{path}.relations[{relation_index}].joinColumns",
                    "rejectedValue": list(relation.join_columns),
                    "reason": (
                        "多表预聚合结果必须按完整 grainColumns 等值关联，"
                        "否则可能产生多对多重复和指标放大"
                    ),
                    "allowedValues": list(requirement.grain_columns),
                    "requiredAction": (
                        "joinColumns 必须完整等于 grainColumns；无法满足时拆分为单表 requirements"
                    ),
                }
            )
    return issues


__all__ = [
    "_analysis_bundle_semantic_issues",
    "_normalize_analysis_bundle_grain",
    "_normalize_comparison_roles",
    "_normalize_duplicate_requirements",
    "_normalize_requirement_columns",
    "_normalize_requirement_columns_in_payload",
    "_normalize_requirement_periods",
    "_validate_requirements_match_understanding",
]


def _suggested_replacement(rejected: Any, allowed_values: list[str]) -> str | None:
    if isinstance(rejected, list) and len(rejected) == 1:
        rejected = rejected[0]
    if not isinstance(rejected, str) or not allowed_values:
        return None
    ranked = sorted(
        (
            (SequenceMatcher(None, rejected, candidate).ratio(), candidate)
            for candidate in allowed_values
        ),
        reverse=True,
    )
    best_score, best = ranked[0]
    next_score = ranked[1][0] if len(ranked) > 1 else 0.0
    if best_score < 0.85 or best_score - next_score < 0.1:
        return None
    return best


def _analysis_table_columns(
    source_id: str,
    table: str,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[ModelColumn, ...]:
    matches = [
        model.columns
        for (candidate_source, qualified), model in _available_tables(snapshots).items()
        if candidate_source == source_id
        and (qualified == table.lower() or qualified.endswith(f".{table.lower()}"))
    ]
    return matches[0] if len(matches) == 1 else ()


def _resolve_requirement_comparison_roles(
    requirement: QueryRequirement,
    requirement_index: int,
    envelope: ReportRequestEnvelope,
) -> tuple[tuple[Literal["yoy", "mom"], ...] | None, dict[str, Any] | None]:
    """把 Planner 的比较范围越界转换为可定点修正的结构化反馈。"""
    try:
        return requirement.resolved_comparison_roles(envelope.comparison_roles), None
    except ValueError as error:
        selected = (
            envelope.comparison_roles
            if requirement.comparison_roles is None
            else requirement.comparison_roles
        )
        rejected = [role for role in selected if role not in envelope.comparison_roles]
        if rejected:
            reason = "comparisonRoles 超出请求允许的比较范围"
            allowed = list(envelope.comparison_roles)
            required_action = (
                "删除 rejectedValue，只保留 allowedValues；省略 comparisonRoles 表示继承请求范围"
            )
        else:
            rejected = ["mom"] if "mom" in selected else list(selected)
            allowed = [role for role in envelope.comparison_roles if role != "mom"]
            reason = str(error)
            required_action = "删除 rejectedValue，只保留当前期间粒度支持的 allowedValues"
        return None, {
            "path": f"requirements[{requirement_index}].comparisonRoles",
            "rejectedValue": rejected,
            "reason": reason,
            "allowedValues": allowed,
            "requiredAction": required_action,
        }


def _available_table_columns(
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> dict[tuple[str, str], tuple[str, ...]]:
    return {
        (table.source_id, f"{table.database.lower()}.{table.name.lower()}"): tuple(
            column.name for column in table.columns
        )
        for snapshot in snapshots
        for table in snapshot.tables
    }


def _available_tables(
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> dict[tuple[str, str], ModelTable]:
    return {
        (table.source_id, f"{table.database.lower()}.{table.name.lower()}"): table
        for snapshot in snapshots
        for table in snapshot.tables
    }
