"""将冻结偏好映射为原生幻灯片文本与页码字段。"""
from copy import deepcopy
from string import Formatter

from .workbook_adapter import FONTS, displayed_date


def prepare_slides(preferences, *, title, period, generated_date, filename, slide_count):
    values = {"title": title, "period": period, "signer": preferences["common"]["signer"],
        "date": displayed_date(generated_date, preferences["common"]["dateFormat"]),
        "filename": filename, "slides": str(slide_count)}
    footer = {}
    for side, template in preferences["footer"].items():
        runs = []
        for literal, field, _, _ in Formatter().parse(template):
            if literal:
                runs.append({"text": literal})
            if field:
                runs.append({"text": "", "field": "slidenum" if field == "slide" else "slidecount"}
                    if field in {"slide", "slides"} else {"text": values[field]})
        footer[side] = runs
    return {**deepcopy(preferences), "fontNames": FONTS, "resolvedFooter": footer,
        "signatureLines": [values["signer"], values["date"],
            *preferences["signature"]["description"].splitlines()]}
