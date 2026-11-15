from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.office import native_access
from smart_reporting.office.documents import OfficeDocuments
from smart_reporting.office.repository import Identity, OfficeRepository
from smart_reporting.reporting.models import ReportingError


@pytest.mark.asyncio
async def test_ai_sources_use_document_space_recheck_session_and_bound_output():
    from smart_reporting.office.ai_sources import attach_office_sources

    engine = create_async_engine('sqlite+aiosqlite://')
    office = OfficeRepository(engine)
    await office.create_schema()
    admin = Identity('db', '1', '10')
    await office.bootstrap(admin, 'Admin')
    space = (await office.spaces(admin))[0]['id']
    entry = await office.register_file(admin, space, None, 'A.docx', 'docx', 'doc', 1,
                                      {'database': 'db', 'companyId': '1'})
    raw = await office.create_session(admin)
    actor = await office.authenticate(raw)
    session = SimpleNamespace(report_id='doc', capabilities={'office': dict(
        database=actor.database, company=actor.company, user=actor.user,
        version=actor.session_version, session=actor.session_reference, file=entry['id'])})
    calls = []

    class Sources:
        async def available(self, user, workspace):
            assert workspace == space and user == actor
            return [{'id': 'sales', 'tables': ['sales.orders']}]

        async def query(self, user, workspace, source, sql):
            assert workspace == space and user == actor
            calls.append((source, sql))
            return {'columns': ['value'], 'rows': [[number] for number in range(300)],
                    'source': {'id': source, 'revision': 1, 'queryId': 'query'}}

    documents = OfficeDocuments(office, None, None, None)
    documents.sources = Sources()
    native_access.bind(session, documents.authorize)
    try:
        agent = SimpleNamespace(tools=[], instructions=[])
        attach_office_sources(agent)
        functions = {tool.__name__: tool for tool in agent.tools}
        assert (await functions['list_office_data_sources']())['items'][0]['id'] == 'sales'
        result = await functions['query_office_data_source']('sales', 'SELECT value FROM sales.orders')
        assert len(result['rows']) == 200 and result['truncated'] and result['totalRows'] == 300
        await office.logout(raw)
        with pytest.raises(ReportingError):
            await functions['query_office_data_source']('sales', 'SELECT value FROM sales.orders')
        assert len(calls) == 1
    finally:
        native_access.bind(SimpleNamespace(capabilities={}), None)
        await engine.dispose()
