"""CSV 快照预览/下载服务（B1，计划 4.1 与 5.1 的服务层核心）。

职责边界：
- 输入永远是调用方（Editor API 层）从当前 revision 授权索引解析并校验过
  身份的本地文件；本服务不解析客户端提交的路径或授权身份。
- 预览/下载不重新查询数据源、不执行分析脚本（计划 3.4）。
- 预览必须走 polars lazy scan（B0 基线：200MiB 全量入内存不可接受），
  禁止每次翻页全文件收集。
- 分页游标签名并绑定 dataset 身份、列选择、limit 与过期时间；序号绑定
  原快照记录顺序（计划 5.3）。
- 错误一律抛 ``ReportingError``，code 取自 ``TRACE_ERROR_HTTP_STATUS``。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import polars as pl

from ..models import ReportingError
from .contracts_v1 import TRACE_BUDGETS_V1

_PREVIEW_DEFAULT_ROWS = TRACE_BUDGETS_V1["preview_default_rows"]
_PREVIEW_MAX_ROWS = TRACE_BUDGETS_V1["preview_max_rows_per_page"]
_PREVIEW_MAX_COLUMNS = TRACE_BUDGETS_V1["preview_max_columns"]
_MAX_CELL_BYTES = TRACE_BUDGETS_V1["preview_max_cell_bytes"]
_MAX_RESPONSE_BYTES = TRACE_BUDGETS_V1["preview_max_response_bytes"]

_CURSOR_TTL_SECONDS = 3600
_CURSOR_MAX_AGE_SECONDS = 24 * 3600
_UNSAFE_FILENAME_PATTERN = re.compile(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+")
# polars \u8bfb\u53d6\u91cd\u590d\u8868\u5934\u65f6\u628a\u540e\u51fa\u73b0\u7684\u540c\u540d\u5217\u6539\u540d\u4e3a\u201c<\u5217\u540d>_duplicated_<n>\u201d\u3002
# 引号内的 CSV 列名可含换行：用 DOTALL + fullmatch，避免 “.” 不跨行或 “$” 匹配末尾换行前位置。
_DUPLICATED_COLUMN_PATTERN = re.compile(r"(?P<base>.+)_duplicated_\d+", re.DOTALL)


@dataclass(frozen=True)
class TraceDatasetFile:
    """从授权索引解析的本地 CSV 快照（登记元数据 + 本地路径）。"""

    dataset_id: str
    local_path: Path
    size: int
    sha256: str
    row_count: int
    filename: str | None = None
    source_type: str = "url_csv"


@contextmanager
def verified_dataset_snapshot(file: TraceDatasetFile) -> Iterator[TraceDatasetFile]:
    """流式复制并校验同一份字节；后续 CSV 读取只使用请求内的临时快照。"""

    try:
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(file.local_path, flags), "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != file.size:
                raise ReportingError("snapshot_integrity_failed", "数据集快照与登记身份不一致。")
            with tempfile.NamedTemporaryFile(suffix=".csv") as snapshot:
                digest = hashlib.sha256()
                size = 0
                # 多读至多一个字节即可识别增长，避免并发追加导致无界复制。
                while chunk := source.read(min(1024 * 1024, file.size - size + 1)):
                    size += len(chunk)
                    if size > file.size:
                        raise ReportingError("snapshot_integrity_failed", "数据集快照与登记身份不一致。")
                    digest.update(chunk)
                    snapshot.write(chunk)
                if size != file.size or not hmac.compare_digest(digest.hexdigest(), file.sha256):
                    raise ReportingError("snapshot_integrity_failed", "数据集快照与登记身份不一致。")
                snapshot.flush()
                yield replace(file, local_path=Path(snapshot.name))
    except OSError as error:
        raise ReportingError("snapshot_integrity_failed", "数据集快照读取失败。") from error


@dataclass(frozen=True)
class TracePreviewPermissions:
    """预览权限决策结果（由 API 层按会话类型与配置构造）。

    blocked_columns：列名精确匹配黑名单（B0 冻结字段策略）。
    """

    blocked_columns: frozenset[str] = frozenset()
    can_download_original: bool = False
    can_download_derived: bool = False


@dataclass(frozen=True)
class TracePreviewPage:
    dataset_id: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str | None, ...], ...]
    row_count_total: int
    offset: int
    limit: int
    next_cursor: str | None
    truncated_cells: int
    truncated_by_budget: bool

    def to_payload(self) -> dict:
        return {
            "datasetId": self.dataset_id,
            "columns": list(self.columns),
            "rows": [list(row) for row in self.rows],
            "rowCountTotal": self.row_count_total,
            "offset": self.offset,
            "limit": self.limit,
            "nextCursor": self.next_cursor,
            "truncatedCells": self.truncated_cells,
            "truncatedByBudget": self.truncated_by_budget,
            "cellTruncationNote": (
                "部分单元格超过 4 KiB 已截断" if self.truncated_cells else None
            ),
        }


def read_csv_header(path: Path) -> list[str]:
    """读取 CSV 列名（按原文、不做类型推断）；预览、列清单、受限列与派生导出共用。"""

    if not path.is_file():
        raise ReportingError("source_missing", "数据集快照文件不存在。")
    try:
        return pl.scan_csv(path, infer_schema=False).collect_schema().names()
    except (OSError, pl.exceptions.PolarsError) as error:
        raise ReportingError("snapshot_integrity_failed", "CSV 快照无法解析。") from error


def is_blocked_column(name: str, blocked_columns: frozenset[str]) -> bool:
    """按原列名判断受限列。

    表头含重复列名时，polars 会把第二个同名列改名为“<列名>_duplicated_<n>”；只做精确匹配时，
    受限列的重复副本会以改名后的列名出现在可预览列与派生导出中，绕过列级限制（计划 5.2）。
    """

    if name in blocked_columns:
        return True
    match = _DUPLICATED_COLUMN_PATTERN.fullmatch(name)
    return match is not None and match.group("base") in blocked_columns


def safe_download_filename(file: TraceDatasetFile) -> str:
    """下载文件名安全化；保留中文，替换路径与控制字符（计划 5.3）。"""

    raw = file.filename or f"{file.dataset_id}.csv"
    name = _UNSAFE_FILENAME_PATTERN.sub("_", raw).strip("._")
    if not name:
        name = file.dataset_id
    if not name.lower().endswith(".csv"):
        name = f"{name}.csv"
    return name[:180]


class TraceCsvPreviewService:
    """CSV 有界预览：分页、受控列选择、签名游标与响应预算。"""

    def __init__(self, *, secret: bytes) -> None:
        if not secret:
            raise ValueError("预览游标签名密钥不能为空")
        self._secret = secret

    # ------------------------------------------------------------------
    # 游标
    # ------------------------------------------------------------------

    def _sign(self, payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._secret, raw, hashlib.sha256).digest()
        body = base64.urlsafe_b64encode(raw).decode("ascii")
        return f"{body}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"

    def _verify(self, cursor: str) -> dict:
        try:
            body_raw, sig_raw = cursor.split(".", 1)

            def _b64(segment: str) -> bytes:
                encoded = segment.encode("ascii")
                return base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))

            body = _b64(body_raw)
            signature = _b64(sig_raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise ReportingError("cursor_invalid", "分页游标格式无效。") from error
        expected = hmac.new(self._secret, body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ReportingError("cursor_invalid", "分页游标签名无效。")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ReportingError("cursor_invalid", "分页游标载荷无效。") from error
        issued_at = payload.get("iat", 0)
        if not isinstance(issued_at, (int, float)) or issued_at > time.time() + 60:
            raise ReportingError("cursor_invalid", "分页游标签发时间无效。")
        if time.time() - issued_at > _CURSOR_MAX_AGE_SECONDS:
            raise ReportingError("cursor_invalid", "分页游标已过期。")
        return payload

    # ------------------------------------------------------------------
    # 预览
    # ------------------------------------------------------------------

    def preview(
        self,
        file: TraceDatasetFile,
        permissions: TracePreviewPermissions,
        *,
        columns: Sequence[str] | None = None,
        limit: int = _PREVIEW_DEFAULT_ROWS,
        cursor: str | None = None,
        report_id: str = "",
        revision: int = 0,
    ) -> TracePreviewPage:
        if not 1 <= limit <= _PREVIEW_MAX_ROWS:
            raise ReportingError(
                "request_invalid",
                f"每页行数必须在 1~{_PREVIEW_MAX_ROWS} 之间。",
            )
        header = read_csv_header(file.local_path)
        offset = 0
        if cursor is not None:
            payload = self._verify(cursor)
            self._ensure_cursor_matches(
                payload, file, columns, limit, report_id, revision
            )
            offset = payload.get("o", 0)
            if not isinstance(offset, int) or offset < 0:
                raise ReportingError("cursor_invalid", "分页游标偏移无效。")
        elif limit != _PREVIEW_DEFAULT_ROWS and limit <= 0:
            raise ReportingError("request_invalid", "每页行数无效。")

        selected = self._resolve_columns(header, columns, permissions)
        rows, truncated_cells, truncated_by_budget = self._read_window(
            file, selected, offset, limit
        )
        has_more = offset + len(rows) < file.row_count and rows
        next_cursor = None
        if has_more:
            # 预算截断时同样签发续翻游标：位置准确，客户端可渐进遍历或缩小请求。
            # 游标绑定 report/revision + 数据集身份 + 列选择 + limit（计划 5.3），
            # 防止同名同内容数据集跨报告重放。
            next_cursor = self._sign(
                {
                    "r": f"{report_id}#{revision}",
                    "d": file.dataset_id,
                    "h": file.sha256[:16],
                    # 绑定请求原样的列选择：显式选择全部列与不选列是两种请求形状，
                    # 若按“是否等于表头”折叠，显式全列请求的续翻会被判为列选择不匹配。
                    "c": list(columns) if columns is not None else None,
                    "l": limit,
                    "o": offset + len(rows),
                    "iat": int(time.time()),
                    "exp": int(time.time()) + _CURSOR_TTL_SECONDS,
                }
            )
        return TracePreviewPage(
            dataset_id=file.dataset_id,
            columns=tuple(selected),
            rows=tuple(rows),
            row_count_total=file.row_count,
            offset=offset,
            limit=limit,
            next_cursor=next_cursor,
            truncated_cells=truncated_cells,
            truncated_by_budget=truncated_by_budget,
        )

    def _ensure_cursor_matches(
        self,
        payload: dict,
        file: TraceDatasetFile,
        columns: Sequence[str] | None,
        limit: int,
        report_id: str,
        revision: int,
    ) -> None:
        if payload.get("r") != f"{report_id}#{revision}":
            raise ReportingError("cursor_invalid", "分页游标与当前报告修订不匹配。")
        if payload.get("d") != file.dataset_id or payload.get("h") != file.sha256[:16]:
            raise ReportingError("cursor_invalid", "分页游标与数据集身份不匹配。")
        cursor_columns = payload.get("c")
        request_key = list(columns) if columns is not None else None
        if cursor_columns != request_key:
            raise ReportingError("cursor_invalid", "分页游标与列选择不匹配。")
        if payload.get("l") != limit:
            raise ReportingError("cursor_invalid", "分页游标与每页行数不匹配。")
        exp = payload.get("exp", 0)
        if not isinstance(exp, (int, float)) or exp < time.time():
            raise ReportingError("cursor_invalid", "分页游标已过期。")

    def visible_columns(
        self, file: TraceDatasetFile, permissions: TracePreviewPermissions
    ) -> tuple[list[str], bool]:
        """当前会话可预览的列（受控列选择的候选）与是否存在受限列。

        受限列只以“存在受限列”布尔值体现，不回显列名或数量（计划 5.2）。
        """

        header = read_csv_header(file.local_path)
        visible = [
            name for name in header if not is_blocked_column(name, permissions.blocked_columns)
        ]
        return visible, len(visible) != len(header)

    def _resolve_columns(
        self,
        header: list[str],
        columns: Sequence[str] | None,
        permissions: TracePreviewPermissions,
    ) -> list[str]:
        if columns is None:
            selected = list(header)
        else:
            unknown = [name for name in columns if name not in header]
            if unknown:
                raise ReportingError(
                    "request_invalid", f"请求列不存在: {', '.join(unknown[:5])}"
                )
            selected = list(columns)
        if not selected:
            raise ReportingError("request_invalid", "至少需要选择一列。")
        if len(selected) > _PREVIEW_MAX_COLUMNS:
            raise ReportingError(
                "resource_limit_exceeded",
                f"单页最多 {_PREVIEW_MAX_COLUMNS} 列，请使用受控列选择。",
            )
        if any(is_blocked_column(name, permissions.blocked_columns) for name in selected):
            # 受限列不回显存在性以外的信息（计划 5.2：不泄露受保护字段）。
            raise ReportingError(
                "dataset_access_denied", "请求包含当前会话无权预览的列。"
            )
        return selected

    def _read_window(
        self, file: TraceDatasetFile, columns: list[str], offset: int, limit: int
    ) -> tuple[list[tuple[str | None, ...]], int, bool]:
        try:
            # 按原文读取：类型推断会把 "0012" 变成 12、"1200.50" 变成 1200.5，核对时显示失真。
            frame = (
                pl.scan_csv(file.local_path, infer_schema=False)
                .select(columns)
                .slice(offset, limit)
                .collect()
            )
        except (OSError, pl.exceptions.PolarsError) as error:
            raise ReportingError(
                "snapshot_integrity_failed", "CSV 快照读取失败。"
            ) from error
        rows: list[tuple[str | None, ...]] = []
        truncated_cells = 0
        budget = _MAX_RESPONSE_BYTES
        truncated_by_budget = False
        for record in frame.iter_rows():
            rendered: list[str | None] = []
            for value in record:
                if value is None:
                    rendered.append(None)
                    continue
                text = value if isinstance(value, str) else str(value)
                raw = text.encode("utf-8")
                if len(raw) > _MAX_CELL_BYTES:
                    keep = text.encode("utf-8")[: _MAX_CELL_BYTES].decode(
                        "utf-8", errors="ignore"
                    )
                    text = keep + "…[截断]"
                    truncated_cells += 1
                    raw = text.encode("utf-8")
                rendered.append(text)
                budget -= len(raw) + 16
            if budget <= 0 and rows:
                # 字节超限返回不足一页记录并如实标记，不伪造完整页（计划 4.1-3）。
                truncated_by_budget = True
                break
            rows.append(tuple(rendered))
        return rows, truncated_cells, truncated_by_budget

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------

    def download_target(
        self, file: TraceDatasetFile, permissions: TracePreviewPermissions
    ) -> tuple[Path, str]:
        """校验下载权限并返回 (本地路径, 安全文件名)。原始快照按原字节返回。"""

        if not permissions.can_download_original:
            raise ReportingError(
                "dataset_access_denied", "当前会话无权下载该数据集的原始文件。"
            )
        if not file.local_path.is_file():
            raise ReportingError("source_missing", "数据集快照文件不存在。")
        if self.blocked_columns_in(file, permissions):
            # 原始字节包含受限列：不能以“原始下载”绕过列级限制（计划 5.2）。
            raise ReportingError(
                "dataset_access_denied",
                "当前会话存在受限列，不能下载原始文件；可使用派生导出（受限列自动掩码）。",
            )
        return file.local_path, safe_download_filename(file)

    def blocked_columns_in(
        self, file: TraceDatasetFile, permissions: TracePreviewPermissions
    ) -> list[str]:
        """文件表头中当前会话受限的列（仅供服务端强制掩码/拒绝，不回显给客户端）。"""

        if not permissions.blocked_columns:
            return []
        return [
            name
            for name in read_csv_header(file.local_path)
            if is_blocked_column(name, permissions.blocked_columns)
        ]


def preview_default_rows() -> int:
    return _PREVIEW_DEFAULT_ROWS
