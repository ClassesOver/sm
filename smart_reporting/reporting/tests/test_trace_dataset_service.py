"""B1 CSV 预览/下载服务测试（计划 4.1/5.2/5.3；fixtures 独立答案支撑）。"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.lineage_fixtures import csv_path, wide_csv_bytes
from smart_reporting.reporting.trace.contracts_v1 import TRACE_BUDGETS_V1
from smart_reporting.reporting.trace.dataset_service import (
    TraceCsvPreviewService,
    TraceDatasetFile,
    TracePreviewPermissions,
    safe_download_filename,
)

SECRET = b"unit-test-secret"
PERMIT_ALL = TracePreviewPermissions()


def _file(
    path: Path,
    dataset_id: str = "dataset-url-test0001",
    rows: int | None = None,
    size: int | None = None,
) -> TraceDatasetFile:
    if rows is None:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = sum(1 for _ in csv.DictReader(handle))
    return TraceDatasetFile(
        dataset_id=dataset_id,
        local_path=path,
        size=size if size is not None else (path.stat().st_size if path.is_file() else 0),
        sha256="0" * 64,
        row_count=rows,
        filename=path.name if path.is_file() else None,
    )


def service() -> TraceCsvPreviewService:
    return TraceCsvPreviewService(secret=SECRET)


# ---------------------------------------------------------------------------
# 分页正确性（boundaries.csv：引号换行是一条记录）
# ---------------------------------------------------------------------------


def test_preview_paginates_boundaries_csv_with_quoted_newline() -> None:
    svc = service()
    file = _file(csv_path("boundaries.csv"))
    page1 = svc.preview(file, PERMIT_ALL, limit=2)
    assert page1.offset == 0
    assert len(page1.rows) == 2
    assert page1.row_count_total == 5
    assert page1.next_cursor is not None
    page2 = svc.preview(file, PERMIT_ALL, limit=2, cursor=page1.next_cursor)
    assert page2.offset == 2
    assert len(page2.rows) == 2
    page3 = svc.preview(file, PERMIT_ALL, limit=2, cursor=page2.next_cursor)
    assert page3.offset == 4
    assert len(page3.rows) == 1
    assert page3.next_cursor is None
    # 引号内换行的"李\n四"是一条记录的 name。
    all_names = [row[1] for page in (page1, page2, page3) for row in page.rows]
    assert "李\n四" in all_names
    assert all_names.count("") == 1


def test_preview_orders_rows_by_snapshot_record_order() -> None:
    svc = service()
    file = _file(csv_path("hospital_revenue.csv"))
    page = svc.preview(file, PERMIT_ALL, limit=10)
    assert [row[0] for row in page.rows] == [
        "2025-08",
        "2025-08",
        "2025-09",
        "2025-09",
    ]
    assert [row[1] for row in page.rows] == ["A院区", "B院区", "A院区", "B院区"]


# ---------------------------------------------------------------------------
# 游标安全
# ---------------------------------------------------------------------------


def test_cursor_rejects_tampering_and_replay_mismatch() -> None:
    svc = service()
    file = _file(csv_path("boundaries.csv"))
    page = svc.preview(file, PERMIT_ALL, limit=2)
    assert page.next_cursor
    tampered = page.next_cursor[:-4] + "AAAA"
    with pytest.raises(ReportingError) as exc:
        svc.preview(file, PERMIT_ALL, limit=2, cursor=tampered)
    assert exc.value.code == "cursor_invalid"
    # 换 limit / 换列集续翻被拒绝。
    with pytest.raises(ReportingError, match="每页行数"):
        svc.preview(file, PERMIT_ALL, limit=3, cursor=page.next_cursor)
    with pytest.raises(ReportingError) as exc:
        svc.preview(file, PERMIT_ALL, limit=2, columns=["id"], cursor=page.next_cursor)
    assert exc.value.code == "cursor_invalid"
    # 跨数据集重放被拒绝。
    other = _file(csv_path("hospital_revenue.csv"), dataset_id="dataset-url-other01")
    with pytest.raises(ReportingError) as exc:
        svc.preview(other, PERMIT_ALL, limit=2, cursor=page.next_cursor)
    assert exc.value.code == "cursor_invalid"


def test_cursor_binds_snapshot_identity() -> None:
    svc = service()
    file = _file(csv_path("boundaries.csv"))
    page = svc.preview(file, PERMIT_ALL, limit=2)
    mutated = TraceDatasetFile(
        dataset_id=file.dataset_id,
        local_path=file.local_path,
        size=file.size,
        sha256="1" * 64,  # 快照身份变化（如重新分析产生新身份）
        row_count=file.row_count,
    )
    with pytest.raises(ReportingError) as exc:
        svc.preview(mutated, PERMIT_ALL, limit=2, cursor=page.next_cursor)
    assert exc.value.code == "cursor_invalid"


# ---------------------------------------------------------------------------
# 请求形状与资源边界
# ---------------------------------------------------------------------------


def test_preview_rejects_invalid_limit_and_columns() -> None:
    svc = service()
    file = _file(csv_path("hospital_revenue.csv"))
    with pytest.raises(ReportingError) as exc:
        svc.preview(file, PERMIT_ALL, limit=0)
    assert exc.value.code == "request_invalid"
    with pytest.raises(ReportingError):
        svc.preview(
            file, PERMIT_ALL, limit=TRACE_BUDGETS_V1["preview_max_rows_per_page"] + 1
        )
    with pytest.raises(ReportingError) as exc:
        svc.preview(file, PERMIT_ALL, columns=["no_such_column"])
    assert exc.value.code == "request_invalid"


def test_preview_wide_table_requires_column_selection() -> None:
    svc = service()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "wide.csv"
        path.write_bytes(wide_csv_bytes(rows=3, columns=60))
        file = _file(path, rows=3)
        with pytest.raises(ReportingError) as exc:
            svc.preview(file, PERMIT_ALL, limit=10)
        assert exc.value.code == "resource_limit_exceeded"
        page = svc.preview(file, PERMIT_ALL, limit=10, columns=["row_id", "c001", "c002"])
        assert page.columns == ("row_id", "c001", "c002")
        assert len(page.rows) == 3


def test_preview_blocked_column_denies_without_leaking() -> None:
    svc = service()
    file = _file(csv_path("hospital_revenue.csv"))
    permissions = TracePreviewPermissions(blocked_columns=frozenset({"revenue"}))
    with pytest.raises(ReportingError) as exc:
        svc.preview(file, permissions, limit=10)
    assert exc.value.code == "dataset_access_denied"
    assert "revenue" not in str(exc.value)
    page = svc.preview(file, permissions, limit=10, columns=["period", "visits"])
    assert page.columns == ("period", "visits")


def test_preview_missing_file_reports_source_missing() -> None:
    svc = service()
    file = _file(Path("/nonexistent/dataset.csv"), rows=1)
    with pytest.raises(ReportingError) as exc:
        svc.preview(file, PERMIT_ALL)
    assert exc.value.code == "source_missing"


# ---------------------------------------------------------------------------
# 截断与预算
# ---------------------------------------------------------------------------


def test_preview_truncates_oversized_cell() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "big_cell.csv"
        big = "x" * (TRACE_BUDGETS_V1["preview_max_cell_bytes"] + 100)
        path.write_text(f"name,note\nA,\"{big}\"\n", encoding="utf-8")
        file = _file(path, rows=1)
        page = service().preview(file, PERMIT_ALL, limit=10)
        assert page.truncated_cells == 1
        assert page.rows[0][1].endswith("…[截断]")
        assert len(page.rows[0][1].encode("utf-8")) <= (
            TRACE_BUDGETS_V1["preview_max_cell_bytes"] + 32
        )


def test_preview_response_budget_returns_partial_page_honestly() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "budget.csv"
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["c1", "c2", "c3"])
        payload = "y" * 3500  # 每格 3.5 KiB：不触发单格截断，但整页超 1 MiB
        for i in range(100):
            writer.writerow([f"{payload}-{i}", payload, payload])
        path.write_text(buffer.getvalue(), encoding="utf-8")
        file = _file(path, rows=100)
        page = service().preview(file, PERMIT_ALL, limit=100)
        assert page.truncated_by_budget is True
        assert len(page.rows) < 100
        assert page.next_cursor is not None  # 可继续渐进翻页
        assert page.rows  # 至少返回一行


# ---------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------


def test_download_requires_permission_and_returns_original_bytes_path() -> None:
    svc = service()
    file = _file(csv_path("hospital_revenue.csv"))
    with pytest.raises(ReportingError) as exc:
        svc.download_target(file, TracePreviewPermissions(can_download_original=False))
    assert exc.value.code == "dataset_access_denied"
    path, filename = svc.download_target(
        file, TracePreviewPermissions(can_download_original=True)
    )
    assert path == csv_path("hospital_revenue.csv")
    assert filename == "hospital_revenue.csv"


def test_safe_download_filename_sanitizes_but_keeps_cjk() -> None:
    file = TraceDatasetFile(
        dataset_id="dataset-url-test0001",
        local_path=Path("/x/y.csv"),
        size=1,
        sha256="0" * 64,
        row_count=1,
        filename="../../门急诊/收入 明细#.csv",
    )
    name = safe_download_filename(file)
    assert ".." not in name
    assert "/" not in name
    assert name.endswith(".csv")
    assert "门急诊" in name and "收入" in name


def test_preview_keeps_original_cell_text_without_type_inference(tmp_path: Path) -> None:
    """预览按原文返回：编码前导零、小数尾零不能因类型推断被改写。"""
    path = tmp_path / "codes.csv"
    path.write_text("dept_code,amount,rate\n0012,1200.50,05%\n0300,980.00,12%\n", encoding="utf-8")
    page = service().preview(_file(path), PERMIT_ALL, limit=10)
    assert page.rows == (("0012", "1200.50", "05%"), ("0300", "980.00", "12%"))


def test_cursor_continues_when_explicit_columns_equal_full_header() -> None:
    """显式选择全部列（受控列选择的窗口恰为整表）时续翻不能被判为列选择不匹配。"""
    svc = service()
    file = _file(csv_path("hospital_revenue.csv"))
    header = list(svc.preview(file, PERMIT_ALL, limit=1).columns)
    page = svc.preview(file, PERMIT_ALL, limit=2, columns=header)
    assert page.next_cursor
    page2 = svc.preview(file, PERMIT_ALL, limit=2, columns=header, cursor=page.next_cursor)
    assert page2.offset == 2


def test_visible_columns_hide_blocked_names_without_count() -> None:
    svc = service()
    file = _file(csv_path("hospital_revenue.csv"))
    columns, restricted = svc.visible_columns(file, PERMIT_ALL)
    assert "revenue" in columns and restricted is False
    blocked = TracePreviewPermissions(blocked_columns=frozenset({"revenue"}))
    columns, restricted = svc.visible_columns(file, blocked)
    assert "revenue" not in columns and restricted is True
    # 可见列可直接用于受控预览。
    assert svc.preview(file, blocked, limit=10, columns=columns).columns == tuple(columns)


def test_duplicated_header_copies_of_blocked_columns_stay_blocked(tmp_path: Path) -> None:
    """重复表头的受限列副本（polars 改名为 *_duplicated_n）不出现在可见列，也不能被预览。"""
    path = tmp_path / "dup.csv"
    path.write_text("name,salary,salary\na,1,2\n", encoding="utf-8")
    svc = service()
    file = _file(path, rows=1)
    blocked = TracePreviewPermissions(
        blocked_columns=frozenset({"salary"}), can_download_original=True
    )
    columns, restricted = svc.visible_columns(file, blocked)
    assert columns == ["name"] and restricted is True
    with pytest.raises(ReportingError) as exc:
        svc.preview(file, blocked, limit=10, columns=["name", "salary_duplicated_0"])
    assert exc.value.code == "dataset_access_denied"
    assert svc.blocked_columns_in(file, blocked) == ["salary", "salary_duplicated_0"]
    # 未受限会话不受影响：重复列照常可见。
    assert svc.visible_columns(file, PERMIT_ALL)[0] == ["name", "salary", "salary_duplicated_0"]


def test_download_original_refused_when_session_has_blocked_columns_in_file() -> None:
    """原始字节包含受限列时不能以原始下载绕过列级限制；表头无受限列时不受影响。"""
    svc = service()
    file = _file(csv_path("hospital_revenue.csv"))
    blocked = TracePreviewPermissions(
        blocked_columns=frozenset({"revenue"}), can_download_original=True
    )
    with pytest.raises(ReportingError) as exc:
        svc.download_target(file, blocked)
    assert exc.value.code == "dataset_access_denied"
    assert "revenue" not in str(exc.value)
    unrelated = TracePreviewPermissions(
        blocked_columns=frozenset({"no_such_column"}), can_download_original=True
    )
    assert svc.download_target(file, unrelated)[0] == csv_path("hospital_revenue.csv")
