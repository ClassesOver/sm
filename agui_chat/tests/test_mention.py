# -*- coding: utf-8 -*-
import json
from datetime import timedelta

from odoo import api, fields
from odoo.tests.common import TransactionCase

from ..models.agui_chat_mention import MentionTokenError


class TestMentionReferences(TransactionCase):

    def setUp(self):
        super(TestMentionReferences, self).setUp()
        self.session_key = "test-session"
        self.env["agui.chat.config"].sudo().get_active_config().write({
            "chat_enabled": True,
            "host_tools_enabled": True,
            "enabled_commands": ",".join([
                "odoo.read_mentioned_records", "odoo.open_mentioned_menu",
                "odoo.open_mentioned_record", "odoo.apply_mentioned_filter",
            ]),
        })
        self.action = self.env["ir.actions.act_window"].create({
            "name": "引用测试联系人",
            "res_model": "res.partner",
            "view_mode": "tree,form",
        })
        self.root_menu = self.env["ir.ui.menu"].create({"name": "引用测试"})
        self.menu = self.env["ir.ui.menu"].create({
            "name": "联系人",
            "parent_id": self.root_menu.id,
            "action": "ir.actions.act_window,%s" % self.action.id,
        })
        self.env["ir.ui.menu"].clear_caches()
        self.partner = self.env["res.partner"].create({
            "name": "引用测试客户甲",
            "email": "private@example.com",
            "comment": "<p>公开备注</p>",
        })
        self.tokens = self.env["agui.chat.mention.token"]

    def _search(self, query="引用测试客户甲", scope="record", current_filter=None):
        return self.tokens.search_mentions(
            query, scope, False, "res.partner", [], current_filter, self.session_key,
        )

    def _candidate(self, result, kind):
        return next(item for item in result["candidates"] if item["kind"] == kind)

    def test_visible_menu_record_search_and_global_budgets(self):
        menu = self._candidate(self._search("联系人", "menu"), "menu")
        record = self._candidate(self._search(), "record")

        self.assertEqual(menu["model"], "res.partner")
        self.assertIn("open", menu["actions"])
        self.assertEqual(record["label"], self.partner.display_name)
        self.assertNotIn("record_id", record)
        result = self._search("引用", "all")
        self.assertLessEqual(len(result["candidates"]), 20)
        self.assertLessEqual(len(result["modelScopes"]), 20)

    def test_token_is_bound_to_user_company_session_and_exact_action(self):
        candidate = self._candidate(self._search(), "record")
        reference = self.tokens.bind_mention(
            candidate["candidateToken"], "read", self.session_key,
        )
        arguments, _audit = self.tokens.resolve_tool_arguments(
            "odoo.read_mentioned_records", {"tokens": [reference["token"]]},
            self.session_key,
        )
        self.assertEqual(arguments["__mention"][0]["record_id"], self.partner.id)

        with self.assertRaises(MentionTokenError):
            self.tokens.resolve_tool_arguments(
                "odoo.open_mentioned_record", {"token": reference["token"]},
                self.session_key,
            )
        with self.assertRaises(MentionTokenError):
            self.tokens.resolve_tool_arguments(
                "odoo.read_mentioned_records", {"tokens": [reference["token"]]},
                "other-session",
            )

        other = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "引用测试用户",
            "login": "mention-test-user",
            "email": "mention-test-user@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            "company_id": self.env.user.company_id.id,
            "company_ids": [(6, 0, [self.env.user.company_id.id])],
        })
        other_env = api.Environment(self.env.cr, other.id, dict(self.env.context))
        with self.assertRaises(MentionTokenError):
            other_env["agui.chat.mention.token"].resolve_tool_arguments(
                "odoo.read_mentioned_records", {"tokens": [reference["token"]]},
                self.session_key,
            )

    def test_expired_candidate_and_bound_token_fail_closed(self):
        candidate = self._candidate(self._search(), "record")
        record = self.tokens.search([("token", "=", candidate["candidateToken"])])
        record.sudo().write({
            "expires_at": fields.Datetime.to_string(
                fields.Datetime.from_string(fields.Datetime.now()) - timedelta(seconds=1)
            )
        })
        with self.assertRaises(MentionTokenError) as caught:
            self.tokens.bind_mention(candidate["candidateToken"], "read", self.session_key)
        self.assertEqual(caught.exception.code, "mention_token_expired")

    def test_authorization_accepts_only_tokens_selected_in_the_current_run(self):
        candidate = self._candidate(self._search(), "record")
        reference = self.tokens.bind_mention(
            candidate["candidateToken"], "read", self.session_key,
        )
        authorizations = self.env["agui.chat.tool.authorization"].with_context(
            agui_session_key=self.session_key
        )
        call = {
            "id": "mention-read-call",
            "tool": "odoo.read_mentioned_records",
            "arguments": {
                "target": {"snapshotId": "page-1", "hostRevision": 1},
                "tokens": [reference["token"]],
            },
            "context": {
                "requestId": "request-mention-read",
                "runId": "run-mention-read",
                "threadId": "thread-mention-read",
                "selectedMentionTokens": [reference["token"]],
            },
        }
        allowed = authorizations.prepare_host_command(call)
        self.assertTrue(allowed["ok"])
        self.assertEqual(
            allowed["bound_call"]["arguments"]["__mention"][0]["record_id"],
            self.partner.id,
        )

        rejected = dict(call, id="mention-read-not-selected")
        rejected["context"] = dict(call["context"], runId="run-not-selected", selectedMentionTokens=[])
        denied = authorizations.prepare_host_command(rejected)
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["code"], "mention_not_selected")

    def test_controlled_read_uses_policy_and_removes_sensitive_binary_values(self):
        self.env["agui.chat.tool.policy"].create({
            "name": "联系人引用读取字段",
            "tool_name": "odoo.read_mentioned_records",
            "access_level": "read",
            "model_name": "res.partner",
            "field_names": "name,email,image,comment,child_ids",
            "confirmation_mode": "never",
        })
        self.env["agui.chat.config"].sudo().get_active_config().write({
            "sensitive_field_names": "email",
        })
        candidate = self._candidate(self._search(), "record")
        reference = self.tokens.bind_mention(
            candidate["candidateToken"], "read", self.session_key,
        )
        result = self.tokens.read_tokens([reference["token"]], self.session_key)
        fields_by_name = {
            item["name"]: item for item in result["records"][0]["fields"]
        }

        self.assertIn("name", fields_by_name)
        self.assertNotIn("email", fields_by_name)
        self.assertNotIn("image", fields_by_name)
        self.assertEqual(fields_by_name["child_ids"]["value"], 0)
        self.assertNotIn("private@example.com", json.dumps(result))
        self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 64 * 1024)

    def test_personal_shared_and_current_filters_bind_without_exposing_domains(self):
        personal = self.env["ir.filters"].create({
            "name": "我的引用筛选",
            "model_id": "res.partner",
            "user_id": self.env.user.id,
            "action_id": self.action.id,
            "domain": "[('name', 'ilike', '引用测试')]",
            "context": "{'group_by': ['company_id']}",
            "sort": "['-name']",
        })
        self.env["ir.filters"].create({
            "name": "共享引用筛选",
            "model_id": "res.partner",
            "user_id": False,
            "action_id": self.action.id,
            "domain": "[]",
            "context": "{}",
            "sort": "[]",
        })
        saved = self._search("引用筛选", "saved_filter")
        self.assertEqual(
            {item["label"] for item in saved["candidates"]},
            {"我的引用筛选", "共享引用筛选"},
        )
        self.assertNotIn("domain", json.dumps(saved))
        personal_candidate = next(
            item for item in saved["candidates"] if item["label"] == personal.name
        )
        reference = self.tokens.bind_mention(
            personal_candidate["candidateToken"], "apply", self.session_key,
        )
        arguments, _audit = self.tokens.resolve_tool_arguments(
            "odoo.apply_mentioned_filter", {"token": reference["token"]},
            self.session_key,
        )
        self.assertEqual(arguments["__mention"][0]["domain"], personal.domain)

        current = self._search("当前", "current_filter", {
            "label": "当前临时筛选",
            "model": "res.partner",
            "menuId": self.menu.id,
            "domain": [["name", "ilike", "引用测试"]],
            "context": {"lang": "zh_CN", "active_test": True},
            "groupBy": ["company_id"],
            "sort": ["-name"],
        })
        candidate = self._candidate(current, "current_filter")
        self.assertNotIn("引用测试\"]]", json.dumps(candidate))
        current_ref = self.tokens.bind_mention(
            candidate["candidateToken"], "apply", self.session_key,
        )
        current_args, _audit = self.tokens.resolve_tool_arguments(
            "odoo.apply_mentioned_filter", {"token": current_ref["token"]},
            self.session_key,
        )
        binding = current_args["__mention"][0]
        self.assertEqual(binding["group_by"], ["company_id"])
        self.assertNotIn("lang", binding["context"])
