"""原生授权和下载复用既有 access log 脱敏机制。"""

import logging

import pytest

from smart_reporting.reporting.delivery.publishing import ReportDownloadAccessLogFilter


@pytest.mark.parametrize("action", ["open", "download", "artifacts"])
def test_native_access_log_redacts_bearer_links(action):
    path = f"/reports/v1/native/{action}/secret-native-grant/word?token=secret-query"
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s", ("GET", path), None)
    assert ReportDownloadAccessLogFilter().filter(record)
    message = record.getMessage()
    assert "secret-native-grant" not in message
    assert "secret-query" not in message
    assert f"/reports/v1/native/{action}/<redacted>" in message
