"""已解析格式偏好映射为独立渲染器设计，不读取可变全局默认。"""

from copy import deepcopy

from ..reporting.delivery.report_design import ReportDesign


def document_design(resolved: dict, *, overrides: dict | None = None) -> ReportDesign:
    document = {"page": deepcopy(resolved["page"]), "signature": {**deepcopy(resolved["signature"]), "dateFormat": resolved["common"]["dateFormat"]},
        "headerFooter": deepcopy(resolved["headerFooter"]),
        "typography": deepcopy(resolved["typography"]), "tables": deepcopy(resolved["tables"]), "watermark": deepcopy(resolved["watermark"]),
        "charts": {"keepWithCaption": resolved["charts"]["keepWithCaption"],
            "captionNumbering": resolved["charts"]["captionNumbering"],
            "imageDpi": resolved["charts"]["imageDpi"]},
        "options": {"cover": resolved["cover"], "toc": resolved["toc"], "sources": resolved["sources"],
            "headerFooter": resolved["headerFooter"]["enabled"], "pageNumbers": resolved["headerFooter"]["pageNumbers"]}}
    if 'bookmarks' in resolved:
        document['pdfOutput'] = {'bookmarks': resolved['bookmarks'], 'imageQuality': resolved['imageQuality']}

    def merge(target, values):
        for key, value in values.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = deepcopy(value)

    merge(document, overrides or {})
    result = ReportDesign.model_validate(document)
    # 复用模板样式、位置；署名和日期始终由本次绑定身份提供。
    result.cover.signature.text = None
    return result
