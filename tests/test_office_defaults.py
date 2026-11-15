import pytest
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.office.model import office_model


def test_web_office_formats_and_assistant_enabled_by_default_but_can_be_disabled(tmp_path):
    pytest.importorskip('fcntl', reason='Production configuration validates Linux host workspaces')
    values = {'REPORTING_HOST_WORKSPACE_ROOT': str(tmp_path / 'workspaces')}
    settings = AgentSettings.from_environment(dict(values), load_env_file=False)
    assert settings.native_docx_enabled
    assert settings.native_pdf_enabled
    assert settings.native_upload_enabled
    assert settings.native_ai_enabled
    disabled = AgentSettings.from_environment({
        **values,
        'AGENT_REPORT_EDITOR_DOCX_ENABLED': 'false',
        'AGENT_REPORT_EDITOR_UPLOAD_ENABLED': 'false',
        'AGENT_REPORT_EDITOR_AI_ENABLED': 'false',
    }, load_env_file=False)
    assert not disabled.native_docx_enabled
    assert not disabled.native_upload_enabled
    assert not disabled.native_ai_enabled


def test_office_model_has_independent_credentials_and_preserves_reporting_fallback(tmp_path):
    pytest.importorskip('fcntl')
    values = {'REPORTING_HOST_WORKSPACE_ROOT': str(tmp_path / 'workspaces'),
              'OPENAI_BASE_URL': 'https://reporting.example/v1', 'OPENAI_API_KEY': 'reporting-secret'}
    fallback = object()
    assert office_model(AgentSettings.from_environment(dict(values), load_env_file=False), fallback) is fallback
    settings = AgentSettings.from_environment({**values, 'AGENT_OFFICE_MODEL': 'file-model',
        'AGENT_OFFICE_MODEL_BASE_URL': 'https://office.example/v1', 'AGENT_OFFICE_MODEL_API_KEY': 'office-secret',
    }, load_env_file=False)
    model = office_model(settings, fallback)
    assert (model.id, str(model.base_url), model.api_key) == ('file-model', 'https://office.example/v1', 'office-secret')
    assert (settings.openai_base_url, settings.openai_api_key) == ('https://reporting.example/v1', 'reporting-secret')
    assert 'office-secret' not in repr(settings)


@pytest.mark.parametrize('endpoint', ['', 'file:///tmp/office', 'https://username:secret@office.example/v1'])
def test_office_model_rejects_incomplete_or_unsafe_endpoint(tmp_path, endpoint):
    pytest.importorskip('fcntl')
    settings = AgentSettings.from_environment({'REPORTING_HOST_WORKSPACE_ROOT': str(tmp_path / 'workspaces'),
        'AGENT_OFFICE_MODEL': 'file-model', 'AGENT_OFFICE_MODEL_BASE_URL': endpoint,
    }, load_env_file=False)
    with pytest.raises(ValueError, match='AGENT_OFFICE_MODEL_BASE_URL') as error:
        office_model(settings, object())
    assert 'secret' not in str(error.value)
