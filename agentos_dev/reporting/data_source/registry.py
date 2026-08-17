from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from ..models import ReportingError
from .models import CONFIG_FILE_NAME, DataSourceConfig, ReportSourceRegistryConfig
from .starrocks import parse_starrocks_source

MAX_CONFIG_BYTES = 1024 * 1024
MAX_CONFIG_DEPTH = 64
MAX_SOURCES = 200
SourceParser = Callable[[Mapping[str, Any], Mapping[str, str]], DataSourceConfig]


def discover_config_paths(
    start_dir: str | Path,
    boundary_dir: str | Path,
    *,
    file_name: str = CONFIG_FILE_NAME,
) -> tuple[Path, ...]:
    if Path(file_name).name != file_name or file_name in {"", ".", ".."}:
        raise ValueError("数据源配置文件名无效。")
    start = Path(start_dir).resolve(strict=True)
    boundary = Path(boundary_dir).resolve(strict=True)
    if not start.is_dir() or not boundary.is_dir():
        raise ValueError("数据源配置查找起点和边界必须是目录。")
    try:
        relative = start.relative_to(boundary)
    except ValueError as error:
        raise ValueError("数据源配置查找起点超出边界。") from error
    if len(relative.parts) > MAX_CONFIG_DEPTH:
        raise ValueError("数据源配置目录层级过深。")
    directories = [boundary]
    current = boundary
    for part in relative.parts:
        current /= part
        directories.append(current)
    paths: list[Path] = []
    for directory in directories:
        candidate = directory / file_name
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"数据源配置必须是普通文件: {candidate}")
        if metadata.st_size > MAX_CONFIG_BYTES:
            raise ValueError(f"数据源配置超过 1 MiB: {candidate}")
        paths.append(candidate)
    return tuple(paths)


def load_report_source_registry(
    start_dir: str | Path,
    boundary_dir: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    file_name: str = CONFIG_FILE_NAME,
    source_parsers: Mapping[str, SourceParser] | None = None,
) -> ReportSourceRegistryConfig:
    paths = discover_config_paths(start_dir, boundary_dir, file_name=file_name)
    raw_sources: dict[str, Mapping[str, Any]] = {}
    defaults: tuple[str, ...] = ()
    defaults_defined = False
    for path in paths:
        document = _load_document(path)
        if "defaultSourceIds" in document:
            defaults = _source_ids(document["defaultSourceIds"], "defaultSourceIds")
            defaults_defined = True
        layer_ids: set[str] = set()
        for raw in document.get("sources", []):
            source_id = _override_id(raw)
            if source_id in layer_ids:
                raise ValueError(f"同一配置层的数据源 id 重复: {source_id}")
            layer_ids.add(source_id)
            if raw.get("disabled") is True:
                if set(raw) != {"id", "disabled"}:
                    raise ValueError("disabled 数据源只能包含 id 和 disabled。")
                raw_sources.pop(source_id, None)
            else:
                if "disabled" in raw:
                    raise ValueError("启用的数据源不得包含 disabled。")
                raw_sources[source_id] = raw
    if len(raw_sources) > MAX_SOURCES:
        raise ValueError(f"生效的数据源不能超过 {MAX_SOURCES} 个。")
    parsers: Mapping[str, SourceParser] = (
        source_parsers
        if source_parsers is not None
        else {"starrocks": cast(SourceParser, parse_starrocks_source)}
    )
    values = os.environ if environ is None else environ
    sources: dict[str, DataSourceConfig] = {}
    for source_id, raw in raw_sources.items():
        source_type = raw.get("type")
        parser = parsers.get(source_type) if isinstance(source_type, str) else None
        if parser is None:
            raise ValueError(f"报表数据源 {source_id} 的 type 不受支持。")
        parsed = parser(raw, values)
        if parsed.id != source_id:
            raise ValueError("数据源解析器返回了不同的 id。")
        sources[source_id] = parsed
    if not defaults_defined:
        defaults = ()
    if any(source_id not in sources for source_id in defaults):
        raise ValueError("defaultSourceIds 包含未注册或已禁用的数据源。")
    return ReportSourceRegistryConfig(
        default_source_ids=defaults,
        sources=sources,
        config_paths=paths,
    )


def load_configured_report_source_registry(
    configured_dir: str | Path | None,
    *,
    current_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ReportSourceRegistryConfig:
    """从部署边界到当前目录递归加载数据源配置。"""
    if configured_dir is None:
        boundary = Path.cwd().resolve()
        start = Path(current_dir or boundary).resolve()
        return load_report_source_registry(start, boundary, environ=environ)
    configured = Path(configured_dir).resolve(strict=True)
    if not configured.is_dir():
        raise ValueError("报表数据源配置路径必须是目录。")
    candidate = Path(current_dir or configured).resolve(strict=True)
    try:
        candidate.relative_to(configured)
    except ValueError:
        candidate = configured
    return load_report_source_registry(candidate, configured, environ=environ)


def require_sources(
    sources: Mapping[str, DataSourceConfig], source_ids: tuple[str, ...]
) -> tuple[DataSourceConfig, ...]:
    missing = [source_id for source_id in source_ids if source_id not in sources]
    if missing:
        raise ReportingError("report_source_not_found", "请求的数据源未在服务端注册。")
    return tuple(sources[source_id] for source_id in source_ids)


def _load_document(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"数据源配置无法读取: {path}") from error
    if not isinstance(payload, dict) or set(payload) - {
        "version",
        "defaultSourceIds",
        "sources",
    }:
        raise ValueError(f"数据源配置包含未知顶层字段: {path}")
    if payload.get("version") != "1":
        raise ValueError(f"数据源配置 version 必须为 1: {path}")
    sources = payload.get("sources", [])
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValueError(f"数据源配置 sources 必须是数组且不超过 {MAX_SOURCES} 项: {path}")
    if "defaultSourceIds" in payload:
        _source_ids(payload["defaultSourceIds"], "defaultSourceIds")
    return payload


def _override_id(raw: Any) -> str:
    if not isinstance(raw, dict):
        raise ValueError("数据源配置项必须是对象。")
    source_id = raw.get("id")
    values = _source_ids([source_id], "source id")
    return values[0]


def _source_ids(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError(f"{label} 必须是最多 20 项的数组。")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", item):
            raise ValueError(f"{label} 包含无效值。")
        result.append(item)
    if len(set(result)) != len(result):
        raise ValueError(f"{label} 不能重复。")
    return tuple(result)
