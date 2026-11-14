"""PDF 与 Word 共用的展示设计适配；不修改正文与服务端业务事实。"""

from __future__ import annotations

import html
from datetime import date
from typing import Any

from .report_design import FONTS, CoverBox, ReportDesign, TextStyle, cover_text


def presentation_context(design: ReportDesign, context: dict[str, Any]) -> dict[str, Any]:
    return {**context, "title": design.cover.title.text if design.cover.title.text is not None else context["title"]}


def signature_date(design: ReportDesign, context: dict[str, Any]) -> str:
    value = context["generatedDate"]
    if design.signature is None or design.signature.date_format == "iso":
        return value
    parsed = date.fromisoformat(value)
    if design.signature.date_format == "chinese":
        return f"{parsed.year}年{parsed.month}月{parsed.day}日"
    return parsed.strftime("%Y/%m/%d")


def header_footer_values(design: ReportDesign, context: dict[str, Any], *, filename: str) -> dict[str, str]:
    return {"title": context["title"], "signer": context["organizationName"],
        "period": context.get("periodLabel", ""), "date": signature_date(design, context), "filename": filename}


def page_decoration_texts(design: ReportDesign, context: dict[str, Any], *, physical_page: int,
    body_start_page: int, page: int | str, pages: int | str, filename: str) -> dict[str, str]:
    """生成与验收共用已解析装饰文本，页码来自实际分页结果。"""
    prefs = design.header_footer
    result = {f"{kind}{side.title()}": "" for kind in ("header", "footer") for side in ("left", "center", "right")}
    if prefs is None or not (prefs.enabled and design.options.header_footer):
        return result
    header, footer = prefs.header, prefs.footer
    if prefs.first_page_different and physical_page == body_start_page:
        header, footer = prefs.first_header, prefs.first_footer
    elif prefs.odd_even_different and physical_page % 2 == 0:
        header, footer = prefs.even_header or prefs.header, prefs.even_footer or prefs.footer
    if physical_page >= body_start_page:
        page += prefs.page_number_start - 1
    values = {**header_footer_values(design, context, filename=filename),
        "page": page if design.options.page_numbers else "", "pages": pages if design.options.page_numbers else ""}
    return {f"{kind}{side.title()}": getattr(template, side).format_map(values)
        for kind, template in (("header", header), ("footer", footer)) for side in ("left", "center", "right")}


def visible_cover_text(design: ReportDesign, context: dict[str, Any]) -> list[str]:
    values = cover_text(design, context)
    return [values[key] for key in ("title", "period", "signature") if getattr(design.cover, key).visible and values[key]]


def text_css(style: TextStyle) -> str:
    return (
        f"font-family:'{FONTS[style.font]}';font-size:{style.size:g}pt;color:{style.color};"
        f"font-weight:{700 if style.bold else 400};line-height:{style.line_height:g};"
        f"margin-top:{style.space_before:g}pt;margin-bottom:{style.space_after:g}pt;"
        f"text-indent:{style.indent:g}pt;"
    )


def cover_html(design: ReportDesign, context: dict[str, Any]) -> str:
    values = cover_text(design, context)
    boxes = []
    for key in ("title", "period", "signature"):
        box = page_cover_box(design, key)
        if box.visible and values[key]:
            boxes.append(
                f'<div class="cover-box cover-{key}" style="left:{box.x:g}mm;top:{box.y:g}mm;'
                f'width:{box.width:g}mm;height:{box.height:g}mm;text-align:{box.align};{text_css(box)}">'
                f'{html.escape(values[key])}</div>'
            )
    return '<section class="report-cover">' + "".join(boxes) + "</section>"


def page_cover_box(design: ReportDesign, key: str) -> CoverBox:
    """封面编辑坐标沿用 A4 参考系，实际输出按所选纸张换算。"""
    box = getattr(design.cover, key)
    if design.page is None:
        return box
    width, height = design.page.dimensions()
    return box.model_copy(update={"x": box.x * width / 210, "y": box.y * height / 297,
        "width": box.width * width / 210, "height": box.height * height / 297})


def design_css(design: ReportDesign) -> str:
    typography = design.typography
    rules = [
        f"@page cover{{margin:0;background:{design.cover.background}}}",
        ".report-cover{display:block;width:210mm;height:297mm;min-height:0;margin:0;position:relative}",
        ".cover-box{position:absolute;box-sizing:border-box;white-space:pre-wrap;overflow:hidden;overflow-wrap:anywhere;padding:0}",
        f".report-body{{{text_css(typography.body)}}}",
        f".report-body p,.report-body li{{margin-top:{typography.body.space_before:g}pt;margin-bottom:{typography.body.space_after:g}pt;text-indent:{typography.body.indent:g}pt}}",
    ]
    if design.pdf_output is not None and not design.pdf_output.bookmarks:
        rules.append('*{bookmark-level:none!important}')
    for selector, style in (
        (".report-body h2,.report-body .report-appendix-title,.report-body .report-summary-title,.report-body .report-source-title", typography.h1),
        (".report-body h3", typography.h2), (".report-body h4", typography.h3),
        (".report-body table,.report-body th,.report-body td,.report-body td p,.report-body th p", typography.table),
        (".report-body .report-figure-caption,.report-body .report-table-caption", typography.caption),
    ):
        rules.append(f"{selector}{{{text_css(style)}}}")
    if design.page is not None:
        width, height = design.page.dimensions()
        margin = design.page.margins
        for name in ("cover", "toc", "body"):
            margins = "0" if name == "cover" else f"{margin.top:g}mm {margin.right:g}mm {margin.bottom:g}mm {margin.left:g}mm"
            rules.append(f"@page {name}{{size:{width:g}mm {height:g}mm;margin:{margins}}}")
        rules.append(f".report-cover{{width:{width:g}mm;height:{height:g}mm}}")
    if design.signature is not None:
        style = design.signature
        rules.append(f".report-signature{{{text_css(style)}text-align:{style.align};break-inside:avoid}}")
        rules.append(f".report-signature p{{{text_css(style)}margin-top:0}}.report-signature p+p{{margin-top:{style.date_gap:g}pt}}")
    if design.tables is not None:
        tables = design.tables
        rules.append(".report-body thead{display:" + ("table-header-group" if tables.repeat_header else "table-row-group") + "}")
        rules.append(".report-body tr{break-inside:" + ("auto" if tables.split_rows else "avoid") + "}")
        if tables.split_rows:
            rules.append(".report-body .report-table-keep{break-inside:auto}")
        if tables.borders == "none":
            rules.append(".report-body th,.report-body td{border:0}")
        elif tables.borders == "light":
            rules.append(".report-body th,.report-body td{border-left:0;border-right:0}")
        if not tables.striped:
            rules.append(".report-body tr.report-row-even{background:transparent}")
    if design.charts is not None and not design.charts.keep_with_caption:
        rules.extend((
            ".report-body .report-figure{break-inside:auto;page-break-inside:auto;break-before:auto;break-after:auto}",
            ".report-body .report-figure-image{break-after:auto;page-break-after:auto}",
            ".report-body .report-figure-caption{break-before:auto;page-break-before:auto;break-after:auto;page-break-after:auto}",
            ".report-body .report-figure+p{break-before:auto;page-break-before:auto}",
            ".report-body p:has(+.report-figure){break-after:auto;page-break-after:auto}",
        ))
    return "".join(rules)


def watermark_boxes(design: ReportDesign) -> list[tuple[float, float, float, float]]:
    boxes = ([(x, y, 75, 35) for y in (55, 135, 215) for x in (25, 110)]
        if design.watermark.placement == "tile" else [(25, 122, 160, 50)])
    width, height = design.page.dimensions() if design.page else (210, 297)
    return [(x * width / 210, y * height / 297, w * width / 210, h * height / 297) for x, y, w, h in boxes]


def watermark_text(design: ReportDesign, context: dict[str, Any]) -> str:
    return design.watermark.text if design.watermark.text is not None else context["watermarkText"]


def watermark_html(design: ReportDesign, context: dict[str, Any]) -> str:
    mark = design.watermark
    if not mark.enabled:
        return ""
    return "".join(
        f'<div style="position:absolute;left:{x:g}mm;top:{y:g}mm;width:{width:g}mm;height:{height:g}mm;'
        f'text-align:center;display:flex;align-items:center;justify-content:center;transform:rotate({mark.angle:g}deg);font-family:\'{FONTS[mark.font]}\';'
        f'font-size:{mark.size:g}pt;line-height:1.15;color:{mark.color};opacity:{mark.opacity:g};'
        f'white-space:pre-wrap;overflow-wrap:anywhere">{html.escape(watermark_text(design, context))}</div>'
        for x, y, width, height in watermark_boxes(design)
    )


def apply_word_style(style: Any, value: TextStyle) -> None:
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    if hasattr(style, "font"):
        style.font.name = FONTS[value.font]
        style.font.size = Pt(value.size)
        style.font.color.rgb = RGBColor.from_string(value.color[1:])
        style.font.bold = value.bold
        fonts = style._element.get_or_add_rPr().get_or_add_rFonts()
        for key in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(qn(f"w:{key}"), FONTS[value.font])
    if hasattr(style, "paragraph_format"):
        paragraph = style.paragraph_format
        paragraph.line_spacing = value.line_height
        paragraph.space_before = Pt(value.space_before)
        paragraph.space_after = Pt(value.space_after)
        paragraph.first_line_indent = Pt(value.indent)


def add_word_textbox(paragraph: Any, *, identity: str, text: str, box: CoverBox, angle: float = 0, behind: bool = False) -> None:
    """VML 文本框在 Word 和 LibreOffice 保持文字可编辑，并相对整页定位。"""
    from docx.oxml import parse_xml

    line = round(box.line_height * 240)
    text_runs = "<w:br/>".join(f'<w:t xml:space="preserve">{html.escape(value)}</w:t>' for value in text.split("\n"))
    shape = parse_xml(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">'
        '<w:pict><v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" path="m,l,21600r21600,l21600,xe">'
        '<v:stroke joinstyle="miter"/><v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>'
        f'<v:shape id="{identity}" type="#_x0000_t202" filled="f" stroked="f" '
        f'style="position:absolute;margin-left:{box.x:g}mm;margin-top:{box.y:g}mm;'
        f'width:{box.width:g}mm;height:{box.height:g}mm;rotation:{angle % 360:g};'
        f'z-index:{-251654144 if behind else 251659264};mso-position-horizontal-relative:page;'
        'mso-position-vertical-relative:page;mso-wrap-style:none">'
        '<v:textbox inset="0,0,0,0"><w:txbxContent><w:p><w:pPr>'
        f'<w:pStyle w:val="Title"/><w:spacing w:before="{round(box.space_before * 20)}" '
        f'w:after="{round(box.space_after * 20)}" w:line="{line}" w:lineRule="auto"/>'
        f'<w:ind w:firstLine="{round(box.indent * 20)}"/><w:jc w:val="{box.align}"/>'
        '<w:keepNext w:val="0"/><w:snapToGrid w:val="0"/></w:pPr><w:r><w:rPr>'
        f'<w:rFonts w:ascii="{FONTS[box.font]}" w:hAnsi="{FONTS[box.font]}" w:eastAsia="{FONTS[box.font]}"/>'
        f'<w:b w:val="{int(box.bold)}"/><w:color w:val="{box.color[1:]}"/>'
        f'<w:sz w:val="{round(box.size * 2)}"/><w:szCs w:val="{round(box.size * 2)}"/>'
        f'</w:rPr>{text_runs}</w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict></w:r>'
    )
    paragraph._p.append(shape)


def add_word_cover(paragraph: Any, design: ReportDesign, context: dict[str, Any]) -> None:
    if design.cover.background.lower() != "#ffffff":
        from docx.oxml import parse_xml

        paragraph._p.append(parse_xml(
            '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:v="urn:schemas-microsoft-com:vml">'
            '<w:pict><v:rect id="ReportCoverBackground" stroked="f" '
            f'fillcolor="{design.cover.background}" style="position:absolute;margin-left:0mm;margin-top:0mm;'
            f'width:{(design.page.dimensions()[0] if design.page else 210):g}mm;height:{(design.page.dimensions()[1] if design.page else 297):g}mm;z-index:-251654145;mso-position-horizontal-relative:page;'
            'mso-position-vertical-relative:page"/></w:pict></w:r>'
        ))
    values = cover_text(design, context)
    for key in ("title", "period", "signature"):
        box = page_cover_box(design, key)
        if box.visible and values[key]:
            add_word_textbox(paragraph, identity=f"ReportCover{key.title()}", text=values[key], box=box)


def add_word_watermark(header: Any, design: ReportDesign, context: dict[str, Any], *, section: int, cover: bool) -> None:
    mark = design.watermark
    if not mark.enabled or (cover and not mark.cover):
        return
    # Word 不支持文本透明度；将字色与页面底色混合，与 PDF 的 alpha 合成保持一致。
    background = design.cover.background if cover else "#ffffff"
    foreground = mark.color
    color = "#" + "".join(f"{round(int(foreground[i:i+2], 16) * mark.opacity + int(background[i:i+2], 16) * (1 - mark.opacity)):02x}" for i in (1, 3, 5))
    import subprocess

    from docx.oxml import parse_xml
    from PIL import ImageFont

    font_path = subprocess.run(["fc-match", "-f", "%{file}", FONTS[mark.font]], capture_output=True, text=True, check=True).stdout
    font = ImageFont.truetype(font_path, round(mark.size * 10))
    text = watermark_text(design, context)
    if not text:
        return
    # WordArt 的几何框决定实际字形大小；使用字体实际字宽创建自然尺寸，避免拉伸。
    text_width = font.getlength(text) / 10 * 25.4 / 72
    text_height = mark.size * 25.4 / 72
    paragraph = header.add_paragraph()
    for index, (x, y, width, height) in enumerate(watermark_boxes(design)):
        actual_width = min(text_width, width)
        paragraph._p.append(parse_xml(
            '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"><w:pict>'
            '<v:shapetype id="_x0000_t136" coordsize="21600,21600" o:spt="136" adj="10800" path="m@7,l@8,m@5,21600l@6,21600e">'
            '<v:formulas><v:f eqn="sum #0 0 10800"/><v:f eqn="prod #0 2 1"/><v:f eqn="sum 21600 0 @1"/>'
            '<v:f eqn="sum 0 0 @2"/><v:f eqn="sum 21600 0 @3"/><v:f eqn="if @0 @3 0"/><v:f eqn="if @0 21600 @1"/>'
            '<v:f eqn="if @0 0 @2"/><v:f eqn="if @0 @4 21600"/><v:f eqn="mid @5 @6"/><v:f eqn="mid @8 @5"/>'
            '<v:f eqn="mid @7 @8"/><v:f eqn="mid @6 @7"/><v:f eqn="sum @6 0 @5"/></v:formulas>'
            '<v:path textpathok="t" o:connecttype="custom" o:connectlocs="@9,0;@10,10800;@11,21600;@12,10800" o:connectangles="270,180,90,0"/>'
            '<v:textpath on="t" fitshape="t"/><v:handles><v:h position="#0,bottomRight" xrange="6629,14971"/></v:handles>'
            '<o:lock v:ext="edit" text="t" shapetype="t"/></v:shapetype>'
            f'<v:shape id="PowerPlusWaterMarkObject{section}_{index}" type="#_x0000_t136" filled="t" '
            f'fillcolor="{color}" stroked="f" style="position:absolute;margin-left:{x + (width - actual_width) / 2:g}mm;'
            f'margin-top:{y + (height - text_height) / 2:g}mm;width:{actual_width:g}mm;height:{text_height:g}mm;'
            f'rotation:{mark.angle:g};z-index:-251654144;mso-position-horizontal-relative:page;mso-position-vertical-relative:page">'
            f'<v:textpath on="t" fitshape="f" style="font-family:{FONTS[mark.font]};font-size:{mark.size:g}pt" '
            f'string="{html.escape(text, quote=True)}"/></v:shape></w:pict></w:r>'
        ))


def cover_layout_issues(pages: list[Any], design: ReportDesign) -> list[dict[str, str]]:
    """读取实际排版的文字行，提示截断或互相覆盖；告警不抛弃已经生成的文件。"""
    if not design.options.cover or not pages:
        return []
    issues = []
    rectangles = []
    labels = {"title": "标题", "period": "期间", "signature": "落款"}
    for box in pages[0]._page_box.descendants():
        if box.element is None or "cover-box" not in box.element.get("class", "").split():
            continue
        children = getattr(box, "children", ())
        if not children:
            continue
        name = next((key for key in labels if f"cover-{key}" in box.element.get("class", "").split()), None)
        if name is None:
            continue
        x, y = box.content_box_x(), box.content_box_y()
        if any(child.position_y + child.height > y + box.height + 1 or child.position_x + child.width > x + box.width + 1 for child in children):
            issues.append({"code": "report_cover_text_overflow", "message": f"封面{labels[name]}超出文字框，部分文字可能被截断，请调整文字框或字号。"})
        # 采用实际文字行的边界；空文字框和未占用留白不计入覆盖。
        rectangles.append((name, min(child.position_x for child in children), min(child.position_y for child in children), max(child.position_x + child.width for child in children), max(child.position_y + child.height for child in children)))
    for index, (name, left, top, right, bottom) in enumerate(rectangles):
        for other, x0, y0, x1, y1 in rectangles[index + 1:]:
            if min(right, x1) - max(left, x0) > 1 and min(bottom, y1) - max(top, y0) > 1:
                issues.append({"code": "report_cover_overlap", "message": f"封面{labels[name]}与{labels[other]}文字区域重叠，请调整位置。"})
    return issues
