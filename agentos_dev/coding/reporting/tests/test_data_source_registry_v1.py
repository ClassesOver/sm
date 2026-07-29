from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentos_dev.coding.reporting.data_source import (
    CONFIG_FILE_NAME,
    discover_config_paths,
    load_report_source_registry,
)


def write_config(directory: Path, payload: dict[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CONFIG_FILE_NAME
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def starrocks_source(
    source_id: str,
    *,
    dsn_env: str,
    database: str = "reporting",
    tables: list[str] | None = None,
    profiling_limits: dict[str, int] | None = None,
) -> dict[str, object]:
    configured_tables = tables or [f"{database}.income"]
    source: dict[str, object] = {
        "id": source_id,
        "type": "starrocks",
        "name": f"{source_id} 数据源",
        "dsnEnv": dsn_env,
        "database": database,
        "tables": configured_tables,
        "periodColumns": {table: "month" for table in configured_tables},
    }
    source.update(profiling_limits or {})
    return source


def test_配置从边界向当前目录递归加载且子层整项覆盖(tmp_path: Path):
    boundary = tmp_path / "workspace"
    current = boundary / "department" / "report"
    parent = write_config(
        boundary,
        {
            "version": "1",
            "defaultSourceIds": ["operations"],
            "sources": [
                starrocks_source("operations", dsn_env="REMOVED_PARENT_DSN"),
                starrocks_source("shared", dsn_env="SHARED_DSN"),
            ],
        },
    )
    child = write_config(
        current,
        {
            "version": "1",
            "sources": [starrocks_source("operations", dsn_env="CHILD_DSN", database="child")],
        },
    )

    registry = load_report_source_registry(
        current,
        boundary,
        environ={
            "CHILD_DSN": "starrocks://reader:secret@db.internal:9030/child",
            "SHARED_DSN": "starrocks://reader:secret@db.internal:9030/reporting",
        },
    )

    assert registry.config_paths == (parent, child)
    assert registry.default_source_ids == ("operations",)
    assert set(registry.sources) == {"operations", "shared"}
    assert registry.sources["operations"].database == "child"
    assert registry.sources["operations"].tables == ("child.income",)


def test_子层可以禁用继承源并显式清空默认源(tmp_path: Path):
    boundary = tmp_path / "workspace"
    current = boundary / "report"
    write_config(
        boundary,
        {
            "version": "1",
            "defaultSourceIds": ["legacy"],
            "sources": [starrocks_source("legacy", dsn_env="LEGACY_DSN")],
        },
    )
    write_config(
        current,
        {
            "version": "1",
            "defaultSourceIds": [],
            "sources": [{"id": "legacy", "disabled": True}],
        },
    )

    registry = load_report_source_registry(current, boundary, environ={})

    assert registry.default_source_ids == ()
    assert registry.sources == {}


def test_子层禁用默认源但未覆盖默认列表时失败(tmp_path: Path):
    boundary = tmp_path / "workspace"
    current = boundary / "report"
    write_config(
        boundary,
        {
            "version": "1",
            "defaultSourceIds": ["legacy"],
            "sources": [starrocks_source("legacy", dsn_env="LEGACY_DSN")],
        },
    )
    write_config(
        current,
        {"version": "1", "sources": [{"id": "legacy", "disabled": True}]},
    )

    with pytest.raises(ValueError, match="defaultSourceIds"):
        load_report_source_registry(current, boundary, environ={})


def test_公开配置不包含dsn或凭据(tmp_path: Path):
    boundary = tmp_path / "workspace"
    write_config(
        boundary,
        {
            "version": "1",
            "sources": [
                starrocks_source(
                    "operations",
                    dsn_env="REPORT_DSN",
                    profiling_limits={
                        "exactDistinctMaxRows": 500_000,
                        "statisticsColumnBatchSize": 12,
                        "topValuesMaxColumns": 8,
                        "topValuesLimit": 6,
                        "profileConcurrency": 3,
                        "queryConcurrency": 2,
                    },
                )
            ],
        },
    )
    registry = load_report_source_registry(
        boundary,
        boundary,
        environ={"REPORT_DSN": "starrocks://reader:private@db.internal:9030/reporting"},
    )

    source = registry.sources["operations"]
    public = source.public_dict()

    assert "dsn" not in repr(public).lower()
    assert "private" not in repr(public)
    assert "db.internal" not in repr(public)
    assert "private" not in repr(registry.sources["operations"])
    assert source.reporting_profile is None
    assert public["limits"] == {
        "statementTimeoutSeconds": 30,
        "maxRows": 1_000_000,
        "maxBytes": 256 * 1024 * 1024,
        "exactDistinctMaxRows": 500_000,
        "statisticsColumnBatchSize": 12,
        "topValuesMaxColumns": 8,
        "topValuesLimit": 6,
        "profileConcurrency": 3,
        "queryConcurrency": 2,
    }


def test_数据源只保存profile引用(tmp_path: Path):
    raw = starrocks_source("operations", dsn_env="REPORT_DSN")
    raw["reportingProfile"] = "hospital-operations"
    write_config(tmp_path, {"version": "1", "sources": [raw]})

    registry = load_report_source_registry(
        tmp_path,
        tmp_path,
        environ={"REPORT_DSN": "starrocks://reader:private@db.internal:9030/reporting"},
    )

    assert registry.sources["operations"].reporting_profile == "hospital-operations"


def test_查找拒绝越界和配置符号链接(tmp_path: Path):
    boundary = tmp_path / "workspace"
    boundary.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="超出边界"):
        discover_config_paths(outside, boundary)

    target = tmp_path / "source.json"
    target.write_text('{"version":"1","sources":[]}', encoding="utf-8")
    (boundary / CONFIG_FILE_NAME).symlink_to(target)
    with pytest.raises(ValueError, match="普通文件"):
        discover_config_paths(boundary, boundary)


@pytest.mark.parametrize(
    "payload",
    [
        {"version": "2", "sources": []},
        {"version": "1", "unknown": True, "sources": []},
        {
            "version": "1",
            "sources": [{"id": "source", "disabled": True, "type": "starrocks"}],
        },
        {
            "version": "1",
            "sources": [
                starrocks_source("source", dsn_env="ONE"),
                starrocks_source("source", dsn_env="TWO"),
            ],
        },
    ],
)
def test_配置契约拒绝未知字段版本和层内重复(tmp_path: Path, payload: dict[str, object]):
    boundary = tmp_path / "workspace"
    write_config(boundary, payload)

    with pytest.raises(ValueError):
        load_report_source_registry(boundary, boundary, environ={})
