import csv
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path, PurePosixPath
from typing import Any

MAX_PART_BYTES = 200 * 1024 * 1024
MAX_PARTS = 20
WORKSPACE_ROOT = Path("/home/daytona/workspace")


class MaterializeFailure(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _path(value: str, *, must_exist: bool = False) -> Path:
    candidate = PurePosixPath(str(value or "").replace("\\", "/"))
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise MaterializeFailure("workspace_path_invalid", "工作区路径无效。")
    path = WORKSPACE_ROOT.joinpath(*candidate.parts)
    current = WORKSPACE_ROOT
    for part in candidate.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise MaterializeFailure("workspace_path_invalid", "工作区路径包含符号链接。")
    if must_exist and (not path.is_file() or path.is_symlink()):
        raise MaterializeFailure("dataset_file_required", "数据源不是普通文件。")
    return path


def _safe_columns(description: Any) -> list[str]:
    values = []
    used: dict[str, int] = {}
    for index, item in enumerate(description or []):
        raw = str(item[0] if isinstance(item, (tuple, list)) else getattr(item, "name", ""))
        name = raw or f"column_{index + 1}"
        count = used.get(name, 0) + 1
        used[name] = count
        values.append(name if count == 1 else f"{name}_{count}")
    return values


def _open_database(path: Path, file_format: str):
    if file_format == "duckdb":
        try:
            import duckdb
        except ImportError as error:
            raise MaterializeFailure(
                "database_driver_unavailable", "当前工具 Snapshot 缺少 DuckDB。"
            ) from error
        return duckdb.connect(str(path), read_only=True)
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _write_rows(
    output_dir: Path,
    columns: list[str],
    rows: list[Any],
    output_format: str,
    start_part: int,
) -> list[Path]:
    pending = [rows]
    outputs: list[Path] = []
    while pending:
        current = pending.pop(0)
        part = start_part + len(outputs)
        if part > MAX_PARTS:
            raise MaterializeFailure("dataset_too_large", "查询结果分片数量超过限制。")
        suffix = ".parquet" if output_format == "parquet" else ".csv"
        output = output_dir / f"part-{part:04d}{suffix}"
        if output_format == "parquet":
            try:
                import pyarrow as pa
                import pyarrow.parquet as pq
            except ImportError as error:
                raise MaterializeFailure(
                    "database_driver_unavailable", "当前工具 Snapshot 缺少 PyArrow。"
                ) from error
            table = pa.Table.from_pylist([dict(zip(columns, row, strict=True)) for row in current])
            if not current:
                table = pa.table({column: pa.array([], type=pa.string()) for column in columns})
            pq.write_table(table, output, compression="zstd")
        else:
            with output.open("w", encoding="utf-8", newline="") as output_file:
                writer = csv.writer(output_file)
                writer.writerow(columns)
                writer.writerows(current)
        if output.stat().st_size <= MAX_PART_BYTES:
            outputs.append(output)
            continue
        output.unlink()
        if len(current) <= 1:
            raise MaterializeFailure("dataset_too_large", "查询结果包含超过单文件限制的记录。")
        middle = len(current) // 2
        pending[0:0] = [current[:middle], current[middle:]]
    return outputs


def _write_arrow_table(output_dir: Path, table: Any, start_part: int) -> list[Path]:
    import pyarrow.parquet as pq

    pending = [table]
    outputs: list[Path] = []
    while pending:
        current = pending.pop(0)
        part = start_part + len(outputs)
        if part > MAX_PARTS:
            raise MaterializeFailure("dataset_too_large", "查询结果分片数量超过限制。")
        output = output_dir / f"part-{part:04d}.parquet"
        pq.write_table(current, output, compression="zstd")
        if output.stat().st_size <= MAX_PART_BYTES:
            outputs.append(output)
            continue
        output.unlink()
        if current.num_rows <= 1:
            raise MaterializeFailure("dataset_too_large", "查询结果包含超过单文件限制的记录。")
        middle = current.num_rows // 2
        pending[0:0] = [current.slice(0, middle), current.slice(middle)]
    return outputs


def materialize_local(payload: dict[str, Any]) -> dict[str, Any]:
    source = _path(str(payload.get("source_path") or ""), must_exist=True)
    output_dir = _path(str(payload.get("output_dir") or ""))
    file_format = str(payload.get("file_format") or "")
    output_format = str(payload.get("output_format") or "parquet")
    query = str(payload.get("query") or "")
    max_rows = int(payload.get("max_rows") or 1_000_000)
    max_bytes = int(payload.get("max_bytes") or 256 * 1024 * 1024)
    if file_format not in {"sqlite", "sqlite3", "db", "duckdb"}:
        raise MaterializeFailure("database_format_unsupported", "不支持该工作区数据库格式。")
    if output_format not in {"csv", "parquet"}:
        raise MaterializeFailure("invalid_output_format", "输出格式无效。")
    if output_dir.exists():
        raise MaterializeFailure("dataset_path_conflict", "数据集输出目录已经存在。")
    output_dir.mkdir(parents=True, mode=0o700)
    result_paths: list[str] = []
    total_rows = 0
    total_bytes = 0
    connection = _open_database(source, file_format)
    try:
        cursor = connection.execute(query)
        columns = _safe_columns(cursor.description)
        part = 0
        while True:
            rows = cursor.fetchmany(50_000)
            if not rows and result_paths:
                break
            total_rows += len(rows)
            if total_rows > max_rows:
                raise MaterializeFailure("dataset_too_large", "查询结果超过允许的行数。")
            outputs = _write_rows(output_dir, columns, list(rows), output_format, part + 1)
            part += len(outputs)
            for output in outputs:
                total_bytes += output.stat().st_size
                if total_bytes > max_bytes:
                    raise MaterializeFailure("dataset_too_large", "查询结果超过允许的数据量。")
                result_paths.append(output.relative_to(WORKSPACE_ROOT).as_posix())
            if not rows:
                break
    finally:
        connection.close()
    return {
        "ok": True,
        "paths": result_paths,
        "rowCount": total_rows,
        "size": total_bytes,
        "schema": {"columns": columns},
    }


def convert_csv(payload: dict[str, Any]) -> dict[str, Any]:
    paths = payload.get("paths")
    output_dir = _path(str(payload.get("output_dir") or ""))
    max_bytes = int(payload.get("max_bytes") or 256 * 1024 * 1024)
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_PARTS:
        raise MaterializeFailure("dataset_invalid", "CSV 分片列表无效。")
    if output_dir.exists():
        raise MaterializeFailure("dataset_path_conflict", "数据集输出目录已经存在。")
    output_dir.mkdir(parents=True, mode=0o700)
    try:
        import pyarrow.csv as pa_csv
    except ImportError as error:
        raise MaterializeFailure(
            "database_driver_unavailable", "当前工具 Snapshot 缺少 PyArrow。"
        ) from error
    outputs: list[str] = []
    total_bytes = 0
    total_rows = 0
    columns: list[str] = []
    for value in paths:
        source = _path(str(value), must_exist=True)
        table = pa_csv.read_csv(source)
        if columns and columns != table.column_names:
            raise MaterializeFailure("dataset_invalid", "CSV 分片列结构不一致。")
        columns = table.column_names
        total_rows += table.num_rows
        written = _write_arrow_table(output_dir, table, len(outputs) + 1)
        for output in written:
            total_bytes += output.stat().st_size
            if total_bytes > max_bytes:
                raise MaterializeFailure("dataset_too_large", "查询结果超过允许的数据量。")
            outputs.append(output.relative_to(WORKSPACE_ROOT).as_posix())
    return {
        "ok": True,
        "paths": outputs,
        "rowCount": total_rows,
        "size": total_bytes,
        "schema": {"columns": columns},
    }


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    action = ""
    payload: dict[str, Any] = {}
    try:
        action, raw_payload = values
        payload = json.loads(raw_payload)
        if action == "materialize_local":
            result = materialize_local(payload)
        elif action == "convert_csv":
            result = convert_csv(payload)
        else:
            raise MaterializeFailure("action_invalid", "数据源运行时操作无效。")
    except MaterializeFailure as error:
        _cleanup_failed_output(action, payload)
        print(
            json.dumps({"ok": False, "code": error.code, "error": str(error)}, ensure_ascii=False)
        )
        return 1
    except Exception as error:
        _cleanup_failed_output(action, payload)
        fingerprint = hashlib.sha256(type(error).__name__.encode("utf-8")).hexdigest()[:12]
        print(
            json.dumps(
                {"ok": False, "code": "materialization_failed", "errorId": fingerprint},
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cleanup_failed_output(action: str, payload: dict[str, Any]) -> None:
    if action not in {"materialize_local", "convert_csv"}:
        return
    try:
        output = _path(str(payload.get("output_dir") or ""))
    except MaterializeFailure:
        return
    if output.exists():
        shutil.rmtree(output)


if __name__ == "__main__":
    raise SystemExit(main())
