import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.office.knowledge import KnowledgeTools, OfficeKnowledge
from smart_reporting.office.repository import Identity, OfficeError, OfficeRepository


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['none', 'attachment', 'foreign_attachment', 'unstar', 'logout', 'revision',
                                    'fabricated', 'uncited', 'insufficient', 'insufficient_with_citation'])
async def test_knowledge_answers_require_actual_reading_and_current_file_access(change):
    engine = create_async_engine('sqlite+aiosqlite://')
    office = OfficeRepository(engine)
    await office.create_schema()
    admin = Identity('db', '1', '10')
    await office.bootstrap(admin, 'Admin')
    space = (await office.spaces(admin))[0]['id']
    entry = await office.register_file(admin, space, None, 'Facts.docx', 'docx', 'doc', 1,
                                      {'database': 'db', 'companyId': '1'})
    if change not in {'attachment', 'foreign_attachment'}:
        await office.favorite(admin, entry['id'], True)
    attachment_ids = [entry['id']] if change == 'attachment' else []
    if change == 'foreign_attachment':
        team = await office.create_space(admin, 'Other workspace', admin.user)
        foreign = await office.register_file(admin, team['id'], None, 'Other.docx', 'docx', 'other', 1, {'database': 'db', 'companyId': '1'})
        attachment_ids = [foreign['id']]
    raw = await office.create_session(admin)
    actor = await office.authenticate(raw)

    class Documents:
        async def contents(self, identity, file):
            return await office.file(identity, file), b'Revenue: 42'

    async def planner(tools, question, history):
        assert not history and question == 'Revenue?'
        assert (await tools.list_knowledge_files())['items'][0]['id'] == entry['id']
        assert (await tools.search_knowledge_files('Revenue'))['items'][0]['fileId'] == entry['id']
        if change == 'fabricated':
            return {'answer': 'Invented', 'citations': [entry['id']]}
        read = await tools.read_knowledge_file(entry['id'])
        assert '42' in read['text'] and read['nextOffset'] is None
        if change == 'unstar':
            await office.favorite(admin, entry['id'], False)
        elif change == 'logout':
            await office.logout(raw)
        elif change == 'revision':
            await office.record_revision(admin, entry['id'], 'doc', 2)
        if change.startswith('insufficient'):
            return {'answer': 'Unsupported sensitive text', 'insufficientEvidence': True,
                    'citations': [read['citationId']] if change == 'insufficient_with_citation' else []}
        return {'answer': 'Revenue is 42.', 'citations': [] if change == 'uncited' else [read['citationId']]}

    service = OfficeKnowledge(office, Documents(), planner=planner,
                             parser=lambda content, format: {'text': content.decode(), 'limitations': []})
    try:
        if change in {'none', 'attachment'}:
            conversation = 'new-thread' if change == 'attachment' else 'default'
            answer = await service.ask(actor, space, 'Revenue?', attachment_ids=attachment_ids, conversation=conversation)
            if change == 'attachment':
                assert not (await office.library(actor, space))['files'][0]['starred']
                assert await office.knowledge_history(actor, space) == []
            assert answer['citations'] == [{'fileId': entry['id'], 'name': 'Facts.docx', 'revision': 1}]
            history = await office.knowledge_history(actor, space, conversation=conversation)
            assert history[0]['answer'] == 'Revenue is 42.'
            assert await office.knowledge_conversations(actor, space) == [{'id': conversation, 'title': 'Revenue?'}]
            await office.update_file(admin, entry['id'], expected_version=1, deleted=True)
            hidden = (await office.knowledge_history(actor, space, conversation=conversation))[0]
            assert '42' not in hidden['answer'] and hidden['citations'] == [] and hidden['sources'] == []
        elif change == 'insufficient':
            answer = await service.ask(actor, space, 'Revenue?')
            assert answer['citations'] == answer['sources'] == []
            assert '资料不足' in answer['answer'] and 'Unsupported' not in answer['answer']
            assert (await office.knowledge_history(actor, space))[0]['answer'] == answer['answer']
        else:
            with pytest.raises(OfficeError):
                await service.ask(actor, space, 'Revenue?', attachment_ids=attachment_ids)
            assert await office.knowledge_history(admin, space) == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_cannot_read_another_users_personal_file():
    engine = create_async_engine('sqlite+aiosqlite://')
    office = OfficeRepository(engine)
    await office.create_schema()
    admin = Identity('db', '1', '10')
    await office.bootstrap(admin, 'Admin')
    await office.provision(admin, '20', 'User')
    user = Identity('db', '1', '20')
    own = (await office.spaces(admin))[0]['id']
    private = (await office.spaces(user))[0]['id']
    file = await office.register_file(user, private, None, 'Private.pdf', 'pdf', 'private', 1,
                                     {'database': 'db', 'companyId': '1'})
    await office.favorite(user, file['id'], True)
    tools = KnowledgeTools(office, None, admin, own)
    try:
        assert (await tools.list_knowledge_files())['items'] == []
        with pytest.raises(OfficeError):
            await tools.read_knowledge_file(file['id'])
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', ['search_revoked', 'history_inherited', 'history_revoked', 'history_unstarred', 'history_moved'])
async def test_search_snippets_and_history_keep_all_exposed_source_authority(scenario):
    engine = create_async_engine('sqlite+aiosqlite://')
    office = OfficeRepository(engine)
    await office.create_schema()
    actor = Identity('db', '1', '10')
    await office.bootstrap(actor, 'Admin')
    space = (await office.spaces(actor))[0]['id']
    scope = {'database': 'db', 'companyId': '1'}
    a = await office.register_file(actor, space, None, 'A.docx', 'docx', 'A', 1, scope)
    b = await office.register_file(actor, space, None, 'B.docx', 'docx', 'B', 1, scope)
    for entry in (a, b):
        await office.favorite(actor, entry['id'], True)

    class Documents:
        async def contents(self, user, file):
            return await office.file(user, file), b'secret-from-A' if file == a['id'] else b'public-B'

    async def planner(tools, question, history):
        if question == 'first':
            await tools.read_knowledge_file(a['id'])
            return {'answer': 'secret-from-A', 'citations': [a['id']]}
        if scenario == 'search_revoked':
            assert 'secret-from-A' in (await tools.search_knowledge_files('secret'))['items'][0]['snippet']
            await tools.read_knowledge_file(b['id'])
            await office.update_file(actor, a['id'], expected_version=1, deleted=True)
        else:
            assert ('secret-from-A' in history[0]['answer']) is (scenario == 'history_inherited')
            await tools.read_knowledge_file(b['id'])
        return {'answer': 'public-B' if scenario in {'history_revoked', 'history_unstarred', 'history_moved'} else 'secret-from-A', 'citations': [b['id']]}

    service = OfficeKnowledge(office, Documents(), planner=planner,
        parser=lambda content, format: {'text': content.decode(), 'limitations': []})
    try:
        if scenario == 'search_revoked':
            with pytest.raises(OfficeError):
                await service.ask(actor, space, 'second')
            assert await office.knowledge_history(actor, space) == []
        else:
            await service.ask(actor, space, 'first')
            if scenario == 'history_revoked':
                await office.update_file(actor, a['id'], expected_version=1, deleted=True)
            if scenario == 'history_unstarred':
                await office.favorite(actor, a['id'], False)
            if scenario == 'history_moved':
                target = (await office.create_space(actor, 'Another team', actor.user))['id']
                await office.update_file(actor, a['id'], expected_version=1, space=target)
            if scenario in {'history_revoked', 'history_unstarred', 'history_moved'}:
                assert 'secret-from-A' not in (await office.knowledge_history(actor, space))[0]['answer']
            answer = await service.ask(actor, space, 'second')
            if scenario == 'history_inherited':
                assert {source['fileId'] for source in answer['sources']} == {a['id'], b['id']}
                await office.update_file(actor, a['id'], expected_version=1, deleted=True)
                assert all('secret-from-A' not in turn['answer'] for turn in await office.knowledge_history(actor, space))
            else:
                assert {source['fileId'] for source in answer['sources']} == {b['id']}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_uses_provider_structured_output_policy_without_dropping_tools(monkeypatch):
    from agno.models.openai import OpenAIChat
    from smart_reporting.reporting import agent_events

    async def run(agent, _prompt, **_kwargs):
        assert agent.use_json_mode is True
        assert agent.structured_outputs is False
        assert {tool.__name__ for tool in agent.tools} == {
            "list_knowledge_files", "search_knowledge_files", "read_knowledge_file",
        }
        return type("Result", (), {"content": '{"answer":"42","citations":["file"]}'})()

    monkeypatch.setattr(agent_events, "run_agent_with_events", run)
    model = OpenAIChat(id="deepseek-v4.1-flash", api_key="test",
                       base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    tools = KnowledgeTools(None, None, Identity("db", "1", "10"), "space", parser=None)
    assert await OfficeKnowledge(None, None, model).plan(tools, "Test", []) == {
        "answer": "42", "citations": ["file"],
    }


@pytest.mark.asyncio
async def test_delete_knowledge_conversation_preserves_other_users_and_rejects_late_save():
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        owner, peer = Identity('db', '1', '10'), Identity('db', '1', '20')
        await office.bootstrap(owner, 'Owner')
        await office.provision(owner, peer.user, 'Peer')
        space = (await office.create_space(owner, 'Team', owner.user))['id']
        await office.set_member(owner, space, peer.user, 'viewer')
        for actor, conversation in [(owner, 'old'), (owner, 'keep'), (peer, 'old')]:
            await office.save_knowledge_turn(actor, space, 'Question', 'Answer', [], [], conversation=conversation)
        await office.delete_knowledge_conversation(owner, space, 'old')
        await office.delete_knowledge_conversation(owner, space, 'old')
        assert await office.knowledge_history(owner, space, conversation='old') == []
        assert len(await office.knowledge_history(peer, space, conversation='old')) == 1
        assert len(await office.knowledge_history(owner, space, conversation='keep')) == 1
        with pytest.raises(OfficeError) as deleted:
            await office.save_knowledge_turn(owner, space, 'Late question', 'Answer', [], [], conversation='old')
        assert deleted.value.code == 'office_knowledge_conversation_deleted'
    finally:
        await engine.dispose()
