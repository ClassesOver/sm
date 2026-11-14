"""旧版本底座/冻结测试的明确种子；不是正式批准或应用路径的验收证据。"""

from uuid import uuid4

from sqlalchemy import insert

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.repository import preference_approval_receipts


async def seed_preference_version(service, raw_session, expected_version):
    """仅向隔离测试库造版本；不调用或改变生产publish的批准边界。"""
    assert service.kind == 'preferences'
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, raw_session, service.auth.clock())
        draft = await service._draft(connection)
        service._expected(draft, expected_version)
        latest = await service._latest(connection)
        if latest:
            service._verified(latest['document'], latest['content_hash'])
            if latest['draft_version'] == draft['version']:
                return service._version_payload(latest)
        id = str(uuid4())
        document = {'schemaVersion': 1, 'testOnly': 'legacy_version_and_freeze_fixture',
            'status': 'fixture_seed_only', 'canApply': False,
            'draft': {'version': draft['version'], 'contentHash': draft['content_hash']}}
        await connection.execute(insert(preference_approval_receipts).values(id=id, document=document,
            content_hash=configuration_hash(document), created_at=service.auth.clock()))
        return await service._publish_in_transaction(connection, draft, latest, approval_id=id)
