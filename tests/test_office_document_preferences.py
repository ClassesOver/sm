from copy import deepcopy

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.office.api import COOKIE, create_office_router, csrf_token
from smart_reporting.office.repository import Identity, OfficeRepository


@pytest.mark.asyncio
async def test_document_preferences_are_personal_versioned_and_exclude_md_exports():
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        admin = Identity('db', '1', 'admin')
        await office.bootstrap(admin, 'Admin')
        for name in ('alice', 'bob'):
            await office.provision(admin, name, name.title())
        foreign = Identity('db', '2', 'alice')
        await office.bootstrap(foreign, 'Other Alice')
        app = FastAPI(); app.include_router(create_office_router(office, public_origin='http://test'))
        path = '/office/api/settings/document-preferences'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            assert (await client.get(path)).status_code == 401
            raw = await office.create_session(Identity('db', '1', 'alice'))
            client.cookies.set(COOKIE, raw)
            headers = {'origin': 'http://test', 'x-csrf-token': csrf_token(raw)}
            response = await client.get(path)
            assert response.status_code == 200, response.text
            initial = response.json()
            assert initial['version'] == 0
            assert set(initial['document']) == {'common', 'word', 'xlsx', 'pptx', 'pdf'}
            assert initial['document']['common']['signer'] == 'Alice'
            changed = deepcopy(initial['document']); changed['word']['typography']['body']['size'] = 14
            body = {'document': changed, 'expectedVersion': 0}
            assert (await client.put(path, json=body)).status_code == 403
            saved = await client.put(path, json=body, headers=headers)
            assert saved.status_code == 200, saved.text
            assert saved.json()['version'] == 1
            assert (await client.put(path, json=body, headers=headers)).status_code == 409
            assert (await client.get('/office/api/settings')).json()['version'] == 0
            for section, field, value in [(None, 'md', {}), ('word', 'cover', True), ('pdf', 'imageQuality', 90), ('xlsx', 'print', {'scalePercent': 50})]:
                invalid = deepcopy(changed)
                (invalid if section is None else invalid[section])[field] = value
                result = await client.put(path, json={'document': invalid, 'expectedVersion': 1}, headers=headers)
                assert result.status_code == 422, result.text
            assert (await client.put(path, json={**body, 'user': 'bob'}, headers=headers)).status_code == 422
            for actor in (Identity('db', '1', 'bob'), foreign):
                client.cookies.set(COOKIE, await office.create_session(actor))
                other = (await client.get(path)).json()
                assert other['version'] == 0 and other['document']['word']['typography']['body']['size'] == 11
            client.cookies.set(COOKIE, raw)
            assert (await client.get(path)).json()['document']['word']['typography']['body']['size'] == 14
            await office.logout(raw)
            assert (await client.get(path)).status_code == 401
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_agent_preferences_are_optional_and_scoped():
    from types import SimpleNamespace
    from smart_reporting.office.document_preferences import OfficeDocumentPreferences
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine); await office.create_schema()
        alice = Identity('db', '1', 'alice'); await office.bootstrap(alice, 'Alice')
        await office.provision(alice, 'bob', 'Bob')
        service = OfficeDocumentPreferences(office)
        agent = SimpleNamespace(instructions='Original rules')
        await service.attach(agent, alice)
        assert agent.instructions == 'Original rules'
        from smart_reporting.office.document_preferences import DocumentPreferencesInput
        value = await service.read(alice)
        await service.save(alice, DocumentPreferencesInput.model_validate({'document': value['document'], 'expectedVersion': 0}))
        await service.attach(agent, alice)
        assert agent.instructions[0] == 'Original rules'
        assert 'Alice' in agent.instructions[-1] and '低优先级' in agent.instructions[-1]
        other = SimpleNamespace(instructions=[])
        await service.attach(other, Identity('db', '1', 'bob'))
        assert other.instructions == []
    finally:
        await engine.dispose()

def test_page_preferences_reject_header_beyond_margin():
    from pydantic import ValidationError
    from smart_reporting.office.document_preferences import DocumentPreferences
    with pytest.raises(ValidationError, match='页边距'):
        DocumentPreferences.model_validate({'common': {'signer': 'Alice'}, 'word': {
            'page': {'margins': {'top': 5}}, 'headerFooter': {'enabled': True, 'headerDistance': 10}}})
