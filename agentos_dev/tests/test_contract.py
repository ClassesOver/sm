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
    assert values["COMMAND_CATALOG_REVISION"] == 8
    assert digest == "66999dc4e1f22d94cf04b9fda3463c99538f00f86150204d4d0dea5d73c8cb60"
    assert app.PROTOCOL == values["PROTOCOL"]
    assert app.BUNDLE_VERSION == values["MODULE_VERSION"]
    assert app.COMMAND_CATALOG_HASH == digest


def test_agent_instructions_enforce_staged_odoo_workflow():
    instructions = "\n".join(app.assistant.instructions)

    assert "能力发现 → odoo.stage_current_form 暂存依赖标量" in instructions
    assert "等待 onchange 新快照 → odoo.search_relation" in instructions
    assert "odoo.validate_current_form" in instructions
    assert "独立确认后 odoo.save_current_form" in instructions
