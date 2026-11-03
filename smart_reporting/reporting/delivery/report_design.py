"""报告设计共享入口；实际模型随独立渲染器一起打包。"""
from .report_runtime.report_design import (
    COLOR,
    FONTS,
    CoverBox,
    CoverDesign,
    DesignModel,
    DesignOptions,
    Font,
    ReportDesign,
    TextStyle,
    Typography,
    WatermarkDesign,
    cover_text,
    resolve_design,
    template_design,
)

__all__ = ['COLOR', 'FONTS', 'CoverBox', 'CoverDesign', 'DesignModel', 'DesignOptions', 'Font', 'ReportDesign', 'TextStyle', 'Typography', 'WatermarkDesign', 'cover_text', 'resolve_design', 'template_design']
