"""备注授权与画布对象授权不得混用。"""
import pytest
from pydantic import ValidationError

from smart_reporting.report_editor.slides_native_ai_api import SlidesNativeAIStartPayload


def payload(**changes):
    return SlidesNativeAIStartPayload.model_validate({
        'clientRequestId': 'notes-test', 'instruction': '生成演讲者备注',
        'expectedSha256': 'a' * 64, 'operations': [], 'scope': 'notes',
        'selection': [{'slideIndex': 0}], **changes,
    })


def test_notes_authorization_is_explicit_page_only():
    value = payload()
    assert value.selection[0].model_dump(by_alias=True, exclude_none=True) == {'slideIndex': 0}
    for changes in ({'selection': [{'slideIndex': 0, 'elementId': 'title'}]},
                    {'scope': 'selection'},
                    {'selection': [{'slideIndex': True}]}):
        with pytest.raises(ValidationError):
            payload(**changes)
    value = payload(scope='selection', selection=[{'slideIndex': 0, 'elementId': 'title'}])
    assert value.selection[0].element_id == 'title'
