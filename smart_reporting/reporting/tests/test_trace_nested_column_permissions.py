"""Nested CSV duplicate aliases must retain the original column's restrictions."""

import csv
import hashlib

import pytest

from smart_reporting.report_editor.trace_exports import _validate_masked_columns_policy
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.dataset_service import (
    TraceCsvPreviewService,
    TraceDatasetFile,
    TracePreviewPermissions,
)


@pytest.fixture(params=["secret", "private\nfield", "private\n"])
def restricted_snapshot(tmp_path, request):
    base = request.param
    alias = base + "_duplicated_0"
    path = tmp_path / "nested.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["public", base, alias, alias])
        writer.writerow(["visible", "first-secret", "second-secret", "third-secret"])
    content = path.read_bytes()
    file = TraceDatasetFile("dataset-nested", path, len(content),
                            hashlib.sha256(content).hexdigest(), 1)
    permissions = TracePreviewPermissions(
        blocked_columns=frozenset({base}), can_download_original=True,
    )
    return file, permissions, alias + "_duplicated_0"


def test_nested_alias_is_not_advertised(restricted_snapshot):
    file, permissions, nested = restricted_snapshot
    service = TraceCsvPreviewService(secret=b"synthetic-test")
    owner_columns, _ = service.visible_columns(file, TracePreviewPermissions())
    assert nested in owner_columns  # Exercise Polars' actual generated name.
    assert service.visible_columns(file, permissions) == (["public"], True)


def test_nested_alias_cannot_be_explicitly_previewed(restricted_snapshot):
    file, permissions, nested = restricted_snapshot
    service = TraceCsvPreviewService(secret=b"synthetic-test")
    with pytest.raises(ReportingError) as error:
        service.preview(file, permissions, columns=[nested])
    assert error.value.code == "dataset_access_denied"
    assert service.preview(file, permissions, columns=["public"]).rows == (("visible",),)


def test_nested_alias_is_in_server_masking_set(restricted_snapshot):
    file, permissions, nested = restricted_snapshot
    service = TraceCsvPreviewService(secret=b"synthetic-test")
    assert nested in service.blocked_columns_in(file, permissions)


def test_derived_export_forces_nested_alias_mask(restricted_snapshot):
    file, permissions, nested = restricted_snapshot
    columns, mask = _validate_masked_columns_policy(file, {}, permissions.blocked_columns)
    assert nested in columns
    assert "public" not in columns
    assert mask == "***"

