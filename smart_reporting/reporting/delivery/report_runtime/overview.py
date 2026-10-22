"""Presentation-only overview binding. Business approval remains server-side."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .markdown import _SECTION_START, SUMMARY_END_SENTINEL, SUMMARY_SENTINEL
from .validation import _input_path

MAX_OVERVIEW_PAYLOAD = 512 * 1024
_GAP = "尚未形成可核验的经营总览，本页暂不列示汇总数值。请结合正文的口径说明与待确认事项阅读。"


def load_overview(state: dict, workspace: Path):
    if "_managementOverviewProjection" in state:
        payload = state["_managementOverviewProjection"]
        return payload if isinstance(payload, dict) else {"invalid": "overview_payload_unavailable"}
    if "_managementOverviewProjectionFile" not in state:
        return None
    identity = state["_managementOverviewProjectionFile"]
    try:
        path = _input_path(workspace, identity["path"], ".json")
        if path.stat().st_size > MAX_OVERVIEW_PAYLOAD:
            raise ValueError("overview payload exceeds budget")
        raw = path.read_bytes()
        if len(raw) != identity["size"] or hashlib.sha256(raw).hexdigest() != identity["sha256"]:
            raise ValueError("overview payload changed")
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {"invalid": "overview_payload_unavailable"}
    except Exception:
        return {"invalid": "overview_payload_unavailable"}


def insert_management_overview(markdown: str, payload, source_sha256: str, presentations):
    reason = "overview_payload_invalid"
    body = _GAP
    status = "unknown"
    try:
        if not isinstance(payload, dict) or set(payload) != {
            "version", "sourceSha256", "qualityInputSha256", "status", "markdown",
        }:
            raise ValueError("overview envelope invalid")
        if payload["version"] != "management-overview-render/1":
            raise ValueError("overview rule unavailable")
        if payload["sourceSha256"] != source_sha256:
            reason = "overview_source_changed"
            raise ValueError("overview source changed")
        candidate = payload["markdown"]
        if (not isinstance(candidate, str) or len(candidate.encode("utf-8")) > MAX_OVERVIEW_PAYLOAD
                or payload["status"] not in {"evaluated", "unavailable"}
                or not isinstance(payload["qualityInputSha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", payload["qualityInputSha256"])):
            raise ValueError("overview content invalid")
        allowed = {item.get("citationId") for item in presentations or () if isinstance(item, dict)}
        citations = re.findall(r"\[\[citation:([^\]\r\n]+)\]\]", candidate)
        plain = re.sub(r"\[\[citation:[^\]\r\n]+\]\]", "", candidate)
        if "[[" in plain or SUMMARY_SENTINEL in candidate or not set(citations) <= allowed:
            raise ValueError("overview source marker invalid")
        body = candidate
        status = "verified"
        reason = "source_bound_overview"
        if payload["status"] == "unavailable":
            # Unavailable views may only show the fixed, number-free limitation.
            body, reason = _GAP, "overview_evidence_unavailable"
    except Exception:
        pass
    starts = list(_SECTION_START.finditer(markdown))
    position = starts[0].start() if starts else len(markdown)
    block = "\n\n".join((SUMMARY_SENTINEL, body.strip(), SUMMARY_END_SENTINEL))
    projected = f"{markdown[:position].rstrip()}\n\n{block}\n\n{markdown[position:]}"
    return projected, {"status": status, "scope": "management_overview_projection", "reason": reason}
