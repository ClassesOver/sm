"""独立的部署交付外观；不读取业务规则文件。"""

from collections.abc import Mapping
from string import Formatter

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class DeliveryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True, alias_generator=to_camel,
    )


class PageLayout(DeliveryModel):
    header_left: str = Field(default="{organization}", max_length=200)
    header_right: str = Field(default="{title}", max_length=200)
    footer_left: str = Field(default="企业智能运营报表", max_length=200)
    footer_right: str = Field(default="第 {page} / {pages} 页", max_length=200)

    @field_validator("header_left", "header_right", "footer_left", "footer_right")
    @classmethod
    def validate_format(cls, value: str) -> str:
        if any(ord(character) < 32 for character in value):
            raise ValueError("页面格式包含控制字符")
        for _literal, name, spec, conversion in Formatter().parse(value):
            if name is not None and (
                name not in {"title", "organization", "page", "pages"} or spec or conversion
            ):
                raise ValueError("页面格式只允许标题、组织和页码占位符")
        return value

    @model_validator(mode="after")
    def require_page_numbers(self) -> "PageLayout":
        fields = {
            name for text in (self.footer_left, self.footer_right)
            for _literal, name, _spec, _conversion in Formatter().parse(text)
        }
        if not {"page", "pages"} <= fields:
            raise ValueError("页脚必须包含 {page} 和 {pages}")
        return self


class DocumentBranding(DeliveryModel):
    organization_name: str = Field(default="上海鼎医信息技术有限公司", min_length=1, max_length=200)
    generated_by_label: str = Field(default="AI 智能报告平台生成", min_length=1, max_length=200)
    watermark_text: str = Field(default="AI 智能报告平台生成", min_length=1, max_length=200)

    @field_validator("organization_name", "generated_by_label", "watermark_text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(ord(character) < 32 for character in normalized):
            raise ValueError("文档品牌字段不能为空或包含控制字符")
        return normalized


class ReportDeliverySettings(DeliveryModel):
    branding: DocumentBranding = Field(default_factory=DocumentBranding)
    page_layout: PageLayout = Field(default_factory=PageLayout)

    @classmethod
    def from_env(cls, values: Mapping[str, str]) -> "ReportDeliverySettings":
        branding = {}
        for field, suffix in (
            ("organizationName", "ORGANIZATION_NAME"),
            ("generatedByLabel", "GENERATED_BY_LABEL"),
            ("watermarkText", "WATERMARK_TEXT"),
        ):
            key = f"AGENT_REPORT_{suffix}"
            if key in values:
                # 编制单位的空配置沿用已有部署默认。
                if suffix == "ORGANIZATION_NAME" and not values[key].strip():
                    continue
                branding[field] = values[key]
        layout = {
            field: values[f"AGENT_REPORT_{suffix}"]
            for field, suffix in (
                ("headerLeft", "HEADER_LEFT"), ("headerRight", "HEADER_RIGHT"),
                ("footerLeft", "FOOTER_LEFT"), ("footerRight", "FOOTER_RIGHT"),
            ) if f"AGENT_REPORT_{suffix}" in values
        }
        return cls(branding=DocumentBranding.model_validate(branding),
                   page_layout=PageLayout.model_validate(layout))
