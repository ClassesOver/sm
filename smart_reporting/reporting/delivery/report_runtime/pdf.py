"""Reporting PDF 渲染、页码和视觉验收能力。"""

from __future__ import annotations

import html
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from string import Formatter
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .markdown import REPORT_VISUAL_THEME
from .validation import MAX_PDF_BYTES, ReportFailure

MAX_PDF_PAGES = 200
DEFAULT_PAGE_LAYOUT = {
    "headerLeft": "{organization}",
    "headerRight": "{title}",
    "footerLeft": "企业智能运营报表",
    "footerRight": "第 {page} / {pages} 页",
}
PAGE_LAYOUT_FIELDS = frozenset(DEFAULT_PAGE_LAYOUT)
PAGE_LAYOUT_PLACEHOLDERS = frozenset({"title", "organization", "page", "pages"})
_CITATION_MARKER = re.compile(r"\[\[citation:([^\]\r\n]+)\]\]")
_SECTION_MARKER = re.compile(r"\[\[section:([^\]\r\n]+)\]\]")
_ANALYSIS_MARKER = re.compile(r"\[\[analysis:([^\]\r\n]+)\]\]")
_CLAIM_MARKER = re.compile(r"\[\[claim:([^\]\r\n]+)\]\]")
_TABLE_MARKER = re.compile(r"\[\[/?table:[^\]\r\n]+\]\]")
_TABLE_OPEN_MARKER = re.compile(r"\[\[table:([^\]\r\n]+)\]\]")
_TABLE_CLOSE_MARKER = re.compile(r"\[\[/table:([^\]\r\n]+)\]\]")
# 数据来源锚点按文档出现顺序扫描：claim 标记、表格起始标记与行内图片。
_TRACE_ANCHOR_MARKER = re.compile(
    r"\[\[claim:(?P<claim>[^\]\r\n]+)\]\]"
    r"|\[\[table:(?P<table>[^\]\r\n]+)\]\]"
    r"|!\[[^\]\r\n]*\]\((?P<src>[^)\s]+)\)"
)
# 静态图来源编号写进图注（图片段落后的 ``*图表：…*`` 约定行），
# 不改图片本身；无图注的图片只进附录，不在正文出现编号。
_CHART_IMAGE_WITH_CAPTION = re.compile(
    r"(?P<image>!\[[^\]\r\n]*\]\((?P<src>[^)\s]+)\))"
    r"(?P<sep>(?:[ \t]*\[来源 [0-9]{3}\])*[ \t]*(?:\r?\n[ \t]*)+)"
    r"\*图表：(?P<caption>[^\r\n*]+)\*"
)
_MAX_TRACE_CLAIMS = 400
_MAX_TRACE_TABLES = 400
_MAX_TRACE_CHARTS = 200
_MAX_TRACE_NUMBERED = 999
_TRACE_STATUS_LABELS = frozenset({"valid", "stale", "unbound", "missing"})
_TRACE_COMMON_KEYS = frozenset({"subjectIds", "status", "datasetIds", "links"})
_TRACE_CLAIM_KEYS = _TRACE_COMMON_KEYS | {
    "claimId", "factValue", "unit", "periods", "formula", "scope",
}
_TRACE_TABLE_KEYS = _TRACE_COMMON_KEYS | {"tableId", "methods"}
_TRACE_CHART_KEYS = _TRACE_COMMON_KEYS | {
    "chartId", "methods", "transformNotes", "unit", "imagePath",
}
_TRACE_DATASET_KEYS = frozenset({"filename", "businessLabel", "periodRoles"})
_TRACE_PERIOD_ROLES = frozenset({"current", "yoy", "mom"})


def _trace_str_list(
    value: Any, *, field: str, max_items: int, max_length: int
) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items:
        raise ReportFailure(f"PDF 数据来源{field}无效")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not 1 <= len(item) <= max_length:
            raise ReportFailure(f"PDF 数据来源{field}无效")
        items.append(item)
    return items


def _trace_links(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 10:
        raise ReportFailure("PDF 数据来源在线定位信息无效")
    links: list[dict[str, str]] = []
    for link in value:
        if not isinstance(link, dict) or set(link) != {"subjectId", "url"}:
            raise ReportFailure("PDF 数据来源在线定位信息无效")
        subject_id = link.get("subjectId")
        url = link.get("url")
        if (
            not isinstance(subject_id, str)
            or not 1 <= len(subject_id) <= 128
            or not _valid_source_url(url, subject_id)
        ):
            raise ReportFailure("PDF 数据来源在线定位信息无效")
        links.append({"subjectId": subject_id, "url": url})
    if len({link["subjectId"] for link in links}) != len(links):
        raise ReportFailure("PDF 数据来源在线定位信息重复")
    return links


def _normalize_trace_entry(
    item: Any, *, keys: frozenset[str], kind: str
) -> dict[str, Any]:
    if not isinstance(item, dict) or set(item) - {"omittedCounts"} != keys:
        raise ReportFailure("PDF 数据来源展示信息无效")
    omitted = item.get("omittedCounts", {})
    if not isinstance(omitted, dict) or any(
        field not in {"datasetIds", "methods", "transformNotes", "subjectIds", "links"}
        or isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100000
        for field, count in omitted.items()
    ):
        raise ReportFailure("PDF 数据来源省略数量无效")
    subject_ids = _trace_str_list(item["subjectIds"], field="主体", max_items=10, max_length=128)
    status = item["status"]
    if status not in _TRACE_STATUS_LABELS:
        raise ReportFailure("PDF 数据来源状态无效")
    dataset_ids = _trace_str_list(item["datasetIds"], field="数据集", max_items=10, max_length=64)
    return {
        **item,
        "kind": kind,
        "subjectIds": subject_ids,
        "status": status,
        "datasetIds": dataset_ids,
        "links": _trace_links(item["links"]),
    }


def _normalize_trace_sources(value: Any) -> dict[str, Any]:
    """严格校验服务端登记的数据来源附录载荷（B8）。

    编号永远由渲染器按正文首次出现顺序分配，载荷只携带冻结摘要与
    在线定位；未知或畸形字段直接失败，不允许模型或客户端注入展示内容。
    """

    if value is None:
        return {"claims": {}, "tables": {}, "charts": [], "datasets": {}}
    if (
        not isinstance(value, dict)
        or set(value) != {"claims", "tables", "charts", "datasets"}
        or not isinstance(value["claims"], list)
        or not isinstance(value["tables"], list)
        or not isinstance(value["charts"], list)
        or not isinstance(value["datasets"], dict)
    ):
        raise ReportFailure("PDF 数据来源展示信息无效")
    if (
        len(value["claims"]) > _MAX_TRACE_CLAIMS
        or len(value["tables"]) > _MAX_TRACE_TABLES
        or len(value["charts"]) > _MAX_TRACE_CHARTS
    ):
        raise ReportFailure("PDF 数据来源数量超出渲染上限")
    datasets: dict[str, dict[str, Any]] = {}
    for dataset_id, info in value["datasets"].items():
        if (
            not isinstance(dataset_id, str)
            or not 1 <= len(dataset_id) <= 64
            or not isinstance(info, dict)
            or set(info) != _TRACE_DATASET_KEYS
        ):
            raise ReportFailure("PDF 数据来源数据集信息无效")
        filename = info["filename"]
        business_label = info["businessLabel"]
        period_roles = info["periodRoles"]
        if (filename is not None and (not isinstance(filename, str) or len(filename) > 255)) or (
            business_label is not None
            and (not isinstance(business_label, str) or len(business_label) > 255)
        ):
            raise ReportFailure("PDF 数据来源数据集信息无效")
        if (
            not isinstance(period_roles, list)
            or len(period_roles) > 3
            or any(role not in _TRACE_PERIOD_ROLES for role in period_roles)
        ):
            raise ReportFailure("PDF 数据来源数据集信息无效")
        datasets[dataset_id] = {
            "filename": filename,
            "businessLabel": business_label,
            "periodRoles": list(period_roles),
        }
    claims: dict[str, dict[str, Any]] = {}
    for item in value["claims"]:
        extra_claim_ids = item.get("claimIds") if isinstance(item, dict) else None
        normalized_item = {key: item_value for key, item_value in item.items() if key != "claimIds"} if isinstance(item, dict) else item
        entry = _normalize_trace_entry(normalized_item, keys=_TRACE_CLAIM_KEYS, kind="claim")
        claim_id = entry["claimId"]
        fact_value = entry["factValue"]
        unit = entry["unit"]
        formula = entry["formula"]
        scope = entry["scope"]
        if (
            not isinstance(claim_id, str)
            or not 1 <= len(claim_id) <= 128
            or claim_id in claims
        ):
            raise ReportFailure("PDF 数据来源 claim 无效或重复")
        if isinstance(fact_value, bool) or not (
            fact_value is None or isinstance(fact_value, (int, float, str))
        ):
            raise ReportFailure("PDF 数据来源事实值无效")
        if isinstance(fact_value, float) and (fact_value != fact_value or fact_value in {float("inf"), float("-inf")}):
            raise ReportFailure("PDF 数据来源事实值无效")
        if isinstance(fact_value, str) and len(fact_value) > 128:
            raise ReportFailure("PDF 数据来源事实值无效")
        if unit is not None and (not isinstance(unit, str) or len(unit) > 64):
            raise ReportFailure("PDF 数据来源单位无效")
        if formula is not None and (not isinstance(formula, str) or len(formula) > 1000):
            raise ReportFailure("PDF 数据来源方法无效")
        if not isinstance(scope, dict) or len(scope) > 20 or any(
            not isinstance(key, str)
            or not 1 <= len(key) <= 64
            or not isinstance(item_value, str)
            or len(item_value) > 256
            for key, item_value in scope.items()
        ):
            raise ReportFailure("PDF 数据来源范围无效")
        entry["periods"] = _trace_str_list(entry["periods"], field="期间", max_items=50, max_length=64)
        claim_ids = [claim_id] if extra_claim_ids is None else _trace_str_list(
            extra_claim_ids, field="claim 标记", max_items=_MAX_TRACE_CLAIMS, max_length=128,
        )
        if not claim_ids or claim_id not in claim_ids or len(set(claim_ids)) != len(claim_ids):
            raise ReportFailure("PDF 数据来源 claim 无效或重复")
        for registered_id in claim_ids:
            if registered_id in claims:
                raise ReportFailure("PDF 数据来源 claim 无效或重复")
            claims[registered_id] = entry
    tables: dict[str, dict[str, Any]] = {}
    for item in value["tables"]:
        entry = _normalize_trace_entry(item, keys=_TRACE_TABLE_KEYS, kind="table")
        table_id = entry["tableId"]
        if (
            not isinstance(table_id, str)
            or not 1 <= len(table_id) <= 128
            or table_id in tables
        ):
            raise ReportFailure("PDF 数据来源表格无效或重复")
        entry["methods"] = _trace_str_list(entry["methods"], field="方法", max_items=5, max_length=128)
        tables[table_id] = entry
    charts: list[dict[str, Any]] = []
    chart_ids: set[str] = set()
    for item in value["charts"]:
        entry = _normalize_trace_entry(item, keys=_TRACE_CHART_KEYS, kind="chart")
        chart_id = entry["chartId"]
        image_path = entry["imagePath"]
        unit = entry["unit"]
        if (
            not isinstance(chart_id, str)
            or not 1 <= len(chart_id) <= 128
            or chart_id in chart_ids
        ):
            raise ReportFailure("PDF 数据来源图表无效或重复")
        chart_ids.add(chart_id)
        if (
            not isinstance(image_path, str)
            or not 1 <= len(image_path) <= 512
            or "\\" in image_path
            or image_path.startswith("/")
            or ".." in PurePosixPath(image_path).parts
        ):
            raise ReportFailure("PDF 数据来源图表路径无效")
        if unit is not None and (not isinstance(unit, str) or len(unit) > 64):
            raise ReportFailure("PDF 数据来源单位无效")
        entry["methods"] = _trace_str_list(entry["methods"], field="方法", max_items=5, max_length=128)
        entry["transformNotes"] = _trace_str_list(
            entry["transformNotes"], field="转换说明", max_items=10, max_length=200
        )
        charts.append(entry)
    return {"claims": claims, "tables": tables, "charts": charts, "datasets": datasets}


def _assign_trace_aliases(markdown: str, trace: dict[str, Any]) -> dict[str, str]:
    """按正文首次出现顺序分配数据来源编号；未出现的登记项排在其后。

    图片按 ``src`` 与登记 ``imagePath`` 的相等或后缀关系唯一匹配；
    匹配不唯一时不给正文编号，附录仍按登记顺序列出。
    """

    chart_alias_by_src: dict[str, str] = {}
    state = {"counter": 0}

    def assign(entry: dict[str, Any]) -> None:
        if entry.get("alias") is not None:
            return
        state["counter"] += 1
        if state["counter"] > _MAX_TRACE_NUMBERED:
            raise ReportFailure("PDF 数据来源编号超出渲染上限")
        entry["alias"] = f"[数据来源 {state['counter']:03d}]"

    charts = trace["charts"]
    for match in _TRACE_ANCHOR_MARKER.finditer(markdown):
        claim_id = match.group("claim")
        table_id = match.group("table")
        src = match.group("src")
        if claim_id is not None:
            entry = trace["claims"].get(claim_id)
            if entry is not None:
                assign(entry)
        elif table_id is not None:
            entry = trace["tables"].get(table_id)
            if entry is not None:
                assign(entry)
        elif src is not None:
            decoded = unquote(urlsplit(src).path)
            candidates = [
                chart
                for chart in charts
                if chart["imagePath"] == decoded or chart["imagePath"].endswith("/" + decoded)
            ]
            if len(candidates) == 1:
                assign(candidates[0])
                chart_alias_by_src[src] = candidates[0]["alias"]
    for entry in (
        *trace["claims"].values(),
        *trace["tables"].values(),
        *charts,
    ):
        assign(entry)
    return chart_alias_by_src



def _normalize_citation_presentations(
    presentations: Any, marker_ids: tuple[str, ...]
) -> list[dict[str, Any]]:
    if not isinstance(presentations, list):
        raise ReportFailure("PDF 缺少服务端实际引用展示信息")
    normalized_by_id: dict[str, dict[str, Any]] = {}
    allowed_keys = {
        "citationId",
        "label",
        "coverageItems",
        "status",
        "method",
        "scope",
        "summary",
        "subjectId",
        "url",
        "links",
    }
    for item in presentations:
        if (
            not isinstance(item, dict)
            or set(item) - allowed_keys
            or not {"citationId", "label", "coverageItems"}.issubset(item)
        ):
            raise ReportFailure("PDF 实际引用展示信息无效")
        citation_id = item.get("citationId")
        label = item.get("label")
        coverage_items = item.get("coverageItems")
        if (
            not isinstance(citation_id, str)
            or not citation_id
            or not isinstance(label, str)
            or not 1 <= len(label) <= 200
            or not isinstance(coverage_items, list)
            or len(coverage_items) > 100
        ):
            raise ReportFailure("PDF 实际引用展示信息与 Markdown 顺序不一致")
        normalized_coverage: list[dict[str, Any]] = []
        for coverage_index, coverage in enumerate(coverage_items, start=1):
            if not isinstance(coverage, dict) or set(coverage) != {"label", "periods"}:
                raise ReportFailure("PDF 实际引用数据覆盖信息无效")
            coverage_label = coverage.get("label")
            periods = coverage.get("periods")
            if (
                not isinstance(coverage_label, str)
                or not 1 <= len(coverage_label) <= 200
                or not isinstance(periods, list)
                or len(periods) > 1200
                or any(not isinstance(period, str) or len(period) > 32 for period in periods)
            ):
                raise ReportFailure("PDF 实际引用数据覆盖信息无效")
            normalized_coverage.append(
                {"label": coverage_label or f"来源项 {coverage_index}", "periods": periods}
            )
        status = item.get("status", "valid")
        method = item.get("method", "冻结快照")
        scope = item.get("scope", "报告登记范围")
        summary = item.get("summary")
        subject_id = item.get("subjectId")
        url = item.get("url")
        raw_links = item.get("links", ())
        if (
            status not in {"valid", "stale", "unbound", "missing"}
            or not isinstance(method, str)
            or not 1 <= len(method) <= 200
            or not isinstance(scope, str)
            or not 1 <= len(scope) <= 500
            or (summary is not None and (not isinstance(summary, str) or len(summary) > 500))
            or (subject_id is not None and (not isinstance(subject_id, str) or len(subject_id) > 128))
            or (url is not None and not _valid_source_url(url, subject_id))
            or not isinstance(raw_links, (list, tuple))
            or len(raw_links) > 100
        ):
            raise ReportFailure("PDF 实际引用摘要信息无效")
        normalized_links: list[dict[str, str]] = []
        for link in raw_links:
            if not isinstance(link, dict) or set(link) != {"subjectId", "label", "url"}:
                raise ReportFailure("PDF 实际引用在线定位信息无效")
            link_subject = link.get("subjectId")
            link_label = link.get("label")
            link_url = link.get("url")
            if (
                not isinstance(link_subject, str)
                or not 1 <= len(link_subject) <= 128
                or not isinstance(link_label, str)
                or not 1 <= len(link_label) <= 100
                or not _valid_source_url(link_url, link_subject)
            ):
                raise ReportFailure("PDF 实际引用在线定位信息无效")
            normalized_links.append(
                {"subjectId": link_subject, "label": link_label, "url": link_url}
            )
        if len({link["subjectId"] for link in normalized_links}) != len(normalized_links):
            raise ReportFailure("PDF 实际引用在线定位信息重复")
        if url is not None and subject_id is not None:
            normalized_links.append(
                {"subjectId": subject_id, "label": "来源对象", "url": url}
            )
        if citation_id in normalized_by_id:
            raise ReportFailure("PDF 实际引用展示信息重复")
        normalized_by_id[citation_id] = {
            "citationId": citation_id,
            "label": label,
            "coverageItems": normalized_coverage,
            "status": status,
            "method": method,
            "scope": scope,
            "summary": summary,
            "subjectId": subject_id,
            "url": url,
            "links": normalized_links,
        }
    presentation_ids = list(normalized_by_id)
    # Manifest 绑定全部授权 DatasetLineage，而专题正文可以只直接使用其中一部分。
    # 展示 ledger 因而允许是 Markdown marker 的超集，但 marker 仍必须逐个来自服务端
    # ledger，且 ledger 自身不能重复，防止模型注入未知 citation 或伪造展示标签。
    if not set(marker_ids).issubset(presentation_ids):
        raise ReportFailure("PDF 实际引用展示信息与 Markdown 引用不一致")
    ordered_ids = [*marker_ids, *(item for item in presentation_ids if item not in marker_ids)]
    normalized = []
    for index, citation_id in enumerate(ordered_ids, start=1):
        normalized.append(
            {
                **normalized_by_id[citation_id],
                "alias": f"[来源 {index:03d}]",
            }
        )
    aliases = {item["citationId"]: item["alias"] for item in normalized}
    return normalized


def _pdf_markdown(
    markdown: str,
    presentations: Any,
    *,
    include_sources: bool = True,
    trace_sources: Any = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """citation 与 B8 数据来源共用"首次出现顺序编号"管线，互不伪造脚注。"""
    trace = _normalize_trace_sources(trace_sources)
    chart_alias_by_src = _assign_trace_aliases(markdown, trace)
    marker_ids = tuple(dict.fromkeys(_CITATION_MARKER.findall(markdown)))
    normalized: list[dict[str, Any]] = []
    if marker_ids:
        normalized = _normalize_citation_presentations(presentations, marker_ids)
        aliases = {item["citationId"]: item["alias"] for item in normalized}

        # 只把服务端登记的 citation 转为可见编号；模型无法控制序号、摘要或链接。
        def visible_citation(match: re.Match[str]) -> str:
            return aliases[match.group(1)] if include_sources else ""

        base_markdown = _CITATION_MARKER.sub(visible_citation, markdown)
    else:
        base_markdown = markdown

    # 未登记的 claim/table 标记不显示编号（模型无法伪造附录条目）。
    def visible_claim(match: re.Match[str]) -> str:
        if not include_sources:
            return ""
        entry = trace["claims"].get(match.group(1))
        return entry["alias"] if entry is not None else ""

    def visible_table_close(match: re.Match[str]) -> str:
        if not include_sources:
            return ""
        entry = trace["tables"].get(match.group(1))
        return f"\n\n{entry['alias']}" if entry is not None else ""

    def visible_chart_caption(match: re.Match[str]) -> str:
        alias = chart_alias_by_src.get(match.group("src")) if include_sources else None
        if alias is None:
            return match.group(0)
        return (
            f"{match.group('image')}{match.group('sep')}"
            f"*图表：{match.group('caption')} {alias}*"
        )

    visible_markdown = _TABLE_CLOSE_MARKER.sub(
        visible_table_close,
        _TABLE_OPEN_MARKER.sub(
            "",
            _CHART_IMAGE_WITH_CAPTION.sub(
                visible_chart_caption,
                _CLAIM_MARKER.sub(
                    visible_claim,
                    _ANALYSIS_MARKER.sub("", _SECTION_MARKER.sub("", base_markdown)),
                ),
            ),
        ),
    )
    entries_by_alias = {
        entry["alias"]: entry
        for entry in (*trace["claims"].values(), *trace["tables"].values(), *trace["charts"])
    }
    entries = [entries_by_alias[alias] for alias in sorted(entries_by_alias)]
    return visible_markdown, normalized, {"entries": entries, "datasets": trace["datasets"]}


def _valid_source_url(value: Any, subject_id: str | None) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 2_000:
        return False
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.fragment:
        return False
    if parsed.username or parsed.password:
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    return bool(subject_id) and query == {"subject": [subject_id]}


def _page_layout(
    value: Any,
    *,
    include_header_footer: bool = True,
    include_page_numbers: bool = True,
) -> dict[str, str]:
    if value is None:
        value = DEFAULT_PAGE_LAYOUT
    if not isinstance(value, dict) or set(value) - PAGE_LAYOUT_FIELDS:
        raise ReportFailure("PDF 页面格式无效")
    layout = dict(DEFAULT_PAGE_LAYOUT)
    for key, item in value.items():
        if not isinstance(item, str) or len(item) > 200:
            raise ReportFailure("PDF 页面格式无效")
        if any(ord(character) < 32 and character != "\t" for character in item):
            raise ReportFailure("PDF 页面格式包含控制字符")
        try:
            parsed = tuple(Formatter().parse(item))
        except ValueError as error:
            raise ReportFailure("PDF 页面格式无效") from error
        if any(
            field_name not in PAGE_LAYOUT_PLACEHOLDERS or format_spec or conversion
            for _literal, field_name, format_spec, conversion in parsed
            if field_name is not None
        ):
            raise ReportFailure("PDF 页面格式包含不受支持的占位符")
        layout[key] = item
    if not include_header_footer:
        layout.update({"headerLeft": "", "headerRight": "", "footerLeft": "", "footerRight": ""})
    elif not include_page_numbers:
        layout["footerRight"] = ""
    footer = f"{layout['footerLeft']}\n{layout['footerRight']}"
    if include_page_numbers and ("{page}" not in footer or "{pages}" not in footer):
        raise ReportFailure("PDF 页脚必须包含当前页和总页数")
    return layout


def _formatted_page_text(
    template: str, *, title: str, organization: str, page: str | int, pages: str | int
) -> str:
    return template.format(title=title, organization=organization, page=page, pages=pages)


def _has_page_layout(
    text: str,
    layout: dict[str, str],
    *,
    title: str,
    organization: str,
    page: str | int,
    pages: str | int,
) -> bool:
    compact = "".join(text.split())
    expected = (
        _formatted_page_text(value, title=title, organization=organization, page=page, pages=pages)
        for value in layout.values()
        if value
    )
    return all("".join(value.split()) in compact for value in expected)


def _toc_page_numbers(
    pages: Sequence[Any], headings: Sequence[Mapping[str, Any]]
) -> dict[str, int]:
    """从 WeasyPrint 页面锚点计算正文从 1 开始的稳定目录页码。"""
    anchor_pages: dict[str, int] = {}
    expected_anchors = {str(item["anchor"]): str(item["anchor"]) for item in headings}
    for physical_page, page in enumerate(pages, start=1):
        anchors = getattr(page, "anchors", None)
        if not isinstance(anchors, Mapping):
            continue
        for anchor in anchors:
            heading_anchor = expected_anchors.get(anchor)
            if heading_anchor is None:
                continue
            if heading_anchor in anchor_pages:
                raise ReportFailure("PDF 正文标题锚点重复")
            anchor_pages[heading_anchor] = physical_page
    if set(anchor_pages) != set(expected_anchors):
        raise ReportFailure("PDF 正文标题锚点不完整")
    body_start_page = anchor_pages[str(headings[0]["anchor"])]
    page_numbers = {anchor: page - body_start_page + 1 for anchor, page in anchor_pages.items()}
    if any(number < 1 for number in page_numbers.values()):
        raise ReportFailure("PDF 正文章节页码顺序无效")
    return page_numbers


def _roman(value: int) -> str:
    if not 1 <= value <= 3_999:
        raise ReportFailure("罗马页码超出支持范围")
    result: list[str] = []
    remaining = value
    for number, numeral in (
        (1000, "m"),
        (900, "cm"),
        (500, "d"),
        (400, "cd"),
        (100, "c"),
        (90, "xc"),
        (50, "l"),
        (40, "xl"),
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    ):
        count, remaining = divmod(remaining, number)
        result.extend(numeral for _index in range(count))
    return "".join(result)


def _page_number_context(
    physical_page: int,
    *,
    body_start_page: int,
    physical_page_count: int,
    first_numbered_page: int = 2,
) -> tuple[str | int, str | int]:
    """返回当前分节内的页码和分节总页数，封面不进入编号体系。

    ``first_numbered_page`` 是首个参与编号的物理页：有封面时为 2，无封面导出时为 1。
    """
    if (
        first_numbered_page not in (1, 2)
        or not first_numbered_page <= physical_page <= physical_page_count
        or not first_numbered_page <= body_start_page <= physical_page_count
    ):
        raise ReportFailure("报表分节页码边界无效")
    if physical_page < body_start_page:
        return (
            _roman(physical_page - first_numbered_page + 1),
            _roman(body_start_page - first_numbered_page),
        )
    return physical_page - body_start_page + 1, physical_page_count - body_start_page + 1


def _pdf_section_pages(reader: Any, sections: list[dict[str, str]]) -> dict[str, int]:
    destinations = getattr(reader, "named_destinations", {})
    pages: dict[str, int] = {}
    for section in sections:
        name = f"report-section-{section['code']}"
        destination = destinations.get(name)
        if destination is None:
            raise ReportFailure("PDF 缺少稳定章节锚点")
        try:
            pages[section["code"]] = int(reader.get_destination_page_number(destination)) + 1
        except Exception as error:
            raise ReportFailure("PDF 章节锚点无法解析") from error
    if list(pages) != [item["code"] for item in sections] or list(pages.values()) != sorted(
        pages.values()
    ):
        raise ReportFailure("PDF 章节锚点顺序与已批准提纲不一致")
    return pages


def _pdf_heading_pages(reader: Any, headings: list[dict[str, Any]]) -> dict[str, int]:
    destinations = getattr(reader, "named_destinations", {})
    pages: dict[str, int] = {}
    for item in headings:
        destination = destinations.get(item["anchor"])
        if destination is None:
            raise ReportFailure("PDF 缺少稳定标题锚点")
        try:
            pages[item["anchor"]] = int(reader.get_destination_page_number(destination)) + 1
        except Exception as error:
            raise ReportFailure("PDF 标题锚点无法解析") from error
    if list(pages.values()) != sorted(pages.values()):
        raise ReportFailure("PDF 标题锚点顺序与编号映射不一致")
    return pages


def _pdf_link_count(reader: Any, *, start_page: int, end_page: int) -> int:
    count = 0
    for page in reader.pages[start_page - 1 : end_page]:
        annotations = page.get("/Annots") or ()
        for reference in annotations:
            try:
                annotation = reference.get_object()
            except Exception:
                continue
            if annotation.get("/Subtype") == "/Link":
                count += 1
    return count


def _apply_pdf_page_decorations(
    path: Path,
    *,
    context: dict[str, Any],
    layout: dict[str, str],
    include_cover: bool = True,
) -> None:
    try:
        import pypdf
        from weasyprint import HTML
    except ImportError as error:
        raise ReportFailure("PDF 页面装饰运行时依赖不可用") from error
    overlay = path.with_name("render.decorations.pdf")
    decorated = path.with_name("render.decorated.pdf")
    try:
        reader = pypdf.PdfReader(str(path))
        if not reader.pages:
            raise ReportFailure("PDF 页面装饰处理缺少页面")
        section_pages = _pdf_section_pages(reader, context["sections"])
        body_start_page = min(section_pages.values())
        page_count = len(reader.pages)
        first_numbered_page = 2 if include_cover else 1
        decoration_pages: list[str] = []
        for page_number in range(first_numbered_page, page_count + 1):
            page_value, pages_value = _page_number_context(
                page_number,
                body_start_page=body_start_page,
                physical_page_count=page_count,
                first_numbered_page=first_numbered_page,
            )
            values = {
                key: html.escape(
                    _formatted_page_text(
                        template,
                        title=context["title"],
                        organization=context["organizationName"],
                        page=page_value,
                        pages=pages_value,
                    )
                )
                for key, template in layout.items()
            }
            decoration_pages.append(
                '<section class="decoration-page"><header><span class="left">'
                f'{values["headerLeft"]}</span><span class="right">{values["headerRight"]}</span></header>'
                f'<div class="watermark">{html.escape(context["watermarkText"])}</div>'
                '<footer><span class="left">'
                f'{values["footerLeft"]}</span><span class="right">{values["footerRight"]}</span></footer></section>'
            )
        document = (
            "<meta charset='utf-8'><style>"
            "@page{size:A4;margin:0}html,body{margin:0}body{"
            "font-family:'Noto Sans CJK SC','Noto Sans CJK JP',sans-serif;color:"
            f"{REPORT_VISUAL_THEME['muted']}"
            "}"
            ".decoration-page{position:relative;box-sizing:border-box;width:210mm;height:297mm;"
            "break-after:page;overflow:hidden}.decoration-page:last-child{break-after:auto}"
            "header,footer{position:absolute;left:18mm;right:18mm;display:grid;"
            "grid-template-columns:minmax(0,1fr) minmax(0,1fr);column-gap:8mm;"
            "font-size:8pt;line-height:1.2}header{top:7mm}footer{bottom:8mm;"
            "border-top:.5pt solid "
            f"{REPORT_VISUAL_THEME['grid']}"
            ";padding-top:2mm}"
            ".left{text-align:left;white-space:pre-wrap;overflow-wrap:anywhere}"
            ".right{text-align:right;white-space:pre-wrap;overflow-wrap:anywhere}"
            ".watermark{position:absolute;left:25mm;right:25mm;top:122mm;text-align:center;"
            "transform:rotate(-32deg);font-size:26pt;line-height:1.15;font-weight:600;"
            "color:rgba(71,84,103,.045);overflow-wrap:anywhere}"
            f"</style><body>{''.join(decoration_pages)}</body>"
        )
        HTML(string=document).write_pdf(str(overlay), pdf_variant="pdf/ua-1")
        overlay_pages = pypdf.PdfReader(str(overlay)).pages
        if len(overlay_pages) != page_count - first_numbered_page + 1:
            raise ReportFailure("PDF 页面装饰页数不一致")
        writer = pypdf.PdfWriter(clone_from=str(path))
        # pypdf 默认将合并产物写成 1.3，即使源文档是 PDF/UA-1（1.7）；保留
        # PDF/UA 所需的版本声明，避免页面装饰步骤让结构化标签变成不一致的协议。
        writer.pdf_header = "%PDF-1.7"
        # WeasyPrint 的命名页沿用绝对页计数。服务端按章节锚点一次生成全部装饰页，
        # 目录使用罗马数字，正文从 1 重启；封面明确不合并任何页面元素。
        for page, overlay_page in zip(
            writer.pages[first_numbered_page - 1 :], overlay_pages, strict=True
        ):
            page.merge_page(overlay_page, over=True)
        with decorated.open("wb") as stream:
            writer.write(stream)
        os.replace(decorated, path)
    except ReportFailure:
        raise
    except Exception as error:
        raise ReportFailure("PDF 页面装饰处理失败") from error
    finally:
        overlay.unlink(missing_ok=True)
        decorated.unlink(missing_ok=True)


__all__ = [
    "DEFAULT_PAGE_LAYOUT",
    "MAX_PDF_BYTES",
    "MAX_PDF_PAGES",
    "PAGE_LAYOUT_FIELDS",
    "PAGE_LAYOUT_PLACEHOLDERS",
    "REPORT_VISUAL_THEME",
    "_apply_pdf_page_decorations",
    "_assign_trace_aliases",
    "_formatted_page_text",
    "_has_page_layout",
    "_normalize_trace_sources",
    "_page_layout",
    "_page_number_context",
    "_pdf_heading_pages",
    "_pdf_link_count",
    "_pdf_markdown",
    "_pdf_section_pages",
    "_toc_page_numbers",
]
