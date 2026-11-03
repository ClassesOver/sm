"""报告展示设计；不修改服务端绑定的业务事实和 Markdown。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

Font = Literal["sans", "serif"]
COLOR = r"^#[0-9a-fA-F]{6}$"
FONTS = {"sans": "Noto Sans CJK SC", "serif": "Noto Serif CJK SC"}


class DesignModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel, allow_inf_nan=False)


class TextStyle(DesignModel):
    font: Font = "sans"
    size: float = Field(11, ge=6, le=72)
    color: str = Field("#172033", pattern=COLOR)
    bold: bool = False
    line_height: float = Field(1.6, ge=1, le=3)
    space_before: float = Field(0, ge=0, le=72)
    space_after: float = Field(6, ge=0, le=72)
    indent: float = Field(0, ge=0, le=48)


class CoverBox(TextStyle):
    text: str | None = Field(None, max_length=600)
    visible: bool = True
    x: float = Field(25, ge=0, le=210)
    y: float = Field(70, ge=0, le=297)
    width: float = Field(160, ge=10, le=210)
    height: float = Field(50, ge=5, le=297)
    align: Literal["left", "center", "right"] = "center"

    @model_validator(mode="after")
    def within_page(self):
        if self.x + self.width > 210.001 or self.y + self.height > 297.001:
            raise ValueError("封面文字框须位于 A4 页面内")
        return self


class CoverDesign(DesignModel):
    preset: Literal["formal", "minimal"] = "formal"
    background: str = Field("#ffffff", pattern=COLOR)
    title: CoverBox = Field(default_factory=lambda: CoverBox(size=28, bold=True, color="#174a66", y=65, height=65))
    period: CoverBox = Field(default_factory=lambda: CoverBox(size=13, y=140, height=30))
    signature: CoverBox = Field(default_factory=lambda: CoverBox(size=11, y=217, height=55))
    show_organization: bool = True
    show_generated_by: bool = True
    show_date: bool = True

    @model_validator(mode="before")
    @classmethod
    def preserve_box_defaults(cls, value: Any) -> Any:
        return _merge_role_defaults(cls, value)


class WatermarkDesign(DesignModel):
    enabled: bool = True
    text: str | None = Field(None, max_length=200)
    font: Font = "sans"
    size: float = Field(26, ge=8, le=72)
    color: str = Field("#475467", pattern=COLOR)
    opacity: float = Field(0.045, ge=0.01, le=0.5)
    angle: float = Field(-32, ge=-90, le=90)
    placement: Literal["center", "tile"] = "center"
    cover: bool = False


class Typography(DesignModel):
    body: TextStyle = Field(default_factory=lambda: TextStyle(font="serif"))
    h1: TextStyle = Field(default_factory=lambda: TextStyle(size=16, bold=True, color="#174a66", space_before=14, space_after=7, line_height=1.4))
    h2: TextStyle = Field(default_factory=lambda: TextStyle(size=13, bold=True, space_before=10, space_after=5, line_height=1.4))
    h3: TextStyle = Field(default_factory=lambda: TextStyle(size=11.5, bold=True, space_before=8, space_after=4, line_height=1.4))
    table: TextStyle = Field(default_factory=lambda: TextStyle(size=9.5, line_height=1.3, space_after=0))
    caption: TextStyle = Field(default_factory=lambda: TextStyle(size=9, line_height=1.35, color="#475467", space_after=4))

    @model_validator(mode="before")
    @classmethod
    def preserve_style_defaults(cls, value: Any) -> Any:
        return _merge_role_defaults(cls, value)


class DesignOptions(DesignModel):
    cover: bool = True
    toc: bool = True
    header_footer: bool = True
    page_numbers: bool = True
    sources: bool = False


class ReportDesign(DesignModel):
    version: Literal[1] = 1
    options: DesignOptions = Field(default_factory=DesignOptions)
    cover: CoverDesign = Field(default_factory=CoverDesign)
    watermark: WatermarkDesign = Field(default_factory=WatermarkDesign)
    typography: Typography = Field(default_factory=Typography)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json", by_alias=True), sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def compact(self) -> dict[str, Any]:
        """按角色归一默认取差异，避免通用子模型默认值使覆盖配置丢失。"""
        def differences(value: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in value.items():
                if isinstance(item, dict):
                    nested = differences(item, baseline[key])
                    if nested:
                        result[key] = nested
                elif item != baseline[key]:
                    result[key] = item
            return result

        return differences(self.model_dump(mode="json", by_alias=True), ReportDesign().model_dump(mode="json", by_alias=True))


def _merge_role_defaults(model: type[DesignModel], value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    result = dict(value)
    for key, field in model.model_fields.items():
        if field.default_factory is None or not isinstance(result.get(key), dict):
            continue
        default = field.default_factory()
        if isinstance(default, DesignModel):
            fields = type(default).model_fields
            overrides = {(fields[name].alias or to_camel(name)) if name in fields else name: item for name, item in result[key].items()}
            result[key] = {**default.model_dump(by_alias=True), **overrides}
    return result


def resolve_design(state: dict[str, Any]) -> ReportDesign:
    design = ReportDesign.model_validate(state.get("_reportDesign") or {})
    options = state.get("_editorExportSettings")
    if isinstance(options, dict):
        design.options = DesignOptions.model_validate({**design.options.model_dump(by_alias=True), **options})
    return design


def cover_text(design: ReportDesign, context: dict[str, Any]) -> dict[str, str]:
    signature = "\n".join(str(context.get(key, "")) for key, enabled in (
        ("organizationName", design.cover.show_organization),
        ("generatedByLabel", design.cover.show_generated_by),
        ("generatedDate", design.cover.show_date),
    ) if enabled)
    defaults = {"title": str(context.get("title", "")), "period": f"分析期间：{context.get('periodLabel', '')}", "signature": signature}
    return {key: box.text if box.text is not None else defaults[key] for key, box in (
        ("title", design.cover.title), ("period", design.cover.period), ("signature", design.cover.signature),
    )}


def template_design(design: ReportDesign) -> ReportDesign:
    result = design.model_copy(deep=True)
    for key in ("title", "period", "signature"):
        getattr(result.cover, key).text = None
    return result
