"""服务端共同数据修订的耐久登记；文件内容由工作区读取边界核验。"""
from pydantic import ConfigDict, Field

from ..reporting.contract import StrictModel
from ..reporting.workflow.checkpoint import FileIdentity


class ReportDataRevision(StrictModel):
    report_id: str = Field(alias='reportId', min_length=1, max_length=256)
    base_revision: int = Field(alias='baseRevision', ge=1)
    snapshot_id: str = Field(alias='snapshotId', pattern=r'^[a-zA-Z0-9_-]{1,128}$')
    parent_snapshot_id: str | None = Field(
        default=None, alias='parentSnapshotId', pattern=r'^[a-zA-Z0-9_-]{1,128}$',
    )
    manifest: FileIdentity


class ReportDataExport(StrictModel):
    report_id: str = Field(alias='reportId', min_length=1, max_length=256)
    base_revision: int = Field(alias='baseRevision', ge=1)
    snapshot_id: str = Field(alias='snapshotId', pattern=r'^[a-zA-Z0-9_-]{1,128}$')
    export_id: str = Field(alias='exportId', pattern=r'^[a-zA-Z0-9_-]{1,128}$')
    revision: int = Field(ge=1)
    manifest: FileIdentity


class ReportDataCellEdit(StrictModel):
    model_config = ConfigDict(extra='forbid', frozen=True, populate_by_name=True, allow_inf_nan=False)
    table_id: str = Field(alias='tableId', pattern=r'^[A-Za-z0-9_-]{1,128}$')
    row: int = Field(ge=0, strict=True)
    column: str = Field(min_length=1, max_length=256)
    expected_value: str | bool | int | float | None = Field(alias='expectedValue')
    value: str | bool | int | float | None


class ReportDataEditRequest(StrictModel):
    expected_snapshot_id: str = Field(alias='expectedSnapshotId', pattern=r'^[A-Za-z0-9_-]{1,128}$')
    edits: tuple[ReportDataCellEdit, ...] = Field(min_length=1, max_length=1000)
