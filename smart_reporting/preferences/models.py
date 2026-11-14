"""五格式偏好契约；本模块不读取环境、时钟或登录身份。"""

from __future__ import annotations

from string import Formatter
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from ..reporting.delivery.settings import ReportDeliverySettings

Format = Literal["md", "xlsx", "pptx", "pdf", "word"]
Font = Literal["sans", "serif"]
DateFormat = Literal["chinese", "iso", "slash"]
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
FORMATS: tuple[Format, ...] = ("md", "xlsx", "pptx", "pdf", "word")


class PreferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True,
        alias_generator=to_camel, allow_inf_nan=False, strict=True)


def _signer(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or not value.strip():
        raise ValueError("落款署名不能为空或包含控制字符")
    return value.strip()


class CommonPreferences(PreferenceModel):
    signer: str = Field(min_length=1, max_length=200)
    generated_by_label: str = Field("", max_length=200)
    date_format: DateFormat = "chinese"
    font: Font = "sans"
    accent_color: Color = "#174a66"

    _normalize_signer = field_validator("signer")(_signer)


class CommonOverrides(PreferenceModel):
    """null 明确表示沿用公共值；不同格式逐字段覆盖。"""

    signer: str | None = Field(None, min_length=1, max_length=200)
    generated_by_label: str | None = Field(None, max_length=200)
    date_format: DateFormat | None = None
    font: Font | None = None
    accent_color: Color | None = None

    @field_validator("signer")
    @classmethod
    def normalize_signer(cls, value):
        return None if value is None else _signer(value)


class TextStyle(PreferenceModel):
    font: Font | None = None
    size: float = Field(11, ge=6, le=72)
    color: Color | None = None
    bold: bool = False
    line_height: float = Field(1.6, ge=1, le=3)
    space_before: float = Field(0, ge=0, le=72)
    space_after: float = Field(6, ge=0, le=72)
    indent: float = Field(0, ge=0, le=48)


class Typography(PreferenceModel):
    body: TextStyle = Field(default_factory=TextStyle)
    h1: TextStyle = Field(default_factory=lambda: TextStyle(size=16, bold=True))
    h2: TextStyle = Field(default_factory=lambda: TextStyle(size=13, bold=True))
    h3: TextStyle = Field(default_factory=lambda: TextStyle(size=11.5, bold=True))
    table: TextStyle = Field(default_factory=lambda: TextStyle(size=9.5, line_height=1.3))
    caption: TextStyle = Field(default_factory=lambda: TextStyle(size=9, color="#475467"))


class SignatureContent(PreferenceModel):
    description: str = Field("", max_length=600)

    @field_validator("description")
    @classmethod
    def plain_description(cls, value):
        if any(ord(char) < 32 and char != "\n" for char in value):
            raise ValueError("落款说明包含控制字符")
        return value.strip()


class SignatureStyle(TextStyle, SignatureContent):
    align: Literal["left", "center", "right"] = "right"
    date_gap: float = Field(4, ge=0, le=72)
    space_before: float = Field(18, ge=0, le=144)


class Margins(PreferenceModel):
    top: float = Field(25, ge=0, le=100)
    right: float = Field(22, ge=0, le=100)
    bottom: float = Field(24, ge=0, le=100)
    left: float = Field(22, ge=0, le=100)


class PagePreferences(PreferenceModel):
    paper: Literal["A4", "A3", "Letter"] = "A4"
    orientation: Literal["portrait", "landscape"] = "portrait"
    margins: Margins = Field(default_factory=Margins)

    @model_validator(mode="after")
    def printable_area(self):
        width, height = {"A4": (210, 297), "A3": (297, 420), "Letter": (215.9, 279.4)}[self.paper]
        if self.orientation == "landscape":
            width, height = height, width
        if width - self.margins.left - self.margins.right < 20 or (
            height - self.margins.top - self.margins.bottom < 20
        ):
            raise ValueError("页边距必须至少保留 20 毫米的可打印宽度和高度")
        return self


class HeaderFooterText(PreferenceModel):
    allowed_fields: ClassVar[frozenset[str]] = frozenset({
        "title", "signer", "period", "date", "filename", "page", "pages",
    })
    left: str = Field("", max_length=200)
    center: str = Field("", max_length=200)
    right: str = Field("", max_length=200)

    @field_validator("left", "center", "right")
    @classmethod
    def supported_fields(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("页眉页脚不能包含控制字符")
        for _literal, name, spec, conversion in Formatter().parse(value):
            if name is not None and (name not in cls.allowed_fields or spec or conversion):
                raise ValueError("请使用本格式支持的插入字段")
        return value


class HeaderFooter(PreferenceModel):
    enabled: bool = True
    header: HeaderFooterText = Field(default_factory=lambda: HeaderFooterText(left="{signer}", right="{title}"))
    footer: HeaderFooterText = Field(default_factory=lambda: HeaderFooterText(right="第 {page} / {pages} 页"))
    style: TextStyle = Field(default_factory=lambda: TextStyle(size=9, color="#475467"))
    header_distance: float = Field(12, ge=0, le=50)
    footer_distance: float = Field(12, ge=0, le=50)
    divider: bool = False


class PagedHeaderFooter(HeaderFooter):
    first_page_different: bool = True
    odd_even_different: bool = False
    first_header: HeaderFooterText = Field(default_factory=HeaderFooterText)
    first_footer: HeaderFooterText = Field(default_factory=HeaderFooterText)
    even_header: HeaderFooterText | None = None
    even_footer: HeaderFooterText | None = None
    page_numbers: bool = True
    page_number_start: int = Field(1, ge=1, le=9999)


class TablePreferences(PreferenceModel):
    repeat_header: bool = True
    split_rows: bool = False
    borders: Literal["light", "all", "none"] = "light"
    striped: bool = True
    caption_numbering: bool = True


class ChartPreferences(PreferenceModel):
    caption_numbering: bool = True
    image_dpi: int = Field(150, ge=72, le=600)
    keep_with_caption: bool = True


class WatermarkPreferences(PreferenceModel):
    enabled: bool = True
    text: str = Field("", max_length=200)
    opacity: float = Field(0.045, ge=0.01, le=0.5)


class PagedPreferences(PreferenceModel):
    common: CommonOverrides = Field(default_factory=CommonOverrides)
    signature: SignatureStyle = Field(default_factory=SignatureStyle)
    page: PagePreferences = Field(default_factory=PagePreferences)
    typography: Typography = Field(default_factory=Typography)
    header_footer: PagedHeaderFooter = Field(default_factory=PagedHeaderFooter)
    tables: TablePreferences = Field(default_factory=TablePreferences)
    charts: ChartPreferences = Field(default_factory=ChartPreferences)
    watermark: WatermarkPreferences = Field(default_factory=WatermarkPreferences)
    cover: bool = True
    toc: bool = True
    sources: bool = False

    @model_validator(mode="after")
    def header_footer_inside_margins(self):
        if self.header_footer.enabled and (
            self.header_footer.header_distance > self.page.margins.top
            or self.header_footer.footer_distance > self.page.margins.bottom
        ):
            raise ValueError("页眉页脚距纸张边缘的距离不能超过对应页边距")
        return self


class PdfPreferences(PagedPreferences):
    bookmarks: bool = True
    # 历史快照兼容字段；PDF/UA始终嵌入字体，不作为可维护开关。
    embed_fonts: bool = True
    image_quality: int = Field(90, ge=50, le=100)


class WordPreferences(PagedPreferences):
    pass


class MarkdownPreferences(PreferenceModel):
    common: CommonOverrides = Field(default_factory=CommonOverrides)
    signature: SignatureContent = Field(default_factory=SignatureContent)
    section_heading_level: int = Field(2, ge=2, le=4)
    toc: bool = False
    table_style: Literal["pipe", "html"] = "pipe"
    list_marker: Literal["-", "*"] = "-"
    code_fence: Literal["backticks", "tildes"] = "backticks"
    image_captions: bool = True
    references: bool = True


class NumberPreferences(PreferenceModel):
    decimal_places: int = Field(2, ge=0, le=15)
    thousands_separator: bool = True
    percent_places: int = Field(2, ge=0, le=15)
    negative_style: Literal["minus", "parentheses", "red"] = "minus"
    date_format: DateFormat = "iso"


class WorkbookPrint(PreferenceModel):
    page: PagePreferences = Field(default_factory=PagePreferences)
    header_footer: HeaderFooter = Field(default_factory=HeaderFooter)
    fit_to_width: int | None = Field(1, ge=1, le=100)
    fit_to_height: int | None = Field(None, ge=1, le=100)
    scale_percent: int | None = Field(None, ge=10, le=400)
    repeat_title_rows: int = Field(1, ge=0, le=20)

    @model_validator(mode="after")
    def scale_or_fit(self):
        if self.scale_percent is not None and (self.fit_to_width is not None or self.fit_to_height is not None):
            raise ValueError("打印按页适配与百分比缩放只能选择一种")
        return self


class WorkbookPreferences(PreferenceModel):
    common: CommonOverrides = Field(default_factory=CommonOverrides)
    signature: SignatureStyle = Field(default_factory=SignatureStyle)
    body: TextStyle = Field(default_factory=TextStyle)
    header: TextStyle = Field(default_factory=lambda: TextStyle(bold=True))
    alignment: Literal["left", "center", "right"] = "left"
    wrap_text: bool = True
    row_height: float | None = Field(None, ge=8, le=409)
    column_width: float | None = Field(None, ge=2, le=100)
    borders: Literal["light", "all", "none"] = "light"
    striped: bool = True
    freeze_header: bool = True
    auto_filter: bool = True
    numbers: NumberPreferences = Field(default_factory=NumberPreferences)
    print: WorkbookPrint = Field(default_factory=WorkbookPrint)


class SlideFooter(HeaderFooterText):
    allowed_fields: ClassVar[frozenset[str]] = frozenset({
        "title", "signer", "period", "date", "filename", "slide", "slides",
    })


class SlidesPreferences(PreferenceModel):
    common: CommonOverrides = Field(default_factory=CommonOverrides)
    signature: SignatureStyle = Field(default_factory=SignatureStyle)
    aspect_ratio: Literal["16:9", "4:3"] = "16:9"
    theme: Literal["executive", "clinical", "modern"] = "executive"
    typography: Typography = Field(default_factory=Typography)
    density: Literal["comfortable", "compact"] = "comfortable"
    layout: Literal["auto", "text", "image_left", "image_right"] = "auto"
    tables: TablePreferences = Field(default_factory=TablePreferences)
    charts: ChartPreferences = Field(default_factory=ChartPreferences)
    footer: SlideFooter = Field(default_factory=lambda: SlideFooter(right="{slide}"))
    footer_style: TextStyle = Field(default_factory=lambda: TextStyle(size=9))
    hide_title_slide_footer: bool = True


class FormatPreferences(PreferenceModel):
    schema_version: Literal[1] = 1
    common: CommonPreferences
    md: MarkdownPreferences = Field(default_factory=MarkdownPreferences)
    xlsx: WorkbookPreferences = Field(default_factory=WorkbookPreferences)
    pptx: SlidesPreferences = Field(default_factory=SlidesPreferences)
    pdf: PdfPreferences = Field(default_factory=PdfPreferences)
    word: WordPreferences = Field(default_factory=WordPreferences)

    @classmethod
    def from_delivery(cls, settings: ReportDeliverySettings) -> FormatPreferences:
        """绑定部署初值，保留既有 Word/PDF 字体和页眉页脚文案。"""
        from ..reporting.delivery.report_runtime.report_design import ReportDesign

        layout = settings.page_layout
        header = HeaderFooterText(left=layout.header_left.replace("{organization}", "{signer}"),
            right=layout.header_right.replace("{organization}", "{signer}"))
        footer = HeaderFooterText(left=layout.footer_left.replace("{organization}", "{signer}"),
            right=layout.footer_right.replace("{organization}", "{signer}"))
        typography = ReportDesign().typography.model_dump(mode="json", by_alias=True)
        for role, style in typography.items():
            if style["font"] == "sans":
                style["font"] = None
            if role in {"h1", "h2", "h3"} and style["color"] == "#174a66":
                style["color"] = None
        paged = {
            "headerFooter": {"header": header, "footer": footer,
                "headerDistance": 8, "footerDistance": 8},
            "page": {"margins": {"top": 20, "right": 18, "bottom": 22, "left": 18}},
            "typography": typography,
            "watermark": {"text": settings.branding.watermark_text},
            "signature": {**ReportDesign().typography.body.model_dump(mode="json", by_alias=True),
                "spaceBefore": 12 * 72 / 25.4},
        }
        return cls(common=CommonPreferences(signer=settings.branding.organization_name, date_format="iso",
            generated_by_label=settings.branding.generated_by_label),
            word=WordPreferences.model_validate(paged), pdf=PdfPreferences.model_validate(paged))


def resolve_format_preferences(document: FormatPreferences, format: Format) -> dict[str, Any]:
    """返回可冻结的独立值；日期和报告身份由任务修订绑定，不能在此刷新。"""
    if format not in FORMATS:
        raise ValueError("unsupported preference format")
    result = getattr(document, format).model_dump(mode="json", by_alias=True)
    result["common"] = {**document.common.model_dump(mode="json", by_alias=True),
        **{key: value for key, value in result["common"].items() if value is not None}}

    def resolve_styles(value, role=""):
        if not isinstance(value, dict):
            return
        if "font" in value and "size" in value:
            value["font"] = value["font"] or result["common"]["font"]
            value["color"] = value["color"] or (
                result["common"]["accentColor"] if role in {"h1", "h2", "h3"} else "#172033")
        for key, nested in value.items():
            resolve_styles(nested, key)

    resolve_styles(result)
    return result
