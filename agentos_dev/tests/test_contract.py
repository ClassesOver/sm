import ast
import hashlib
import json
from pathlib import Path

from agentos_dev import app


def odoo_contract():
    source = Path("agui_chat/models/agui_chat_config.py").read_text(encoding="utf-8")
    values = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
    material = {
        "protocol": values["PROTOCOL"],
        "commands": values["HOST_COMMAND_NAMES"],
        "revision": values["COMMAND_CATALOG_REVISION"],
    }
    digest = hashlib.sha256(json.dumps(
        material, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")).hexdigest()
    return values, digest


def test_agentos_contract_matches_odoo_source():
    values, digest = odoo_contract()
    assert values["COMMAND_CATALOG_REVISION"] == 5
    assert digest == "03dc60812aad2fa725f65bbbf70bb2ae892ed5d0312319ae114fba6909d3cbea"
    assert app.PROTOCOL == values["PROTOCOL"]
    assert app.BUNDLE_VERSION == values["MODULE_VERSION"]
    assert app.COMMAND_CATALOG_HASH == digest
