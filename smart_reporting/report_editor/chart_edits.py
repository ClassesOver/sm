"""编辑器 AI 改图登记（draft 侧车）。

登记记录与草稿同目录（``draft/.chart-edits.json``），由编辑器在
``_draft_lock`` 内原子写入；图片、脚本、作图数据落在不可变目录
``chart-edits/<editId>/``，文件身份即登记身份。正文引用了哪条记录，
哪条就是采用版本；未被引用的记录在导出或修订清理时回收。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..reporting.contract import SHA256_PATTERN, StrictModel, safe_relative_posix_path
from ..reporting.models import ReportingError

CHART_EDITS_REGISTRY_VERSION = 1
CHART_EDITS_DIR = "chart-edits"
CHART_EDIT_ID_PATTERN = re.compile(r"^cedit-[0-9a-z]{8,32}$")
TABLE_EDIT_ID_PATTERN = re.compile(r"^tedit-[0-9a-z]{8,32}$")
_MAX_CHART_EDIT_FIELDS = 100
_MAX_TABLE_EDIT_MARKDOWN_CHARS = 128 * 1024


class ChartEditFileRef(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    size: int = Field(gt=0, le=200 * 1024 * 1024)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = safe_relative_posix_path(value, "改图文件路径必须是安全的工作区相对路径")
        return path.as_posix()

    def as_identity(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


class ChartEditSkipped(StrictModel):
    """L3（超出登记数据）或暂不支持部分的逐条说明。"""

    request: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)


class ChartEditChartMeta(StrictModel):
    """改图后的图表语义字段快照（登记进新 revision 追溯时使用）。"""

    title: str = Field(min_length=1, max_length=200)
    alt_text: str = Field(alias="altText", min_length=1, max_length=200)
    visual_form: str = Field(alias="visualForm", min_length=1, max_length=200)
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=100)


class ChartEditRecord(StrictModel):
    """一条已成功执行的改图登记。

    只有 ``status="succeeded"`` 的记录写入登记；失败结果经任务状态接口
    返回，不进入资产放行与导出链路。``image`` 是新图身份，``script`` 是
    生成脚本身份，``plotDataFiles`` 是本次作图实际使用（且已核验）的
    chart-input 文件身份。
    """

    edit_id: str = Field(alias="editId", pattern=CHART_EDIT_ID_PATTERN.pattern)
    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    base_image_path: str = Field(alias="baseImagePath", min_length=1, max_length=1024)
    base_image_sha256: str = Field(alias="baseImageSha256", pattern=SHA256_PATTERN)
    instruction: str = Field(min_length=1, max_length=2000)
    level: tuple[Literal["L1", "L2"], ...] = Field(min_length=1, max_length=4)
    data_origin: Literal["original", "rebound", "template"] = Field(
        default="original", alias="dataOrigin"
    )
    image: ChartEditFileRef
    script: ChartEditFileRef
    plot_data_files: tuple[ChartEditFileRef, ...] = Field(
        alias="plotDataFiles", min_length=1, max_length=50
    )
    data_bindings: tuple[dict[str, Any], ...] = Field(
        alias="dataBindings", default=(), max_length=100
    )
    chart: ChartEditChartMeta
    visual_inspection_receipt: dict[str, Any] = Field(
        alias="visualInspectionReceipt", default_factory=dict
    )
    warnings: tuple[str, ...] = Field(default=(), max_length=_MAX_CHART_EDIT_FIELDS)
    skipped: tuple[ChartEditSkipped, ...] = Field(default=(), max_length=20)
    status: Literal["succeeded"] = "succeeded"
    created_at: str = Field(alias="createdAt", min_length=1, max_length=64)
    user_id: str = Field(alias="userId", min_length=1, max_length=256)

    @field_validator("base_image_path")
    @classmethod
    def validate_base_image_path(cls, value: str) -> str:
        path = safe_relative_posix_path(value, "改图底图路径必须是安全的工作区相对路径")
        return path.as_posix()

    @model_validator(mode="after")
    def validate_record(self) -> ChartEditRecord:
        if len(set(self.level)) != len(self.level):
            raise ValueError("改图级别不能重复")
        if len({item.path for item in self.plot_data_files}) != len(self.plot_data_files):
            raise ValueError("作图数据文件不能重复")
        return self


class TableEditRecord(StrictModel):
    """一条已成功执行的 AI 改表登记（设计稿 §14.1，与改图同一侧车）。

    ``markdown`` 是服务端装配的新表完整块（含 ``[[table:newTableId]]`` 协议
    标记与表题）；``body_sha256`` 是按导出清单同一规则（``_TABLE_BLOCK`` 捕获
    的表体）计算的哈希，接受后正文块体必须与之一致才登记追溯。单元格取值
    全部来自 ``table_trace``（TableTraceV1）逐格绑定的冻结事实。
    """

    edit_id: str = Field(alias="editId", pattern=TABLE_EDIT_ID_PATTERN.pattern)
    table_id: str = Field(alias="tableId", min_length=1, max_length=128)
    analysis_id: str = Field(alias="analysisId", min_length=1, max_length=128)
    new_table_id: str = Field(alias="newTableId", min_length=1, max_length=128)
    instruction: str = Field(min_length=1, max_length=2000)
    body_sha256: str = Field(alias="bodySha256", pattern=SHA256_PATTERN)
    markdown: str = Field(min_length=1, max_length=_MAX_TABLE_EDIT_MARKDOWN_CHARS)
    table_trace: dict[str, Any] = Field(alias="tableTrace", default_factory=dict)
    warnings: tuple[str, ...] = Field(default=(), max_length=_MAX_CHART_EDIT_FIELDS)
    skipped: tuple[ChartEditSkipped, ...] = Field(default=(), max_length=20)
    status: Literal["succeeded"] = "succeeded"
    created_at: str = Field(alias="createdAt", min_length=1, max_length=64)
    user_id: str = Field(alias="userId", min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_record(self) -> TableEditRecord:
        if self.new_table_id == self.table_id:
            raise ValueError("改表新 tableId 不能与原表相同")
        return self


def chart_edits_registry_path(markdown_path: str) -> str:
    source = PurePosixPath(markdown_path)
    return str(source.parent / "draft" / ".chart-edits.json")


def chart_edit_output_dir(markdown_path: str, edit_id: str) -> str:
    """改图产物目录：``<revision>/chart-edits/<editId>/``（不可变路径）。"""

    if not CHART_EDIT_ID_PATTERN.fullmatch(edit_id):
        raise ValueError("改图标识非法")
    source = PurePosixPath(markdown_path)
    return str(source.parent / CHART_EDITS_DIR / edit_id)


def chart_edit_image_src(markdown_path: str, edit_id: str) -> str:
    """新图在正文中的引用形式（相对修订目录，与原图同一规则）。"""

    image_path = PurePosixPath(chart_edit_output_dir(markdown_path, edit_id)) / "chart.png"
    relative = image_path.relative_to(PurePosixPath(markdown_path).parent)
    return relative.as_posix()


def _parse_registry_payload(content: bytes) -> dict[str, Any]:
    """解析共享侧车外壳，不在这里耦合校验改图与改表记录。"""

    try:
        payload = json.loads(content)
    except ValueError as error:
        raise ValueError("改图登记不是合法 JSON") from error
    if not isinstance(payload, dict) or payload.get("version") != CHART_EDITS_REGISTRY_VERSION:
        raise ValueError("改图登记版本不识别")
    return payload


def _parse_chart_records(payload: dict[str, Any]) -> tuple[ChartEditRecord, ...]:
    records_raw = payload.get("records")
    if not isinstance(records_raw, list):
        raise ValueError("改图登记记录缺失")
    records: list[ChartEditRecord] = []
    seen: set[str] = set()
    for raw in records_raw:
        if not isinstance(raw, dict):
            raise ValueError("改图登记记录损坏")
        record = ChartEditRecord.model_validate(raw)
        if record.edit_id in seen:
            raise ValueError("改图登记 editId 重复")
        seen.add(record.edit_id)
        records.append(record)
    return tuple(records)


def _parse_table_records(payload: dict[str, Any]) -> tuple[TableEditRecord, ...]:
    table_edits: list[TableEditRecord] = []
    seen_tables: set[str] = set()
    # tableEdits 为 §14 追加键：旧登记文件没有该键时视为空。
    table_edits_raw = payload.get("tableEdits", [])
    if not isinstance(table_edits_raw, list):
        raise ValueError("改表登记记录缺失")
    for raw in table_edits_raw:
        if not isinstance(raw, dict):
            raise ValueError("改表登记记录损坏")
        record = TableEditRecord.model_validate(raw)
        if record.edit_id in seen_tables:
            raise ValueError("改表登记 editId 重复")
        seen_tables.add(record.edit_id)
        table_edits.append(record)
    return tuple(table_edits)


def parse_chart_edit_records(content: bytes) -> tuple[ChartEditRecord, ...]:
    return _parse_chart_records(_parse_registry_payload(content))


def parse_table_edit_records(content: bytes) -> tuple[TableEditRecord, ...]:
    return _parse_table_records(_parse_registry_payload(content))


async def load_chart_edit_records(
    workspace: Any, thread_id: str, markdown_path: str
) -> tuple[ChartEditRecord, ...]:
    """读取登记；登记不存在视为空（旧报告/未改图），损坏抛 ``ValueError``。"""

    path = chart_edits_registry_path(markdown_path)
    if not await workspace.apath_exists(thread_id, path):
        return ()
    content, _media_type = await workspace.afile_bytes(thread_id, path)
    return parse_chart_edit_records(content)


async def load_table_edit_records(
    workspace: Any, thread_id: str, markdown_path: str
) -> tuple[TableEditRecord, ...]:
    """读取改表登记；不存在视为空，损坏抛 ``ValueError``。"""

    path = chart_edits_registry_path(markdown_path)
    if not await workspace.apath_exists(thread_id, path):
        return ()
    content, _media_type = await workspace.afile_bytes(thread_id, path)
    return parse_table_edit_records(content)


async def append_chart_edit_record(
    workspace: Any, thread_id: str, markdown_path: str, record: ChartEditRecord
) -> None:
    """在已有登记上原子追加一条记录；调用方必须持有对应草稿锁。"""

    path = chart_edits_registry_path(markdown_path)
    payload = await _load_registry_payload(workspace, thread_id, markdown_path)
    records = _parse_chart_records(payload)
    if any(item.edit_id == record.edit_id for item in records):
        raise ReportingError("snapshot_integrity_failed", "改图登记 editId 已存在。")
    payload["records"] = [
        item.model_dump(mode="json", by_alias=True) for item in (*records, record)
    ]
    encoded = _encode_registry_payload(payload)
    await _rewrite_registry(workspace, thread_id, path, encoded)


async def append_table_edit_record(
    workspace: Any, thread_id: str, markdown_path: str, record: TableEditRecord
) -> None:
    """在已有登记上原子追加一条改表记录；调用方必须持有对应草稿锁。"""

    path = chart_edits_registry_path(markdown_path)
    payload = await _load_registry_payload(workspace, thread_id, markdown_path)
    table_edits = _parse_table_records(payload)
    if any(item.edit_id == record.edit_id for item in table_edits):
        raise ReportingError("snapshot_integrity_failed", "改表登记 editId 已存在。")
    payload["tableEdits"] = [
        item.model_dump(mode="json", by_alias=True) for item in (*table_edits, record)
    ]
    encoded = _encode_registry_payload(payload)
    await _rewrite_registry(workspace, thread_id, path, encoded)


async def _load_registry_payload(
    workspace: Any, thread_id: str, markdown_path: str
) -> dict[str, Any]:
    path = chart_edits_registry_path(markdown_path)
    if not await workspace.apath_exists(thread_id, path):
        return {"version": CHART_EDITS_REGISTRY_VERSION, "records": [], "tableEdits": []}
    content, _media_type = await workspace.afile_bytes(thread_id, path)
    return _parse_registry_payload(content)


def _encode_registry_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


async def _rewrite_registry(workspace: Any, thread_id: str, path: str, encoded: bytes) -> None:
    # 追加写入与覆盖写共用工作区层的原子替换与每路径写锁。
    await workspace.awrite_bytes(thread_id, path, encoded, overwrite=True)
    # 回读确认登记已持久化，避免静默丢失改图身份。
    stored, _media_type = await workspace.afile_bytes(thread_id, path)
    if hashlib.sha256(stored).hexdigest() != hashlib.sha256(encoded).hexdigest():
        raise ReportingError("snapshot_integrity_failed", "改图登记写入后校验失败。")


def chart_edit_summary(instruction: str, limit: int = 80) -> str:
    """追溯 transformNotes 使用的要求摘要；不回传全文。"""

    normalized = " ".join(instruction.split())
    return normalized[:limit]
