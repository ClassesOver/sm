from io import BytesIO
from zipfile import ZipFile
import pytest
from smart_reporting.report_editor.native_models import NativeScope
from smart_reporting.report_editor.native_xlsx_threads import xlsx_thread_actor, validate_xlsx_thread_actors

def _source():
    data = BytesIO()
    with ZipFile(data, 'w') as package:
        package.writestr('xl/threadedComments/threadedComment1.xml', '<ThreadedComments><threadedComment id="old" personId="historical" dT="2020-01-01T00:00:00"><text>历史作者</text></threadedComment></ThreadedComments>')
    return data.getvalue()

def test_thread_actor_binds_database_company_user_and_preserves_historical_identity():
    scope = NativeScope(database='db', companyId='c', userId='u', threadId='t')
    actor = xlsx_thread_actor(scope)
    assert actor['author'] == 'u'
    assert actor == xlsx_thread_actor(scope.model_copy(update={'thread_id': 'another'}))
    for key in ('database', 'company_id', 'user_id'):
        assert actor['personId'] != xlsx_thread_actor(scope.model_copy(update={key: 'other'}))['personId']
    old = {'id': 'old', 'personId': 'historical', 'author': '历史作者', 'dT': '2020-01-01T00:00:00', 'replies': []}
    reply = {'id': 'new', **actor, 'dT': '2026-11-13T00:00:00', 'text': '回复'}
    operation = {'kind': 'patchThreadedComments', 'changes': [{'thread': {**old, 'replies': [reply]}}]}
    validate_xlsx_thread_actors(_source(), [operation], actor)
    with pytest.raises(ValueError, match='actor_required'):
        validate_xlsx_thread_actors(_source(), [operation], None)
    for key in ('author', 'personId'):
        forged = {'kind': operation['kind'], 'changes': [{'thread': {**old, 'replies': [{**reply, key: '伪造'}]}}]}
        with pytest.raises(ValueError, match='actor_mismatch'):
            validate_xlsx_thread_actors(_source(), [forged], actor)
