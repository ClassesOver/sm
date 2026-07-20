# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron_data = env["ir.model.data"].search([
        ("module", "=", "agui_chat_import"),
        ("name", "=", "ir_cron_process_x2many_import_jobs"),
        ("model", "=", "ir.cron"),
    ], limit=1)
    if cron_data:
        env["ir.cron"].browse(cron_data.res_id).exists().unlink()
        cron_data.unlink()
    cr.execute(
        "UPDATE agui_chat_x2many_import_job "
        "SET state = 'preview', rows_json = '[]', mapping_json = '{}', "
        "parse_options_json = '{}', preview_rows_json = '[]', "
        "mapping_hash = NULL, revision = 0 "
        "WHERE state IN ('validating', 'queued')"
    )
    terminal_jobs = env["agui.chat.x2many.import.job"].sudo().search([
        ("state", "in", ["done", "failed"]),
    ])
    source_attachments = terminal_jobs.mapped("source_attachment_id")
    if terminal_jobs:
        terminal_jobs.write({
            "source_attachment_id": False,
            "rows_json": "[]",
            "preview_rows_json": "[]",
        })
    if source_attachments:
        source_attachments.unlink()
