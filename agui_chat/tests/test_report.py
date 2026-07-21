# -*- coding: utf-8 -*-
import hashlib
import json
from unittest.mock import Mock, patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..controllers.main import _attachment_type
from ..models.agui_chat_report import (
    COMMAND_NAME,
    ReportError,
    _aggregate,
    _binding_resolver,
    _export_current_view_dataset,
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

    def _source_values(self, selected_ids=None, domain=None):
        session = self.env["agui.chat.session"]._create_session()
        return session, {
            "threadId": session.thread_id,
            "target": {
                "snapshotId": "snapshot-report-1",
                "hostRevision": 1,
                "controllerId": "controller-report-1",
                "dataPointId": "data-report-1",
                "model": "res.partner",
                "resId": False,
            },
            "viewType": "list",
            "menuId": self.menu.id,
            "actionId": self.action.id,
            "domain": domain if domain is not None else [["name", "ilike", "报表客户"]],
            "context": {"active_test": True},
            "groupBy": [],
            "sort": ["-name"],
            "selectedIds": selected_ids or [],
        }

    def _current_payload(self, source, mode="describe", request_item=None):
        return {
            "source": {"kind": "current_view", "sourceHandle": source.handle},
            "target": {
                "snapshotId": source.snapshot_id,
                "hostRevision": source.host_revision,
                "controllerId": source.controller_id,
                "dataPointId": source.data_point_id,
                "model": source.model_name,
                "resId": False,
            },
            "mode": mode,
            "requests": [request_item or {}],
        }

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

    def test_current_view_source_uses_full_domain_or_selected_intersection(self):
        other = self.env["res.partner"].create({"name": "报表客户乙"})
        _session, values = self._source_values()
        source = self.env["agui.chat.report.source"]._bind_current_view(
            values, self.session_key,
        )
        self.assertEqual(source.scope, "domain")
        payload = self._current_payload(source)
        resolved = _binding_resolver(
            self.env(context=dict(self.env.context, agui_session_key=self.session_key)),
            payload,
            {"threadId": source.thread_id},
        )
        result = _handler(self.env, payload, dict(
            resolved["handler_context"],
            thread_id=source.thread_id,
            odoo_session="browser-session",
        ))
        self.assertGreaterEqual(result["reports"][0]["rowCount"], 2)
        self.assertNotIn("domain", result["reports"][0])
        self.assertNotIn("selectedIds", result["reports"][0])

        _session, selected_values = self._source_values(selected_ids=[other.id])
        selected = self.env["agui.chat.report.source"]._bind_current_view(
            selected_values, self.session_key,
        )
        selected_result = _handler(
            self.env,
            self._current_payload(selected),
            {
                "filter_bindings": [{
                    "label": "当前列表",
                    "kind": "current_view",
                    "model": "res.partner",
                    "domain": selected._load_json("domain_json", []),
                    "context": selected._load_json("context_json", {}),
                    "group_by": [],
                    "sort": selected._load_json("sort_json", []),
                    "selected_ids": selected._load_json("selected_ids_json", []),
                    "allowed_fields": ["id", "name"],
                }],
                "report_sources": selected,
            },
        )
        self.assertEqual(selected.scope, "selected")
        self.assertEqual(selected_result["reports"][0]["rowCount"], 1)

    def test_current_view_source_rejects_out_of_domain_selection_and_stale_range(self):
        outsider = self.env["res.partner"].create({"name": "范围外联系人"})
        _session, values = self._source_values(selected_ids=[outsider.id])
        with self.assertRaises(ReportError) as caught:
            self.env["agui.chat.report.source"]._bind_current_view(
                values, self.session_key,
            )
        self.assertEqual(caught.exception.code, "report_selection_forbidden")

        _session, values = self._source_values()
        source = self.env["agui.chat.report.source"]._bind_current_view(
            values, self.session_key,
        )
        changed = dict(values, sourceHandle=source.handle, selectedIds=[self.partner.id])
        with self.assertRaises(ReportError) as caught:
            self.env["agui.chat.report.source"]._bind_current_view(
                changed, self.session_key,
            )
        self.assertEqual(caught.exception.code, "stale_report_source")

    def test_current_view_source_limits_binding_size_and_rechecks_selected_scope(self):
        _session, values = self._source_values(selected_ids=[self.partner.id])
        with patch(
                "odoo.addons.agui_chat.models.agui_chat_report.MAX_REPORT_SOURCE_BIND_BYTES", 16,
        ):
            with self.assertRaises(ReportError) as caught:
                self.env["agui.chat.report.source"]._bind_current_view(
                    values, self.session_key,
                )
        self.assertEqual(caught.exception.code, "report_source_too_large")

        source = self.env["agui.chat.report.source"]._bind_current_view(
            values, self.session_key,
        )
        source.sudo().write({
            "domain_json": json.dumps([["id", "=", self.partner.id + 9999]]),
        })
        with self.assertRaises(ReportError) as caught:
            _binding_resolver(
                self.env(context=dict(self.env.context, agui_session_key=self.session_key)),
                self._current_payload(source),
                {"threadId": source.thread_id},
            )
        self.assertEqual(caught.exception.code, "report_selection_forbidden")

    def test_current_view_detail_writes_hashed_fragments_then_consumes_source(self):
        for index in range(5):
            self.env["res.partner"].create({"name": "报表客户分片%s" % index})
        _session, values = self._source_values()
        source = self.env["agui.chat.report.source"]._bind_current_view(
            values, self.session_key,
        )
        binding = {
            "label": "当前列表",
            "kind": "current_view",
            "model": "res.partner",
            "domain": source._load_json("domain_json", []),
            "context": source._load_json("context_json", {}),
            "group_by": [],
            "sort": source._load_json("sort_json", []),
            "selected_ids": [],
            "allowed_fields": ["id", "name"],
        }
        captured = {}

        def inspect_upload(_env, _thread, _browser_session, entries):
            captured["entries"] = [
                (path, open(local_path, "rb").read(), mime_type)
                for path, local_path, mime_type in entries
            ]

        with patch(
                "odoo.addons.agui_chat.models.agui_chat_report.MAX_REPORT_PART_BYTES", 80,
        ), patch(
                "odoo.addons.agui_chat.models.agui_chat_report._upload_local_files",
                side_effect=inspect_upload,
        ):
            result = _export_current_view_dataset(
                self.env, source, binding, {"fields": ["id", "name"]},
                source.thread_id, "browser-session", "2026-07-21 12:00:00",
            )

        entries = captured["entries"]
        manifest_path, manifest_content, _mime = entries[-1]
        manifest = json.loads(manifest_content.decode("utf-8"))
        self.assertEqual(manifest_path, result["manifestPath"])
        self.assertTrue(manifest_path.startswith("报表/原始数据/"))
        self.assertGreaterEqual(result["fragmentCount"], 2)
        self.assertEqual(manifest["rowCount"], result["rowCount"])
        self.assertNotIn("domain", manifest)
        self.assertNotIn("selectedIds", manifest)
        by_path = {path: content for path, content, _mime in entries[:-1]}
        for fragment in manifest["fragments"]:
            self.assertEqual(
                hashlib.sha256(by_path[fragment["path"]]).hexdigest(),
                fragment["sha256"],
            )
        source.invalidate_cache()
        self.assertEqual(source.state, "consumed")
        self.assertFalse(source.domain_json)
        self.assertFalse(source.context_json)
        self.assertFalse(source.selected_ids_json)

    def test_current_view_detail_limits_rows_and_upload_failure_keeps_source(self):
        self.env["res.partner"].create({"name": "报表客户上限"})
        _session, values = self._source_values()
        source = self.env["agui.chat.report.source"]._bind_current_view(
            values, self.session_key,
        )
        binding = {
            "label": "当前列表", "kind": "current_view", "model": "res.partner",
            "domain": source._load_json("domain_json", []),
            "context": source._load_json("context_json", {}),
            "group_by": [], "sort": [], "selected_ids": [],
            "allowed_fields": ["id", "name"],
        }
        with patch(
                "odoo.addons.agui_chat.models.agui_chat_report.MAX_CURRENT_VIEW_ROWS", 1,
        ):
            with self.assertRaises(ReportError) as caught:
                _export_current_view_dataset(
                    self.env, source, binding, {"fields": ["id", "name"]},
                    source.thread_id, "browser-session", "2026-07-21 12:00:00",
                )
        self.assertEqual(caught.exception.code, "report_dataset_too_large")

        with patch(
                "odoo.addons.agui_chat.models.agui_chat_report._upload_local_files",
                side_effect=ReportError("workspace_upload_failed"),
        ):
            with self.assertRaises(ReportError):
                _export_current_view_dataset(
                    self.env, source, binding, {"fields": ["id", "name"]},
                    source.thread_id, "browser-session", "2026-07-21 12:00:00",
                )
        source.invalidate_cache()
        self.assertEqual(source.state, "active")
        self.assertTrue(source.domain_json)

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
