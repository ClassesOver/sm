# -*- coding: utf-8 -*-
import json
from copy import deepcopy
from datetime import datetime, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase

from ..models.agui_chat_config import HOST_COMMAND_NAMES
from ..models.agui_chat_tool import normalize_host_arguments


class TestDefaultReadPolicies(TransactionCase):

    def test_missing_model_policy_adds_no_restriction(self):
        policy = self.env["agui.chat.tool.policy"]
        configured = policy.evaluate(
            "odoo.apply_filter", {"target": {"model": "hr.employee"}},
        )
        unconfigured = policy.evaluate(
            "odoo.apply_filter", {"target": {"model": "res.partner"}},
        )

        self.assertTrue(configured["allowed"])
        self.assertFalse(configured["requires_confirmation"])
        self.assertTrue(unconfigured["allowed"])
        self.assertFalse(unconfigured["requires_confirmation"])
        self.assertFalse(unconfigured["policy_id"])

    def test_unconfigured_employee_filter_is_authorized(self):
        policy = self.env["agui.chat.tool.policy"]
        policy.search([
            ("tool_name", "=", "odoo.apply_filter"),
            ("model_name", "=", "hr.employee"),
        ]).write({"active": False})
        policy.create({
            "name": "联系人筛选限制",
            "tool_name": "odoo.apply_filter",
            "access_level": "read",
            "model_name": "res.partner",
            "confirmation_mode": "never",
        })
        self.env["agui.chat.config"].sudo().get_active_config().write({
            "chat_enabled": True,
            "host_tools_enabled": True,
            "enabled_commands": "odoo.apply_filter",
        })

        decision = self.env["agui.chat.tool.authorization"].prepare_host_command({
            "id": "unconfigured-employee-filter",
            "tool": "odoo.apply_filter",
            "arguments": {
                "target": {
                    "snapshotId": "agui-filter-snapshot",
                    "hostRevision": 1,
                    "controllerId": "controller-1",
                    "dataPointId": "hr.employee_30",
                    "model": "hr.employee",
                    "resId": False,
                },
                "domain": [["name", "ilike", "admin"]],
                "label": "名称包含 admin",
            },
            "context": {
                "requestId": "request-unconfigured-filter",
                "runId": "run-unconfigured-filter",
                "threadId": "thread-unconfigured-filter",
            },
        })

        self.assertTrue(decision["ok"])
        self.assertFalse(decision.get("needs_confirmation"))
        self.assertEqual(
            decision["bound_call"]["arguments"]["domain"],
            [["name", "ilike", "admin"]],
        )
        authorization = self.env["agui.chat.tool.authorization"].search([
            ("token", "=", decision["authorization_id"]),
        ])
        self.assertFalse(authorization.policy_id)

class TestHostArgumentNormalization(TransactionCase):

    def test_single_filter_condition_is_wrapped_as_a_domain(self):
        target = {"model": "hr.employee"}
        normalized = normalize_host_arguments(
            "odoo.apply_filter",
            {"target": target, "domain": ["id", "=", 1], "label": "ID = 1"},
        )

        self.assertEqual(normalized["domain"], [["id", "=", 1]])
        self.assertEqual(normalized["target"], target)

    def test_complete_filter_domain_is_unchanged(self):
        domain = ["|", ["name", "ilike", "A"], ["name", "ilike", "B"]]
        normalized = normalize_host_arguments(
            "odoo.apply_filter", {"domain": domain, "label": "A 或 B"},
        )

        self.assertEqual(normalized["domain"], domain)


class TestRelationToolPolicy(TransactionCase):

    def setUp(self):
        super(TestRelationToolPolicy, self).setUp()
        self.env["agui.chat.tool.policy"].search([]).write({"active": False})
        self.policy = self.env["agui.chat.tool.policy"].create({
            "name": "Partner relation lookup",
            "tool_name": "odoo.search_relation",
            "access_level": "read",
            "model_name": "sale.order",
            "field_names": "partner_id",
        })

    def test_relation_command_is_declared(self):
        self.assertIn("odoo.search_relation", HOST_COMMAND_NAMES)

    def test_enter_edit_mode_command_is_declared(self):
        self.assertIn("odoo.enter_edit_mode", HOST_COMMAND_NAMES)

    def test_relation_field_uses_policy_allowlist(self):
        allowed = self.env["agui.chat.tool.policy"].evaluate(
            "odoo.search_relation",
            {
                "target": {"model": "sale.order"},
                "field": "partner_id",
                "query": "Shanghai",
                "operation": "set",
            },
        )
        denied = self.env["agui.chat.tool.policy"].evaluate(
            "odoo.search_relation",
            {
                "target": {"model": "sale.order"},
                "field": "company_id",
                "query": "My Company",
                "operation": "set",
            },
        )
        self.assertTrue(allowed["allowed"])
        self.assertFalse(allowed["requires_confirmation"])
        self.assertFalse(denied["allowed"])

    def test_patch_saves_without_confirmation(self):
        self.env["agui.chat.tool.policy"].create({
            "name": "修改联系人",
            "tool_name": "odoo.patch_current_form",
            "access_level": "write",
            "model_name": "res.partner",
            "field_names": "name",
        })
        decision = self.env["agui.chat.tool.policy"].evaluate(
            "odoo.patch_current_form",
            {
                "target": {"model": "res.partner"},
                "patch": {"name": "新名称"},
            },
        )
        self.assertTrue(decision["allowed"])
        self.assertFalse(decision["requires_confirmation"])

    def test_save_and_discard_require_confirmation(self):
        for tool_name in ("odoo.save_current_form", "odoo.discard_current_form"):
            self.env["agui.chat.tool.policy"].create({
                "name": tool_name,
                "tool_name": tool_name,
                "access_level": "write",
                "model_name": "res.partner",
            })
            decision = self.env["agui.chat.tool.policy"].evaluate(
                tool_name,
                {"target": {"model": "res.partner"}},
            )
            self.assertTrue(decision["allowed"])
            self.assertTrue(decision["requires_confirmation"])

    def test_patch_risk_matrix_and_confirmation_modes(self):
        risk_policy = self.env["agui.chat.tool.policy"].create({
            "name": "联系人风险策略",
            "tool_name": "odoo.patch_current_form",
            "access_level": "write",
            "model_name": "res.partner",
            "field_names": "name,comment,parent_id,phone",
            "high_risk_field_names": "phone",
        })
        policy = self.env["agui.chat.tool.policy"]
        scalar = policy.evaluate("odoo.patch_current_form", {
            "target": {"model": "res.partner"}, "patch": {"name": "A"},
        })
        multiple = policy.evaluate("odoo.patch_current_form", {
            "target": {"model": "res.partner"},
            "patch": {"name": "A", "comment": "B"},
        })
        relation = policy.evaluate("odoo.patch_current_form", {
            "target": {"model": "res.partner"}, "patch": {"parent_id": 1},
        })
        marked = policy.evaluate("odoo.patch_current_form", {
            "target": {"model": "res.partner"}, "patch": {"phone": "10086"},
        })
        self.assertFalse(scalar["requires_confirmation"])
        self.assertIn("multiple_fields", multiple["risk_reasons"])
        self.assertIn("relation_field", relation["risk_reasons"])
        self.assertIn("policy_high_risk_field", marked["risk_reasons"])
        self.assertTrue(multiple["requires_confirmation"])
        self.assertTrue(relation["requires_confirmation"])
        self.assertTrue(marked["requires_confirmation"])

        risk_policy.write({"confirmation_mode": "never"})
        self.assertFalse(policy.evaluate("odoo.patch_current_form", {
            "target": {"model": "res.partner"}, "patch": {"parent_id": 1},
        })["requires_confirmation"])
        risk_policy.write({"confirmation_mode": "always"})
        self.assertTrue(policy.evaluate("odoo.patch_current_form", {
            "target": {"model": "res.partner"}, "patch": {"name": "A"},
        })["requires_confirmation"])

    def _patch_target(self):
        return {
            "snapshotId": "snapshot-risk",
            "hostRevision": 5,
            "controllerId": "controller-risk",
            "dataPointId": "res.partner_%s" % self.env.user.partner_id.id,
            "model": "res.partner",
            "resId": self.env.user.partner_id.id,
        }

    def _prepare_risky_patch(self, call_id="risky-patch"):
        target = self._patch_target()
        return self.env["agui.chat.tool.authorization"].prepare_host_command({
            "id": call_id,
            "tool": "odoo.patch_current_form",
            "arguments": {"target": target, "patch": {"phone": "10086"}},
            "preview": {
                "target": target,
                "changes": [{
                    "field": "phone", "label": "电话", "fieldType": "char",
                    "oldValue": "", "newValue": "10086", "sensitive": False,
                }],
            },
            "context": {
                "requestId": "request-%s" % call_id,
                "runId": "run-%s" % call_id,
                "threadId": "thread-%s" % call_id,
            },
        })

    def _enable_risky_patch(self):
        config = self.env["agui.chat.config"].sudo().get_active_config()
        config.write({
            "chat_enabled": True,
            "host_tools_enabled": True,
            "write_tools_enabled": True,
            "enabled_commands": "odoo.patch_current_form",
        })
        return self.env["agui.chat.tool.policy"].create({
            "name": "电话高风险修改",
            "tool_name": "odoo.patch_current_form",
            "access_level": "write",
            "model_name": "res.partner",
            "field_names": "phone",
            "high_risk_field_names": "phone",
        })

    def test_confirmation_expiry_and_duplicate_events_are_idempotent(self):
        self._enable_risky_patch()
        decision = self._prepare_risky_patch("duplicate-confirm")
        self.assertTrue(decision["needs_confirmation"])
        authorization = self.env["agui.chat.tool.authorization"].search([
            ("token", "=", decision["authorization_id"]),
        ])
        self.assertTrue(authorization.transition(True)["ok"])
        authorization.complete({"ok": True, "saved": True})
        replay = authorization.transition(True)
        self.assertTrue(replay["ok"])
        self.assertEqual(replay["authorization_id"], authorization.token)
        self.assertEqual(replay["replay_result"]["saved"], True)

        expired = self._prepare_risky_patch("expired-confirm")
        expired_authorization = self.env["agui.chat.tool.authorization"].search([
            ("token", "=", expired["authorization_id"]),
        ])
        expired_authorization.write({"expires_at": "2000-01-01 00:00:00"})
        self.assertEqual(
            expired_authorization.transition(True)["code"], "authorization_expired"
        )

    def test_undo_authorization_is_one_time_and_replayable(self):
        policy = self._enable_risky_patch()
        policy.write({"field_names": "name", "high_risk_field_names": False})
        target = self._patch_target()
        call = {
            "id": "undo-source",
            "tool": "odoo.patch_current_form",
            "arguments": {"target": target, "patch": {"name": "After"}},
            "preview": {
                "target": target,
                "changes": [{
                    "field": "name", "label": "名称", "fieldType": "char",
                    "oldValue": "Before", "newValue": "After", "sensitive": False,
                }],
            },
            "context": {
                "requestId": "request-undo", "runId": "run-undo", "threadId": "thread-undo",
            },
        }
        decision = self.env["agui.chat.tool.authorization"].prepare_host_command(call)
        source = self.env["agui.chat.tool.authorization"].search([
            ("token", "=", decision["authorization_id"]),
        ])
        source.complete({
            "ok": True,
            "undo_payload": {
                "target": target, "patch": {"name": "Before"}, "expected": {"name": "After"},
            },
        })
        undo_decision = source.prepare_undo()
        self.assertTrue(undo_decision["ok"])
        undo = self.env["agui.chat.tool.authorization"].search([
            ("token", "=", undo_decision["undo_authorization_id"]),
        ])
        self.assertEqual(undo.authorization_kind, "undo")
        self.assertTrue(undo.begin_undo_execution()["ok"])
        undo.complete({"ok": True, "undone": True})
        replay = undo.begin_undo_execution()
        self.assertTrue(replay["replay_result"]["undone"])

        self.assertTrue(fields.Datetime.from_string(undo.expires_at) > fields.Datetime.from_string(source.create_date))

    def test_prepare_patch_normalizes_json_string(self):
        config = self.env["agui.chat.config"].sudo().get_active_config()
        config.write({
            "chat_enabled": True,
            "host_tools_enabled": True,
            "write_tools_enabled": True,
            "enabled_commands": "odoo.patch_current_form",
        })
        self.env["agui.chat.tool.policy"].create({
            "name": "修改联系人工作地点",
            "tool_name": "odoo.patch_current_form",
            "access_level": "write",
            "model_name": "res.partner",
            "field_names": "work_location",
            "confirmation_mode": "never",
        })
        decision = self.env["agui.chat.tool.authorization"].prepare_host_command({
            "id": "string-patch-call",
            "tool": "odoo.patch_current_form",
            "arguments": {
                "target": {
                    "snapshotId": "snapshot-1",
                    "hostRevision": 1,
                    "controllerId": "controller-1",
                    "dataPointId": "res.partner_1",
                    "model": "res.partner",
                    "resId": 1,
                },
                "patch": '[{"field":"work_location","value":"西安"}]',
            },
            "context": {
                "requestId": "request-string-patch",
                "runId": "run-string-patch",
                "threadId": "thread-string-patch",
            },
        })
        self.assertTrue(decision["ok"])
        self.assertEqual(
            decision["bound_call"]["arguments"]["patch"],
            [{"field": "work_location", "value": "西安"}],
        )


class TestHostCommandAuthorization(TransactionCase):

    def setUp(self):
        super(TestHostCommandAuthorization, self).setUp()
        self.env["agui.chat.tool.policy"].search([]).write({"active": False})
        self.config = self.env["agui.chat.config"].sudo().get_active_config()
        self.config.write({
            "chat_enabled": True,
            "host_tools_enabled": True,
            "write_tools_enabled": True,
            "enabled_commands": "odoo.patch_current_form,odoo.save_current_form",
        })
        self.env["agui.chat.tool.policy"].create({
            "name": "授权测试修改联系人",
            "tool_name": "odoo.patch_current_form",
            "access_level": "write",
            "model_name": "res.partner",
            "field_names": "name",
        })
        self.env["agui.chat.tool.policy"].create({
            "name": "授权测试保存联系人",
            "tool_name": "odoo.save_current_form",
            "access_level": "write",
            "model_name": "res.partner",
        })

    def _call(self, tool_name, call_id, arguments=None):
        values = {
            "target": {
                "snapshotId": "snapshot-%s" % call_id,
                "hostRevision": 1,
                "controllerId": "controller-1",
                "dataPointId": "res.partner_1",
                "model": "res.partner",
                "resId": 1,
            },
        }
        values.update(arguments or {})
        return {
            "id": call_id,
            "tool": tool_name,
            "arguments": values,
            "context": {
                "requestId": "request-%s" % call_id,
                "runId": "run-%s" % call_id,
                "threadId": "thread-%s" % call_id,
            },
        }

    def test_completed_command_replays_once_and_rejects_payload_tampering(self):
        call = self._call(
            "odoo.patch_current_form", "replay-call", {"patch": {"name": "第一次"}}
        )
        authorizations = self.env["agui.chat.tool.authorization"]
        first = authorizations.prepare_host_command(call)
        self.assertTrue(first["ok"])
        authorization = authorizations.search([
            ("token", "=", first["authorization_id"]),
        ])
        authorization.complete({"ok": True, "saved": True})

        replay = authorizations.prepare_host_command(call)
        self.assertEqual(replay["authorization_id"], authorization.token)
        self.assertEqual(replay["replay_result"], {"ok": True, "saved": True})
        self.assertEqual(authorizations.search_count([
            ("tool_call_id", "=", "replay-call"),
        ]), 1)

        tampered = deepcopy(call)
        tampered["arguments"]["patch"]["name"] = "篡改值"
        mismatch = authorizations.prepare_host_command(tampered)
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["code"], "idempotency_payload_mismatch")

        audits = self.env["agui.chat.tool.audit"].search([
            ("tool_call_id", "=", "replay-call"),
        ])
        self.assertEqual(set(audits.mapped("result")), {"allowed", "ok"})

    def test_host_results_use_a_separate_bounded_storage_limit(self):
        authorizations = self.env["agui.chat.tool.authorization"]
        stored_call = self._call(
            "odoo.patch_current_form", "large-host-result", {"patch": {"name": "新名称"}}
        )
        stored_decision = authorizations.prepare_host_command(stored_call)
        stored = authorizations.search([
            ("token", "=", stored_decision["authorization_id"]),
        ])
        large_snapshot = "x" * (200 * 1024)
        self.assertTrue(stored.complete({"ok": True, "snapshot": large_snapshot})["ok"])
        self.assertEqual(stored._json_result()["snapshot"], large_snapshot)

        oversized_call = self._call(
            "odoo.patch_current_form", "oversized-host-result", {"patch": {"name": "超限"}}
        )
        oversized_decision = authorizations.prepare_host_command(oversized_call)
        oversized = authorizations.search([
            ("token", "=", oversized_decision["authorization_id"]),
        ])
        failure = oversized.complete({"ok": True, "snapshot": "x" * (512 * 1024)})
        self.assertFalse(failure["ok"])
        self.assertEqual(failure["code"], "result_too_large")
        self.assertEqual(oversized._json_result(), {"ok": False, "code": "result_too_large"})
        self.assertEqual(oversized.complete({"ok": True})["code"], "result_too_large")

    def test_confirmation_rejection_is_terminal(self):
        decision = self.env["agui.chat.tool.authorization"].prepare_host_command(
            self._call("odoo.save_current_form", "reject-call")
        )
        self.assertTrue(decision["needs_confirmation"])
        authorization = self.env["agui.chat.tool.authorization"].search([
            ("token", "=", decision["authorization_id"]),
        ])

        rejected = authorization.transition(False)
        self.assertEqual(rejected["code"], "authorization_rejected")
        self.assertEqual(authorization.state, "rejected")
        second = authorization.transition(True)
        self.assertEqual(second["code"], "authorization_not_pending")

    def test_expired_confirmation_never_executes(self):
        decision = self.env["agui.chat.tool.authorization"].prepare_host_command(
            self._call("odoo.save_current_form", "expired-call")
        )
        authorization = self.env["agui.chat.tool.authorization"].search([
            ("token", "=", decision["authorization_id"]),
        ])
        authorization.write({
            "expires_at": fields.Datetime.to_string(datetime.utcnow() - timedelta(minutes=1)),
        })

        expired = authorization.transition(True)
        self.assertEqual(expired["code"], "authorization_expired")
        self.assertEqual(authorization.state, "expired")

    def test_server_policy_denies_hidden_or_unlisted_fields(self):
        denied = self.env["agui.chat.tool.authorization"].prepare_host_command(
            self._call(
                "odoo.patch_current_form",
                "hidden-field-call",
                {"patch": {"password": "not-allowed"}},
            )
        )
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["code"], "policy_denied")
        audit = self.env["agui.chat.tool.audit"].search([
            ("tool_call_id", "=", "hidden-field-call"),
        ], limit=1)
        details = json.loads(audit.details_json)
        self.assertIn("field_mismatch", details["policy_mismatches"])

    def test_new_navigation_commands_are_declared_but_default_denied(self):
        new_commands = {
            "odoo.open_menu", "odoo.apply_filter", "odoo.open_record",
            "odoo.open_create", "odoo.enter_edit_mode", "odoo.activate_view_control",
        }
        self.assertTrue(new_commands.issubset(set(HOST_COMMAND_NAMES)))
        self.assertFalse(new_commands.intersection(self.config.enabled_command_names()))
        decision = self.env["agui.chat.tool.authorization"].prepare_host_command({
            "id": "disabled-open-menu",
            "tool": "odoo.open_menu",
            "arguments": {"target": {"snapshotId": "page-1", "hostRevision": 1}, "menuId": 8},
            "context": {
                "requestId": "request-disabled-menu",
                "runId": "run-disabled-menu",
                "threadId": "thread-disabled-menu",
            },
        })
        self.assertEqual(decision["code"], "command_disabled")

    def test_page_target_is_accepted_for_selected_menu_navigation(self):
        self.config.write({"enabled_commands": "odoo.open_menu"})
        self.env["agui.chat.tool.policy"].create({
            "name": "打开已选菜单",
            "tool_name": "odoo.open_menu",
            "access_level": "navigation",
            "confirmation_mode": "never",
        })
        decision = self.env["agui.chat.tool.authorization"].prepare_host_command({
            "id": "open-selected-menu",
            "tool": "odoo.open_menu",
            "arguments": {"target": {"snapshotId": "page-2", "hostRevision": 2}, "menuId": 8},
            "context": {
                "requestId": "request-open-menu",
                "runId": "run-open-menu",
                "threadId": "thread-open-menu",
            },
        })
        self.assertTrue(decision["ok"])
        self.assertFalse(decision.get("needs_confirmation"))
        self.assertEqual(
            set(decision["bound_call"]["arguments"]["target"]),
            {"snapshotId", "hostRevision"},
        )

    def test_enter_edit_mode_is_navigation_not_write(self):
        self.config.write({
            "enabled_commands": "odoo.enter_edit_mode",
            "write_tools_enabled": False,
        })
        self.env["agui.chat.tool.policy"].create({
            "name": "进入编辑模式",
            "tool_name": "odoo.enter_edit_mode",
            "access_level": "navigation",
            "model_name": "res.partner",
            "confirmation_mode": "never",
        })
        decision = self.env["agui.chat.tool.authorization"].prepare_host_command(
            self._call("odoo.enter_edit_mode", "enter-edit-mode")
        )
        self.assertTrue(decision["ok"])
        self.assertFalse(decision.get("needs_confirmation"))

    def test_object_control_requires_write_toggle_and_confirmation(self):
        self.config.write({
            "enabled_commands": "odoo.activate_view_control",
            "write_tools_enabled": False,
        })
        self.env["agui.chat.tool.policy"].create({
            "name": "激活页面控件",
            "tool_name": "odoo.activate_view_control",
            "access_level": "write",
            "model_name": "res.partner",
            "confirmation_mode": "never",
        })
        call = self._call("odoo.activate_view_control", "object-control", {
            "controlToken": "opaque-control-token",
            "__control": {
                "type": "object", "label": "确认订单", "recordLabel": "Acme",
            },
        })
        disabled = self.env["agui.chat.tool.authorization"].prepare_host_command(call)
        self.assertEqual(disabled["code"], "write_tools_disabled")

        self.config.write({"write_tools_enabled": True})
        decision = self.env["agui.chat.tool.authorization"].prepare_host_command(call)
        self.assertTrue(decision["needs_confirmation"])
        self.assertIn("object_button", decision["risk_reasons"])
        self.assertEqual(decision["preview"]["control"], {
            "type": "object", "label": "确认订单", "recordLabel": "Acme",
        })

        self.config.write({"write_tools_enabled": False})
        action_call = self._call("odoo.activate_view_control", "action-control", {
            "controlToken": "opaque-action-token",
            "__control": {
                "type": "action", "label": "查看明细", "recordLabel": "Acme",
            },
        })
        action_decision = self.env["agui.chat.tool.authorization"].prepare_host_command(action_call)
        self.assertTrue(action_decision["ok"])
        self.assertFalse(action_decision.get("needs_confirmation"))
