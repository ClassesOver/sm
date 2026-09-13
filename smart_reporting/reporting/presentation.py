"""报告完成回复的统一格式。"""

from typing import Any
from urllib.parse import urlparse

from loguru import logger

_DEFAULT_COMPLETION_TEMPLATE = """## 报表已生成

### {report_title}

报告已完成发布。

{actions}
"""

_DEFAULT_ACTION_TEMPLATES = {
    "editor": "[**编辑报告**]({url})",
    "pdf": "[下载 PDF]({url})",
    "word": "[下载 Word]({url})",
}
_DEFAULT_ACTION_SEPARATOR = " · "


def _is_valid_delivery_url(url: object) -> bool:
    if (
        not isinstance(url, str)
        or not url
        or any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in url)
    ):
        return False
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False
    hostname_text = hostname if isinstance(hostname, str) else ""
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and bool(hostname_text)
        and not any(char.isspace() for char in hostname_text)
    )


def _normalize_report_title(report: dict[str, Any]) -> str | None:
    title = report.get("reportTitle")
    if isinstance(title, str):
        title = title.strip()
        if title:
            return title
    report_id = report.get("reportId")
    if isinstance(report_id, str) and report_id.strip():
        return report_id.strip()
    return None


def _format_completion_actions(
    urls: dict[str, str | None],
    templates: dict[str, str] | None = None,
    separator: str | None = None,
) -> str:
    templates = templates or _DEFAULT_ACTION_TEMPLATES
    separator = separator if separator is not None else _DEFAULT_ACTION_SEPARATOR
    actions: list[str] = []
    for key in ("editor", "pdf", "word"):
        url = urls.get(key)
        if not _is_valid_delivery_url(url):
            continue
        template = templates.get(key) or _DEFAULT_ACTION_TEMPLATES.get(key, "[{key}]({url})")
        actions.append(template.format(url=url))
    return separator.join(actions)


def completed_report_content(
    payload: dict[str, Any],
    *,
    template: str | None = None,
) -> str | None:
    if payload.get("status") != "completed":
        return None
    report = payload.get("report")
    if not isinstance(report, dict):
        return None
    pdf = report.get("pdf")
    word = report.get("word")
    editor = report.get("editor")
    pdf_url = pdf.get("downloadUrl") if isinstance(pdf, dict) else None
    word_url = word.get("downloadUrl") if isinstance(word, dict) else None
    editor_url = editor.get("openUrl") if isinstance(editor, dict) else None

    report_title = _normalize_report_title(report)
    if report_title is None:
        return "## 报告发布未完成\n\n未获取到有效的报表名称，请重试报表发布。"

    actions = _format_completion_actions({"editor": editor_url, "pdf": pdf_url, "word": word_url})
    if not actions:
        return "## 报告发布未完成\n\n未生成有效的编辑、PDF 或 Word 交付链接，请重试报表发布。"

    template = template if template is not None else _DEFAULT_COMPLETION_TEMPLATE
    try:
        return template.format(
            report_title=report_title,
            editor_url=editor_url or "",
            pdf_url=pdf_url or "",
            word_url=word_url or "",
            actions=actions,
        ).strip()
    except (KeyError, ValueError, IndexError, AttributeError, TypeError) as error:
        logger.bind(error_type=type(error).__name__).warning("report_completion_template_invalid")
        return _DEFAULT_COMPLETION_TEMPLATE.format(
            report_title=report_title,
            editor_url=editor_url or "",
            pdf_url=pdf_url or "",
            word_url=word_url or "",
            actions=actions,
        ).strip()
