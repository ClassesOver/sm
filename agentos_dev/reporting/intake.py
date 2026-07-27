from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from pydantic import SecretStr

from .models import ReportingError, TemporarySourceRequest

_KEY_ALIASES = {
    "类型": "source_type",
    "type": "source_type",
    "host": "host",
    "ip": "host",
    "port": "port",
    "user": "username",
    "username": "username",
    "pwd": "password",
    "password": "password",
    "db": "database",
    "database": "database",
}
_LINE = re.compile(r"^\s*([A-Za-z]+|类型)\s*[:：=]\s*(.*?)\s*$")
_DDL = re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)", re.IGNORECASE)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_PASSWORD_KEYS = frozenset({"pwd", "password"})


@dataclass(frozen=True)
class ParsedReportIntake:
    sanitized_text: str
    source_request: TemporarySourceRequest | None
    ddl_tables: tuple[str, ...]
    metadata_fingerprint: str


class ReportIntakeService:
    def parse(self, text: str) -> ParsedReportIntake:
        if not isinstance(text, str) or not text.strip():
            raise ReportingError("report_intake_empty", "报表请求不能为空。")
        blocks = self._connection_blocks(text)
        if len(blocks) > 1:
            raise ReportingError(
                "source_connection_ambiguous", "检测到多个连接块，请每次只提交一个数据源。"
            )
        source_request = None
        sanitized = text
        if blocks:
            start, end, values = blocks[0]
            source_request = self._source_request(values)
            replacement = self._sanitized_connection(values)
            sanitized = f"{text[:start]}{replacement}{text[end:]}"
        tables = self._ddl_tables(text)
        fingerprint_input = "\n".join(tables).encode("utf-8")
        fingerprint = hashlib.sha256(fingerprint_input).hexdigest()
        return ParsedReportIntake(sanitized, source_request, tables, fingerprint)

    def _connection_blocks(self, text: str) -> list[tuple[int, int, dict[str, str]]]:
        lines = text.splitlines(keepends=True)
        blocks: list[tuple[int, int, dict[str, str]]] = []
        current: dict[str, str] = {}
        start = 0
        offset = 0
        for line in [*lines, ""]:
            match = _LINE.match(line.rstrip("\r\n"))
            raw_key = match.group(1).lower() if match else ""
            key = _KEY_ALIASES.get(raw_key)
            if key and match is not None:
                if not current:
                    start = offset
                if key in current:
                    raise ReportingError(
                        "source_connection_ambiguous", f"连接块字段 {raw_key} 重复。"
                    )
                current[key] = match.group(2).strip()
            elif current:
                if "password" in current or "source_type" in current:
                    blocks.append((start, offset, current))
                current = {}
            offset += len(line)
        return blocks

    def _source_request(self, values: dict[str, str]) -> TemporarySourceRequest:
        required = {"source_type", "host", "username", "password", "database"}
        if missing := sorted(required - set(values)):
            raise ReportingError(
                "source_connection_incomplete", f"连接块缺少字段: {', '.join(missing)}。"
            )
        source_type = values["source_type"].strip().lower()
        if source_type not in {"starrocks", "star rocks"}:
            raise ReportingError("source_type_unsupported", "临时连接仅支持 StarRocks。")
        try:
            port = int(values.get("port") or "9030")
            return TemporarySourceRequest(
                host=values["host"],
                port=port,
                username=values["username"],
                password=SecretStr(values["password"]),
                database=values["database"],
            )
        except (TypeError, ValueError) as error:
            raise ReportingError("source_connection_invalid", "连接块字段无效。") from error

    def _sanitized_connection(self, values: dict[str, str]) -> str:
        ordered = (
            ("类型", "StarRocks"),
            ("host", values.get("host", "")),
            ("port", values.get("port", "9030")),
            ("user", values.get("username", "")),
            ("password", "[REDACTED]"),
            ("database", values.get("database", "")),
        )
        return "\n".join(f"{key}: {value}" for key, value in ordered) + "\n"

    def _ddl_tables(self, text: str) -> tuple[str, ...]:
        result: list[str] = []
        for raw in _DDL.findall(text):
            parts = [part.strip('`"') for part in raw.split(".")]
            if not 1 <= len(parts) <= 2 or any(not _IDENTIFIER.fullmatch(part) for part in parts):
                raise ReportingError("ddl_table_invalid", "DDL 中的数据表名称无效。")
            normalized = ".".join(part.lower() for part in parts)
            if normalized not in result:
                result.append(normalized)
        return tuple(result)
