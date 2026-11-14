"""模板正文图片只能来自本修订已登记且实际身份一致的资源。"""
from hashlib import sha256

import pytest


def image(path, raw=b'actual registered image'):
    return {'path': path, 'size': len(raw), 'sha256': sha256(raw).hexdigest()}


def test_template_image_binding_uses_registered_paths_and_preserves_source_keys():
    from smart_reporting.reporting.delivery.template_body_resources import bind_template_images

    registered = [image('reports/charts/one.png'), image('reports/第二图.png')]
    bindings, issues = bind_template_images(
        '![one](charts/one.png)\n\n![two](%E7%AC%AC%E4%BA%8C%E5%9B%BE.png)',
        'reports/body.md', registered)
    assert bindings == {'charts/one.png': registered[0], '%E7%AC%AC%E4%BA%8C%E5%9B%BE.png': registered[1]}
    assert not issues


@pytest.mark.parametrize('source', ['../private.png', '/private.png', 'https://host/private.png',
    'data:image/png;base64,AA', 'charts/one.png?secret=1', 'charts/one.png#fragment', 'unknown.png'])
def test_template_unregistered_or_unsafe_image_cannot_become_a_file_read(source):
    from smart_reporting.reporting.delivery.template_body_resources import bind_template_images

    bindings, issues = bind_template_images(f'![x]({source})', 'reports/body.md', [image('reports/charts/one.png')])
    assert not bindings
    assert issues and issues[0]['code'] == 'report_template_body_resource_unavailable'


def test_template_image_binding_rejects_conflicting_registered_identity_without_guessing():
    from smart_reporting.reporting.delivery.template_body_resources import bind_template_images

    bindings, issues = bind_template_images('![x](one.png)', 'reports/body.md',
        [image('reports/one.png'), image('reports/one.png', b'foreign')])
    assert not bindings and issues


@pytest.mark.parametrize('identity', [
    {'path': 'reports/one.png', 'size': 10 * 1024 * 1024 + 1, 'sha256': 'a' * 64},
    {'path': 'reports/one.csv', 'size': 10, 'sha256': 'a' * 64},
])
def test_template_image_binding_enforces_image_limits_before_resource_read(identity):
    from smart_reporting.reporting.delivery.template_body_resources import bind_template_images

    bindings, issues = bind_template_images(f'![x]({identity["path"].split("/")[-1]})', 'reports/body.md', [identity])
    assert not bindings and issues


def test_preflight_body_resources_read_actual_bytes_and_reject_drift(tmp_path):
    from smart_reporting.management.preference_template_preflight import template_body_resources

    raw = b'actual registered image'
    (tmp_path / 'reports').mkdir()
    (tmp_path / 'reports/one.png').write_bytes(raw)
    frozen = {'markdown': '![x](one.png)', 'markdownPath': 'reports/body.md',
        'state': {'sources': [image('reports/one.png', raw)]}}
    resources, issues = template_body_resources(tmp_path, frozen)
    assert resources == {'one.png': raw} and not issues
    (tmp_path / 'reports/one.png').write_bytes(b'changed')
    resources, issues = template_body_resources(tmp_path, frozen)
    assert resources == {} and issues[0]['code'] == 'report_template_body_resource_unavailable'


@pytest.mark.anyio
async def test_bound_template_snapshot_copies_manifest_images_without_dataset_slots(tmp_path, monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.tests.test_preference_template_preflight import template_case

    service, _, _, repository, context, root, _, _, _ = await template_case(tmp_path)
    chart = image('registered-chart.png', (root / 'chart.png').read_bytes())
    (root / chart['path']).write_bytes((root / 'chart.png').read_bytes())
    md = context.job['render']['markdown']
    manifest = SimpleNamespace(markdown=SimpleNamespace(model_dump=lambda **_: deepcopy(md)), trace_index=None,
        charts=(SimpleNamespace(model_dump=lambda **_: deepcopy(chart)),))
    monkeypatch.setattr(service.editor.trace, 'load_manifest', AsyncMock(return_value=manifest))
    destination = tmp_path / 'frozen-copy'
    materials, _, binding = await service._snapshot(context, repository.state, destination)
    assert materials.template_source['images'] == [chart]
    assert (destination / chart['path']).read_bytes() == (root / 'chart.png').read_bytes()
    assert chart in binding['identities']
    assert chart not in materials.state['sources']


def test_template_resource_identity_is_frozen_outside_dataset_list(tmp_path):
    from copy import deepcopy

    from smart_reporting.management.preference_preflight import _verify_materials
    from smart_reporting.tests.test_preference_template_preflight import direct_case

    _, materials, _ = direct_case(tmp_path)
    chart = image('separate.png', (tmp_path / 'chart.png').read_bytes())
    (tmp_path / chart['path']).write_bytes((tmp_path / 'chart.png').read_bytes())
    materials.template_source['images'] = [chart]
    before = deepcopy(materials.state['sources'])
    _, frozen, first_hash = _verify_materials(materials, formats=('word',))
    assert frozen['templateSource']['images'] == [chart]
    assert frozen['state']['sources'] == before
    (tmp_path / chart['path']).write_bytes(b'changed')
    from smart_reporting.management.models import ManagementError
    with pytest.raises(ManagementError):
        _verify_materials(materials, formats=('word',))
