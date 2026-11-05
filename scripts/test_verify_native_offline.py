"""Fail-closed checks for the standalone acceptance script, not engine behavior."""
import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).with_name('verify_native_offline.py')
_SPEC = importlib.util.spec_from_file_location('verify_native_offline', _SCRIPT)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_real_nonisolated_host_is_rejected_and_stale_success_is_replaced(tmp_path):
    if sorted(name for _, name in socket.if_nameindex()) == ['lo']:
        pytest.skip('This host is already isolated; run the positive container probe instead')
    report = tmp_path / 'evidence.json'
    report.write_text('{"ok": true, "stale": true}')
    result = subprocess.run([sys.executable, str(_SCRIPT), '--provenance', 'mounted-runtime-probe',
                             '--output-dir', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1
    failure = json.loads(result.stdout)
    assert failure['ok'] is False
    assert 'network_isolation_not_established' in failure['issue']
    assert json.loads(report.read_text()) == failure


def test_missing_shipped_entry_asset_cannot_pass_static_acceptance(tmp_path):
    (tmp_path / 'index.html').write_text('<script src="/reports/v1/editor/assets/missing.js"></script>')
    with pytest.raises(RuntimeError, match='static_asset_missing:'):
        _MODULE.verify_static(tmp_path)
