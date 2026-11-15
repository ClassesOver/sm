"""原生编辑传输边界与独立灰度开关。"""

import pytest

from smart_reporting.http.identity import requires_workspace_capability
from smart_reporting.http.request_limits import (
    MAX_REPORT_EDITOR_WRITE_REQUEST_BYTES,
    report_editor_write_request_limit,
)
from smart_reporting.runtime.settings import AgentSettings


# GenOffice Web 以四格式编辑、AI 与上传为主入口，默认开启；PDF 文字编辑仍需显式开启。
_NATIVE_DEFAULTS = {"docx": True, "pdf": True, "ai": True, "pdf_text": False, "upload": True}


def test_native_feature_defaults():
    settings = AgentSettings.from_environment({}, load_env_file=False)
    for feature, enabled in _NATIVE_DEFAULTS.items():
        assert getattr(settings, f"native_{feature}_enabled") is enabled


@pytest.mark.parametrize("feature", list(_NATIVE_DEFAULTS))
def test_native_feature_environment_does_not_change_other_features(feature):
    # 每项能力按环境独立开关：把一项设为与默认相反，其余保持默认。
    flipped = not _NATIVE_DEFAULTS[feature]
    settings = AgentSettings.from_environment(
        {f"AGENT_NATIVE_{feature.upper()}_ENABLED": str(flipped).lower()}, load_env_file=False
    )
    for candidate, enabled in _NATIVE_DEFAULTS.items():
        expected = flipped if candidate == feature else enabled
        assert getattr(settings, f"native_{candidate}_enabled") is expected


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
    assert native_import_request_limit('/reports/v1/native/doc/1/api/slides/open','POST') == 24*1024*1024+64*1024
    assert native_import_request_limit('/reports/v1/native/doc/1/api/slides/open','GET') is None
    assert report_editor_write_request_limit('/reports/v1/native/doc/1/api/slides/open','POST') is None
    assert report_editor_write_request_limit('/reports/v1/native/import','POST') is None


@pytest.mark.parametrize('feature',['docx','pdf','ai','pdf_text','upload'])
def test_documented_native_feature_names_take_precedence_over_legacy_alias(feature):
    name=f'AGENT_REPORT_EDITOR_{feature.upper()}_ENABLED'
    settings=AgentSettings.from_environment({name:'true',f'AGENT_NATIVE_{feature.upper()}_ENABLED':'false'},load_env_file=False)
    assert getattr(settings,f'native_{feature}_enabled') is True
