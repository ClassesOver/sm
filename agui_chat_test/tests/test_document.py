# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestAguiChatDocument(TransactionCase):

    def setUp(self):
        super(TestAguiChatDocument, self).setUp()
        self.env["agui.chat.tool.policy"].search([]).write({"active": False})
        self.env["agui.chat.tool.policy"].create({
            "name": "通用单据字段白名单测试",
            "tool_name": "odoo.patch_current_form",
            "access_level": "write",
            "model_name": "agui.chat.test.document",
            "field_names": "name",
            "confirmation_mode": "never",
        })
        self.standard = self.env.ref("agui_chat_test.option_standard_exact")
        self.special = self.env.ref("agui_chat_test.option_special_exact")

    def test_onchange_updates_hidden_domain_key(self):
        document = self.env["agui.chat.test.document"].new({
            "document_type": "standard",
        })
        document.document_type = "special"
        document._onchange_document_type()
        self.assertEqual(document.domain_key, "special")

    def test_amount_constraint_rolls_back_invalid_write(self):
        document = self.env["agui.chat.test.document"].create({
            "name": "约束测试",
            "required_code": "constraint-test",
            "amount": 10,
        })
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                document.write({"amount": -1})
        document.invalidate_cache(["amount"])
        self.assertEqual(document.amount, 10)

    def test_relation_candidates_are_separated_by_domain_key(self):
        standard_ids = self.env["agui.chat.test.option"].search([
            ("domain_key", "=", "standard"),
        ]).ids
        special_ids = self.env["agui.chat.test.option"].search([
            ("domain_key", "=", "special"),
        ]).ids
        self.assertIn(self.standard.id, standard_ids)
        self.assertNotIn(self.special.id, standard_ids)
        self.assertIn(self.special.id, special_ids)

    def test_test_policy_keeps_patch_field_allowlist(self):
        allowed = self.env["agui.chat.tool.policy"].evaluate(
            "odoo.patch_current_form",
            {
                "target": {"model": "agui.chat.test.document"},
                "patch": {"name": "允许字段"},
            },
        )
        denied = self.env["agui.chat.tool.policy"].evaluate(
            "odoo.patch_current_form",
            {
                "target": {"model": "agui.chat.test.document"},
                "patch": {"create_uid": 1},
            },
        )
        self.assertTrue(allowed["allowed"])
        self.assertFalse(denied["allowed"])

    def test_cleanup_removes_archived_session_and_tool_artifacts(self):
        config = self.env["agui.chat.config"].sudo().get_active_config()
        config.write({
            "chat_enabled": True,
            "host_tools_enabled": True,
            "write_tools_enabled": True,
            "enabled_commands": "odoo.patch_current_form",
        })
        session = self.env["agui.chat.session"].create_session()
        session.write({"active": False})
        attachment = self.env["ir.attachment"].create({
            "name": "agui-upload-test.txt",
            "datas": "dGVzdA==",
            "res_model": "agui.chat.session",
            "res_id": session.id,
        })
        decision = self.env["agui.chat.tool.authorization"].prepare_host_command({
            "id": "e2e-cleanup-call",
            "tool": "odoo.patch_current_form",
            "arguments": {
                "target": {
                    "snapshotId": "cleanup-snapshot",
                    "hostRevision": 1,
                    "controllerId": "cleanup-controller",
                    "dataPointId": "cleanup-record",
                    "model": "agui.chat.test.document",
                    "resId": False,
                },
                "patch": {"name": "清理测试"},
            },
            "context": {
                "requestId": "request-e2e-cleanup-call",
                "runId": "run-e2e-cleanup-call",
                "threadId": session.thread_id,
            },
        })
        authorization = self.env["agui.chat.tool.authorization"].search([
            ("token", "=", decision["authorization_id"]),
        ])
        audits = self.env["agui.chat.tool.audit"].search([
            ("authorization_id", "=", authorization.id),
        ])

        self.env["agui.chat.test.document"].cleanup_e2e(
            "agui_chat_test", [], [session.id]
        )

        self.assertFalse(session.exists())
        self.assertFalse(attachment.exists())
        self.assertFalse(authorization.exists())
        self.assertFalse(audits.exists())
