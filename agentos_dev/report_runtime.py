"""固定报表运行时；由 WorkspaceReportToolkit 以哈希校验后的源码运行。"""

from __future__ import annotations

import csv
import hashlib
import html as html_module
import json
import re
import shutil
import sys
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

import matplotlib

matplotlib.use("Agg")
from typing import Annotated, Literal

import matplotlib.pyplot as plt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

MAX_ROWS = 100_000
MAX_COLUMNS = 100
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_MEMORY = 128 * 1024 * 1024
MAX_RESULT_BYTES = 32 * 1024
MAX_APPENDIX_ROWS = 1_000
MAX_APPENDIX_COLUMNS = 20
SUPPORTED = {".csv", ".xls", ".xlsx", ".json", ".jsonl"}
TEMPLATES = {"经营", "财务", "项目"}
FAILURE_TTL_SECONDS = 24 * 60 * 60


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SummaryOperation(_Operation):
    type: Literal["summary"]


class ColumnOperation(_Operation):
    type: Literal["trend", "top_bottom", "share", "pivot", "iqr"]
    column: str
    limit: int = Field(default=10, ge=1, le=1000)


AnalysisOperation = Annotated[SummaryOperation | ColumnOperation, Field(discriminator="type")]
ANALYSIS_OPERATIONS = TypeAdapter(list[AnalysisOperation])


class ReportFailure(ValueError):
    pass


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode())


def _columns(frame: pd.DataFrame) -> list[str]:
    result: list[str] = []
    counts: dict[str, int] = {}
    for raw in frame.columns:
        name = str(raw).strip() or "未命名"
        counts[name] = counts.get(name, 0) + 1
        result.append(name if counts[name] == 1 else f"{name} ({counts[name]})")
    return result


def _check(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = _columns(frame)
    if len(frame) > MAX_ROWS or len(frame.columns) > MAX_COLUMNS:
        raise ReportFailure("数据集超过行列边界")
    if int(frame.memory_usage(index=True, deep=True).sum()) > MAX_MEMORY:
        raise ReportFailure("数据集展开内存超过 128 MiB")
    return frame


def _safe_path(workspace: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReportFailure("路径必须是当前工作区的相对路径")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or any(part in ("", ".") for part in path.parts):
        raise ReportFailure("路径必须是当前工作区的相对路径")
    result = workspace.joinpath(*path.parts)
    try:
        result.relative_to(workspace)
    except ValueError as error:
        raise ReportFailure("路径越界") from error
    if result.is_symlink() or not result.is_file():
        raise ReportFailure("路径不是普通文件")
    return result


def _signature(path: Path) -> None:
    data = path.read_bytes()[:8]
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"} and data[:2] not in {b"PK", b"\xd0\xcf"}:
        raise ReportFailure("文件签名与扩展名不匹配")
    if suffix in {".csv", ".json", ".jsonl"} and data.startswith(b"PK"):
        raise ReportFailure("文件签名与扩展名不匹配")


def _read(path: Path, sheet: str | None = None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            frame = pd.read_csv(path)
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                header = next(csv.reader(stream), [])
            if len(header) == len(frame.columns):
                frame.columns = header
            return frame
        if suffix in {".xls", ".xlsx"}:
            selected = sheet
            if selected is None:
                workbook = pd.ExcelFile(path)
                selected = workbook.sheet_names[0]
                if suffix == ".xlsx":
                    from openpyxl import load_workbook

                    book = load_workbook(path, read_only=True, data_only=True)
                    visible = [
                        item.title for item in book.worksheets if item.sheet_state == "visible"
                    ]
                    book.close()
                    if visible:
                        selected = visible[0]
                workbook.close()
            return pd.read_excel(path, sheet_name=selected)
        if suffix == ".jsonl":
            return pd.read_json(path, lines=True)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
            raise ReportFailure("JSON 仅支持顶层对象数组")
        return pd.DataFrame(raw)
    except ReportFailure:
        raise
    except Exception as error:
        raise ReportFailure("数据文件格式无效或工作表不存在") from error


class ReportRuntime:
    def __init__(self, workspace: str | Path, state_root: str | Path | None = None):
        self.workspace = Path(workspace).resolve()
        self.state_root = Path(state_root or "/tmp/workspace-report").resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        now = time.time()
        for path in self.state_root.iterdir():
            if path.is_dir() and now - path.stat().st_mtime > FAILURE_TTL_SECONDS:
                shutil.rmtree(path, ignore_errors=True)

    def _state(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f-]{36}", job_id):
            raise ReportFailure("job_id 无效")
        path = self.state_root / job_id
        if not path.is_dir():
            raise ReportFailure("任务不存在")
        return path

    def _load(self, job_id: str) -> dict[str, Any]:
        state = self._state(job_id)
        return json.loads((state / "state.json").read_text(encoding="utf-8"))

    def _save(self, state: dict[str, Any]) -> None:
        path = self.state_root / state["jobId"]
        path.mkdir(parents=True, exist_ok=True)
        (path / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def prepare(self, paths: list[str], sheet_name: str | None = None) -> dict[str, Any]:
        if not isinstance(paths, list) or not 1 <= len(paths) <= 5:
            raise ReportFailure("paths 数量必须在 1 至 5 个之间")
        if len(set(paths)) != len(paths):
            raise ReportFailure("paths 不能重复")
        files = [_safe_path(self.workspace, path) for path in paths]
        if any(path.suffix.lower() not in SUPPORTED for path in files):
            raise ReportFailure("不支持的数据文件格式")
        for path in files:
            _signature(path)
        suffixes = {path.suffix.lower() for path in files}
        if len(suffixes) != 1:
            raise ReportFailure("多文件必须使用相同格式")
        if sum(path.stat().st_size for path in files) > MAX_TOTAL_BYTES:
            raise ReportFailure("源文件合计超过 100 MiB")
        frames = [_check(_read(path, sheet_name)) for path in files]
        first = list(frames[0].columns)
        for frame in frames[1:]:
            if list(frame.columns) != first:
                raise ReportFailure("多文件必须具有相同字段")
            for column in first:
                left = frame[column]
                right = frames[0][column]
                if pd.api.types.is_numeric_dtype(left) != pd.api.types.is_numeric_dtype(right):
                    raise ReportFailure("多文件字段类型不兼容")
        frame = _check(pd.concat(frames, ignore_index=True))
        warnings: list[str] = []
        if frame.empty:
            warnings.append("数据集没有数据行")
        job_id = str(uuid.uuid4())
        state = {
            "jobId": job_id,
            "status": "prepared",
            "paths": paths,
            "sheetName": sheet_name,
            "hashes": {
                path: hashlib.sha256(file.read_bytes()).hexdigest()
                for path, file in zip(paths, files)
            },
            "schema": [{"name": name, "type": str(frame[name].dtype)} for name in frame.columns],
            "rowCount": len(frame),
            "columnCount": len(frame.columns),
            "analyses": {},
            "warnings": warnings,
        }
        self._save(state)
        return {
            key: state[key]
            for key in (
                "jobId",
                "status",
                "schema",
                "rowCount",
                "columnCount",
                "hashes",
                "warnings",
            )
        }

    def _frame(self, state: dict[str, Any]) -> pd.DataFrame:
        frames = []
        for path in state["paths"]:
            file = _safe_path(self.workspace, path)
            if hashlib.sha256(file.read_bytes()).hexdigest() != state["hashes"][path]:
                raise ReportFailure("源文件发生变化，任务已失效")
            frames.append(_check(_read(file, state.get("sheetName"))))
        return _check(pd.concat(frames, ignore_index=True))

    def analyze(self, job_id: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        state = self._load(job_id)
        if state["status"] != "prepared":
            raise ReportFailure("任务状态不允许分析")
        frame = self._frame(state)
        try:
            validated = ANALYSIS_OPERATIONS.validate_python(operations)
        except ValueError as error:
            raise ReportFailure("分析操作参数无效") from error
        result = []
        for operation in validated:
            kind = operation.type
            analysis_id = str(uuid.uuid4())
            value: Any
            if kind == "summary":
                summary: dict[str, dict[str, Any]] = {}
                for column in frame.columns:
                    series = frame[column]
                    item: dict[str, Any] = {
                        "count": int(series.count()),
                        "unique": int(series.nunique()),
                    }
                    if pd.api.types.is_numeric_dtype(series):
                        item.update(
                            mean=float(series.mean()),
                            min=float(series.min()),
                            max=float(series.max()),
                        )
                    summary[column] = item
                value = summary
            elif isinstance(operation, ColumnOperation):
                column = operation.column
                if column not in frame.columns:
                    raise ReportFailure("分析字段不存在")
                series = frame[column]
                if kind == "iqr":
                    numeric = pd.to_numeric(series, errors="coerce").dropna()
                    q1, q3 = numeric.quantile([0.25, 0.75])
                    spread = q3 - q1
                    value = {
                        "lower": float(q1 - 1.5 * spread),
                        "upper": float(q3 + 1.5 * spread),
                        "count": int(
                            ((numeric < q1 - 1.5 * spread) | (numeric > q3 + 1.5 * spread)).sum()
                        ),
                    }
                elif kind == "share":
                    counts = series.value_counts(dropna=False).head(operation.limit)
                    value = {str(key): float(item / counts.sum()) for key, item in counts.items()}
                elif kind == "trend":
                    value = [
                        {"index": str(index), "value": value}
                        for index, value in series.head(operation.limit).items()
                    ]
                else:
                    counts = series.value_counts(dropna=False).head(operation.limit)
                    value = {str(key): int(item) for key, item in counts.items()}
            else:
                raise ReportFailure("不支持的分析类型")
            state["analyses"][analysis_id] = {"type": kind, "value": value}
            result.append({"analysisId": analysis_id, "type": kind, "result": value})
        state["status"] = "analyzed"
        self._save(state)
        return {"jobId": job_id, "status": state["status"], "analyses": result}

    def compile(
        self, job_id: str, title: str, template: str, blocks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        state = self._load(job_id)
        if state["status"] != "analyzed" or template not in TEMPLATES:
            raise ReportFailure("任务状态或模板无效")
        self._frame(state)
        for block in blocks:
            if block.get("type") not in {
                "summary",
                "kpi",
                "body",
                "table",
                "chart",
                "note",
                "page_break",
                "appendix",
            }:
                raise ReportFailure("blocks 包含不支持的块类型")
            if (
                block.get("type") in {"kpi", "table", "chart"}
                and block.get("analysis_id") not in state["analyses"]
            ):
                raise ReportFailure("blocks 只能引用已保存的 analysis_id")
        state.update(
            {
                "status": "compiled",
                "title": str(title)[:120],
                "template": template,
                "blocks": blocks,
            }
        )
        self._save(state)
        return {"jobId": job_id, "status": "compiled", "template": template}

    def render(self, job_id: str) -> dict[str, Any]:
        state = self._load(job_id)
        if state["status"] != "compiled":
            raise ReportFailure("任务状态不允许渲染")
        self._frame(state)
        try:
            import pypdf
            from weasyprint import HTML
        except ImportError as error:
            raise ReportFailure("PDF 运行时依赖不可用") from error
        job = self.state_root / job_id
        chart = job / "chart.png"
        frame = self._frame(state)
        fig, axis = plt.subplots(figsize=(8, 4))
        numeric = frame.select_dtypes(include="number")
        if not numeric.empty:
            numeric.iloc[:, 0].plot(kind="bar", ax=axis)
        fig.tight_layout()
        fig.savefig(chart)
        plt.close(fig)
        title = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", state["title"]).strip("._") or "报表"
        output = self.workspace / "报表" / "生成结果" / job_id / f"{title}.pdf"
        output.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for block in state["blocks"]:
            analysis = state["analyses"].get(block.get("analysis_id"), {})
            if block.get("type") in {"table", "kpi", "summary"}:
                rows.append(
                    f"<h2>{html_module.escape(str(block.get('type')))}</h2><pre>{html_module.escape(json.dumps(analysis.get('value', {}), ensure_ascii=False, default=str))}</pre>"
                )
            elif block.get("type") == "note":
                rows.append(f"<p>{html_module.escape(str(block.get('text', '')))}</p>")
            elif block.get("type") == "appendix":
                truncated = (
                    len(frame) > MAX_APPENDIX_ROWS or len(frame.columns) > MAX_APPENDIX_COLUMNS
                )
                rows.append(
                    f"<p>附录行数：{min(len(frame), MAX_APPENDIX_ROWS)}；截断：{'是' if truncated else '否'}</p>"
                )
        html = f"<meta charset='utf-8'><style>@page{{size:A4;margin:18mm}}body{{font-family:'Noto Sans CJK SC','Noto Sans CJK JP',sans-serif}}img{{width:100%}}pre{{white-space:pre-wrap}}</style><h1>{html_module.escape(state['title'])}</h1><p>模板：{html_module.escape(state['template'])}</p><img src='{chart.as_uri()}'><p>数据行数：{len(frame)}</p>{''.join(rows)}"
        temporary = output.with_suffix(".tmp.pdf")
        HTML(string=html, base_url=str(self.workspace)).write_pdf(str(temporary))
        reader = pypdf.PdfReader(str(temporary))
        if not reader.pages:
            raise ReportFailure("PDF 校验失败")
        temporary.replace(output)
        shutil.rmtree(job, ignore_errors=True)
        return {
            "jobId": job_id,
            "status": "rendered",
            "path": str(output.relative_to(self.workspace)),
        }


def main(arguments: list[str] | None = None) -> int:
    values = arguments if arguments is not None else sys.argv[1:]
    try:
        action, payload_text = values
        payload = json.loads(payload_text)
        runtime = ReportRuntime(Path.cwd())
        if action == "capabilities":
            result = {
                "runtime": {"python": sys.version.split()[0], "pandas": pd.__version__},
                "formats": sorted(SUPPORTED),
                "analyses": ["summary", "trend", "top_bottom", "share", "pivot", "iqr"],
                "charts": ["bar", "horizontal_bar", "line", "area", "pie", "donut", "scatter"],
                "templates": sorted(TEMPLATES),
                "fonts": ["Noto CJK"],
            }
        elif action == "prepare":
            result = runtime.prepare(payload["paths"], payload.get("sheet_name"))
        elif action == "analyze":
            result = runtime.analyze(payload["job_id"], payload["operations"])
        elif action == "compile":
            result = runtime.compile(
                payload["job_id"], payload["title"], payload["template"], payload["blocks"]
            )
        elif action == "render":
            result = runtime.render(payload["job_id"])
        else:
            raise ReportFailure("未知报表操作")
        encoded = json.dumps(result, ensure_ascii=False, default=str)
        if len(encoded.encode()) > MAX_RESULT_BYTES:
            raise ReportFailure("报表工具结果超过 32 KiB")
        print(encoded)
        return 0
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
