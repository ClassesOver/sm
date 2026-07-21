# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


REMOVED_PAGE_COMMANDS = {
    "odoo.read_mentioned_records",
    "odoo.open_mentioned_menu",
    "odoo.open_mentioned_record",
    "odoo.apply_mentioned_filter",
    "odoo.prepare_x2many_import",
    "odoo.get_x2many_import_status",
}

REMOVED_XML_IDS = {
    "access_agui_chat_mention_token_user",
    "command_apply_mentioned_filter",
    "command_get_x2many_import_status",
    "command_open_mentioned_menu",
    "command_open_mentioned_record",
    "command_prepare_x2many_import",
    "command_read_mentioned_records",
    "policy_get_x2many_import_status",
    "policy_prepare_x2many_import",
    "rule_agui_chat_mention_token_user",
}


def _unlink_xml_records(env, xml_names):
    records = env["ir.model.data"].search([
        ("module", "=", "agui_chat"),
        ("name", "in", list(xml_names)),
    ])
    for data in records:
        if data.model in env:
            env[data.model].browse(data.res_id).exists().unlink()
        data.unlink()


def _remove_disabled_command_names(cr):
    cr.execute(
        "SELECT id, enabled_commands FROM agui_chat_config "
        "WHERE enabled_commands IS NOT NULL"
    )
    for config_id, value in cr.fetchall():
        configured = [name.strip() for name in value.split(",") if name.strip()]
        enabled = [name for name in configured if name not in REMOVED_PAGE_COMMANDS]
        if enabled != configured:
            cr.execute(
                "UPDATE agui_chat_config SET enabled_commands = %s WHERE id = %s",
                (",".join(enabled), config_id),
            )


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _remove_disabled_command_names(cr)

    policies = env["agui.chat.tool.policy"].with_context(active_test=False).search([
        ("tool_name", "in", list(REMOVED_PAGE_COMMANDS)),
    ])
    policies.unlink()
    commands = env["agui.chat.command"].with_context(active_test=False).search([
        ("code", "in", list(REMOVED_PAGE_COMMANDS)),
    ])
    commands.unlink()
    _unlink_xml_records(env, REMOVED_XML_IDS)

    cr.execute(
        "ALTER TABLE agui_chat_config "
        "DROP COLUMN IF EXISTS mention_model_id"
    )
    cr.execute("DROP TABLE IF EXISTS agui_chat_mention_token CASCADE")
    mention_model = env["ir.model"].search([
        ("model", "=", "agui.chat.mention.token"),
    ])
    if mention_model:
        mention_model.with_context(_force_unlink=True).unlink()
    env["ir.model.data"].search([
        ("module", "=", "agui_chat"),
        ("name", "=", "model_agui_chat_mention_token"),
    ]).unlink()

    env["agui.chat.session"]._archive_for_protocol_upgrade()
