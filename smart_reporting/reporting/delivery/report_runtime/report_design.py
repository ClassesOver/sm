"""报告展示设计；不修改服务端绑定的业务事实和 Markdown。"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from string import Formatter
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


class PageMargins(DesignModel):
    top: float = Field(20, ge=0, le=100)
    right: float = Field(18, ge=0, le=100)
    bottom: float = Field(22, ge=0, le=100)
    left: float = Field(18, ge=0, le=100)


class DocumentPage(DesignModel):
    paper: Literal["A4", "A3", "Letter"] = "A4"
    orientation: Literal["portrait", "landscape"] = "portrait"
    margins: PageMargins = Field(default_factory=PageMargins)

    def dimensions(self) -> tuple[float, float]:
        width, height = {"A4": (210, 297), "A3": (297, 420), "Letter": (215.9, 279.4)}[self.paper]
        return (height, width) if self.orientation == "landscape" else (width, height)

    @model_validator(mode="after")
    def printable_area(self):
        width, height = self.dimensions()
        if width - self.margins.left - self.margins.right < 20 or height - self.margins.top - self.margins.bottom < 20:
            raise ValueError("页边距必须保留至少 20 毫米的正文区域")
        return self


class SignatureDesign(TextStyle):
    align: Literal["left", "center", "right"] = "right"
    space_before: float = Field(0, ge=0, le=144)
    date_gap: float = Field(4, ge=0, le=72)
    description: str = Field("", max_length=600)
    date_format: Literal["chinese", "iso", "slash"] = "iso"


class HeaderFooterText(DesignModel):
    left: str = Field("", max_length=200)
    center: str = Field("", max_length=200)
    right: str = Field("", max_length=200)

    @model_validator(mode="after")
    def supported_fields(self):
        for value in (self.left, self.center, self.right):
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError("页眉页脚不能包含控制字符")
            for _literal, name, spec, conversion in Formatter().parse(value):
                if name is not None and (name not in {"title", "signer", "period", "date", "filename", "page", "pages"} or spec or conversion):
                    raise ValueError("页眉页脚包含不支持的字段")
        return self


class HeaderFooterDesign(DesignModel):
    enabled: bool = True
    header: HeaderFooterText = Field(default_factory=HeaderFooterText)
    footer: HeaderFooterText = Field(default_factory=HeaderFooterText)
    style: TextStyle = Field(default_factory=lambda: TextStyle(size=9, color="#475467"))
    header_distance: float = Field(12, ge=0, le=50)
    footer_distance: float = Field(12, ge=0, le=50)
    divider: bool = False
    first_page_different: bool = True
    odd_even_different: bool = False
    first_header: HeaderFooterText = Field(default_factory=HeaderFooterText)
    first_footer: HeaderFooterText = Field(default_factory=HeaderFooterText)
    even_header: HeaderFooterText | None = None
    even_footer: HeaderFooterText | None = None
    page_numbers: bool = True
    page_number_start: int = Field(1, ge=1, le=9999)


class TableDesign(DesignModel):
    repeat_header: bool = True
    split_rows: bool = False
    borders: Literal["light", "all", "none"] = "light"
    striped: bool = True
    caption_numbering: bool = True


class PdfOutputDesign(DesignModel):
    bookmarks: bool = True
    image_quality: int = Field(90, ge=50, le=100)


class ChartDesign(DesignModel):
    keep_with_caption: bool = True
    # 历史设计未声明此字段时保留原图注；格式偏好会冻结显式布尔值。
    caption_numbering: bool | None = None
    image_dpi: int | None = Field(None, ge=72, le=600)


class ReportDesign(DesignModel):
    version: Literal[1] = 1
    options: DesignOptions = Field(default_factory=DesignOptions)
    cover: CoverDesign = Field(default_factory=CoverDesign)
    watermark: WatermarkDesign = Field(default_factory=WatermarkDesign)
    typography: Typography = Field(default_factory=Typography)
    page: DocumentPage | None = None
    signature: SignatureDesign | None = None
    header_footer: HeaderFooterDesign | None = None
    tables: TableDesign | None = None
    pdf_output: PdfOutputDesign | None = None
    charts: ChartDesign | None = None

    def digest(self) -> str:
        document = self.model_dump(mode="json", by_alias=True)
        # 旧设计没有新增可选字段；保持其历史哈希，不让升级使旧修订失效。
        for key in ("page", "signature", "headerFooter", "tables", "pdfOutput", "charts"):
            if document[key] is None:
                document.pop(key)
        if document.get("charts", {}).get("captionNumbering") is None:
            document.get("charts", {}).pop("captionNumbering", None)
        if document.get("charts", {}).get("imageDpi") is None:
            document.get("charts", {}).pop("imageDpi", None)
        return hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def compact(self) -> dict[str, Any]:
        """按角色归一默认取差异，避免通用子模型默认值使覆盖配置丢失。"""
        def differences(value: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in value.items():
                if isinstance(item, dict):
                    nested = differences(item, baseline[key]) if isinstance(baseline.get(key), dict) else item
                    if nested:
                        result[key] = nested
                elif item != baseline[key]:
                    result[key] = item
            return result

        document = self.model_dump(mode="json", by_alias=True)
        if document.get("charts"):
            if document["charts"]["captionNumbering"] is None:
                document["charts"].pop("captionNumbering")
            if document["charts"]["imageDpi"] is None:
                document["charts"].pop("imageDpi")
        return differences(document, ReportDesign().model_dump(mode="json", by_alias=True))


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


def resolve_design(state: dict[str, Any], *, format: Literal["pdf", "word"] = "pdf") -> ReportDesign:
    document = deepcopy(state.get("_formatDesigns", {}).get(format, {}))

    def merge(target, overrides):
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = deepcopy(value)

    merge(document, state.get("_reportDesign") or {})
    design = ReportDesign.model_validate(document)
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
