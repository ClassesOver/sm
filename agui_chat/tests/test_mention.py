# -*- coding: utf-8 -*-
import json
from datetime import timedelta

from odoo import api, fields
from odoo.tests.common import TransactionCase, tagged

from ..models.agui_chat_mention import MentionTokenError
from .common import configure_test_runtime


@tagged("agui_mention")
class TestMentionReferences(TransactionCase):

    def setUp(self):
        super(TestMentionReferences, self).setUp()
        self.session_key = "test-session"
        configure_test_runtime(self.env).write({
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
        return self.tokens._search_mentions(
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

    def test_loaded_menu_tree_marks_only_explicit_window_actions(self):
        root = self.env["ir.ui.menu"].load_menus(False)

        def find_menu(node, menu_id):
            if node.get("id") == menu_id:
                return node
            for child in node.get("children") or []:
                found = find_menu(child, menu_id)
                if found:
                    return found
            return False

        folder = find_menu(root, self.root_menu.id)
        menu = find_menu(root, self.menu.id)
        self.assertFalse(folder["action_id"])
        self.assertEqual(menu["action_id"], self.action.id)

    def test_global_soft_quotas_empty_browse_and_explicit_model_budget(self):
        for index in range(12):
            self.env["res.partner"].create({"name": "配额客户 %02d" % index})
        for index in range(8):
            action = self.env["ir.actions.act_window"].create({
                "name": "配额菜单 %02d" % index,
                "res_model": "res.partner",
                "view_mode": "tree,form",
            })
            self.env["ir.ui.menu"].create({
                "name": "配额菜单 %02d" % index,
                "parent_id": self.root_menu.id,
                "action": "ir.actions.act_window,%s" % action.id,
            })
        for index in range(8):
            self.env["ir.filters"].create({
                "name": "配额收藏 %02d" % index,
                "model_id": "res.partner",
                "user_id": self.env.user.id,
                "action_id": self.action.id,
                "domain": "[]",
                "context": "{}",
                "sort": "[]",
            })
        self.env["ir.ui.menu"].clear_caches()
        current_filter = {
            "label": "配额当前筛选",
            "model": "res.partner",
            "menuId": self.menu.id,
            "domain": [],
            "context": {},
            "groupBy": [],
            "sort": [],
        }

        result = self.tokens._search_mentions(
            "配额", "all", False, "res.partner", [], current_filter, self.session_key,
        )
        kinds = [item["kind"] for item in result["candidates"]]
        self.assertTrue(kinds)
        self.assertTrue(set(kinds).issubset({"record", "menu"}))
        self.assertNotIn("saved_filter", kinds)
        self.assertNotIn("current_filter", kinds)

        explicit = self.tokens._search_mentions(
            "配额", "record", "res.partner", "res.partner", [], False,
            self.session_key,
        )
        self.assertGreater(len(explicit["candidates"]), 5)
        self.assertLessEqual(len(explicit["candidates"]), 20)
        self.assertTrue(self.tokens._search_mentions(
            "", "menu", False, "res.partner", [], False, self.session_key,
        )["candidates"])
        self.assertTrue(self.tokens._search_mentions(
            "", "saved_filter", False, "res.partner", [], False, self.session_key,
        )["candidates"])
        self.assertTrue(self.tokens._search_mentions(
            "", "current_filter", False, "res.partner", [], current_filter,
            self.session_key,
        )["candidates"])
        self.assertFalse(self.tokens._search_mentions(
            "", "record", False, "res.partner", [], False, self.session_key,
        )["candidates"])

    def test_menu_catalog_rebuilds_with_create_capability(self):
        catalog = self.tokens._menu_catalog()
        item = next(entry for entry in catalog if entry["menu_id"] == self.menu.id)
        self.assertEqual(item["can_create"], self.tokens._can("res.partner", "create"))
        self.assertIsNot(catalog, self.tokens._menu_catalog())

    def test_model_picker_exposes_up_to_one_hundred_visible_models(self):
        catalog = [{
            "model": "x.model.%03d" % index,
            "fullPath": "模型 %03d" % index,
            "menu_id": index + 1,
            "action_id": index + 1000,
        } for index in range(120)]
        scopes = self.tokens._model_scopes(False, [], catalog)
        catalog[3]["model"] = "res.partner"
        partner_model = self.env["ir.model"].search([("model", "=", "res.partner")], limit=1)
        self.env["agui.chat.config"].sudo().get_active_config().write({
            "mention_model_id": partner_model.id,
        })
        filtered = self.tokens._model_scopes(False, [], catalog)
        self.assertEqual([item["model"] for item in filtered], ["res.partner"])
        self.assertEqual(len(scopes), 100)
        self.assertEqual(scopes[0]["model"], "x.model.000")
        self.assertEqual(scopes[-1]["model"], "x.model.099")

    def test_model_whitelist_filters_all_kinds_and_revokes_old_tokens(self):
        personal = self.env["ir.filters"].create({
            "name": "白名单收藏筛选",
            "model_id": "res.partner",
            "user_id": self.env.user.id,
            "action_id": self.action.id,
            "domain": "[]",
            "context": "{}",
            "sort": "[]",
        })
        current_filter = {
            "label": "白名单当前筛选",
            "model": "res.partner",
            "menuId": self.menu.id,
            "domain": [],
            "context": {},
            "groupBy": [],
            "sort": [],
        }
        candidates = {
            "menu": self._candidate(self._search("联系人", "menu"), "menu"),
            "record": self._candidate(self._search(), "record"),
            "saved_filter": self._candidate(
                self._search(personal.name, "saved_filter"), "saved_filter"
            ),
            "current_filter": self._candidate(
                self._search("白名单", "current_filter", current_filter), "current_filter"
            ),
        }
        actions = {"menu": "open", "record": "read", "saved_filter": "apply", "current_filter": "apply"}
        bound = {
            kind: self.tokens._bind_mention(item["candidateToken"], actions[kind], self.session_key)
            for kind, item in candidates.items()
        }

        disallowed_model = self.env["ir.model"].search([
            ("model", "=", "res.users"),
        ], limit=1)
        self.env["agui.chat.config"].sudo().get_active_config().write({
            "mention_model_id": disallowed_model.id,
        })

        for scope in ("menu", "record", "saved_filter", "current_filter"):
            result = self._search(
                "白名单" if scope == "current_filter" else "联系人",
                scope, current_filter if scope == "current_filter" else None,
            )
            self.assertFalse(result["candidates"])
        for kind, item in candidates.items():
            with self.assertRaises(MentionTokenError) as caught:
                self.tokens._bind_mention(
                    item["candidateToken"], actions[kind], self.session_key,
                )
            self.assertEqual(caught.exception.code, "mention_permission_revoked")
        for kind, reference in bound.items():
            with self.assertRaises(MentionTokenError) as caught:
                self.tokens._resolved_binding(
                    reference["token"], kind, actions[kind], self.session_key,
                )
            self.assertEqual(caught.exception.code, "mention_permission_revoked")

    def test_menu_group_revocation_invalidates_candidates_and_bound_tokens(self):
        group = self.env["res.groups"].create({"name": "引用菜单临时权限"})
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "引用撤权用户",
            "login": "mention-revoked-user",
            "email": "mention-revoked-user@example.com",
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id, group.id,
            ])],
            "company_id": self.env.user.company_id.id,
            "company_ids": [(6, 0, [self.env.user.company_id.id])],
        })
        self.menu.write({"groups_id": [(6, 0, [group.id])]})
        self.env["ir.ui.menu"].clear_caches()
        user_env = api.Environment(self.env.cr, user.id, dict(self.env.context))
        tokens = user_env["agui.chat.mention.token"]

        search = tokens._search_mentions(
            "联系人", "menu", False, "res.partner", [], False, self.session_key,
        )
        candidate = self._candidate(search, "menu")
        reference = tokens._bind_mention(
            candidate["candidateToken"], "open", self.session_key,
        )

        user.write({"groups_id": [(3, group.id)]})
        self.env["ir.ui.menu"].clear_caches()
        user_env.user.invalidate_cache(["groups_id"])

        refreshed = tokens._search_mentions(
            "联系人", "menu", False, "res.partner", [], False, self.session_key,
        )
        self.assertFalse(any(
            item["resourceKey"] == candidate["resourceKey"]
            for item in refreshed["candidates"]
        ))
        with self.assertRaises(MentionTokenError) as candidate_error:
            tokens._bind_mention(
                candidate["candidateToken"], "open", self.session_key,
            )
        self.assertEqual(
            candidate_error.exception.code, "mention_resource_unavailable"
        )
        with self.assertRaises(MentionTokenError) as bound_error:
            tokens._resolved_binding(
                reference["token"], "menu", "open", self.session_key,
            )
        self.assertEqual(
            bound_error.exception.code, "mention_resource_unavailable"
        )

    def test_inactive_reference_command_revokes_old_actions(self):
        candidate = self._candidate(self._search(), "record")
        reference = self.tokens._bind_mention(
            candidate["candidateToken"], "read", self.session_key,
        )
        command = self.env.ref("agui_chat.command_read_mentioned_records")
        command.write({"active": False})

        refreshed = self._candidate(self._search(), "record")
        self.assertNotIn("read", refreshed["actions"])
        with self.assertRaises(MentionTokenError) as candidate_error:
            self.tokens._bind_mention(
                candidate["candidateToken"], "read", self.session_key,
            )
        self.assertEqual(
            candidate_error.exception.code, "mention_permission_revoked"
        )
        with self.assertRaises(MentionTokenError) as bound_error:
            self.tokens._resolved_binding(
                reference["token"], "record", "read", self.session_key,
            )
        self.assertEqual(bound_error.exception.code, "mention_permission_revoked")

        command.write({"active": True})
        restored = self._candidate(self._search(), "record")
        self.assertIn("read", restored["actions"])

    def test_token_is_bound_to_user_company_session_and_exact_action(self):
        candidate = self._candidate(self._search(), "record")
        reference = self.tokens._bind_mention(
            candidate["candidateToken"], "read", self.session_key,
        )
        arguments, _audit = self.tokens._resolve_tool_arguments(
            "odoo.read_mentioned_records", {"tokens": [reference["token"]]},
            self.session_key,
        )
        self.assertEqual(arguments["__mention"][0]["record_id"], self.partner.id)

        with self.assertRaises(MentionTokenError):
            self.tokens._resolve_tool_arguments(
                "odoo.open_mentioned_record", {"token": reference["token"]},
                self.session_key,
            )
        with self.assertRaises(MentionTokenError):
            self.tokens._resolve_tool_arguments(
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
            other_env["agui.chat.mention.token"]._resolve_tool_arguments(
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
            self.tokens._bind_mention(candidate["candidateToken"], "read", self.session_key)
        self.assertEqual(caught.exception.code, "mention_token_expired")

    def test_authorization_accepts_only_tokens_selected_in_the_current_run(self):
        candidate = self._candidate(self._search(), "record")
        reference = self.tokens._bind_mention(
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
        allowed = authorizations._prepare_host_command(call)
        self.assertTrue(allowed["ok"])
        self.assertEqual(
            allowed["bound_call"]["arguments"]["__mention"][0]["record_id"],
            self.partner.id,
        )

        rejected = dict(call, id="mention-read-not-selected")
        rejected["context"] = dict(call["context"], runId="run-not-selected", selectedMentionTokens=[])
        denied = authorizations._prepare_host_command(rejected)
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
        reference = self.tokens._bind_mention(
            candidate["candidateToken"], "read", self.session_key,
        )
        result = self.tokens._read_tokens([reference["token"]], self.session_key)
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
        reference = self.tokens._bind_mention(
            personal_candidate["candidateToken"], "apply", self.session_key,
        )
        arguments, _audit = self.tokens._resolve_tool_arguments(
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
        current_ref = self.tokens._bind_mention(
            candidate["candidateToken"], "apply", self.session_key,
        )
        current_args, _audit = self.tokens._resolve_tool_arguments(
            "odoo.apply_mentioned_filter", {"token": current_ref["token"]},
            self.session_key,
        )
        binding = current_args["__mention"][0]
        self.assertEqual(binding["group_by"], ["company_id"])
        self.assertNotIn("lang", binding["context"])
