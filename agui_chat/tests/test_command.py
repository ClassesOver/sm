# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from ..models.agui_chat_config import HOST_COMMAND_NAMES


PAGE_COMMAND_XML_IDS = {
    "odoo.read_mentioned_records": "command_read_mentioned_records",
    "odoo.open_mentioned_menu": "command_open_mentioned_menu",
    "odoo.open_mentioned_record": "command_open_mentioned_record",
    "odoo.apply_mentioned_filter": "command_apply_mentioned_filter",
    "odoo.open_menu": "command_open_menu",
    "odoo.apply_filter": "command_apply_filter",
    "odoo.open_record": "command_open_record",
    "odoo.open_create": "command_open_create",
    "odoo.open_x2many_record": "command_open_x2many_record",
    "odoo.open_x2many_create": "command_open_x2many_create",
    "odoo.prepare_x2many_import": "command_prepare_x2many_import",
    "odoo.get_x2many_import_status": "command_get_x2many_import_status",
    "odoo.reload_current_form": "command_reload_current_form",
    "odoo.enter_edit_mode": "command_enter_edit_mode",
    "odoo.activate_view_control": "command_activate_view_control",
    "odoo.search_relation": "command_search_relation",
    "odoo.stage_current_form": "command_stage_current_form",
    "odoo.patch_current_form": "command_patch_current_form",
    "odoo.validate_current_form": "command_validate_current_form",
    "odoo.save_current_form": "command_save_current_form",
    "odoo.discard_current_form": "command_discard_current_form",
}


class TestAguiChatCommand(TransactionCase):

    def test_page_master_data_matches_host_catalog(self):
        commands = self.env["agui.chat.command"].with_context(active_test=False).search([
            ("command_type", "=", "page"),
        ])
        self.assertEqual(set(commands.mapped("code")), set(HOST_COMMAND_NAMES))
        self.assertEqual(set(PAGE_COMMAND_XML_IDS), set(HOST_COMMAND_NAMES))
        for code, xml_id in PAGE_COMMAND_XML_IDS.items():
            self.assertEqual(self.env.ref("agui_chat.%s" % xml_id).code, code)

    def test_command_code_is_unique(self):
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.env["agui.chat.command"].create({
                "name": "重复命令",
                "code": "odoo.open_menu",
                "command_type": "page",
            })

    def test_command_code_must_match_type(self):
        with self.assertRaises(ValidationError):
            self.env["agui.chat.command"].create({
                "name": "非法页面命令",
                "code": "odoo.unknown",
                "command_type": "page",
            })
        with self.assertRaises(ValidationError):
            self.env["agui.chat.command"].create({
                "name": "非法业务命令",
                "code": "custom.approve",
                "command_type": "business",
            })

    def test_legacy_strings_compute_command_tags(self):
        business = self.env["agui.chat.command"].create({
            "name": "测试审批",
            "code": "odoo.business.test.approve",
            "command_type": "business",
        })
        config = self.env["agui.chat.config"].create({
            "name": "旧配置",
            "enabled_commands": "odoo.open_record, odoo.open_menu",
            "enabled_business_commands": business.code,
        })
        self.assertEqual(
            set(config.enabled_command_ids.mapped("code")),
            {"odoo.open_menu", "odoo.open_record"},
        )
        self.assertEqual(config.enabled_business_command_ids, business)

    def test_command_tags_write_back_legacy_strings(self):
        page_commands = self.env["agui.chat.command"].search([
            ("code", "in", ["odoo.open_record", "odoo.open_menu"]),
        ])
        archive = self.env["agui.chat.command"].create({
            "name": "测试归档",
            "code": "odoo.business.test.archive",
            "command_type": "business",
            "sequence": 20,
        })
        approve = self.env["agui.chat.command"].create({
            "name": "测试审批",
            "code": "odoo.business.test.approve",
            "command_type": "business",
            "sequence": 10,
        })
        config = self.env["agui.chat.config"].create({"name": "标签配置"})
        config.write({
            "enabled_command_ids": [(6, 0, page_commands.ids)],
            "enabled_business_command_ids": [(6, 0, (archive | approve).ids)],
        })
        self.assertEqual(
            config.enabled_commands,
            "odoo.open_menu,odoo.open_record",
        )
        self.assertEqual(
            config.enabled_business_commands,
            "odoo.business.test.approve,odoo.business.test.archive",
        )

    def test_page_and_business_command_tags_cannot_mix(self):
        business = self.env["agui.chat.command"].create({
            "name": "测试审批",
            "code": "odoo.business.test.approve",
            "command_type": "business",
        })
        config = self.env["agui.chat.config"].create({"name": "隔离配置"})
        with self.assertRaises(ValidationError):
            config.write({"enabled_command_ids": [(6, 0, business.ids)]})
