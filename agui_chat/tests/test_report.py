# -*- coding: utf-8 -*-
from unittest.mock import Mock, patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..controllers.main import _attachment_type
from ..models.agui_chat_report import (
    COMMAND_NAME,
    ReportError,
    _aggregate,
    _binding_resolver,
    _handler,
    _sort_parts,
    _upload_files,
)
from .common import configure_test_runtime


@tagged("agui_report")
class TestFilterReports(TransactionCase):

    def setUp(self):
        super(TestFilterReports, self).setUp()
        self.session_key = "report-session"
        self.config = configure_test_runtime(self.env)
        self.config.write({
            "chat_enabled": True,
            "host_tools_enabled": True,
            "write_tools_enabled": False,
            "enabled_commands": "odoo.apply_mentioned_filter,odoo.read_mentioned_records",
            "enabled_business_commands": COMMAND_NAME,
        })
        self.action = self.env["ir.actions.act_window"].create({
            "name": "报表联系人",
            "res_model": "res.partner",
            "view_mode": "tree,form",
        })
        self.root_menu = self.env["ir.ui.menu"].create({"name": "报表测试"})
        self.menu = self.env["ir.ui.menu"].create({
            "name": "联系人",
            "parent_id": self.root_menu.id,
            "action": "ir.actions.act_window,%s" % self.action.id,
        })
        self.env["ir.ui.menu"].clear_caches()
        self.partner = self.env["res.partner"].create({"name": "报表客户甲"})
        self.saved_filter = self.env["ir.filters"].create({
            "name": "报表收藏筛选",
            "model_id": "res.partner",
            "user_id": self.env.user.id,
            "action_id": self.action.id,
            "domain": "[('name', 'ilike', '报表客户')]",
            "context": "{'group_by': ['company_id']}",
            "sort": "['-name']",
        })
        self.policy = self.env["agui.chat.tool.policy"].create({
            "name": "联系人筛选报表",
            "tool_name": COMMAND_NAME,
            "access_level": "read",
            "model_name": "res.partner",
            "field_names": "id,name,active,company_id,create_date",
            "confirmation_mode": "never",
        })
        self.tokens = self.env["agui.chat.mention.token"].with_context(
            agui_session_key=self.session_key,
        )

    def _saved_reference(self, action="read"):
        result = self.tokens._search_mentions(
            "报表收藏", "saved_filter", False, "res.partner", [], False,
            self.session_key,
        )
        candidate = next(
            item for item in result["candidates"] if item["label"] == self.saved_filter.name
        )
        return candidate, self.tokens._bind_mention(
            candidate["candidateToken"], action, self.session_key,
        )

    def _current_reference(self):
        result = self.tokens._search_mentions(
            "当前", "current_filter", False, "res.partner", [], {
                "label": "当前报表筛选",
                "model": "res.partner",
                "menuId": self.menu.id,
                "domain": [["name", "ilike", "报表客户"]],
                "context": {},
                "groupBy": ["company_id"],
                "sort": ["-name"],
            }, self.session_key,
        )
        candidate = next(item for item in result["candidates"] if item["kind"] == "current_filter")
        return self.tokens._bind_mention(candidate["candidateToken"], "read", self.session_key)

    def test_filter_read_and_apply_are_distinct_and_read_requires_report_policy(self):
        candidate, read_reference = self._saved_reference("read")
        self.assertEqual(candidate["actions"], ["read", "apply"])
        self.assertFalse(read_reference["pageAction"])
        _candidate, apply_reference = self._saved_reference("apply")
        self.assertTrue(apply_reference["pageAction"])

        with self.assertRaises(Exception):
            self.tokens._resolved_binding(
                read_reference["token"], "saved_filter", "apply", self.session_key,
            )
        with self.assertRaises(Exception):
            self.tokens._resolved_binding(
                apply_reference["token"], "saved_filter", "read", self.session_key,
            )

        self.policy.write({"active": False})
        result = self.tokens._search_mentions(
            "报表收藏", "saved_filter", False, "res.partner", [], False,
            self.session_key,
        )
        candidate = next(item for item in result["candidates"] if item["label"] == self.saved_filter.name)
        self.assertEqual(candidate["actions"], ["apply"])

    def test_binding_resolver_accepts_only_current_message_filter_read_tokens(self):
        _candidate, saved = self._saved_reference()
        current = self._current_reference()
        payload = {
            "mode": "detail",
            "requests": [
                {"token": saved["token"], "fields": ["id", "name"]},
                {"token": current["token"], "fields": ["id", "name"]},
            ],
        }
        context = {"selectedMentionTokens": [saved["token"], current["token"]]}
        resolved = _binding_resolver(
            self.env(context=dict(self.env.context, agui_session_key=self.session_key)),
            payload, context,
        )
        self.assertEqual(len(resolved["policy_bindings"]), 2)
        self.assertEqual(resolved["audit_details"]["models"], ["res.partner"])

        with self.assertRaises(ReportError) as caught:
            _binding_resolver(
                self.env(context=dict(self.env.context, agui_session_key=self.session_key)),
                payload, {"selectedMentionTokens": [saved["token"]]},
            )
        self.assertEqual(caught.exception.code, "mention_not_selected")

        record_search = self.tokens._search_mentions(
            "报表客户甲", "record", False, "res.partner", [], False,
            self.session_key,
        )
        record_candidate = next(item for item in record_search["candidates"] if item["kind"] == "record")
        record = self.tokens._bind_mention(
            record_candidate["candidateToken"], "read", self.session_key,
        )
        with self.assertRaises(Exception):
            _binding_resolver(
                self.env(context=dict(self.env.context, agui_session_key=self.session_key)),
                {"mode": "describe", "requests": [{"token": record["token"]}]},
                {"selectedMentionTokens": [record["token"]]},
            )

        self.action.write({"res_model": "res.users"})
        with self.assertRaises(Exception) as caught:
            _binding_resolver(
                self.env(context=dict(self.env.context, agui_session_key=self.session_key)),
                {"mode": "describe", "requests": [{"token": current["token"]}]},
                {"selectedMentionTokens": [current["token"]]},
            )
        self.assertEqual(caught.exception.code, "mention_resource_unavailable")

    def test_invalid_batch_fails_before_authorization_is_created(self):
        _candidate, saved = self._saved_reference()
        current = self._current_reference()
        payload = {
            "mode": "detail",
            "requests": [
                {"token": saved["token"], "fields": ["id", "name"]},
                {"token": current["token"], "fields": ["id", "email"]},
            ],
        }
        call = {
            "id": "report-atomic",
            "tool": COMMAND_NAME,
            "arguments": payload,
            "context": {
                "requestId": "request-report-atomic",
                "runId": "run-report-atomic",
                "threadId": "thread-report-atomic",
                "selectedMentionTokens": [saved["token"], current["token"]],
            },
        }
        authorizations = self.env["agui.chat.tool.authorization"].with_context(
            agui_session_key=self.session_key,
        )
        before = authorizations.search_count([])
        result = authorizations._prepare_business_command(call)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "field_not_allowed")
        self.assertEqual(authorizations.search_count([]), before)
        audit = self.env["agui.chat.tool.audit"].search([
            ("request_id", "=", "request-report-atomic"),
            ("result", "=", "denied"),
        ], limit=1)
        self.assertTrue(audit)
        self.assertIn("field_not_allowed", audit.details_json)

        aggregate_payload = {
            "mode": "aggregate",
            "requests": [
                {
                    "token": saved["token"],
                    "dimensions": [],
                    "metrics": [{"field": "id", "aggregation": "count"}],
                },
                {
                    "token": current["token"],
                    "dimensions": [],
                    "metrics": [{"field": "active", "aggregation": "sum"}],
                },
            ],
        }
        aggregate_call = dict(call, id="report-atomic-aggregation", arguments=aggregate_payload)
        aggregate_call["context"] = dict(
            call["context"],
            requestId="request-report-atomic-aggregation",
            runId="run-report-atomic-aggregation",
        )
        result = authorizations._prepare_business_command(aggregate_call)
        self.assertEqual(result["code"], "invalid_aggregation")
        self.assertEqual(authorizations.search_count([]), before)

    def test_describe_executes_without_write_tools_and_rechecks_policy(self):
        _candidate, saved = self._saved_reference()
        payload = {"mode": "describe", "requests": [{"token": saved["token"]}]}
        call = {
            "id": "report-describe-read",
            "tool": COMMAND_NAME,
            "arguments": payload,
            "context": {
                "requestId": "request-report-describe-read",
                "runId": "run-report-describe-read",
                "threadId": "thread-report-describe-read",
                "selectedMentionTokens": [saved["token"]],
            },
        }
        runtime = dict(
            self.env.context,
            agui_session_key=self.session_key,
            agui_odoo_session="odoo-report-session",
        )
        authorization_model = self.env["agui.chat.tool.authorization"].with_context(
            runtime
        )
        decision = authorization_model._prepare_business_command(call)
        self.assertTrue(decision["ok"])
        result = self.env["agui.chat.command.execution"].with_context(runtime)._execute_named(
            COMMAND_NAME,
            payload,
            decision["authorization_id"],
            decision["authorization_id"],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["reports"][0]["filterLabel"], self.saved_filter.name)

        _candidate, revoked = self._saved_reference()
        revoked_payload = {
            "mode": "describe", "requests": [{"token": revoked["token"]}],
        }
        revoked_call = dict(call, id="report-describe-revoked", arguments=revoked_payload)
        revoked_call["context"] = dict(
            call["context"],
            requestId="request-report-describe-revoked",
            runId="run-report-describe-revoked",
            selectedMentionTokens=[revoked["token"]],
        )
        revoked_decision = authorization_model._prepare_business_command(revoked_call)
        self.assertTrue(revoked_decision["ok"])
        self.policy.write({"active": False})
        denied = self.env["agui.chat.command.execution"].with_context(runtime)._execute_named(
            COMMAND_NAME,
            revoked_payload,
            revoked_decision["authorization_id"],
            revoked_decision["authorization_id"],
        )
        self.assertEqual(denied["code"], "mention_permission_revoked")
        authorization = self.env["agui.chat.tool.authorization"].search([
            ("token", "=", revoked_decision["authorization_id"]),
        ])
        audit = self.env["agui.chat.tool.audit"].search([
            ("authorization_id", "=", authorization.id),
            ("result", "=", "denied"),
        ], limit=1)
        self.assertTrue(audit)
        self.assertIn("mention_permission_revoked", audit.details_json)

    def test_policy_rejects_missing_binary_sensitive_and_x2many_fields(self):
        values = {
            "name": "无效报表策略",
            "tool_name": COMMAND_NAME,
            "access_level": "read",
            "model_name": "res.partner",
            "confirmation_mode": "never",
        }
        with self.assertRaises(ValidationError):
            self.env["agui.chat.tool.policy"].create(values)
        for fields_value in ("name,image", "name,child_ids", "name,password"):
            with self.assertRaises(ValidationError):
                self.env["agui.chat.tool.policy"].create(dict(
                    values, field_names=fields_value,
                ))

    def test_detail_5000_boundary_and_aggregate_date_bucket(self):
        binding = {
            "label": "边界筛选",
            "kind": "current_filter",
            "model": "res.partner",
            "domain": [("id", "=", self.partner.id)],
            "context": {"active_test": True},
            "group_by": [],
            "sort": [],
            "allowed_fields": ["id", "name", "create_date"],
        }
        payload = {
            "mode": "detail",
            "requests": [{"token": "server-bound", "fields": ["id", "name"]}],
        }
        with patch("odoo.models.BaseModel.search_count", return_value=5001):
            with self.assertRaises(ReportError) as caught:
                _handler(self.env, payload, {"filter_bindings": [binding]})
        self.assertEqual(caught.exception.code, "aggregation_required")

        with patch("odoo.models.BaseModel.search_count", return_value=5000), patch(
                "odoo.addons.agui_chat.models.agui_chat_report._upload_files"):
            result = _handler(self.env, payload, {
                "filter_bindings": [binding],
                "thread_id": "thread-boundary",
                "odoo_session": "session-boundary",
            })
        self.assertEqual(result["reports"][0]["rowCount"], 1)

        rows, rules = _aggregate(self.env, binding, {
            "dimensions": ["create_date:month"],
            "metrics": [{"field": "id", "aggregation": "count"}],
        })
        self.assertTrue(rows)
        self.assertEqual(rules, [])

    def test_hyphen_sort_only_accepts_a_single_field(self):
        self.assertEqual(_sort_parts("-name"), ("name", "desc"))
        with self.assertRaises(ReportError):
            _sort_parts("-name desc")

    def test_report_attachment_suffix_recovers_missing_mime_type(self):
        self.assertEqual(
            _attachment_type("application/octet-stream", "report.jsonl"),
            ("application/x-ndjson", "document"),
        )
        self.assertEqual(
            _attachment_type("application/octet-stream", "report.exe"),
            ("application/octet-stream", False),
        )

    def test_workspace_upload_failure_removes_already_uploaded_files(self):
        session = self.env["agui.chat.session"]._create_session()
        success = Mock()
        success.raise_for_status.return_value = None
        success.json.return_value = {"ok": True}
        failure = Exception("upload failed")
        with patch(
                "odoo.addons.agui_chat.models.agui_chat_report.requests.post",
                side_effect=[success, failure],
        ) as post, patch(
                "odoo.addons.agui_chat.models.agui_chat_report.requests.delete",
        ) as delete:
            with self.assertRaises(ReportError):
                _upload_files(self.env, session.thread_id, "browser-session", [
                    ("reports/data/one.jsonl", b"{}\n", "application/x-ndjson"),
                    ("reports/data/one.meta.json", b"{}", "application/json"),
                ])
        self.assertEqual(delete.call_count, 1)
        self.assertEqual(
            post.call_args_list[0].kwargs["headers"]["X-AGUI-Thread"],
            session.thread_id,
        )
        self.assertEqual(
            delete.call_args.kwargs["headers"]["X-AGUI-Thread"],
            session.thread_id,
        )
