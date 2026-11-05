"""原生编辑传输边界与独立灰度开关。"""

import pytest

from smart_reporting.http.identity import requires_workspace_capability
from smart_reporting.http.request_limits import (
    MAX_REPORT_EDITOR_WRITE_REQUEST_BYTES,
    report_editor_write_request_limit,
)
from smart_reporting.runtime.settings import AgentSettings


def test_native_features_are_disabled_independently_by_default():
    settings = AgentSettings.from_environment({}, load_env_file=False)
    for feature in ("docx", "pdf", "ai", "pdf_text", "upload"):
        assert getattr(settings, f"native_{feature}_enabled") is False


@pytest.mark.parametrize("feature", ["docx", "pdf", "ai", "pdf_text", "upload"])
def test_native_feature_environment_does_not_enable_other_features(feature):
    settings = AgentSettings.from_environment(
        {f"AGENT_NATIVE_{feature.upper()}_ENABLED": "true"}, load_env_file=False
    )
    for candidate in ("docx", "pdf", "ai", "pdf_text", "upload"):
        assert getattr(settings, f"native_{candidate}_enabled") is (candidate == feature)


def test_native_writes_have_json_limit_before_session_parsing():
    for method in ("POST", "PUT"):
        assert report_editor_write_request_limit(
            "/reports/v1/native/doc-1/2/api/save", method
        ) == MAX_REPORT_EDITOR_WRITE_REQUEST_BYTES
    assert report_editor_write_request_limit("/reports/v1/native/doc-1/2/api/file", "GET") is None


def test_native_upload_requires_workspace_identity_but_document_uses_own_grant():
    for path in ("/reports/v1/native/import", "/reports/v1/native/import/"):
        assert requires_workspace_capability(path, has_thread=False, has_capability=False)
    assert not requires_workspace_capability(
        "/reports/v1/native/doc-1/2/api/file", has_thread=False, has_capability=False
    )
    assert requires_workspace_capability(
        "/reports/v1/native/doc-1/2/api/file", has_thread=True, has_capability=False
    )


def test_native_upload_has_separate_streaming_limit_above_json_limit():
    from smart_reporting.http.request_limits import native_import_request_limit
    assert native_import_request_limit('/reports/v1/native/import','POST') == 24*1024*1024+64*1024
    assert native_import_request_limit('/reports/v1/native/import/','POST') == 24*1024*1024+64*1024
    assert native_import_request_limit('/reports/v1/native/doc/1/api/save','POST') is None
    assert report_editor_write_request_limit('/reports/v1/native/import','POST') is None


@pytest.mark.parametrize('feature',['docx','pdf','ai','pdf_text','upload'])
def test_documented_native_feature_names_take_precedence_over_legacy_alias(feature):
    name=f'AGENT_REPORT_EDITOR_{feature.upper()}_ENABLED'
    settings=AgentSettings.from_environment({name:'true',f'AGENT_NATIVE_{feature.upper()}_ENABLED':'false'},load_env_file=False)
    assert getattr(settings,f'native_{feature}_enabled') is True
