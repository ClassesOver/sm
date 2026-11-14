"""执行器摘要必须跟随实际桥接选择、部署覆盖目录和锁文件。"""

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.preference_evidence import executor_manifest


def engine(tmp_path, monkeypatch, name='slides', script='build-pptx', bundled=True):
    root = tmp_path / name
    (root / 'bridge').mkdir(parents=True)
    (root / 'bridge' / (script + '.ts')).write_text('source-v1')
    (root / 'package-lock.json').write_text('lock-v1')
    if bundled:
        (root / 'dist').mkdir()
        (root / 'dist' / (script + '.mjs')).write_text('bundle-v1')
    monkeypatch.setenv('AGENT_REPORTING_' + name.upper() + '_ENGINE_DIR', str(root))
    return root


def test_manifest_changes_when_actual_deployed_bundle_changes(tmp_path, monkeypatch):
    root = engine(tmp_path, monkeypatch)
    before = configuration_hash(executor_manifest())
    (root / 'dist/build-pptx.mjs').write_text('bundle-v2')
    assert configuration_hash(executor_manifest()) != before


def test_manifest_changes_when_bridge_source_or_lock_changes(tmp_path, monkeypatch):
    root = engine(tmp_path, monkeypatch, bundled=False)
    first = configuration_hash(executor_manifest())
    (root / 'bridge/build-pptx.ts').write_text('source-v2')
    second = configuration_hash(executor_manifest())
    assert first != second
    (root / 'package-lock.json').write_text('lock-v2')
    assert configuration_hash(executor_manifest()) != second


def test_manifest_binds_override_location_and_selected_entrypoint(tmp_path, monkeypatch):
    root = engine(tmp_path, monkeypatch)
    result = executor_manifest()
    entry = result['officeBridges']['slides']
    assert entry['root'] == str(root.resolve())
    assert entry['mode'] == 'bundle'
    assert entry['entrypoint']['path'] == 'dist/build-pptx.mjs'
    (root / 'dist/build-pptx.mjs').unlink()
    entry = executor_manifest()['officeBridges']['slides']
    assert entry['mode'] == 'source'
    assert entry['entrypoint']['path'] == 'bridge/build-pptx.ts'
    assert entry['entrypoint']['exists'] is True


def test_manifest_and_run_bridge_use_same_selected_entrypoint(tmp_path, monkeypatch):
    from smart_reporting.reporting.delivery import office_engine

    root = engine(tmp_path, monkeypatch)
    called = []
    with monkeypatch.context() as scoped:
        scoped.setattr(office_engine.subprocess, 'run', lambda command, **kwargs: called.append((command, kwargs)))
        office_engine.run_bridge('slides', 'build-pptx', tmp_path / 'request.json')
    selected = executor_manifest()['officeBridges']['slides']['entrypoint']['path']
    assert called[0][0][1] == str(root / selected)
    assert called[0][1]['cwd'] == root


def test_manifest_binds_actual_converter_selection_and_executable_bytes(tmp_path, monkeypatch):
    from smart_reporting.management import preference_executor as module

    converter = tmp_path / 'pandoc'
    converter.write_text('converter-v1')
    real = module.shutil.which
    monkeypatch.setattr(module.shutil, 'which', lambda name: str(converter) if name == 'pandoc' else real(name))
    first = executor_manifest()
    converter.write_text('converter-v2')
    second = executor_manifest()
    assert configuration_hash(first) != configuration_hash(second)
    assert second['converters']['word']['path'] == str(converter.resolve())
    other = tmp_path / 'pandoc-other'
    other.write_text('converter-v2')
    monkeypatch.setattr(module.shutil, 'which', lambda name: str(other) if name == 'pandoc' else real(name))
    assert configuration_hash(second) != configuration_hash(executor_manifest())


def test_manifest_binds_fontconfig_selected_font_bytes(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    font = tmp_path / 'selected-font.ttf'
    font.write_bytes(b'font-v1')
    real = subprocess.run
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs:
        SimpleNamespace(stdout=str(font), returncode=0) if command[0] == 'fc-match' else real(command, **kwargs))
    first = executor_manifest()
    font.write_bytes(b'font-v2')
    assert configuration_hash(first) != configuration_hash(executor_manifest())


def test_manifest_binds_pdf_wasm_override_bytes_and_location(tmp_path, monkeypatch):
    engine(tmp_path, monkeypatch, name='pdf', script='cli')
    directory = tmp_path / 'actual-wasm'
    directory.mkdir()
    for name in ('pdfium.wasm', 'hb-subset.wasm'):
        (directory / name).write_bytes(b'asset-v1')
    monkeypatch.setenv('AGENT_REPORTING_PDF_WASM_DIR', str(directory))
    first = executor_manifest()
    (directory / 'pdfium.wasm').write_bytes(b'asset-v2')
    assert configuration_hash(first) != configuration_hash(executor_manifest())
    monkeypatch.setenv('AGENT_REPORTING_PDF_WASM_DIR', str(tmp_path / 'missing-wasm'))
    changed = executor_manifest()
    assert configuration_hash(first) != configuration_hash(changed)
    assert changed['runtimeIdentityComplete'] is False
    assert changed['runtimeIdentityIssues']


def test_manifest_includes_source_imports_and_never_claims_unproven_runtime_complete(tmp_path, monkeypatch):
    root = engine(tmp_path, monkeypatch, name='pdf', script='cli', bundled=False)
    (root / 'src').mkdir()
    module = root / 'src' / 'actual-consumer.ts'
    module.write_text('consumer-v1')
    first = executor_manifest()
    module.write_text('consumer-v2')
    changed = executor_manifest()
    assert configuration_hash(first) != configuration_hash(changed)
    assert changed['runtimeIdentityComplete'] is False
    codes = {item['code'] for item in changed['runtimeIdentityIssues']}
    assert 'pdf_runtime_asset_missing' in codes


def test_manifest_pdf_asset_paths_match_native_source_selector():
    import json
    import subprocess

    from smart_reporting.management import preference_executor as module
    from smart_reporting.reporting.delivery.office_engine import engine_dir

    directory = engine_dir('pdf')
    native = subprocess.run(['node', '--import', 'tsx', '--input-type=module', '-e',
        "import {pdfiumWasmPath,hbSubsetWasmPath} from './src/main/wasm-path.ts';"
        "process.stdout.write(JSON.stringify({'pdfium.wasm':pdfiumWasmPath(),'hb-subset.wasm':hbSubsetWasmPath()}));"],
        cwd=directory, capture_output=True, text=True, check=True)
    declared = module._pdf_asset_identity(directory, directory / 'bridge/cli.ts')['files']
    assert {name: item['path'] for name, item in declared.items()} == json.loads(native.stdout)


def test_failed_native_asset_resolution_is_not_complete_even_if_fallback_files_exist(tmp_path, monkeypatch):
    import subprocess

    root = engine(tmp_path, monkeypatch, name='pdf', script='cli')
    (root / 'wasm').mkdir()
    for name in ('pdfium.wasm', 'hb-subset.wasm'):
        (root / 'wasm' / name).write_bytes(b'not-proven-selected')
    real = subprocess.run
    def fail_selector(command, **kwargs):
        if command[:2] == ['node', '-e']:
            raise subprocess.CalledProcessError(1, command)
        return real(command, **kwargs)
    monkeypatch.setattr(subprocess, 'run', fail_selector)
    manifest = executor_manifest()
    assert manifest['runtimeIdentityComplete'] is False
    assert any(item['code'] == 'pdf_runtime_asset_resolution_failed' for item in manifest['runtimeIdentityIssues'])


def test_manifest_binds_workspace_recovery_implementation():
    manifest = executor_manifest()
    identities = {item['path']: item for item in manifest['files']}
    identity = identities['smart_reporting/reporting/host_workspace.py']
    assert identity['exists'] is True
    from hashlib import sha256
    from pathlib import Path

    from smart_reporting.reporting import host_workspace

    assert identity['sha256'] == sha256(Path(host_workspace.__file__).read_bytes()).hexdigest()
