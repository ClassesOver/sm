import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.office.repository import Identity, OfficeError, OfficeRepository


@pytest.mark.asyncio
async def test_bulk_files_are_atomic_and_bound_to_writer_and_workspace():
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        owner, viewer = Identity('db', '1', 'owner'), Identity('db', '1', 'viewer')
        await office.bootstrap(owner, 'Owner')
        await office.provision(owner, viewer.user, 'Viewer')
        space = (await office.create_space(owner, 'Team', owner.user))['id']
        other_space = next(item['id'] for item in await office.spaces(owner) if item['personal_user'] == owner.user)
        await office.set_member(owner, space, viewer.user, 'viewer')
        scope = {'database': 'db', 'companyId': '1'}
        first = await office.register_file(owner, space, None, 'One.docx', 'docx', 'one', 1, scope)
        second = await office.register_file(owner, space, None, 'Two.pdf', 'pdf', 'two', 1, scope)
        third = await office.register_file(owner, other_space, None, 'Three.xlsx', 'xlsx', 'three', 1, scope)
        selected = {first['id']: 1, second['id']: 1}
        assert await office.bulk_files(viewer, space, selected, 'star') == {'count': 2}
        assert all(item['starred'] for item in (await office.library(viewer, space))['files'])
        assert not any(item['starred'] for item in (await office.library(owner, space))['files'])
        await office.bulk_files(viewer, space, selected, 'unstar')
        assert not any(item['starred'] for item in (await office.library(viewer, space))['files'])
        with pytest.raises(OfficeError):
            await office.bulk_files(viewer, space, selected, 'delete')
        with pytest.raises(OfficeError, match='文件已变化'):
            await office.bulk_files(owner, space, {**selected, third['id']: 1}, 'delete')
        await office.update_file(owner, second['id'], expected_version=1, name='Renamed.pdf')
        with pytest.raises(OfficeError, match='文件已变化'):
            await office.bulk_files(owner, space, selected, 'delete')
        assert len((await office.library(owner, space))['files']) == 2
        assert await office.bulk_files(owner, space, {first['id']: 1, second['id']: 2}, 'delete') == {'count': 2}
        assert (await office.library(owner, space))['files'] == []
        assert (await office.file(owner, third['id']))['name'] == 'Three.xlsx'
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_hiding_recent_file_is_personal_and_reopening_restores_it():
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine, clock=lambda: 123456)
        await office.create_schema()
        owner, viewer = Identity('db', '1', 'owner'), Identity('db', '1', 'viewer')
        await office.bootstrap(owner, 'Owner')
        await office.provision(owner, viewer.user, 'Viewer')
        space = (await office.create_space(owner, 'Team', owner.user))['id']
        await office.set_member(owner, space, viewer.user, 'viewer')
        entry = await office.register_file(owner, space, None, 'One.docx', 'docx', 'one', 1,
                                           {'database': 'db', 'companyId': '1'})
        assert not (await office.library(viewer, space))['files'][0]['recentHidden']
        await office.favorite(viewer, entry['id'], True)
        await office.bulk_files(viewer, space, {entry['id']: 1}, 'hide_recent')
        hidden = (await office.library(viewer, space))['files'][0]
        assert hidden['starred'] and hidden['recentHidden'] and hidden['seen'] == 0
        assert not (await office.library(owner, space))['files'][0]['recentHidden']
        assert (await office.file(viewer, entry['id']))['revision'] == 1
        await office.touch(viewer, entry['id'])
        reopened = (await office.library(viewer, space))['files'][0]
        assert reopened['starred'] and not reopened['recentHidden'] and reopened['seen'] == 123456000
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_bulk_move_requires_both_spaces_and_preserves_native_identity():
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        owner, editor = Identity('db', '1', 'owner'), Identity('db', '1', 'editor')
        await office.bootstrap(owner, 'Owner')
        await office.provision(owner, editor.user, 'Editor')
        source = (await office.create_space(owner, 'Source', owner.user))['id']
        destination = (await office.create_space(owner, 'Destination', owner.user))['id']
        await office.set_member(owner, source, editor.user, 'editor')
        folder = await office.create_folder(owner, destination, None, 'Target')
        foreign = await office.create_folder(owner, source, None, 'Foreign')
        scope = {'database': 'db', 'companyId': '1'}
        first = await office.register_file(owner, source, None, 'One.docx', 'docx', 'one', 1, scope)
        second = await office.register_file(owner, source, None, 'Two.pdf', 'pdf', 'two', 2, scope)
        selection = {first['id']: 1, second['id']: 1}
        with pytest.raises(OfficeError):
            await office.bulk_files(editor, source, selection, 'move', destination=destination, folder=folder['id'])
        await office.set_member(owner, destination, editor.user, 'editor')
        with pytest.raises(OfficeError):
            await office.bulk_files(editor, source, selection, 'move', destination=destination, folder=foreign['id'])
        await office.update_file(owner, second['id'], expected_version=1, name='Renamed.pdf')
        with pytest.raises(OfficeError):
            await office.bulk_files(editor, source, selection, 'move', destination=destination, folder=folder['id'])
        assert len((await office.library(editor, source))['files']) == 2
        assert (await office.library(editor, destination))['files'] == []
        selection[second['id']] = 2
        assert await office.bulk_files(editor, source, selection, 'move', destination=destination, folder=folder['id']) == {'count': 2}
        assert (await office.library(editor, source))['files'] == []
        moved = {item['id']: item for item in (await office.library(editor, destination))['files']}
        assert set(moved) == set(selection)
        for entry in (first, second):
            result = moved[entry['id']]
            assert (result['document'], result['revision'], result['folder'], result['version']) == (
                entry['document'], entry['revision'], folder['id'], selection[entry['id']] + 1)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_moves_recheck_both_spaces_and_folder_delete_stays_in_space():
    engine = create_async_engine('sqlite+aiosqlite://')
    office = OfficeRepository(engine)
    await office.create_schema()
    owner = Identity('db', '1', '10')
    reader = Identity('db', '1', '20')
    await office.bootstrap(owner, 'Owner')
    await office.provision(owner, '20', 'Reader')
    source = (await office.create_space(owner, 'Source', '10'))['id']
    target = (await office.create_space(owner, 'Target', '10'))['id']
    await office.set_member(owner, source, '20', 'editor')
    folder = await office.create_folder(owner, source, None, 'Parent')
    child = await office.create_folder(owner, source, folder['id'], 'Child')
    scope = {'database': 'db', 'companyId': '1'}
    moved = await office.register_file(owner, source, child['id'], 'Move.docx', 'docx', 'move', 1, scope)
    deleted = await office.register_file(owner, source, child['id'], 'Delete.pdf', 'pdf', 'delete', 1, scope)
    other = await office.register_file(owner, target, None, 'Keep.xlsx', 'xlsx', 'keep', 1, scope)
    try:
        with pytest.raises(OfficeError):
            await office.update_file(reader, moved['id'], expected_version=1, space=target)
        await office.update_file(owner, moved['id'], expected_version=1, space=target)
        assert (await office.file(owner, moved['id']))['folder'] is None
        with pytest.raises(OfficeError):
            await office.file(reader, moved['id'])
        with pytest.raises(OfficeError):
            await office.delete_folder(owner, target, folder['id'])
        removed = await office.delete_folder(owner, source, folder['id'])
        assert removed == {'folders': 2, 'files': 1}
        assert (await office.library(owner, source)) == {'folders': [], 'files': []}
        with pytest.raises(OfficeError):
            await office.file(owner, deleted['id'])
        assert (await office.file(owner, other['id']))['name'] == 'Keep.xlsx'
        assert (await office.file(owner, moved['id']))['space'] == target
        await office.update_space(owner, target, archived=True)
        with pytest.raises(OfficeError):
            await office.update_file(owner, moved['id'], expected_version=2, name='Changed.docx')
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_office_copy_names_are_unique_and_version_bound():
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        actor = Identity('db', '1', 'owner')
        await office.bootstrap(actor, 'Owner')
        space = (await office.spaces(actor))[0]['id']
        folder = await office.create_folder(actor, space, None, 'Parent')
        scope = {'database': 'db', 'companyId': '1'}
        source = await office.register_file(actor, space, folder['id'], 'Source.docx', 'docx', 'source', 2, scope)

        async def register(document, version=1):
            return await office.register_file(actor, space, folder['id'], source['name'], 'docx', document, 1,
                                              scope, copy_source=(source['id'], version))

        first = await register('copy-1')
        assert (await register('copy-1'))['id'] == first['id']
        second = await register('copy-2')
        assert [first['name'], second['name']] == ['Source 副本.docx', 'Source 副本 2.docx']
        assert first['revision'] == second['revision'] == 1
        assert len({source['id'], first['id'], second['id']}) == 3
        await office.update_file(actor, source['id'], expected_version=1, name='Renamed.docx')
        with pytest.raises(OfficeError, match='源文件已变化'):
            await register('copy-3')
        restored = await office.file(actor, source['id'])
        assert restored['revision'] == 2 and restored['document'] == 'source'
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_report_archive_retry_respects_current_file_location_and_deletion():
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        owner = Identity('db', '1', '10')
        admin = Identity('db', '1', '20')
        await office.bootstrap(admin, 'Admin')
        await office.provision(admin, owner.user, 'Publisher')
        personal = (await office.spaces(owner))[0]['id']
        team = (await office.create_space(admin, 'Team', admin.user))['id']
        await office.set_member(admin, team, owner.user, 'editor')
        scope = {'database': 'db', 'companyId': '1', 'userId': owner.user}

        async def archive():
            return await office.register_file(
                owner, personal, None, 'Report.docx', 'docx', 'report', 1,
                scope, follow_existing=True,
            )

        file = await archive()
        assert (await archive())['id'] == file['id']
        await office.update_file(owner, file['id'], expected_version=1, space=team)
        assert (await archive())['space'] == team
        await office.set_member(admin, team, owner.user, None)
        with pytest.raises(OfficeError):
            await archive()
        await office.set_member(admin, team, owner.user, 'editor')
        await office.update_file(owner, file['id'], expected_version=2, deleted=True)
        with pytest.raises(OfficeError):
            await archive()
        assert await office.owns_document('report')
        assert (await office.library(owner, personal))['files'] == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_favorite_groups_are_personal_and_only_change_current_starred_files():
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        owner, viewer = Identity('db', '1', 'owner'), Identity('db', '1', 'viewer')
        await office.bootstrap(owner, 'Owner')
        await office.provision(owner, viewer.user, 'Viewer')
        space = (await office.create_space(owner, 'Team', owner.user))['id']
        await office.set_member(owner, space, viewer.user, 'viewer')
        scope = {'database': 'db', 'companyId': '1'}
        first = await office.register_file(owner, space, None, 'One.docx', 'docx', 'one', 1, scope)
        second = await office.register_file(owner, space, None, 'Two.pdf', 'pdf', 'two', 1, scope)
        await office.favorite(viewer, first['id'], True)
        selected = {first['id']: 1, second['id']: 1}
        with pytest.raises(OfficeError) as unstarred:
            await office.bulk_files(viewer, space, selected, 'group', group='客户')
        assert unstarred.value.status == 409
        assert all(item['favoriteGroup'] is None for item in (await office.library(viewer, space))['files'])

        await office.favorite(viewer, second['id'], True)
        assert await office.bulk_files(viewer, space, selected, 'group', group=' 客户 ') == {'count': 2}
        assert {item['favoriteGroup'] for item in (await office.library(viewer, space))['files']} == {'客户'}
        assert all(item['favoriteGroup'] is None for item in (await office.library(owner, space))['files'])
        await office.bulk_files(viewer, space, {first['id']: 1}, 'group', group=None)
        await office.favorite(viewer, second['id'], False)
        await office.favorite(viewer, second['id'], True)
        assert all(item['favoriteGroup'] is None for item in (await office.library(viewer, space))['files'])
    finally:
        await engine.dispose()
