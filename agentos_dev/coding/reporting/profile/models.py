from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..contract import MeasureSemantic

PROFILE_DIRECTORY_NAME = "reporting_profiles"
PROFILE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
FIELD_REF_PATTERN = (
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\."
    r"[A-Za-z_][A-Za-z0-9_$]{0,127}\."
    r"[A-Za-z_][A-Za-z0-9_$]{0,127}\."
    r"[A-Za-z_][A-Za-z0-9_$]{0,127}$"
)


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class DimensionPatch(ProfileModel):
    code: str = Field(pattern=PROFILE_ID_PATTERN)
    enabled: bool = True
    kind: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2_000)
    field_refs: tuple[str, ...] | None = Field(
        default=None, alias="fieldRefs", min_length=1, max_length=100
    )

    @field_validator("field_refs")
    @classmethod
    def validate_field_refs(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return _field_refs(value)


class MetricPatch(ProfileModel):
    code: str = Field(pattern=PROFILE_ID_PATTERN)
    enabled: bool = True
    kind: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2_000)
    aggregation: Literal["sum", "count", "count_distinct", "average", "ratio"] | None = None
    field_ref: str | None = Field(default=None, alias="fieldRef", pattern=FIELD_REF_PATTERN)
    numerator_metric: str | None = Field(
        default=None, alias="numeratorMetric", pattern=PROFILE_ID_PATTERN
    )
    denominator_metric: str | None = Field(
        default=None, alias="denominatorMetric", pattern=PROFILE_ID_PATTERN
    )
    zero_denominator_policy: Literal["disclose", "null"] | None = Field(
        default=None, alias="zeroDenominatorPolicy"
    )


class ReconciliationPatch(ProfileModel):
    code: str = Field(pattern=PROFILE_ID_PATTERN)
    enabled: bool = True
    left_metric: str | None = Field(default=None, alias="leftMetric", pattern=PROFILE_ID_PATTERN)
    right_metric: str | None = Field(default=None, alias="rightMetric", pattern=PROFILE_ID_PATTERN)
    grain: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=20)
    absolute_tolerance: float | None = Field(default=None, alias="absoluteTolerance", ge=0)
    relative_tolerance: float | None = Field(default=None, alias="relativeTolerance", ge=0)

    @field_validator("grain")
    @classmethod
    def validate_grain(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return _codes(value)


class ScopeFilterPatch(ProfileModel):
    code: str = Field(pattern=PROFILE_ID_PATTERN)
    enabled: bool = True
    description: str | None = Field(default=None, max_length=2_000)
    field_refs: tuple[str, ...] | None = Field(
        default=None, alias="fieldRefs", min_length=1, max_length=200
    )
    value: str | None = Field(default=None, min_length=1, max_length=1_000)
    required_for_all_tables: bool | None = Field(default=None, alias="requiredForAllTables")

    @field_validator("field_refs")
    @classmethod
    def validate_field_refs(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return _field_refs(value)


class SectionPatch(ProfileModel):
    code: str = Field(pattern=PROFILE_ID_PATTERN)
    enabled: bool = True
    title: str | None = Field(default=None, min_length=1, max_length=300)
    required: bool | None = None
    required_capabilities: tuple[str, ...] | None = Field(
        default=None, alias="requiredCapabilities", max_length=100
    )

    @field_validator("required_capabilities")
    @classmethod
    def validate_capabilities(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return _codes(value)


class PageLayoutPatch(ProfileModel):
    header_left: str | None = Field(default=None, alias="headerLeft", max_length=200)
    header_right: str | None = Field(default=None, alias="headerRight", max_length=200)
    footer_left: str | None = Field(default=None, alias="footerLeft", max_length=200)
    footer_right: str | None = Field(default=None, alias="footerRight", max_length=200)

    @field_validator("header_left", "header_right", "footer_left", "footer_right")
    @classmethod
    def validate_formats(cls, value: str | None) -> str | None:
        return _page_format(value)


class ReportingProfileDocument(ProfileModel):
    version: Literal["1"] = "1"
    profile_id: str = Field(alias="profileId", pattern=PROFILE_ID_PATTERN)
    revision: str = Field(min_length=1, max_length=128)
    extends: tuple[str, ...] = Field(default=(), max_length=20)
    dimensions: tuple[DimensionPatch, ...] = Field(default=(), max_length=500)
    metrics: tuple[MetricPatch, ...] = Field(default=(), max_length=1_000)
    reconciliations: tuple[ReconciliationPatch, ...] = Field(default=(), max_length=500)
    scope_filters: tuple[ScopeFilterPatch, ...] = Field(
        default=(), alias="scopeFilters", max_length=100
    )
    measure_semantics: tuple[MeasureSemantic, ...] = Field(
        default=(), alias="measureSemantics", max_length=2_000
    )
    sections: tuple[SectionPatch, ...] = Field(default=(), max_length=200)
    section_order: tuple[str, ...] | None = Field(
        default=None, alias="sectionOrder", min_length=1, max_length=200
    )
    page_layout: PageLayoutPatch | None = Field(default=None, alias="pageLayout")

    @model_validator(mode="after")
    def validate_codes(self) -> ReportingProfileDocument:
        if self.profile_id in self.extends or len(set(self.extends)) != len(self.extends):
            raise ValueError("Profile extends 无效")
        for values in (
            self.dimensions,
            self.metrics,
            self.reconciliations,
            self.scope_filters,
            self.sections,
        ):
            codes = [item.code for item in values]
            if len(codes) != len(set(codes)):
                raise ValueError("同一 Profile 层的 code 不能重复")
            if any(
                item.enabled is False and item.model_fields_set - {"code", "enabled"}
                for item in values
            ):
                raise ValueError("停用项只能包含 code 和 enabled")
        semantic_refs = [item.field_ref.lower() for item in self.measure_semantics]
        if len(semantic_refs) != len(set(semantic_refs)):
            raise ValueError("同一 Profile 层的 measureSemantics.fieldRef 不能重复")
        if self.section_order is not None:
            _codes(self.section_order)
        return self


class EffectiveDimension(ProfileModel):
    code: str = Field(pattern=PROFILE_ID_PATTERN)
    kind: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2_000)
    field_refs: tuple[str, ...] = Field(alias="fieldRefs", min_length=1, max_length=100)

    @field_validator("field_refs")
    @classmethod
    def validate_field_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _field_refs(value) or ()


class EffectiveMetric(ProfileModel):
    code: str = Field(pattern=PROFILE_ID_PATTERN)
    kind: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2_000)
    aggregation: Literal["sum", "count", "count_distinct", "average", "ratio"]
    field_ref: str | None = Field(default=None, alias="fieldRef", pattern=FIELD_REF_PATTERN)
    numerator_metric: str | None = Field(
        default=None, alias="numeratorMetric", pattern=PROFILE_ID_PATTERN
    )
    denominator_metric: str | None = Field(
        default=None, alias="denominatorMetric", pattern=PROFILE_ID_PATTERN
    )
    zero_denominator_policy: Literal["disclose", "null"] = Field(
        default="disclose", alias="zeroDenominatorPolicy"
    )

    @model_validator(mode="after")
    def validate_definition(self) -> EffectiveMetric:
        if self.aggregation == "ratio":
            if self.field_ref or not self.numerator_metric or not self.denominator_metric:
                raise ValueError("ratio 指标必须且只能声明分子和分母指标")
        elif not self.field_ref or self.numerator_metric or self.denominator_metric:
            raise ValueError("基础指标必须且只能声明 fieldRef")
        return self


class EffectiveReconciliation(ProfileModel):
    code: str = Field(pattern=PROFILE_ID_PATTERN)
    left_metric: str = Field(alias="leftMetric", pattern=PROFILE_ID_PATTERN)
    right_metric: str = Field(alias="rightMetric", pattern=PROFILE_ID_PATTERN)
    grain: tuple[str, ...] = Field(min_length=1, max_length=20)
    absolute_tolerance: float = Field(default=0, alias="absoluteTolerance", ge=0)
    relative_tolerance: float = Field(default=0, alias="relativeTolerance", ge=0)

    @field_validator("grain")
    @classmethod
    def validate_grain(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _codes(value) or ()


class EffectiveScopeFilter(ProfileModel):
    code: str = Field(pattern=PROFILE_ID_PATTERN)
    description: str = Field(default="", max_length=2_000)
    field_refs: tuple[str, ...] = Field(alias="fieldRefs", min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=1_000)
    required_for_all_tables: bool = Field(default=False, alias="requiredForAllTables")

    @field_validator("field_refs")
    @classmethod
    def validate_field_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _field_refs(value) or ()


class EffectiveSection(ProfileModel):
    code: str = Field(pattern=PROFILE_ID_PATTERN)
    title: str = Field(min_length=1, max_length=300)
    required: bool = False
    required_capabilities: tuple[str, ...] = Field(
        default=(), alias="requiredCapabilities", max_length=100
    )

    @field_validator("required_capabilities")
    @classmethod
    def validate_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _codes(value) or ()


class EffectivePageLayout(ProfileModel):
    header_left: str = Field(default="上海鼎医信息技术有限公司", alias="headerLeft", max_length=200)
    header_right: str = Field(default="{title}", alias="headerRight", max_length=200)
    footer_left: str = Field(default="企业智能运营报表", alias="footerLeft", max_length=200)
    footer_right: str = Field(default="第 {page} / {pages} 页", alias="footerRight", max_length=200)

    @field_validator("header_left", "header_right", "footer_left", "footer_right")
    @classmethod
    def validate_formats(cls, value: str) -> str:
        return _page_format(value) or ""

    @model_validator(mode="after")
    def require_page_numbers(self) -> EffectivePageLayout:
        footer = f"{self.footer_left}\n{self.footer_right}"
        if "{page}" not in footer or "{pages}" not in footer:
            raise ValueError("页脚必须包含 {page} 和 {pages}")
        return self


class ProfileLayerRef(ProfileModel):
    profile_id: str = Field(alias="profileId", pattern=PROFILE_ID_PATTERN)
    revision: str = Field(min_length=1, max_length=128)


class EffectiveReportingProfile(ProfileModel):
    profile_id: str = Field(alias="profileId", pattern=PROFILE_ID_PATTERN)
    revision: str = Field(min_length=1, max_length=128)
    effective_profile_hash: str = Field(alias="effectiveProfileHash", pattern=r"^[0-9a-f]{64}$")
    layers: tuple[ProfileLayerRef, ...] = Field(min_length=1, max_length=100)
    dimensions: tuple[EffectiveDimension, ...] = Field(default=(), max_length=500)
    metrics: tuple[EffectiveMetric, ...] = Field(default=(), max_length=1_000)
    reconciliations: tuple[EffectiveReconciliation, ...] = Field(default=(), max_length=500)
    scope_filters: tuple[EffectiveScopeFilter, ...] = Field(
        default=(), alias="scopeFilters", max_length=100
    )
    measure_semantics: tuple[MeasureSemantic, ...] = Field(
        default=(), alias="measureSemantics", max_length=2_000
    )
    sections: tuple[EffectiveSection, ...] = Field(min_length=1, max_length=200)
    page_layout: EffectivePageLayout = Field(
        default_factory=EffectivePageLayout, alias="pageLayout"
    )

    @model_validator(mode="after")
    def validate_hash(self) -> EffectiveReportingProfile:
        payload = self.model_dump(mode="json", by_alias=True, exclude={"effective_profile_hash"})
        if effective_profile_hash(payload) != self.effective_profile_hash:
            raise ValueError("effectiveProfileHash 与 Profile 内容不一致")
        return self


@dataclass(frozen=True)
class ReportingProfileRegistry:
    documents: dict[str, ReportingProfileDocument]
    config_paths: tuple[Path, ...]


@dataclass(frozen=True)
class FieldReference:
    source_id: str
    database: str
    table: str
    column: str

    @property
    def qualified_table(self) -> str:
        return f"{self.database}.{self.table}"


def parse_field_ref(value: str) -> FieldReference:
    if not re.fullmatch(FIELD_REF_PATTERN, value):
        raise ValueError("fieldRef 必须使用 source.database.table.column")
    source_id, database, table, column = value.rsplit(".", 3)
    return FieldReference(source_id, database.lower(), table.lower(), column.lower())


def effective_profile_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _field_refs(value: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    if len(set(value)) != len(value) or any(
        not re.fullmatch(FIELD_REF_PATTERN, item) for item in value
    ):
        raise ValueError("fieldRefs 包含重复或无效引用")
    return value


def _codes(value: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    if len(set(value)) != len(value) or any(
        not re.fullmatch(PROFILE_ID_PATTERN, item) for item in value
    ):
        raise ValueError("capability code 包含重复或无效值")
    return value


def _page_format(value: str | None) -> str | None:
    if value is None:
        return None
    if any(ord(character) < 32 and character not in "\t" for character in value):
        raise ValueError("页面格式包含控制字符")
    try:
        parsed = tuple(Formatter().parse(value))
    except ValueError as error:
        raise ValueError("页面格式无效") from error
    for _literal, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if field_name not in {"title", "page", "pages"} or format_spec or conversion:
            raise ValueError("页面格式只允许 {title}、{page} 和 {pages}")
    return value
