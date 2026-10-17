from smart_reporting.report_editor.capabilities import (
    FULL_EDITOR_CAPABILITIES,
    EditorCapabilities,
)


def test_missing_capabilities_mean_full_editor_session():
    resolved = EditorCapabilities.of(None)

    assert resolved is FULL_EDITOR_CAPABILITIES
    assert resolved.full and not resolved.restricted
    assert resolved.download_original and resolved.download_derived and resolved.drilldown
    assert resolved.blocked_columns == frozenset()


def test_share_capabilities_default_to_least_privilege():
    resolved = EditorCapabilities.of({"blocked_columns": ["patient_id", 7]})

    assert resolved.restricted
    assert resolved.blocked_columns == frozenset({"patient_id", "7"})
    assert not (resolved.download_original or resolved.download_derived or resolved.drilldown)
    # 空字典是受限会话，不能被当成完整权限。
    assert EditorCapabilities.of({}).restricted
    assert EditorCapabilities.of(resolved) is resolved
